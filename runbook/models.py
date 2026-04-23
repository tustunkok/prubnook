from django.db import models
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from .crypto_utils import encrypt_text, decrypt_text


class PlatformSSHKey(models.Model):
    name = models.CharField(max_length=255)
    private_key_encrypted = models.TextField()
    public_key = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    def set_private_key(self, private_key: str):
        self.private_key_encrypted = encrypt_text(private_key)

    def get_private_key(self) -> str:
        return decrypt_text(self.private_key_encrypted)

    def __str__(self):
        return self.name


class Runbook(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_runbooks')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def is_schedulable(self):
        steps = self.steps.all()
        if not steps.exists():
            return False
        return all(
            s.step_type in (Step.STEP_TYPE_WEBHOOK, Step.STEP_TYPE_SHELL)
            and not s.requires_approval
            for s in steps
        )


class Step(models.Model):
    STEP_TYPE_MANUAL = 'manual'
    STEP_TYPE_WEBHOOK = 'webhook'
    STEP_TYPE_SHELL = 'shell'
    STEP_TYPES = [
        (STEP_TYPE_MANUAL, 'Manual'),
        (STEP_TYPE_WEBHOOK, 'Webhook'),
        (STEP_TYPE_SHELL, 'Shell'),
    ]

    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    step_type = models.CharField(max_length=20, choices=STEP_TYPES)
    config = models.JSONField(default=dict)

    on_success_next = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='success_predecessors'
    )
    on_failure_next = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='failure_predecessors'
    )

    requires_approval = models.BooleanField(default=False)
    ssh_key = models.ForeignKey(
        PlatformSSHKey, on_delete=models.SET_NULL, null=True, blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.runbook.name} - Step {self.order}: {self.name}"


class RunbookExecution(models.Model):
    TRIGGER_MANUAL = 'manual'
    TRIGGER_SCHEDULED = 'scheduled'
    TRIGGER_API = 'api'
    TRIGGER_TYPES = [
        (TRIGGER_MANUAL, 'Manual'),
        (TRIGGER_SCHEDULED, 'Scheduled'),
        (TRIGGER_API, 'API'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_WAITING_APPROVAL = 'waiting_approval'
    STATUS_WAITING_MANUAL = 'waiting_manual'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_WAITING_APPROVAL, 'Waiting Approval'),
        (STATUS_WAITING_MANUAL, 'Waiting Manual'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE, related_name='executions')
    triggered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    trigger_type = models.CharField(max_length=20, choices=TRIGGER_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    current_step = models.ForeignKey(Step, on_delete=models.SET_NULL, null=True, blank=True)
    context = models.JSONField(default=dict)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"Execution #{self.id} of {self.runbook.name}"


class StepExecution(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_WAITING_APPROVAL = 'waiting_approval'
    STATUS_WAITING_MANUAL = 'waiting_manual'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_WAITING_APPROVAL, 'Waiting Approval'),
        (STATUS_WAITING_MANUAL, 'Waiting Manual'),
    ]

    execution = models.ForeignKey(RunbookExecution, on_delete=models.CASCADE, related_name='step_executions')
    step = models.ForeignKey(Step, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    output = models.TextField(blank=True)
    exit_code = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['started_at']

    def __str__(self):
        return f"StepExecution #{self.id} - {self.step.name}"


class ApprovalRequest(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    step_execution = models.ForeignKey(StepExecution, on_delete=models.CASCADE, related_name='approval_requests')
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approval_requests_sent')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests_handled')
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ['-requested_at']


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict)

    class Meta:
        ordering = ['-timestamp']


class ScheduledJob(models.Model):
    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE)
    cron_expression = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    link = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-created_at']


class RunbookPermission(models.Model):
    PERMISSION_VIEW = 'view'
    PERMISSION_EDIT = 'edit'
    PERMISSION_RUN = 'run'
    PERMISSION_ADMIN = 'admin'
    PERMISSION_TYPES = [
        (PERMISSION_VIEW, 'View'),
        (PERMISSION_EDIT, 'Edit'),
        (PERMISSION_RUN, 'Run'),
        (PERMISSION_ADMIN, 'Admin'),
    ]

    runbook = models.ForeignKey(Runbook, on_delete=models.CASCADE, related_name='permissions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='runbook_permissions', null=True, blank=True)
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='runbook_permissions', null=True, blank=True)
    permission = models.CharField(max_length=20, choices=PERMISSION_TYPES)

    class Meta:
        unique_together = [['runbook', 'user', 'group', 'permission']]

    def clean(self):
        super().clean()
        if (self.user is None and self.group is None) or (self.user is not None and self.group is not None):
            raise ValidationError('Exactly one of user or group must be set.')

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class SchedulerHeartbeat(models.Model):
    hostname = models.CharField(max_length=255, default='default')
    pid = models.IntegerField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now=True)
