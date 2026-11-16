from django.apps import AppConfig


class GuardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.guard"
    verbose_name = "محافظت از متن"

    def ready(self):
        from . import signals  # noqa: F401
