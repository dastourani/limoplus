from django.contrib import admin

from django import forms
from django.utils import timezone

from apps.catalog.jalali import jalali_date as fa_date

from .models import FaqItem, HelpPage, SitePage, SiteSettings


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


class SitePageForm(forms.ModelForm):
    important = forms.BooleanField(
        label="این تغییر مهم است",
        required=False,
        help_text="کاربرانی که این صفحه را از این به بعد باز نکرده‌اند، در اپ پیام «… به‌روز شد» می‌بینند. برای غلط‌گیری و تغییر کوچک نزنید.",
    )

    class Meta:
        model = SitePage
        fields = ("slug", "title", "body", "show_in_app")


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    form = SitePageForm
    list_display = ("title", "slug", "show_in_app", "changed", "important")
    list_editable = ("show_in_app",)
    readonly_fields = ("important_at_fa",)
    fields = ("slug", "title", "body", "show_in_app", "important", "important_at_fa")

    @admin.display(description="آخرین تغییر")
    def changed(self, obj):
        return fa_date(obj.updated_at)

    @admin.display(description="آخرین تغییر مهم")
    def important(self, obj):
        return fa_date(obj.important_at) if obj.important_at else "—"

    @admin.display(description="آخرین تغییر مهم")
    def important_at_fa(self, obj):
        return fa_date(obj.important_at) if obj and obj.important_at else "—"

    def save_model(self, request, obj, form, change):
        if form.cleaned_data.get("important"):
            obj.important_at = timezone.now()
        super().save_model(request, obj, form, change)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "body" in form.base_fields:
            form.base_fields["body"].widget.attrs.update({"data-md-editor": "1", "rows": 18})
        return form


@admin.register(HelpPage)
class HelpPageAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_hidden", "changed")
    list_editable = ("order", "is_hidden")
    fields = ("title", "body", "order", "is_hidden")

    @admin.display(description="آخرین تغییر")
    def changed(self, obj):
        return fa_date(obj.updated_at)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # The lesson editor (toolbar, formulas, live preview) on the text box.
        form.base_fields["body"].widget.attrs.update({"data-md-editor": "1", "rows": 18})
        return form

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FaqItem)
class FaqItemAdmin(admin.ModelAdmin):
    list_display = ("question", "order", "is_hidden")
    list_editable = ("order", "is_hidden")

    def has_delete_permission(self, request, obj=None):
        return False
