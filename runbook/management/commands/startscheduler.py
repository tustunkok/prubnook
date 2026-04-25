import logging
import os
import time
from django.core.management.base import BaseCommand
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone
from runbook.models import ScheduledJob, RunbookExecution, SchedulerHeartbeat
from runbook.execution_engine import ExecutionEngine

logger = logging.getLogger('runbook.scheduler')

# In-memory cache: job_id -> cron_expression
_scheduled_job_cache = {}
_last_sync_time = None


def _update_heartbeat():
    """Write/update the scheduler heartbeat row."""
    try:
        SchedulerHeartbeat.objects.update_or_create(
            hostname='default',
            defaults={'pid': os.getpid()},
        )
    except Exception:
        logger.exception('Failed to update heartbeat')


def run_scheduled_job(job_id):
    close_old_connections()
    try:
        job = ScheduledJob.objects.get(pk=job_id, is_active=True)
    except ScheduledJob.DoesNotExist:
        logger.warning('ScheduledJob %s not found or inactive; skipping.', job_id)
        return
    if not job.runbook.is_active:
        logger.warning('ScheduledJob %s references a disabled runbook; skipping.', job_id)
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
    Reconcile active DB jobs with APScheduler registered jobs.
    Must be called with a fresh DB connection.
    """
    global _scheduled_job_cache, _last_sync_time

    close_old_connections()

    try:
        db_jobs = {j.id: j for j in ScheduledJob.objects.all()}
    except Exception:
        logger.exception('Failed to fetch scheduled jobs from DB')
        return

    scheduler_job_ids = set(_scheduled_job_cache.keys())
    db_job_ids = set(db_jobs.keys())

    # Remove jobs deleted or deactivated in DB
    for sid in list(scheduler_job_ids):
        job = db_jobs.get(sid)
        if job is None or not job.is_active:
            try:
                scheduler.remove_job(str(sid))
                logger.info('Removed job %s from scheduler', sid)
            except Exception:
                pass
            _scheduled_job_cache.pop(sid, None)

    # Add new jobs or update changed ones
    for sid, job in db_jobs.items():
        if not job.is_active:
            continue

        current_cron = job.cron_expression
        cached_cron = _scheduled_job_cache.get(sid)

        if cached_cron is None:
            # Brand-new job
            try:
                trigger = CronTrigger.from_crontab(current_cron)
                scheduler.add_job(
                    run_scheduled_job,
                    trigger=trigger,
                    id=str(sid),
                    args=[sid],
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                _scheduled_job_cache[sid] = current_cron
                logger.info('Added job %s with cron "%s"', sid, current_cron)
            except Exception:
                logger.exception('Failed to add job %s', sid)
                continue

        elif cached_cron != current_cron:
            # Existing job with updated cron
            try:
                trigger = CronTrigger.from_crontab(current_cron)
                scheduler.reschedule_job(str(sid), trigger=trigger)
                _scheduled_job_cache[sid] = current_cron
                logger.info('Rescheduled job %s to cron "%s"', sid, current_cron)
            except Exception:
                logger.exception('Failed to reschedule job %s', sid)
                continue

        # Update next_run_at in DB regardless
        try:
            aps_job = scheduler.get_job(str(sid))
            if aps_job and aps_job.next_run_time:
                job.next_run_at = aps_job.next_run_time
                job.save(update_fields=['next_run_at'])
        except Exception:
            logger.exception('Failed to update next_run_at for job %s', sid)

    _last_sync_time = timezone.now()


def _check_sync_request(scheduler: BackgroundScheduler):
    """
    Lightweight DB poll to detect hot-reload requests from signals.
    """
    global _last_sync_time
    close_old_connections()

    try:
        heartbeat = SchedulerHeartbeat.objects.filter(hostname='default').first()
    except Exception:
        logger.exception('Failed to read heartbeat for sync check')
        return

    if heartbeat and heartbeat.sync_requested_at:
        if _last_sync_time is None or heartbeat.sync_requested_at > _last_sync_time:
            logger.info('Sync request detected; reconciling jobs...')
            sync_scheduler_jobs(scheduler)
            # Clear the flag so we don't keep syncing
            try:
                SchedulerHeartbeat.objects.filter(hostname='default').update(
                    sync_requested_at=None
                )
            except Exception:
                logger.exception('Failed to clear sync_requested_at')


class Command(BaseCommand):
    help = 'Starts the APScheduler for runbook automation with dynamic reloading'

    def handle(self, *args, **options):
        if not settings.SCHEDULER_ENABLED:
            self.stdout.write(self.style.WARNING('Scheduler is disabled.'))
            return

        scheduler = BackgroundScheduler()
        scheduler.start()

        # Initial full sync
        sync_scheduler_jobs(scheduler)
        _update_heartbeat()
        self.stdout.write(self.style.SUCCESS('Scheduler started. Press Ctrl+C to exit.'))

        # Fast-polling sync watcher (~hot reload)
        scheduler.add_job(
            _check_sync_request,
            'interval',
            seconds=5,
            id='__check_sync_request__',
            replace_existing=True,
            args=[scheduler],
        )

        # Periodic full safety sync
        scheduler.add_job(
            sync_scheduler_jobs,
            'interval',
            seconds=60,
            id='__sync_scheduler_jobs__',
            replace_existing=True,
            args=[scheduler],
        )

        # Heartbeat
        scheduler.add_job(
            _update_heartbeat,
            'interval',
            seconds=60,
            id='__update_heartbeat__',
            replace_existing=True,
        )

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.shutdown()
            self.stdout.write(self.style.SUCCESS('Scheduler stopped.'))
