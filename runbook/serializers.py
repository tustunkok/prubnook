from django.contrib.auth.models import User
from rest_framework import serializers
from .models import (
    PlatformSSHKey, Runbook, Step, RunbookExecution,
    StepExecution, ApprovalRequest, AuditLog, ScheduledJob,
    Notification, RunbookPermission,
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class PlatformSSHKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = PlatformSSHKey
        fields = ['id', 'name', 'public_key', 'created_at', 'created_by']
        read_only_fields = ['created_at', 'created_by']


class StepSerializer(serializers.ModelSerializer):
    class Meta:
        model = Step
        fields = [
            'id', 'runbook', 'order', 'name', 'description',
            'step_type', 'config', 'on_success_next', 'on_failure_next',
            'requires_approval', 'ssh_key', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class RunbookSerializer(serializers.ModelSerializer):
    steps = StepSerializer(many=True, read_only=True)
    owner = UserSerializer(read_only=True)

    class Meta:
        model = Runbook
        fields = ['id', 'name', 'description', 'owner', 'is_active', 'steps', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class StepExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StepExecution
        fields = ['id', 'execution', 'step', 'status', 'started_at', 'completed_at', 'output', 'exit_code']
        read_only_fields = ['started_at', 'completed_at']


class RunbookExecutionSerializer(serializers.ModelSerializer):
    step_executions = StepExecutionSerializer(many=True, read_only=True)
    triggered_by = UserSerializer(read_only=True)

    class Meta:
        model = RunbookExecution
        fields = [
            'id', 'runbook', 'triggered_by', 'trigger_type',
            'status', 'started_at', 'completed_at', 'current_step',
            'context', 'step_executions'
        ]
        read_only_fields = ['started_at', 'completed_at', 'triggered_by']


class ApprovalRequestSerializer(serializers.ModelSerializer):
    requested_by = UserSerializer(read_only=True)
    approved_by = UserSerializer(read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            'id', 'step_execution', 'requested_by', 'approved_by',
            'requested_at', 'approved_at', 'status', 'comment'
        ]
        read_only_fields = ['requested_at', 'approved_at', 'requested_by', 'approved_by']


class AuditLogSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'action', 'entity_type', 'entity_id', 'timestamp', 'details']
        read_only_fields = ['timestamp']


class ScheduledJobSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)

    class Meta:
        model = ScheduledJob
        fields = ['id', 'runbook', 'cron_expression', 'is_active', 'created_by', 'created_at', 'last_run_at']
        read_only_fields = ['created_by', 'created_at', 'last_run_at']


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'user', 'message', 'is_read', 'created_at', 'link']
        read_only_fields = ['created_at']


class RunbookPermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunbookPermission
        fields = ['id', 'runbook', 'user', 'permission']
