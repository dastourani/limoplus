from django.contrib import admin

from .models import AppRelease
from .service import clear_cache


@admin.register(AppRelease)
class AppReleaseAdmin(admin.ModelAdmin):
    list_display = ("build", "channel", "version_name", "platform", "is_required", "is_published", "created_at")
    list_filter = ("channel", "platform", "is_required", "is_published")
    fieldsets = (
        (None, {"fields": ("platform", "channel", "build", "version_name", "notes")}),
        ("فایل همه‌کاره (لازم)", {"fields": ("apk", "download_url"),
                                   "description": "روی همه‌ی گوشی‌ها نصب می‌شود. دکمه‌ی اصلی دانلود سایت همین است."}),
        ("دو فایل سبک‌تر (اختیاری)", {"fields": ("apk_arm64", "url_arm64", "apk_32", "url_32"),
                                     "description": "به‌روزرسانی داخل اپ خودش فایل مناسب گوشی را می‌گیرد؛ در سایت هم به‌صورت دو پیوند کوچک می‌آیند."}),
        (None, {"fields": ("is_required", "is_published")}),
    )

    change_list_template = "admin/releases/apprelease/change_list.html"

    def get_urls(self):
        from django.db import transaction
        from django.urls import path

        urls = super().get_urls()
        custom_urls = [
            path(
                "sync-github/",
                transaction.non_atomic_requests(self.admin_site.admin_view(self.sync_github_view)),
                name="releases_apprelease_sync_github",
            ),
        ]
        return custom_urls + urls

    def sync_github_view(self, request):
        from django.contrib import messages
        from django.shortcuts import redirect
        from .github_sync import sync_release_from_github

        if request.method == "POST":
            rel, msg = sync_release_from_github(download_files=False)
            if rel:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
        return redirect("..")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        clear_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        clear_cache()
