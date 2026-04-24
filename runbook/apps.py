from django.apps import AppConfig


class RunbookConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'runbook'

    def ready(self):
        import runbook.signals  # noqa: F401
