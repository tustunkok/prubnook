import subprocess
import requests
import jinja2
import paramiko
import io
from django.utils import timezone
from django.contrib.auth.models import User
from .models import (
    RunbookExecution, StepExecution, ApprovalRequest,
    Notification, AuditLog, Step, PlatformSSHKey,
)
from .crypto_utils import decrypt_text


class ExecutionEngine:
    def __init__(self, execution: RunbookExecution):
        self.execution = execution
        self.context = execution.context or {}
        self.jinja_env = jinja2.Environment()

    def _render(self, template_str: str) -> str:
        return self.jinja_env.from_string(template_str).render(self.context)

    def _log(self, step_exec: StepExecution, message: str):
        step_exec.output += message + '\n'
        step_exec.save(update_fields=['output'])

    def _audit(self, action: str, entity_type: str, entity_id: str, details: dict = None):
        AuditLog.objects.create(
            user=self.execution.triggered_by,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details or {},
        )

    def _notify(self, message: str, link: str = ''):
        if not self.execution.triggered_by:
            return
        Notification.objects.create(
            user=self.execution.triggered_by,
            message=message,
            link=link,
        )

    def run(self):
        execution = self.execution
        if execution.status not in [RunbookExecution.STATUS_PENDING, RunbookExecution.STATUS_RUNNING]:
            return

        execution.status = RunbookExecution.STATUS_RUNNING
        execution.save(update_fields=['status'])

        self._audit('execution_started', 'RunbookExecution', execution.id)

        # Find starting step
        steps = list(execution.runbook.steps.all())
        if not steps:
            self._complete_execution()
            return

        current_step = execution.current_step
        if not current_step:
            current_step = steps[0]
            execution.current_step = current_step
            execution.save(update_fields=['current_step'])

        step_index = {s.id: s for s in steps}
        ordered_steps = sorted(steps, key=lambda s: (s.order, s.id))

        while current_step:
            step_exec = StepExecution.objects.create(
                execution=execution,
                step=current_step,
                status=StepExecution.STATUS_RUNNING,
            )

            if current_step.requires_approval:
                step_exec.status = StepExecution.STATUS_WAITING_APPROVAL
                step_exec.save(update_fields=['status'])
                execution.status = RunbookExecution.STATUS_WAITING_APPROVAL
                execution.save(update_fields=['status'])
                ApprovalRequest.objects.create(
                    step_execution=step_exec,
                    requested_by=self.execution.triggered_by or User.objects.first(),
                )
                self._notify(f"Approval required for step '{current_step.name}' in execution #{execution.id}",
                             f"/executions/{execution.id}/")
                self._audit('approval_requested', 'StepExecution', step_exec.id)
                return

            success = self._execute_step(step_exec)

            if step_exec.status == StepExecution.STATUS_WAITING_MANUAL:
                execution.status = RunbookExecution.STATUS_WAITING_MANUAL
                execution.save(update_fields=['status'])
                self._notify(f"Manual action required for step '{current_step.name}' in execution #{execution.id}",
                             f"/executions/{execution.id}/")
                return

            next_step = None
            if success:
                if current_step.on_success_next:
                    next_step = current_step.on_success_next
                else:
                    # Default: next in order
                    idx = ordered_steps.index(current_step)
                    if idx + 1 < len(ordered_steps):
                        next_step = ordered_steps[idx + 1]
            else:
                if current_step.on_failure_next:
                    next_step = current_step.on_failure_next
                else:
                    execution.status = RunbookExecution.STATUS_FAILED
                    execution.completed_at = timezone.now()
                    execution.save(update_fields=['status', 'completed_at'])
                    self._audit('execution_failed', 'RunbookExecution', execution.id)
                    self._notify(f"Execution #{execution.id} failed at step '{current_step.name}'",
                                 f"/executions/{execution.id}/")
                    return

            current_step = next_step
            if current_step:
                execution.current_step = current_step
                execution.save(update_fields=['current_step'])

        self._complete_execution()

    def _execute_step(self, step_exec: StepExecution) -> bool:
        step = step_exec.step
        step_type = step.step_type

        try:
            if step_type == Step.STEP_TYPE_MANUAL:
                return self._execute_manual(step_exec)
            elif step_type == Step.STEP_TYPE_WEBHOOK:
                return self._execute_webhook(step_exec)
            elif step_type == Step.STEP_TYPE_SHELL:
                return self._execute_shell(step_exec)
            else:
                raise ValueError(f"Unknown step type: {step_type}")
        except Exception as e:
            step_exec.status = StepExecution.STATUS_FAILED
            step_exec.output += f"\nERROR: {str(e)}"
            step_exec.save(update_fields=['status', 'output'])
            return False

    def _execute_manual(self, step_exec: StepExecution) -> bool:
        step_exec.status = StepExecution.STATUS_WAITING_MANUAL
        step_exec.output = "Waiting for manual confirmation..."
        step_exec.save(update_fields=['status', 'output'])
        return False  # Paused, not yet success

    def _execute_webhook(self, step_exec: StepExecution) -> bool:
        step = step_exec.step
        config = step.config or {}
        url = self._render(config.get('url', ''))
        method = config.get('method', 'GET').upper()
        headers = {k: self._render(v) for k, v in config.get('headers', {}).items()}
        body = self._render(config.get('body', ''))
        timeout = config.get('timeout', 30)

        step_exec.output = f"Webhook: {method} {url}\n"
        step_exec.save(update_fields=['output'])

        try:
            if method == 'GET':
                resp = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                resp = requests.post(url, headers=headers, data=body, timeout=timeout)
            elif method == 'PUT':
                resp = requests.put(url, headers=headers, data=body, timeout=timeout)
            elif method == 'DELETE':
                resp = requests.delete(url, headers=headers, timeout=timeout)
            else:
                resp = requests.request(method, url, headers=headers, data=body, timeout=timeout)

            step_exec.output += f"Status: {resp.status_code}\nBody: {resp.text[:2000]}\n"
            step_exec.exit_code = resp.status_code
            step_exec.save(update_fields=['output', 'exit_code'])

            if 200 <= resp.status_code < 300:
                step_exec.status = StepExecution.STATUS_COMPLETED
                step_exec.completed_at = timezone.now()
                step_exec.save(update_fields=['status', 'completed_at'])
                # Optionally parse response into context
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        self.execution.context.update(data)
                        self.execution.save(update_fields=['context'])
                except Exception:
                    pass
                return True
            else:
                step_exec.status = StepExecution.STATUS_FAILED
                step_exec.completed_at = timezone.now()
                step_exec.save(update_fields=['status', 'completed_at'])
                return False
        except requests.RequestException as e:
            step_exec.output += f"Request failed: {str(e)}\n"
            step_exec.status = StepExecution.STATUS_FAILED
            step_exec.completed_at = timezone.now()
            step_exec.save(update_fields=['output', 'status', 'completed_at'])
            return False

    def _execute_shell(self, step_exec: StepExecution) -> bool:
        step = step_exec.step
        config = step.config or {}
        command = self._render(config.get('command', ''))
        timeout = config.get('timeout', 300)
        is_remote = config.get('is_remote', False)

        step_exec.output = f"Command: {command}\n"
        step_exec.save(update_fields=['output'])

        if is_remote:
            return self._execute_remote_shell(step_exec, command, config, timeout)
        else:
            return self._execute_local_shell(step_exec, command, timeout)

    def _execute_local_shell(self, step_exec: StepExecution, command: str, timeout: int) -> bool:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            step_exec.output += f"Exit code: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}\n"
            step_exec.exit_code = result.returncode
            step_exec.save(update_fields=['output', 'exit_code'])

            if result.returncode == 0:
                step_exec.status = StepExecution.STATUS_COMPLETED
                step_exec.completed_at = timezone.now()
                step_exec.save(update_fields=['status', 'completed_at'])
                return True
            else:
                step_exec.status = StepExecution.STATUS_FAILED
                step_exec.completed_at = timezone.now()
                step_exec.save(update_fields=['status', 'completed_at'])
                return False
        except subprocess.TimeoutExpired:
            step_exec.output += "Command timed out.\n"
            step_exec.status = StepExecution.STATUS_FAILED
            step_exec.completed_at = timezone.now()
            step_exec.save(update_fields=['output', 'status', 'completed_at'])
            return False

    def _execute_remote_shell(self, step_exec: StepExecution, command: str, config: dict, timeout: int) -> bool:
        host = config.get('host', '')
        user = config.get('user', '')
        port = config.get('port', 22)
        ssh_key = step_exec.step.ssh_key

        if not ssh_key:
            step_exec.output += "No SSH key configured for remote shell step.\n"
            step_exec.status = StepExecution.STATUS_FAILED
            step_exec.completed_at = timezone.now()
            step_exec.save(update_fields=['output', 'status', 'completed_at'])
            return False

        private_key_str = ssh_key.get_private_key()
        pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key_str))

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(hostname=host, port=port, username=user, pkey=pkey, timeout=timeout)
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out_text = stdout.read().decode('utf-8', errors='replace')
            err_text = stderr.read().decode('utf-8', errors='replace')
            client.close()

            step_exec.output += f"Remote exit code: {exit_code}\nSTDOUT:\n{out_text}\nSTDERR:\n{err_text}\n"
            step_exec.exit_code = exit_code
            step_exec.save(update_fields=['output', 'exit_code'])

            if exit_code == 0:
                step_exec.status = StepExecution.STATUS_COMPLETED
                step_exec.completed_at = timezone.now()
                step_exec.save(update_fields=['status', 'completed_at'])
                return True
            else:
                step_exec.status = StepExecution.STATUS_FAILED
                step_exec.completed_at = timezone.now()
                step_exec.save(update_fields=['status', 'completed_at'])
                return False
        except Exception as e:
            step_exec.output += f"SSH connection failed: {str(e)}\n"
            step_exec.status = StepExecution.STATUS_FAILED
            step_exec.completed_at = timezone.now()
            step_exec.save(update_fields=['output', 'status', 'completed_at'])
            return False

    def _complete_execution(self):
        self.execution.status = RunbookExecution.STATUS_COMPLETED
        self.execution.completed_at = timezone.now()
        self.execution.current_step = None
        self.execution.save(update_fields=['status', 'completed_at', 'current_step'])
        self._audit('execution_completed', 'RunbookExecution', self.execution.id)
        self._notify(f"Execution #{self.execution.id} completed successfully",
                     f"/executions/{self.execution.id}/")

    def approve_step(self, approval: ApprovalRequest, approved_by: User, comment: str = ''):
        approval.approved_by = approved_by
        approval.approved_at = timezone.now()
        approval.status = ApprovalRequest.STATUS_APPROVED
        approval.comment = comment
        approval.save()

        step_exec = approval.step_execution
        step_exec.status = StepExecution.STATUS_RUNNING
        step_exec.save(update_fields=['status'])

        self.execution.status = RunbookExecution.STATUS_RUNNING
        self.execution.save(update_fields=['status'])

        success = self._execute_step(step_exec)
        self._continue_after_step(step_exec, success)

    def reject_step(self, approval: ApprovalRequest, approved_by: User, comment: str = ''):
        approval.approved_by = approved_by
        approval.approved_at = timezone.now()
        approval.status = ApprovalRequest.STATUS_REJECTED
        approval.comment = comment
        approval.save()

        step_exec = approval.step_execution
        step_exec.status = StepExecution.STATUS_FAILED
        step_exec.completed_at = timezone.now()
        step_exec.save(update_fields=['status', 'completed_at'])

        self._continue_after_step(step_exec, False)

    def manual_confirm(self, step_exec: StepExecution):
        if step_exec.status != StepExecution.STATUS_WAITING_MANUAL:
            return

        step_exec.status = StepExecution.STATUS_COMPLETED
        step_exec.completed_at = timezone.now()
        step_exec.output += "\nManually confirmed by operator."
        step_exec.save(update_fields=['status', 'completed_at', 'output'])

        self.execution.status = RunbookExecution.STATUS_RUNNING
        self.execution.save(update_fields=['status'])

        self._continue_after_step(step_exec, True)

    def _continue_after_step(self, step_exec: StepExecution, success: bool):
        execution = self.execution
        current_step = step_exec.step
        steps = list(execution.runbook.steps.all())
        ordered_steps = sorted(steps, key=lambda s: (s.order, s.id))

        next_step = None
        if success:
            if current_step.on_success_next:
                next_step = current_step.on_success_next
            else:
                idx = ordered_steps.index(current_step)
                if idx + 1 < len(ordered_steps):
                    next_step = ordered_steps[idx + 1]
        else:
            if current_step.on_failure_next:
                next_step = current_step.on_failure_next
            else:
                execution.status = RunbookExecution.STATUS_FAILED
                execution.completed_at = timezone.now()
                execution.save(update_fields=['status', 'completed_at'])
                self._audit('execution_failed', 'RunbookExecution', execution.id)
                self._notify(f"Execution #{execution.id} failed at step '{current_step.name}'",
                             f"/executions/{execution.id}/")
                return

        if next_step:
            execution.current_step = next_step
            execution.save(update_fields=['current_step'])
            self.run()  # Continue execution
        else:
            self._complete_execution()
