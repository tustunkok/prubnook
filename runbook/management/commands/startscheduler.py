import os
from django.core.management.base import BaseCommand
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from runbook.models import ScheduledJob, RunbookExecution, SchedulerHeartbeat
from runbook.execution_engine import ExecutionEngine


# In-memory cache of scheduled job IDs to detect changes
_scheduled_job_cache = {}


def _update_heartbeat():
    """Write/update the scheduler heartbeat row."""
    SchedulerHeartbeat.objects.update_or_create(
        hostname='default',
        defaults={'pid': os.getpid()},
    )


def run_scheduled_job(job_id):
    close_old_connections()
    try:
        job = ScheduledJob.objects.get(pk=job_id, is_active=True)
    except ScheduledJob.DoesNotExist:
        return
    execution = RunbookExecution.objects.create(
        runbook=job.runbook,
        trigger_type=RunbookExecution.TRIGGER_SCHEDULED,
        status=RunbookExecution.STATUS_PENDING,
    )
    engine = ExecutionEngine(execution)
    engine.run()
    job.last_run_at = timezone.now()
    job.save(update_fields=['last_run_at'])


def sync_scheduler_jobs(scheduler: BackgroundScheduler):
    """
    Compare active DB jobs with APScheduler registered jobs and reconcile.
    """
    global _scheduled_job_cache
    db_jobs = {j.id: j for j in ScheduledJob.objects.all()}
    scheduler_job_ids = set(_scheduled_job_cache.keys())
    db_job_ids = set(db_jobs.keys())

    # Remove jobs deleted or deactivated in DB
    for sid in list(scheduler_job_ids):
        job = db_jobs.get(sid)
        if job is None or not job.is_active:
            try:
                scheduler.remove_job(str(sid))
            except Exception:
                pass
            _scheduled_job_cache.pop(sid, None)

    # Add or update jobs
    for sid, job in db_jobs.items():
        if not job.is_active:
            continue
        current_cron = job.cron_expression
        needs_update = (
            sid not in _scheduled_job_cache
            or _scheduled_job_cache[sid] != current_cron
        )
        if needs_update:
            try:
                trigger = CronTrigger.from_crontab(current_cron)
                scheduler.add_job(
                    run_scheduled_job,
                    trigger=trigger,
                    id=str(sid),
                    args=[sid],
                    replace_existing=True,
                )
                _scheduled_job_cache[sid] = current_cron
                # Update next_run_at in DB
                aps_job = scheduler.get_job(str(sid))
                if aps_job and aps_job.next_run_time:
                    job.next_run_at = aps_job.next_run_time
                    job.save(update_fields=['next_run_at'])
            except Exception as e:
                print(f"Failed to schedule job {sid}: {e}")


class Command(BaseCommand):
    help = 'Starts the APScheduler for runbook automation with dynamic reloading'

    def handle(self, *args, **options):
        if not settings.SCHEDULER_ENABLED:
            self.stdout.write(self.style.WARNING('Scheduler is disabled.'))
            return

        scheduler = BackgroundScheduler()
        scheduler.start()

        # Initial sync
        sync_scheduler_jobs(scheduler)
        _update_heartbeat()
        self.stdout.write(self.style.SUCCESS('Scheduler started. Press Ctrl+C to exit.'))

        # Add internal watchdog jobs
        scheduler.add_job(
            sync_scheduler_jobs,
            'interval',
            seconds=30,
            id='__sync_scheduler_jobs__',
            replace_existing=True,
            args=[scheduler],
        )
        scheduler.add_job(
            _update_heartbeat,
            'interval',
            seconds=60,
            id='__update_heartbeat__',
            replace_existing=True,
        )

        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.shutdown()
            self.stdout.write(self.style.SUCCESS('Scheduler stopped.'))
