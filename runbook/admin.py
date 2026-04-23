from django.contrib import admin
from .models import (
    PlatformSSHKey, Runbook, Step, RunbookExecution,
    StepExecution, ApprovalRequest, AuditLog,
    ScheduledJob, Notification, RunbookPermission, SchedulerHeartbeat,
)


@admin.register(PlatformSSHKey)
class PlatformSSHKeyAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at', 'created_by']
    search_fields = ['name']


class StepInline(admin.TabularInline):
    model = Step
    extra = 1
    fields = ['order', 'name', 'step_type', 'requires_approval']


@admin.register(Runbook)
class RunbookAdmin(admin.ModelAdmin):
    list_display = ['name', 'owner', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    list_filter = ['is_active', 'created_at']
    inlines = [StepInline]


@admin.register(RunbookExecution)
class RunbookExecutionAdmin(admin.ModelAdmin):
    list_display = ['id', 'runbook', 'trigger_type', 'status', 'started_at', 'completed_at']
    list_filter = ['status', 'trigger_type', 'started_at']
    search_fields = ['runbook__name']


@admin.register(StepExecution)
class StepExecutionAdmin(admin.ModelAdmin):
    list_display = ['id', 'execution', 'step', 'status', 'started_at', 'exit_code']
    list_filter = ['status', 'started_at']


@admin.register(ApprovalRequest)
class ApprovalRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'step_execution', 'status', 'requested_by', 'requested_at']
    list_filter = ['status', 'requested_at']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'entity_type', 'entity_id', 'user', 'timestamp']
    list_filter = ['action', 'entity_type', 'timestamp']
    search_fields = ['action', 'entity_id']


@admin.register(ScheduledJob)
class ScheduledJobAdmin(admin.ModelAdmin):
    list_display = ['runbook', 'cron_expression', 'is_active', 'last_run_at', 'next_run_at']
    list_filter = ['is_active']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'is_read', 'created_at']
    list_filter = ['is_read', 'created_at']


@admin.register(RunbookPermission)
class RunbookPermissionAdmin(admin.ModelAdmin):
    list_display = ['runbook', 'user', 'group', 'permission']
    list_filter = ['permission']


@admin.register(SchedulerHeartbeat)
class SchedulerHeartbeatAdmin(admin.ModelAdmin):
    list_display = ['hostname', 'pid', 'timestamp']
