from django.contrib import admin

from .models import FaqItem, SitePage, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """One row only: contact details, store links, the trust seal."""

    fieldsets = (
        ("صفحه‌ی اول", {"fields": ("tagline", "audience", "intro")}),
        ("دانلود", {"fields": ("bazaar_url", "myket_url", "apk_url")}),
        ("تماس", {"fields": ("email", "phone", "address", "telegram_url", "instagram_url")}),
        ("اینماد", {"fields": ("enamad_html",)}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FaqItem)
class FaqItemAdmin(admin.ModelAdmin):
    list_display = ("question", "order", "is_hidden")
    list_editable = ("order", "is_hidden")

    def has_delete_permission(self, request, obj=None):
        return False
