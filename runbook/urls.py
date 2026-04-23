from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'ssh-keys', views.PlatformSSHKeyViewSet)
router.register(r'runbooks', views.RunbookViewSet, basename='runbook')
router.register(r'steps', views.StepViewSet)
router.register(r'executions', views.RunbookExecutionViewSet)
router.register(r'step-executions', views.StepExecutionViewSet)
router.register(r'approvals', views.ApprovalRequestViewSet)
router.register(r'audit-logs', views.AuditLogViewSet)
router.register(r'scheduled-jobs', views.ScheduledJobViewSet)
router.register(r'notifications', views.NotificationViewSet)
router.register(r'permissions', views.RunbookPermissionViewSet)

urlpatterns = [
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls')),

    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.dashboard, name='dashboard'),

    path('runbooks/', views.RunbookListView.as_view(), name='runbook_list'),
    path('runbooks/<int:pk>/', views.RunbookDetailView.as_view(), name='runbook_detail'),
    path('runbooks/create/', views.RunbookCreateView.as_view(), name='runbook_create'),
    path('runbooks/<int:pk>/update/', views.RunbookUpdateView.as_view(), name='runbook_update'),
    path('runbooks/<int:pk>/delete/', views.RunbookDeleteView.as_view(), name='runbook_delete'),
    path('runbooks/<int:runbook_id>/start/', views.execution_start, name='execution_start'),
    path('runbooks/<int:runbook_id>/add-user-permission/', views.runbook_add_user_permission, name='runbook_add_user_permission'),
    path('runbooks/<int:runbook_id>/add-group-permission/', views.runbook_add_group_permission, name='runbook_add_group_permission'),
    path('runbooks/<int:runbook_id>/transfer-ownership/', views.runbook_transfer_ownership, name='runbook_transfer_ownership'),
    path('permissions/<int:permission_id>/remove/', views.runbook_remove_permission, name='runbook_remove_permission'),

    path('runbooks/<int:runbook_id>/steps/create/', views.step_create, name='step_create'),
    path('steps/<int:pk>/update/', views.step_update, name='step_update'),
    path('steps/<int:pk>/delete/', views.step_delete, name='step_delete'),

    path('executions/', views.execution_list, name='execution_list'),
    path('executions/<int:pk>/', views.execution_detail, name='execution_detail'),

    path('approvals/<int:approval_id>/approve/', views.execution_approve, name='execution_approve'),
    path('approvals/<int:approval_id>/reject/', views.execution_reject, name='execution_reject'),
    path('step-executions/<int:step_exec_id>/confirm/', views.execution_manual_confirm, name='execution_manual_confirm'),

    path('ssh-keys/', views.SSHKeyListView.as_view(), name='sshkey_list'),
    path('ssh-keys/create/', views.sshkey_create, name='sshkey_create'),

    path('approvals/', views.approval_queue, name='approval_queue'),
    path('audit-logs/', views.AuditLogListView.as_view(), name='auditlog_list'),

    path('notifications/<int:pk>/mark-read/', views.notification_mark_read, name='notification_mark_read'),

    # Scheduled Jobs
    path('scheduled-jobs/', views.ScheduledJobListView.as_view(), name='scheduledjob_list'),
    path('scheduled-jobs/create/', views.scheduledjob_create, name='scheduledjob_create'),
    path('scheduled-jobs/<int:pk>/update/', views.scheduledjob_update, name='scheduledjob_update'),
    path('scheduled-jobs/<int:pk>/delete/', views.scheduledjob_delete, name='scheduledjob_delete'),

    # Scheduler Dashboard
    path('scheduler-dashboard/', views.scheduler_dashboard, name='scheduler_dashboard'),

    # User & Group Management
    path('users/', views.user_list, name='user_list'),
    path('users/create/', views.user_create, name='user_create'),
    path('users/<int:pk>/update/', views.user_update, name='user_update'),
    path('users/<int:pk>/delete/', views.user_delete, name='user_delete'),

    path('groups/', views.group_list, name='group_list'),
    path('groups/create/', views.group_create, name='group_create'),
    path('groups/<int:pk>/update/', views.group_update, name='group_update'),
    path('groups/<int:pk>/delete/', views.group_delete, name='group_delete'),
]
