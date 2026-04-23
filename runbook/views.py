import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User, Group
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import (
    PlatformSSHKey, Runbook, Step, RunbookExecution,
    StepExecution, ApprovalRequest, AuditLog, ScheduledJob,
    Notification, RunbookPermission, SchedulerHeartbeat,
)
from .permissions import has_runbook_permission, get_visible_runbooks
from .serializers import (
    PlatformSSHKeySerializer, RunbookSerializer, StepSerializer,
    RunbookExecutionSerializer, StepExecutionSerializer,
    ApprovalRequestSerializer, AuditLogSerializer,
    ScheduledJobSerializer, NotificationSerializer, RunbookPermissionSerializer,
)
from .execution_engine import ExecutionEngine


# ------------------------------------------------------------------
# Auth Views
# ------------------------------------------------------------------
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'runbook/login.html')


def logout_view(request):
    logout(request)
    return redirect('login')


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------
@login_required
def dashboard(request):
    runbooks = Runbook.objects.filter(is_active=True)[:10]
    executions = RunbookExecution.objects.all()[:10]
    pending_approvals = ApprovalRequest.objects.filter(status=ApprovalRequest.STATUS_PENDING)
    notifications = Notification.objects.filter(user=request.user, is_read=False)[:5]
    return render(request, 'runbook/dashboard.html', {
        'runbooks': runbooks,
        'executions': executions,
        'pending_approvals': pending_approvals,
        'notifications': notifications,
    })


# ------------------------------------------------------------------
# Runbook Web Views
# ------------------------------------------------------------------
class RunbookListView(ListView):
    model = Runbook
    template_name = 'runbook/runbook_list.html'
    context_object_name = 'runbooks'
    paginate_by = 20

    def get_queryset(self):
        return get_visible_runbooks(self.request.user)


class RunbookDetailView(DetailView):
    model = Runbook
    template_name = 'runbook/runbook_detail.html'
    context_object_name = 'runbook'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        runbook = self.object
        user = self.request.user
        context['can_manage_permissions'] = (
            user.is_superuser or runbook.owner == user or
            has_runbook_permission(user, runbook, RunbookPermission.PERMISSION_ADMIN)
        )
        context['user_permissions'] = runbook.permissions.filter(user__isnull=False)
        context['group_permissions'] = runbook.permissions.filter(group__isnull=False)
        context['all_users'] = User.objects.all().order_by('username')
        context['all_groups'] = Group.objects.all().order_by('name')
        context['permission_types'] = RunbookPermission.PERMISSION_TYPES
        return context


class RunbookCreateView(CreateView):
    model = Runbook
    fields = ['name', 'description', 'is_active']
    template_name = 'runbook/runbook_form.html'
    success_url = reverse_lazy('runbook_list')

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class RunbookUpdateView(UpdateView):
    model = Runbook
    fields = ['name', 'description', 'is_active']
    template_name = 'runbook/runbook_form.html'

    def get_success_url(self):
        return reverse('runbook_detail', kwargs={'pk': self.object.pk})


class RunbookDeleteView(DeleteView):
    model = Runbook
    template_name = 'runbook/runbook_confirm_delete.html'
    success_url = reverse_lazy('runbook_list')


@login_required
def runbook_add_user_permission(request, runbook_id):
    runbook = get_object_or_404(Runbook, pk=runbook_id)
    if not (request.user.is_superuser or runbook.owner == request.user or has_runbook_permission(request.user, runbook, RunbookPermission.PERMISSION_ADMIN)):
        messages.error(request, 'You do not have permission to manage this runbook.')
        return redirect('runbook_detail', pk=runbook_id)
    if request.method == 'POST':
        user_id = request.POST.get('user')
        permission = request.POST.get('permission')
        user = get_object_or_404(User, pk=user_id)
        RunbookPermission.objects.get_or_create(runbook=runbook, user=user, permission=permission)
        messages.success(request, f"Permission '{permission}' granted to {user.username}.")
    return redirect('runbook_detail', pk=runbook_id)


@login_required
def runbook_add_group_permission(request, runbook_id):
    runbook = get_object_or_404(Runbook, pk=runbook_id)
    if not (request.user.is_superuser or runbook.owner == request.user or has_runbook_permission(request.user, runbook, RunbookPermission.PERMISSION_ADMIN)):
        messages.error(request, 'You do not have permission to manage this runbook.')
        return redirect('runbook_detail', pk=runbook_id)
    if request.method == 'POST':
        group_id = request.POST.get('group')
        permission = request.POST.get('permission')
        group = get_object_or_404(Group, pk=group_id)
        RunbookPermission.objects.get_or_create(runbook=runbook, group=group, permission=permission)
        messages.success(request, f"Permission '{permission}' granted to group {group.name}.")
    return redirect('runbook_detail', pk=runbook_id)


@login_required
def runbook_remove_permission(request, permission_id):
    perm = get_object_or_404(RunbookPermission, pk=permission_id)
    runbook = perm.runbook
    if not (request.user.is_superuser or runbook.owner == request.user or has_runbook_permission(request.user, runbook, RunbookPermission.PERMISSION_ADMIN)):
        messages.error(request, 'You do not have permission to manage this runbook.')
        return redirect('runbook_detail', pk=runbook.pk)
    perm.delete()
    messages.success(request, 'Permission removed.')
    return redirect('runbook_detail', pk=runbook.pk)


@login_required
def runbook_transfer_ownership(request, runbook_id):
    runbook = get_object_or_404(Runbook, pk=runbook_id)
    if not (request.user.is_superuser or runbook.owner == request.user):
        messages.error(request, 'Only the owner or a superuser can transfer ownership.')
        return redirect('runbook_detail', pk=runbook_id)
    if request.method == 'POST':
        new_owner_id = request.POST.get('new_owner')
        new_owner = get_object_or_404(User, pk=new_owner_id)
        runbook.owner = new_owner
        runbook.save(update_fields=['owner'])
        messages.success(request, f"Ownership transferred to {new_owner.username}.")
    return redirect('runbook_detail', pk=runbook_id)


# ------------------------------------------------------------------
# Step Web Views
# ------------------------------------------------------------------
@login_required
def step_create(request, runbook_id):
    runbook = get_object_or_404(Runbook, pk=runbook_id)
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description', '')
        step_type = request.POST.get('step_type')
        order = request.POST.get('order', 0)
        config_raw = request.POST.get('config', '{}')
        requires_approval = request.POST.get('requires_approval') == 'on'
        ssh_key_id = request.POST.get('ssh_key')
        on_success_next_id = request.POST.get('on_success_next') or None
        on_failure_next_id = request.POST.get('on_failure_next') or None

        try:
            config = json.loads(config_raw)
        except json.JSONDecodeError:
            config = {}

        step = Step.objects.create(
            runbook=runbook,
            name=name,
            description=description,
            step_type=step_type,
            order=order,
            config=config,
            requires_approval=requires_approval,
            ssh_key_id=ssh_key_id or None,
            on_success_next_id=on_success_next_id,
            on_failure_next_id=on_failure_next_id,
        )
        return redirect('runbook_detail', pk=runbook_id)
    steps = runbook.steps.all()
    ssh_keys = PlatformSSHKey.objects.all()
    return render(request, 'runbook/step_form.html', {
        'runbook': runbook,
        'steps': steps,
        'ssh_keys': ssh_keys,
        'config_json': '{}',
    })


@login_required
def step_update(request, pk):
    step = get_object_or_404(Step, pk=pk)
    if request.method == 'POST':
        step.name = request.POST.get('name')
        step.description = request.POST.get('description', '')
        step.step_type = request.POST.get('step_type')
        step.order = request.POST.get('order', 0)
        try:
            step.config = json.loads(request.POST.get('config', '{}'))
        except json.JSONDecodeError:
            step.config = {}
        step.requires_approval = request.POST.get('requires_approval') == 'on'
        step.ssh_key_id = request.POST.get('ssh_key') or None
        step.on_success_next_id = request.POST.get('on_success_next') or None
        step.on_failure_next_id = request.POST.get('on_failure_next') or None
        step.save()
        return redirect('runbook_detail', pk=step.runbook_id)
    steps = step.runbook.steps.all()
    ssh_keys = PlatformSSHKey.objects.all()
    return render(request, 'runbook/step_form.html', {
        'step': step,
        'runbook': step.runbook,
        'steps': steps,
        'ssh_keys': ssh_keys,
        'config_json': json.dumps(step.config, indent=2) if step.config else '{}',
    })


@login_required
def step_delete(request, pk):
    step = get_object_or_404(Step, pk=pk)
    runbook_id = step.runbook_id
    step.delete()
    return redirect('runbook_detail', pk=runbook_id)


# ------------------------------------------------------------------
# Execution Web Views
# ------------------------------------------------------------------
@login_required
def execution_list(request):
    executions = RunbookExecution.objects.all()
    return render(request, 'runbook/execution_list.html', {'executions': executions})


@login_required
def execution_detail(request, pk):
    execution = get_object_or_404(RunbookExecution, pk=pk)
    return render(request, 'runbook/execution_detail.html', {'execution': execution})


@login_required
def execution_start(request, runbook_id):
    runbook = get_object_or_404(Runbook, pk=runbook_id)
    if not has_runbook_permission(request.user, runbook, RunbookPermission.PERMISSION_RUN):
        messages.error(request, 'You do not have permission to run this runbook.')
        return redirect('runbook_list')
    execution = RunbookExecution.objects.create(
        runbook=runbook,
        triggered_by=request.user,
        trigger_type=RunbookExecution.TRIGGER_MANUAL,
        status=RunbookExecution.STATUS_PENDING,
    )
    engine = ExecutionEngine(execution)
    engine.run()
    return redirect('execution_detail', pk=execution.id)


@login_required
def execution_approve(request, approval_id):
    approval = get_object_or_404(ApprovalRequest, pk=approval_id, status=ApprovalRequest.STATUS_PENDING)
    comment = request.POST.get('comment', '')
    engine = ExecutionEngine(approval.step_execution.execution)
    engine.approve_step(approval, request.user, comment)
    return redirect('execution_detail', pk=approval.step_execution.execution_id)


@login_required
def execution_reject(request, approval_id):
    approval = get_object_or_404(ApprovalRequest, pk=approval_id, status=ApprovalRequest.STATUS_PENDING)
    comment = request.POST.get('comment', '')
    engine = ExecutionEngine(approval.step_execution.execution)
    engine.reject_step(approval, request.user, comment)
    return redirect('execution_detail', pk=approval.step_execution.execution_id)


@login_required
def execution_manual_confirm(request, step_exec_id):
    step_exec = get_object_or_404(StepExecution, pk=step_exec_id, status=StepExecution.STATUS_WAITING_MANUAL)
    engine = ExecutionEngine(step_exec.execution)
    engine.manual_confirm(step_exec)
    return redirect('execution_detail', pk=step_exec.execution_id)


# ------------------------------------------------------------------
# SSH Key Web Views
# ------------------------------------------------------------------
class SSHKeyListView(ListView):
    model = PlatformSSHKey
    template_name = 'runbook/sshkey_list.html'
    context_object_name = 'ssh_keys'


@login_required
def sshkey_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        private_key = request.POST.get('private_key')
        public_key = request.POST.get('public_key', '')
        key = PlatformSSHKey.objects.create(
            name=name,
            public_key=public_key,
            created_by=request.user,
        )
        key.set_private_key(private_key)
        key.save()
        return redirect('sshkey_list')
    return render(request, 'runbook/sshkey_form.html')


# ------------------------------------------------------------------
# Approval Queue
# ------------------------------------------------------------------
@login_required
def approval_queue(request):
    approvals = ApprovalRequest.objects.filter(status=ApprovalRequest.STATUS_PENDING)
    return render(request, 'runbook/approval_queue.html', {'approvals': approvals})


# ------------------------------------------------------------------
# Audit Log
# ------------------------------------------------------------------
class AuditLogListView(ListView):
    model = AuditLog
    template_name = 'runbook/auditlog_list.html'
    context_object_name = 'audit_logs'
    paginate_by = 50


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------
@login_required
def notification_mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    return redirect(request.META.get('HTTP_REFERER', 'dashboard'))


# ------------------------------------------------------------------
# API ViewSets
# ------------------------------------------------------------------
class PlatformSSHKeyViewSet(viewsets.ModelViewSet):
    queryset = PlatformSSHKey.objects.all()
    serializer_class = PlatformSSHKeySerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        private_key = self.request.data.get('private_key')
        if private_key:
            instance.set_private_key(private_key)
            instance.save()


class RunbookViewSet(viewsets.ModelViewSet):
    serializer_class = RunbookSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return get_visible_runbooks(self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        runbook = self.get_object()
        if not has_runbook_permission(request.user, runbook, RunbookPermission.PERMISSION_RUN):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        execution = RunbookExecution.objects.create(
            runbook=runbook,
            triggered_by=request.user,
            trigger_type=RunbookExecution.TRIGGER_API,
            status=RunbookExecution.STATUS_PENDING,
        )
        engine = ExecutionEngine(execution)
        engine.run()
        return Response(RunbookExecutionSerializer(execution).data)


class StepViewSet(viewsets.ModelViewSet):
    queryset = Step.objects.all()
    serializer_class = StepSerializer
    permission_classes = [IsAuthenticated]


class RunbookExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RunbookExecution.objects.all()
    serializer_class = RunbookExecutionSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        execution = self.get_object()
        step_exec = execution.step_executions.filter(status=StepExecution.STATUS_WAITING_APPROVAL).first()
        if not step_exec:
            return Response({'detail': 'No approval pending.'}, status=status.HTTP_400_BAD_REQUEST)
        approval = step_exec.approval_requests.filter(status=ApprovalRequest.STATUS_PENDING).first()
        if not approval:
            return Response({'detail': 'No approval request found.'}, status=status.HTTP_400_BAD_REQUEST)
        engine = ExecutionEngine(execution)
        engine.approve_step(approval, request.user, request.data.get('comment', ''))
        return Response(RunbookExecutionSerializer(execution).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        execution = self.get_object()
        step_exec = execution.step_executions.filter(status=StepExecution.STATUS_WAITING_APPROVAL).first()
        if not step_exec:
            return Response({'detail': 'No approval pending.'}, status=status.HTTP_400_BAD_REQUEST)
        approval = step_exec.approval_requests.filter(status=ApprovalRequest.STATUS_PENDING).first()
        if not approval:
            return Response({'detail': 'No approval request found.'}, status=status.HTTP_400_BAD_REQUEST)
        engine = ExecutionEngine(execution)
        engine.reject_step(approval, request.user, request.data.get('comment', ''))
        return Response(RunbookExecutionSerializer(execution).data)

    @action(detail=True, methods=['post'])
    def manual_confirm(self, request, pk=None):
        execution = self.get_object()
        step_exec = execution.step_executions.filter(status=StepExecution.STATUS_WAITING_MANUAL).first()
        if not step_exec:
            return Response({'detail': 'No manual confirmation pending.'}, status=status.HTTP_400_BAD_REQUEST)
        engine = ExecutionEngine(execution)
        engine.manual_confirm(step_exec)
        return Response(RunbookExecutionSerializer(execution).data)


class StepExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StepExecution.objects.all()
    serializer_class = StepExecutionSerializer
    permission_classes = [IsAuthenticated]


class ApprovalRequestViewSet(viewsets.ModelViewSet):
    queryset = ApprovalRequest.objects.all()
    serializer_class = ApprovalRequestSerializer
    permission_classes = [IsAuthenticated]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]


class ScheduledJobViewSet(viewsets.ModelViewSet):
    queryset = ScheduledJob.objects.all()
    serializer_class = ScheduledJobSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class NotificationViewSet(viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notification).data)


class RunbookPermissionViewSet(viewsets.ModelViewSet):
    queryset = RunbookPermission.objects.all()
    serializer_class = RunbookPermissionSerializer
    permission_classes = [IsAuthenticated]


# ------------------------------------------------------------------
# Scheduled Job Web Views
# ------------------------------------------------------------------
class ScheduledJobListView(ListView):
    model = ScheduledJob
    template_name = 'runbook/scheduledjob_list.html'
    context_object_name = 'scheduled_jobs'
    paginate_by = 20


@login_required
def scheduledjob_create(request):
    if request.method == 'POST':
        runbook_id = request.POST.get('runbook')
        cron_expression = request.POST.get('cron_expression')
        is_active = request.POST.get('is_active') == 'on'
        runbook = get_object_or_404(Runbook, pk=runbook_id)
        if not runbook.is_schedulable:
            messages.error(request, 'This runbook is not eligible for scheduling. It must contain only webhook or shell steps with no approval gates.')
            return redirect('scheduledjob_create')
        ScheduledJob.objects.create(
            runbook=runbook,
            cron_expression=cron_expression,
            is_active=is_active,
            created_by=request.user,
        )
        messages.success(request, 'Scheduled job created.')
        return redirect('scheduledjob_list')
    runbooks = [rb for rb in Runbook.objects.filter(is_active=True) if rb.is_schedulable]
    return render(request, 'runbook/scheduledjob_form.html', {
        'runbooks': runbooks,
    })


@login_required
def scheduledjob_update(request, pk):
    job = get_object_or_404(ScheduledJob, pk=pk)
    if request.method == 'POST':
        runbook_id = request.POST.get('runbook')
        cron_expression = request.POST.get('cron_expression')
        is_active = request.POST.get('is_active') == 'on'
        runbook = get_object_or_404(Runbook, pk=runbook_id)
        if not runbook.is_schedulable:
            messages.error(request, 'This runbook is not eligible for scheduling.')
            return redirect('scheduledjob_update', pk=pk)
        job.runbook = runbook
        job.cron_expression = cron_expression
        job.is_active = is_active
        job.save()
        messages.success(request, 'Scheduled job updated.')
        return redirect('scheduledjob_list')
    runbooks = [rb for rb in Runbook.objects.filter(is_active=True) if rb.is_schedulable]
    return render(request, 'runbook/scheduledjob_form.html', {
        'job': job,
        'runbooks': runbooks,
    })


@login_required
def scheduledjob_delete(request, pk):
    job = get_object_or_404(ScheduledJob, pk=pk)
    if request.method == 'POST':
        job.delete()
        messages.success(request, 'Scheduled job deleted.')
        return redirect('scheduledjob_list')
    return render(request, 'runbook/scheduledjob_confirm_delete.html', {'job': job})


# ------------------------------------------------------------------
# Scheduler Dashboard
# ------------------------------------------------------------------
@login_required
def scheduler_dashboard(request):
    heartbeat = SchedulerHeartbeat.objects.first()
    scheduler_alive = False
    if heartbeat:
        delta = timezone.now() - heartbeat.timestamp
        scheduler_alive = delta.total_seconds() < 120

    jobs = ScheduledJob.objects.all()
    for job in jobs:
        # next_run_at is populated by the scheduler process; show 'Unknown' if not set
        pass

    return render(request, 'runbook/scheduler_dashboard.html', {
        'scheduler_alive': scheduler_alive,
        'heartbeat': heartbeat,
        'jobs': jobs,
    })


# ------------------------------------------------------------------
# User & Group Management (staff only)
# ------------------------------------------------------------------
staff_required = user_passes_test(lambda u: u.is_staff)


@staff_required
def user_list(request):
    users = User.objects.all().order_by('username')
    return render(request, 'runbook/user_list.html', {'users': users})


@staff_required
def user_create(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email', '')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        password = request.POST.get('password')
        is_staff = request.POST.get('is_staff') == 'on'
        is_superuser = request.POST.get('is_superuser') == 'on'
        group_ids = request.POST.getlist('groups')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
        user.is_staff = is_staff
        user.is_superuser = is_superuser
        user.save()
        user.groups.set(group_ids)
        messages.success(request, 'User created.')
        return redirect('user_list')
    groups = Group.objects.all()
    return render(request, 'runbook/user_form.html', {'groups': groups})


@staff_required
def user_update(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        user.username = request.POST.get('username')
        user.email = request.POST.get('email', '')
        user.first_name = request.POST.get('first_name', '')
        user.last_name = request.POST.get('last_name', '')
        user.is_staff = request.POST.get('is_staff') == 'on'
        user.is_superuser = request.POST.get('is_superuser') == 'on'
        password = request.POST.get('password')
        if password:
            user.set_password(password)
        user.save()
        user.groups.set(request.POST.getlist('groups'))
        messages.success(request, 'User updated.')
        return redirect('user_list')
    groups = Group.objects.all()
    return render(request, 'runbook/user_form.html', {'user_obj': user, 'groups': groups})


@staff_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        user.delete()
        messages.success(request, 'User deleted.')
        return redirect('user_list')
    return render(request, 'runbook/user_confirm_delete.html', {'user_obj': user})


@staff_required
def group_list(request):
    groups = Group.objects.all().order_by('name')
    return render(request, 'runbook/group_list.html', {'groups': groups})


@staff_required
def group_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        group = Group.objects.create(name=name)
        group.user_set.set(request.POST.getlist('users'))
        messages.success(request, 'Group created.')
        return redirect('group_list')
    users = User.objects.all().order_by('username')
    return render(request, 'runbook/group_form.html', {'users': users})


@staff_required
def group_update(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        group.name = request.POST.get('name')
        group.save()
        group.user_set.set(request.POST.getlist('users'))
        messages.success(request, 'Group updated.')
        return redirect('group_list')
    users = User.objects.all().order_by('username')
    return render(request, 'runbook/group_form.html', {'group_obj': group, 'users': users})


@staff_required
def group_delete(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        group.delete()
        messages.success(request, 'Group deleted.')
        return redirect('group_list')
    return render(request, 'runbook/group_confirm_delete.html', {'group_obj': group})
