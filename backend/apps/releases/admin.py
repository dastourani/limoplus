from django.contrib import admin

from .models import AppRelease
from .service import clear_cache


@admin.register(AppRelease)
class AppReleaseAdmin(admin.ModelAdmin):
    list_display = ("build", "version_name", "platform", "is_required", "is_published", "created_at")
    list_filter = ("platform", "is_required", "is_published")
    fieldsets = (
        (None, {"fields": ("platform", "build", "version_name", "notes")}),
        ("فایل همه‌کاره (لازم)", {"fields": ("apk", "download_url"),
                                   "description": "روی همه‌ی گوشی‌ها نصب می‌شود. دکمه‌ی اصلی دانلود سایت همین است."}),
        ("دو فایل سبک‌تر (اختیاری)", {"fields": ("apk_arm64", "url_arm64", "apk_32", "url_32"),
                                     "description": "به‌روزرسانی داخل اپ خودش فایل مناسب گوشی را می‌گیرد؛ در سایت هم به‌صورت دو پیوند کوچک می‌آیند."}),
        (None, {"fields": ("is_required", "is_published")}),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        clear_cache()
