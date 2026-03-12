from django.apps import AppConfig


class UsageLimitsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'usage_limits'

    def ready(self):
        import usage_limits.signals