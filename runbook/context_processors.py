from .models import Notification


def notifications(request):
    if request.user and request.user.is_authenticated:
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        recent = Notification.objects.filter(user=request.user, is_read=False)[:5]
        return {
            'unread_notification_count': unread_count,
            'recent_notifications': recent,
        }
    return {
        'unread_notification_count': 0,
        'recent_notifications': [],
    }
