from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "محتوا"

    def ready(self):
        # Jalali dates and Persian digits in lists/read-only fields, plus Jalali entry widgets in every admin form.
        from .jalali_admin import install as install_jalali_admin
        from .panel_display import install as install_panel_display

        install_panel_display()
        install_jalali_admin()
