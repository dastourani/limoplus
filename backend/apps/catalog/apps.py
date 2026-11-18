from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "محتوا"

    def ready(self):
        # Jalali dates and Persian digits in every list and read-only field of the panel.
        from .panel_display import install

        install()
        # «رویدادها»: a login is recorded wherever it happens (admin form, the panel hand-off), not view by view.
        from . import signals  # noqa: F401
