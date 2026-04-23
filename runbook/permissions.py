from django.db import models
from django.contrib.auth.models import User
from .models import Runbook, RunbookPermission


def has_runbook_permission(user: User, runbook: Runbook, permission: str) -> bool:
    """
    Check if a user has a specific permission on a runbook.
    Hierarchy:
      1. Runbook owner -> all permissions
      2. Superuser -> all permissions
      3. Direct user permission
      4. Group permission (via any of user's groups)
    Admin permission implies view, edit, and run.
    """
    if not user or not user.is_authenticated:
        return False

    if runbook.owner_id == user.id or user.is_superuser:
        return True

    # Admin implies everything
    perms_to_check = [permission]
    if permission != RunbookPermission.PERMISSION_ADMIN:
        perms_to_check.append(RunbookPermission.PERMISSION_ADMIN)

    # Direct user permission
    if RunbookPermission.objects.filter(
        runbook=runbook,
        user=user,
        permission__in=perms_to_check,
    ).exists():
        return True

    # Group permission
    user_group_ids = user.groups.values_list('id', flat=True)
    if user_group_ids and RunbookPermission.objects.filter(
        runbook=runbook,
        group_id__in=user_group_ids,
        permission__in=perms_to_check,
    ).exists():
        return True

    return False


def get_visible_runbooks(user: User):
    """Return queryset of runbooks the user can see."""
    if not user or not user.is_authenticated:
        return Runbook.objects.none()
    if user.is_superuser:
        return Runbook.objects.all()
    return Runbook.objects.filter(
        models.Q(owner=user) |
        models.Q(permissions__user=user) |
        models.Q(permissions__group__in=user.groups.all())
    ).distinct()
