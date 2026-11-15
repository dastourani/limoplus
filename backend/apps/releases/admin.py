from django.contrib import admin

from .models import AppRelease
from .service import clear_cache


@admin.register(AppRelease)
class AppReleaseAdmin(admin.ModelAdmin):
    list_display = ("build", "version_name", "platform", "is_required", "is_published", "created_at")
    list_filter = ("platform", "is_required", "is_published")
    fields = ("platform", "build", "version_name", "notes", "apk", "download_url", "is_required", "is_published")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        clear_cache()
