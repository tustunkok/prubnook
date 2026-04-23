from django.utils.deprecation import MiddlewareMixin
from .models import AuditLog


class AuditLogMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if not request.user or not request.user.is_authenticated:
            return None
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
            action = f"{request.method}_{view_func.__name__}"
            AuditLog.objects.create(
                user=request.user,
                action=action,
                entity_type='request',
                entity_id='0',
                details={
                    'path': request.path,
                    'args': view_args,
                    'kwargs': {k: str(v) for k, v in view_kwargs.items()},
                }
            )
        return None
