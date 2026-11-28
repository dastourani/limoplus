from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.db.models import BooleanField, OuterRef, Subquery, Value
from django.db.models.functions import Substr
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html

from apps.catalog import access
from apps.catalog.filters import BookFilter
from apps.catalog.jalali import fa_digits, jalali_datetime
from apps.catalog.models import ContentNode

from . import core
from .models import CopyEvent, GuardSettings, TraceHit, Tracker

LEVELS = {"high": ("زیاد", "#B33A3A"), "mid": ("متوسط", "#B7791F"), "low": ("کم", "#23864B")}


def _event_state(event: CopyEvent) -> str:
    if event.packed:
        return "متن ذخیره‌شده"
    return "نشانی دقیق" if core.is_exact(event) else "نسخه عوض شده"


def _book_titles_for_events(events) -> dict[str, str]:
    step = ContentNode.steplen
    roots = {e.node.path[:step] for e in events if e.node_id and e.node}
    if not roots:
        return {}
    return dict(
        ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, path__in=roots)
        .values_list("path", "title")
    )


def _format_event_for_user(event: CopyEvent, *, is_teacher_view: bool, book_titles: dict[str, str]) -> dict:
    book_title = "—"
    if event.node_id and event.node:
        book_title = book_titles.get(event.node.path[: ContentNode.steplen], "—")
    row_data = {
        "event": event,
        "book_title": book_title,
        "when": jalali_datetime(event.created_at),
        "text": core.text_of(event),
        "state": _event_state(event),
        "is_teacher_view": is_teacher_view,
    }
    if is_teacher_view:
        row_data["display_user"] = core.masked_user_label(event.user)
    return row_data


@admin.register(Tracker)
class TrackerAdmin(admin.ModelAdmin):
    """«ردیاب متن»: who copied a pasted text, Bale alerts & risk table (superuser), and teacher-scoped tracing."""

    @staticmethod
    def _teacher_can_trace(user) -> bool:
        return bool(access.is_book_teacher(user) and core.traceable_books(user).exists())

    def has_module_permission(self, request):
        return bool(
            access.acts_as_panel_superuser(request)
            or access.is_teacher_preview(request)
            or self._teacher_can_trace(request.user)
        )

    def has_view_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if obj is not None:
            return False
        return bool(access.is_teacher_preview(request) or self._teacher_can_trace(request.user))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        return super().changeform_view(request, object_id, form_url, extra_context)

    def history_view(self, request, object_id, extra_context=None):
        if not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        return super().history_view(request, object_id, extra_context)

    def delete_view(self, request, object_id, extra_context=None):
        if not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        return super().delete_view(request, object_id, extra_context)

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied

        is_admin = access.acts_as_panel_superuser(request)
        row = GuardSettings.get() if is_admin else None
        found = None
        pasted = ""

        # فقط مدیر کل می‌تواند تنظیمات هشدارهای بله را تغییر دهد
        if request.method == "POST" and "alerts" in request.POST:
            if not is_admin:
                raise PermissionDenied
            row.bale_alerts = request.POST["alerts"] == "on"
            row.save(update_fields=["bale_alerts"])
            messages.success(request, "هشدارهای بله روشن شد." if row.bale_alerts else "هشدارهای بله خاموش شد.")
            return redirect(request.path)

        if request.method == "POST":
            pasted = request.POST.get("text", "")[:20000]
            scoped_events = (
                CopyEvent.objects.all()
                if is_admin
                else core.scope_to_traceable_books(CopyEvent.objects.all(), request.user, "node__path")
            )
            result = core.trace(pasted, events=scoped_events)

            marked_events = result["marked"]
            similar_events = result["similar"]
            book_titles = (
                _book_titles_for_events(marked_events + similar_events)
                if (is_admin or access.is_teacher_preview(request))
                else dict(core.traceable_books(request.user).values_list("path", "title"))
            )

            for event in marked_events:
                TraceHit.objects.get_or_create(event=event, found_by=request.user)

            found = {
                "codes": result["codes"],
                "marked": [_format_event_for_user(e, is_teacher_view=not is_admin, book_titles=book_titles) for e in marked_events],
                "similar": [_format_event_for_user(e, is_teacher_view=not is_admin, book_titles=book_titles) for e in similar_events],
                "is_isolated_teacher": not is_admin,
            }

        step = ContentNode.steplen
        book_subquery = ContentNode.objects.filter(
            path=Substr(OuterRef("event__node__path"), 1, step),
            kind=ContentNode.Kind.BOOK,
            depth=1,
        ).values("title")[:1]
        recent_qs = (
            TraceHit.objects.select_related("event", "event__user", "event__node", "found_by")
            .annotate(_lp_book_title=Subquery(book_subquery))
            .order_by("-created_at", "-id")
        )
        recent_qs = core.scope_to_traceable_books(recent_qs, request.user, "event__node__path")[:20]

        recent_hits = []
        for hit in recent_qs:
            ev = hit.event
            if is_admin:
                display_user = str(ev.user) if ev and ev.user_id else "—"
                found_by_label = str(hit.found_by) if hit.found_by_id else "—"
            else:
                display_user = core.masked_user_label(ev.user if ev else None)
                if not hit.found_by_id:
                    found_by_label = "—"
                elif hit.found_by_id == request.user.id:
                    found_by_label = "شما"
                else:
                    found_by_label = core.masked_user_label(hit.found_by, fallback="همکار/مدیر")
            recent_hits.append({
                "hit": hit,
                "hit_url": reverse("admin:guard_tracehit_change", args=[hit.pk]),
                "book_title": getattr(hit, "_lp_book_title", None) or "—",
                "section_title": ev.node.title if ev and ev.node_id else "—",
                "user_id": ev.user_id if (is_admin and ev) else None,
                "display_user": display_user,
                "found_by_label": found_by_label,
                "when": jalali_datetime(hit.created_at),
                "note": hit.note or "—",
                "is_teacher_view": not is_admin,
            })

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
            "recent_hits": recent_hits,
            "risky": risky,
            "limit": core.DAILY_LIMIT,
        }
        return TemplateResponse(request, "admin/guard/tracker.html", context)


class TraceHitBookFilter(BookFilter):
    path_field = "event__node__path"


@admin.register(TraceHit)
class TraceHitAdmin(admin.ModelAdmin):
    """«تاریخچه ردیابی‌های متن»: سوابق اثرانگشت‌های کشف‌شده با ایزولاسیون کامل برای اساتید."""

    list_filter = (TraceHitBookFilter, "created_at")
    list_select_related = ("event", "event__user", "event__node", "event__revision", "found_by")

    def has_module_permission(self, request):
        return bool(
            access.acts_as_panel_superuser(request)
            or access.is_teacher_preview(request)
            or TrackerAdmin._teacher_can_trace(request.user)
        )

    def has_view_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if access.is_teacher_preview(request):
            return True
        if not request.user.is_active:
            return False
        if obj is not None:
            return core.can_view_event(request.user, obj.event)
        return TrackerAdmin._teacher_can_trace(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return access.acts_as_panel_superuser(request)

    def has_delete_permission(self, request, obj=None):
        return access.acts_as_panel_superuser(request)

    def _check_direct_object_access(self, request, object_id):
        if access.acts_as_panel_superuser(request) or access.is_teacher_preview(request):
            return
        if not (request.user.is_active and TrackerAdmin._teacher_can_trace(request.user)):
            raise PermissionDenied
        hit = TraceHit.objects.select_related("event__node").filter(pk=unquote(object_id)).first()
        if hit is not None and not core.can_view_event(request.user, hit.event):
            raise PermissionDenied

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if object_id:
            self._check_direct_object_access(request, object_id)
        return super().changeform_view(request, object_id, form_url, extra_context)

    def history_view(self, request, object_id, extra_context=None):
        self._check_direct_object_access(request, object_id)
        return super().history_view(request, object_id, extra_context)

    def get_queryset(self, request):
        step = ContentNode.steplen
        book_subquery = ContentNode.objects.filter(
            path=Substr(OuterRef("event__node__path"), 1, step),
            kind=ContentNode.Kind.BOOK,
            depth=1,
        ).values("title")[:1]
        qs = (
            super()
            .get_queryset(request)
            .select_related("event", "event__user", "event__node", "event__revision", "found_by")
            .annotate(
                _lp_book_title=Subquery(book_subquery),
                _lp_is_admin=Value(access.acts_as_panel_superuser(request), output_field=BooleanField()),
            )
        )
        return core.scope_to_traceable_books(qs, request.user, "event__node__path")

    def get_list_display(self, request):
        if access.acts_as_panel_superuser(request):
            return ("book_col", "section_col", "copied_user_col", "fingerprint_col", "found_by_col", "note_col", "when_col")
        return ("book_col", "section_col", "copied_user_col", "state_col", "found_by_col", "note_col", "when_col")

    def get_search_fields(self, request):
        if access.acts_as_panel_superuser(request):
            return ("event__code", "event__user__phone", "found_by__phone", "event__node__title", "note")
        return ("event__node__title", "note")

    def get_fields(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return (
                "book_col",
                "section_col",
                "copied_user_col",
                "event_link",
                "copied_text_col",
                "state_col",
                "fingerprint_col",
                "found_by_col",
                "note",
                "when_col",
            )
        return (
            "book_col",
            "section_col",
            "copied_user_col",
            "copied_text_col",
            "state_col",
            "found_by_col",
            "note",
            "when_col",
        )

    def get_readonly_fields(self, request, obj=None):
        ro = (
            "book_col",
            "section_col",
            "copied_user_col",
            "event_link",
            "copied_text_col",
            "state_col",
            "fingerprint_col",
            "found_by_col",
            "when_col",
        )
        if access.acts_as_panel_superuser(request):
            return ro
        return ro + ("note",)

    @admin.display(description="کتاب")
    def book_col(self, obj):
        title = getattr(obj, "_lp_book_title", None)
        if title:
            return title
        book = core.book_of_event(obj.event) if obj.event_id else None
        return book.title if book else "—"

    @admin.display(description="بخش")
    def section_col(self, obj):
        if obj.event_id and obj.event.node_id:
            return obj.event.node.title
        return "—"

    @admin.display(description="کاربر کپی‌کننده")
    def copied_user_col(self, obj):
        if not obj.event_id or not obj.event.user_id:
            return "—"
        user = obj.event.user
        if getattr(obj, "_lp_is_admin", False):
            url = reverse("admin:accounts_user_change", args=[user.pk])
            return format_html('<a href="{}"><b>{}</b></a>', url, user)
        return core.masked_user_label(user)

    @admin.display(description="ردیاب")
    def found_by_col(self, obj):
        if not obj.found_by_id:
            return "—"
        if getattr(obj, "_lp_is_admin", False):
            url = reverse("admin:accounts_user_change", args=[obj.found_by_id])
            return format_html('<a href="{}">{}</a>', url, obj.found_by)
        return core.masked_user_label(obj.found_by, fallback="همکار/مدیر")

    @admin.display(description="اثرانگشت")
    def fingerprint_col(self, obj):
        return obj.event.code if obj.event_id else "—"

    @admin.display(description="رویداد کپی")
    def event_link(self, obj):
        if not obj.event_id or not getattr(obj, "_lp_is_admin", False):
            return "—"
        url = reverse("admin:guard_copyevent_change", args=[obj.event_id])
        return format_html('<a href="{}">کپی #{} ({})</a>', url, obj.event_id, obj.event.code)

    @admin.display(description="متن کپی‌شده")
    def copied_text_col(self, obj):
        return core.text_of(obj.event) if obj.event_id else "—"

    @admin.display(description="وضعیت نشانه")
    def state_col(self, obj):
        return _event_state(obj.event) if obj.event_id else "—"

    @admin.display(description="یادداشت پیگیری")
    def note_col(self, obj):
        return obj.note or "—"

    @admin.display(description="زمان ردیابی", ordering="created_at")
    def when_col(self, obj):
        return jalali_datetime(obj.created_at)


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
        return access.acts_as_panel_superuser(request)

    def has_view_permission(self, request, obj=None):
        return access.acts_as_panel_superuser(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return access.acts_as_panel_superuser(request)

    def has_delete_permission(self, request, obj=None):
        return False
