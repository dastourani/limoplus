from django.contrib import admin

from django import forms
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.jalali import jalali_date as fa_date

from .models import FaqItem, HelpPage, SiteNavItem, SitePage, SiteSettings, TeacherApplication, TeacherInvitation


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    """One row only: contact details, store links, the trust seal."""

    fieldsets = (
        ("صفحه‌ی اول", {"fields": ("tagline", "audience", "intro", "show_updates", "show_sample_test", "show_home_faq")}),
        ("باکس‌های معرفی صفحه‌ی اول", {"fields": (
            "features_title", "features_sub",
            "feat1_title", "feat1_body",
            "feat2_title", "feat2_body",
            "feat3_title", "feat3_body",
            "feat4_title", "feat4_body",
        )}),
        ("بخش میانی و فوتر", {"fields": ("band_title", "band_sub", "footer_about")}),
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
        fields = ("slug", "title", "order", "show_in_nav", "show_in_footer", "show_in_app", "body")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "order" in self.fields:
            self.fields["order"].required = False

    def clean_order(self):
        val = self.cleaned_data.get("order")
        return val if val is not None else (self.instance.order if self.instance and self.instance.pk else 10)


@admin.register(SitePage)
class SitePageAdmin(admin.ModelAdmin):
    form = SitePageForm
    list_display = ("title", "slug", "order", "show_in_nav", "show_in_footer", "show_in_app", "changed", "important")
    list_editable = ("order", "show_in_nav", "show_in_footer", "show_in_app")
    readonly_fields = ("important_at_fa",)
    fields = ("slug", "title", "order", "show_in_nav", "show_in_footer", "show_in_app", "body", "important", "important_at_fa")

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


@admin.register(SiteNavItem)
class SiteNavItemAdmin(admin.ModelAdmin):
    list_display = ("title", "parent", "url", "order", "is_hidden")
    list_editable = ("parent", "url", "order", "is_hidden")
    fields = ("parent", "title", "url", "order", "is_hidden")


@admin.register(TeacherApplication)
class TeacherApplicationAdmin(admin.ModelAdmin):
    """A superuser-only review queue; decisions never create staff or grant book access."""

    list_display = ("name", "phone", "book_or_link", "status", "submitted_at", "reviewed_by", "reviewed_at", "invite_action")
    list_filter = ("status",)
    search_fields = ("name", "phone", "book_or_link", "explanation", "sample_work")
    ordering = ("-submitted_at", "-pk")
    date_hierarchy = "submitted_at"
    list_per_page = 50
    actions = None
    fields = (
        "name", "phone", "book_or_link", "explanation", "sample_work",
        "status", "review_note", "submitted_at", "reviewed_by", "reviewed_at",
    )
    readonly_fields = ("name", "phone", "book_or_link", "explanation", "sample_work", "submitted_at", "reviewed_by", "reviewed_at")

    @admin.display(description="دعوت استاد")
    def invite_action(self, obj):
        if obj.status != TeacherApplication.Status.APPROVED:
            return "—"
        url = reverse("admin:website_teacherinvitation_add") + f"?application={obj.pk}"
        return format_html('<a class="button" href="{}">دعوت با قابلیت محدود</a>', url)

    @staticmethod
    def _is_manager(request):
        user = request.user
        return user.is_active and user.is_staff and user.is_superuser

    def has_module_permission(self, request):
        return self._is_manager(request)

    def has_view_permission(self, request, obj=None):
        return self._is_manager(request)

    def has_add_permission(self, request):
        # Only the public form creates submissions; keep the queue append-only.
        return False

    def has_change_permission(self, request, obj=None):
        return self._is_manager(request)

    def has_delete_permission(self, request, obj=None):
        # Preserve applications and Django's change log for audit.
        return False

    def save_model(self, request, obj, form, change):
        if change:
            previous = TeacherApplication.objects.only("status", "review_note").get(pk=obj.pk)
            now = timezone.now()
            if previous.status != obj.status or previous.review_note != obj.review_note:
                obj.reviewed_by = request.user
                obj.reviewed_at = now
            if previous.status == TeacherApplication.Status.APPROVED and obj.status != TeacherApplication.Status.APPROVED:
                TeacherInvitation.objects.filter(
                    application=obj, status=TeacherInvitation.Status.ISSUED
                ).update(
                    status=TeacherInvitation.Status.REVOKED,
                    revoked_by=request.user,
                    revoked_at=now,
                    revocation_reason="درخواست استاد از وضعیت تأیید خارج شد.",
                )
        super().save_model(request, obj, form, change)


# The separate workflow admins are imported after the existing site settings and application queue are registered.
from . import workflow_admin  # noqa: F401,E402
