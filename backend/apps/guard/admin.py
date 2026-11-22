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


def _mask_phone(phone: str) -> str:
    """ماسک کردن شماره تماس کاربر برای حفظ حریم خصوصی: 0912***3456"""
    if not phone or len(phone) < 7:
        return "کاربر لیموخوان"
    return phone[:4] + "***" + phone[-4:]


def _format_event_for_user(event: CopyEvent, request_user) -> dict:
    row_data = _row(event)
    if not request_user.is_superuser:
        # برای اساتید، هویت کاربر به شکل ماسک‌شده ایمن ارائه می‌شود
        masked = _mask_phone(event.user.phone)
        full_name = f"{event.user.first_name} {event.user.last_name}".strip()
        display_user = f"{full_name} ({masked})" if full_name else masked
        row_data["display_user"] = display_user
        row_data["is_teacher_view"] = True
    else:
        row_data["is_teacher_view"] = False
    return row_data


@admin.register(Tracker)
class TrackerAdmin(admin.ModelAdmin):
    """«ردیاب متن»: who copied a pasted text, the Bale alerts switch, and the riskiest accounts."""

    def has_module_permission(self, request):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        from apps.catalog.access import is_book_teacher
        return bool(request.user.is_active and request.user.is_superuser)

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied

        is_admin = request.user.is_superuser
        row = GuardSettings.get() if is_admin else None
        found = None
        pasted = ""

        # فقط مدیر کل می‌تواند تنظیمات هشدارهای بله را تغییر دهد
        if is_admin and request.method == "POST" and "alerts" in request.POST:
            row.bale_alerts = request.POST["alerts"] == "on"
            row.save(update_fields=["bale_alerts"])
            messages.success(request, "هشدارهای بله روشن شد." if row.bale_alerts else "هشدارهای بله خاموش شد.")
            return redirect(request.path)

        if request.method == "POST":
            pasted = request.POST.get("text", "")[:20000]
            result = core.trace(pasted)

            marked_events = result["marked"]
            similar_events = result["similar"]

            # ایزولاسیون کامل برای استاد: فقط کپی‌های مربوط به کتاب‌های خودش نمایش داده می‌شود
            if not is_admin:
                from apps.catalog.access import book_editor_ids
                from apps.catalog.models import ContentNode

                my_book_ids = set(book_editor_ids(request.user).values_list("book_id", flat=True))
                
                def _is_my_book(event):
                    if not event.node:
                        return False
                    root_path = event.node.path[:ContentNode.steplen]
                    root_book = ContentNode.objects.filter(path=root_path, kind=ContentNode.Kind.BOOK, depth=1).first()
                    return root_book and root_book.id in my_book_ids

                marked_events = [e for e in marked_events if _is_my_book(e)]
                similar_events = [e for e in similar_events if _is_my_book(e)]

            for event in marked_events:
                TraceHit.objects.get_or_create(event=event, found_by=request.user)

            found = {
                "codes": result["codes"],
                "marked": [_format_event_for_user(e, request.user) for e in marked_events],
                "similar": [_format_event_for_user(e, request.user) for e in similar_events],
                "total_matched_raw": len(result["marked"]) + len(result["similar"]),
                "is_isolated_teacher": not is_admin,
            }

        risky = []
        if is_admin:
            for r in core.risk_table()[:50]:
                label, color = LEVELS[r["level"]]
                for key in ("copies_7d", "full_days_30d", "sections_7d", "hits", "new_devices_7d"):
                    r[key] = fa_digits(r[key])
                r["badge"] = format_html('<b style="color:{}">{} ({})</b>', color, fa_digits(r["score"]), label)
                risky.append(r)

        from apps.catalog.backups import bale_ready

        page_title = "ردیاب متن" if is_admin else "ردیاب محتوای من (حفاظت اثر)"
        context = {
            **self.admin_site.each_context(request),
            "title": page_title,
            "opts": self.model._meta,
            "is_admin": is_admin,
            "alerts_on": row.bale_alerts if row else False,
            "bale_ready": bale_ready() if is_admin else False,
            "found": found,
            "pasted": pasted,
            "risky": risky,
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
