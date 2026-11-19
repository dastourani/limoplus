from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.html import format_html

from apps.catalog.jalali import fa_digits, jalali_datetime

from . import core
from .models import CopyEvent, GuardSettings, TraceHit, Tracker

LEVELS = {"high": ("زیاد", "#B33A3A"), "mid": ("متوسط", "#B7791F"), "low": ("کم", "#23864B")}


def _row(event: CopyEvent) -> dict:
    exact = core.is_exact(event) if not event.packed else None
    return {
        "event": event,
        "when": jalali_datetime(event.created_at),
        "text": core.text_of(event),
        "state": "متن ذخیره‌شده" if event.packed else ("نشانی دقیق" if exact else "نسخه عوض شده"),
    }


@admin.register(Tracker)
class TrackerAdmin(admin.ModelAdmin):
    """«ردیاب متن»: who copied a pasted text, the Bale alerts switch, and the riskiest accounts."""

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        row = GuardSettings.get()
        found = None
        pasted = ""
        if request.method == "POST" and "alerts" in request.POST:
            row.bale_alerts = request.POST["alerts"] == "on"
            row.save(update_fields=["bale_alerts"])
            messages.success(request, "هشدارهای بله روشن شد." if row.bale_alerts else "هشدارهای بله خاموش شد.")
            return redirect(request.path)
        if request.method == "POST":
            pasted = request.POST.get("text", "")[:20000]
            result = core.trace(pasted)
            for event in result["marked"]:
                TraceHit.objects.get_or_create(event=event, found_by=request.user)
            found = {"codes": result["codes"], "marked": [_row(e) for e in result["marked"]],
                     "similar": [_row(e) for e in result["similar"]]}
        from apps.catalog.backups import bale_ready

        risky = []
        for r in core.risk_table()[:50]:
            label, color = LEVELS[r["level"]]
            for key in ("copies_7d", "full_days_30d", "sections_7d", "hits", "new_devices_7d"):
                r[key] = fa_digits(r[key])
            r["badge"] = format_html('<b style="color:{}">{} ({})</b>', color, fa_digits(r["score"]), label)
            risky.append(r)
        context = {
            **self.admin_site.each_context(request), "title": "ردیاب متن", "opts": self.model._meta,
            "alerts_on": row.bale_alerts, "bale_ready": bale_ready(), "found": found, "pasted": pasted, "risky": risky,
            "limit": core.DAILY_LIMIT,
        }
        return TemplateResponse(request, "admin/guard/tracker.html", context)


@admin.register(CopyEvent)
class CopyEventAdmin(admin.ModelAdmin):
    list_display = ("user", "node", "when", "length", "platform", "code")
    list_filter = ("platform", "mode")
    search_fields = ("user__phone", "code")
    readonly_fields = ("user", "node", "revision", "mode", "start", "end", "length", "platform", "code", "created_at", "text")
    exclude = ("packed", "text_hash")

    @admin.display(description="زمان", ordering="created_at")
    def when(self, obj):
        return jalali_datetime(obj.created_at)

    @admin.display(description="متن کپی‌شده")
    def text(self, obj):
        return core.text_of(obj)

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False
