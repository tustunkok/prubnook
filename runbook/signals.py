from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from .models import ScheduledJob, SchedulerHeartbeat


@receiver(post_save, sender=ScheduledJob)
@receiver(post_delete, sender=ScheduledJob)
def trigger_scheduler_sync(sender, instance, **kwargs):
    """
    Notify the scheduler process that jobs have changed and a sync is needed.
    The scheduler's fast-polling watcher picks this up within ~5 seconds.
    """
    try:
        SchedulerHeartbeat.objects.update_or_create(
            hostname='default',
            defaults={'sync_requested_at': timezone.now()},
        )
    except Exception:
        # Swallow silently; the periodic safety sync will catch it anyway.
        pass
