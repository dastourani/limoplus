from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Substr
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.accounts.models import User
from apps.catalog.filters import BookFKFilter, NodeBookFilter, NodeChapterFilter, YesNoFilter
from apps.catalog.models import ContentNode

from .models import Dashboard, ExamAttempt, Note, SectionProgress


class ReadOnlyAdmin(admin.ModelAdmin):
    """Learner data is shown to admins but never edited or deleted from the admin."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SectionProgress)
class SectionProgressAdmin(ReadOnlyAdmin):
    list_display = ("user", "node", "book", "percent", "is_done", "updated_at")
    list_filter = ("is_done", BookFKFilter)
    search_fields = ("user__phone",)


@admin.register(ExamAttempt)
class ExamAttemptAdmin(ReadOnlyAdmin):
    list_display = ("user", "node", "started_at", "result", "score")
    list_filter = ("negative_marking",)
    search_fields = ("user__phone",)

    @admin.display(description="نتیجه")
    def result(self, obj):
        from apps.catalog.jalali import fa_digits

        return fa_digits(f"{obj.correct} درست · {obj.wrong} غلط · {obj.blank} نزده") + ("" if obj.negative_marking else " (بدون نمره‌ی منفی)")

    @admin.display(description="درصد", ordering="score_percent")
    def score(self, obj):
        from apps.catalog.panel_display import badges, fa_number

        if obj.score_percent is None:
            return badges(("ناتمام", "grey"))
        color = "green" if obj.score_percent >= 70 else "yellow" if obj.score_percent >= 40 else "red"
        return badges((f"{fa_number(round(obj.score_percent))}٪", color))


class NoteHasBodyFilter(YesNoFilter):
    title = "یادداشت متنی"
    parameter_name = "has_body"

    def yes(self, qs):
        return qs.exclude(body="")

    def no(self, qs):
        return qs.filter(body="")


NOTE_BG = {"yellow": "#FFF6C2", "green": "#E3F6EB", "blue": "#E8F0FF", "pink": "#FFE6EE"}
NOTE_BORDER = {"yellow": "#E5B800", "green": "#2F7D4F", "blue": "#3B6FD8", "pink": "#D6457A"}
COLOR_FA = {"yellow": "زرد", "green": "سبز", "blue": "آبی", "pink": "صورتی"}


@admin.register(Note)
class NoteAdmin(ReadOnlyAdmin):
    change_list_template = "admin/study/note/change_list.html"
    list_display = ("content_col", "place_col", "who_col", "kind_col")
    list_filter = (NodeBookFilter, NodeChapterFilter, NoteHasBodyFilter, "color", "mode", "is_archived")
    search_fields = ("user__phone", "quote", "body", "node__title")
    list_per_page = 40

    def get_queryset(self, request):
        step = ContentNode.steplen
        book = ContentNode.objects.filter(path=Substr(OuterRef("node__path"), 1, step))
        chapter = ContentNode.objects.filter(path=Substr(OuterRef("node__path"), 1, 2 * step), kind=ContentNode.Kind.CHAPTER)
        return (
            super()
            .get_queryset(request)
            .select_related("user", "node")
            .annotate(
                p_book=Subquery(book.values("title")[:1]),
                p_chapter_pos=Subquery(chapter.values("position")[:1]),
                p_chapter_title=Subquery(chapter.values("title")[:1]),
            )
            .order_by("-created_at", "-id")
        )

    @admin.display(description="متن هایلایت و یادداشت")
    def content_col(self, obj):
        from apps.catalog.panel_display import tex

        bg = NOTE_BG.get(obj.color, "#FFF6C2")
        bd = NOTE_BORDER.get(obj.color, "#E5B800")
        quote_html = (
            format_html(
                '<div style="padding:5px 9px;border-right:3px solid {};background:{};border-radius:6px;margin-bottom:4px">{}</div>',
                bd, bg, tex(obj.quote, 220),
            )
            if obj.quote
            else ""
        )
        body_html = format_html('<div style="margin-top:2px"><b>یادداشت:</b> {}</div>', tex(obj.body, 220)) if obj.body else ""
        return format_html('<div style="min-width:260px;max-width:520px">{}{}</div>', quote_html, body_html or ("" if quote_html else "—"))

    @admin.display(description="جا (کتاب › فصل › بخش)")
    def place_col(self, obj):
        from apps.catalog.jalali import fa_digits

        book = obj.p_book or "بدون کتاب"
        chapter = f"فصل {fa_digits(obj.p_chapter_pos)}" if obj.p_chapter_pos else (obj.p_chapter_title or "")
        section = obj.node.title if obj.node.kind == "section" else "مقدمه‌ی فصل"
        filter_url = f"?node__id__exact={obj.node_id}"
        return format_html(
            '<div class="lp-quiet">{} › {}</div><div><a href="{}" title="فیلتر روی همین بخش"><b>{}</b></a></div>',
            book, chapter, filter_url, section,
        )

    @admin.display(description="کاربر و زمان", ordering="created_at")
    def who_col(self, obj):
        from apps.catalog.jalali import jalali_datetime

        user_url = reverse("admin:accounts_user_change", args=[obj.user_id])
        filter_url = f"?user__id__exact={obj.user_id}"
        return format_html(
            '<div><a href="{}"><b>{}</b></a> · <a href="{}" class="lp-quiet">فیلتر کاربر</a></div>'
            '<div class="lp-quiet" style="white-space:nowrap">{}</div>',
            user_url, obj.user.phone, filter_url, jalali_datetime(obj.created_at),
        )

    @admin.display(description="نوع و رنگ")
    def kind_col(self, obj):
        from apps.catalog.panel_display import badges

        return badges(
            ("یادداشت", "blue") if obj.body else ("هایلایت", "yellow"),
            (COLOR_FA.get(obj.color, obj.color), "grey"),
            ("چکیده", "green") if obj.mode == "summary" else ("درسنامه", "grey"),
            obj.is_archived and ("حذف‌شده", "red"),
        )

    def changelist_view(self, request, extra_context=None):
        from apps.catalog.panel_display import fa_number

        week_ago = timezone.now() - timedelta(days=7)
        active = Note.objects.filter(is_archived=False)
        step = ContentNode.steplen
        book_sq = ContentNode.objects.filter(path=Substr(OuterRef("node__path"), 1, step))

        sec_rows = (
            active.values("node_id", "node__title", "node__path")
            .annotate(
                book_title=Subquery(book_sq.values("title")[:1]),
                total=Count("id"),
                learners=Count("user_id", distinct=True),
                notes_n=Count("id", filter=~Q(body="")),
            )
            .order_by("-total")[:8]
        )
        top_sections = []
        for r in sec_rows:
            sample_q = (
                active.filter(node_id=r["node_id"])
                .exclude(quote="")
                .values("quote")
                .annotate(c=Count("id"))
                .order_by("-c")
                .first()
            )
            top_sections.append({
                "node_id": r["node_id"],
                "book": r["book_title"] or "",
                "section": r["node__title"],
                "total": fa_number(r["total"]),
                "learners": fa_number(r["learners"]),
                "notes_n": fa_number(r["notes_n"]),
                "sample": (sample_q["quote"][:90] + ("…" if len(sample_q["quote"]) > 90 else "")) if sample_q else "",
            })

        user_rows = (
            active.values("user_id", "user__phone")
            .annotate(
                total=Count("id"),
                week=Count("id", filter=Q(created_at__gte=week_ago)),
                notes_n=Count("id", filter=~Q(body="")),
            )
            .order_by("-week", "-total")[:8]
        )
        top_users = [
            {
                "user_id": r["user_id"],
                "phone": r["user__phone"],
                "user_url": reverse("admin:accounts_user_change", args=[r["user_id"]]),
                "total": fa_number(r["total"]),
                "week": fa_number(r["week"]),
                "notes_n": fa_number(r["notes_n"]),
            }
            for r in user_rows
        ]

        filtered_user = request.GET.get("user__id__exact")
        filtered_node = request.GET.get("node__id__exact")
        ctx = {
            **(extra_context or {}),
            "top_sections": top_sections,
            "top_users": top_users,
            "has_active_filter": bool(filtered_user or filtered_node or request.GET.get("q") or request.GET.get("book")),
        }
        return super().changelist_view(request, extra_context=ctx)


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from .dashboard import build

        context = {**self.admin_site.each_context(request), "title": "داشبورد آمار", "opts": self.model._meta, **build()}
        return TemplateResponse(request, "admin/study/dashboard.html", context)


def _hms(seconds: int) -> str:
    """Exact time for the owner: «۴ ساعت و ۲۰ دقیقه و ۱۵ ثانیه»."""
    from apps.catalog.jalali import fa_digits

    h, rest = divmod(int(seconds or 0), 3600)
    m, s = divmod(rest, 60)
    parts = [f"{h} ساعت" if h else "", f"{m} دقیقه" if m else "", f"{s} ثانیه" if s or not (h or m) else ""]
    return fa_digits(" و ".join(p for p in parts if p))


from .models import StudyTime  # noqa: E402


@admin.register(StudyTime)
class StudyTimeAdmin(ReadOnlyAdmin):
    """«زمان مطالعه»: the most active learners, one learner in detail (?user=…), and the average time per section of
    a book (?book=…) to see which parts take longest."""

    def changelist_view(self, request, extra_context=None):
        from apps.catalog.jalali import jalali_date

        today = timezone.localdate()
        week = today - timedelta(days=6)
        ctx = {**self.admin_site.each_context(request), "title": "زمان مطالعه", "opts": self.model._meta}
        user_id = request.GET.get("user")
        book_slug = request.GET.get("book")
        if user_id and user_id.isdigit():
            u = User.objects.filter(pk=int(user_id)).first()
            rows = StudyTime.objects.filter(user=u)
            ctx["person"] = u
            ctx["person_total"] = _hms(rows.aggregate(s=Sum("seconds"))["s"] or 0)
            ctx["by_book"] = [
                {"title": t, "time": _hms(s)} for t, s in rows.values_list("book__title").annotate(s=Sum("seconds")).order_by("-s").values_list("book__title", "s")
            ]
            ctx["by_kind"] = [
                {"kind": StudyTime.Kind(k).label, "time": _hms(s)} for k, s in rows.values_list("kind").annotate(s=Sum("seconds")).order_by("-s").values_list("kind", "s")
            ]
            chapters = {}
            for path, s in rows.values_list("node__path").annotate(s=Sum("seconds")).values_list("node__path", "s"):
                chapters[path[: ContentNode.steplen * 2]] = chapters.get(path[: ContentNode.steplen * 2], 0) + s
            names = {n.path: n for n in ContentNode.objects.filter(path__in=list(chapters))}
            ctx["by_chapter"] = sorted(
                ({"title": f"{names[p].get_parent().title}، {names[p].title}" if p in names and names[p].depth > 1 else (names[p].title if p in names else "؟"), "seconds": s, "time": _hms(s)} for p, s in chapters.items()),
                key=lambda r: -r["seconds"],
            )
            ctx["by_day"] = [
                {"day": jalali_date(d), "time": _hms(s)}
                for d, s in rows.filter(day__gte=today - timedelta(days=29)).values_list("day").annotate(s=Sum("seconds")).order_by("-day").values_list("day", "s")
            ]
        elif book_slug:
            book = ContentNode.objects.filter(depth=1, slug=book_slug).first()
            rows = StudyTime.objects.filter(book=book)
            per = rows.values("node_id", "node__title", "node__path").annotate(s=Sum("seconds"), people=Count("user", distinct=True)).order_by("node__path")
            ctx["book"] = book
            ctx["sections"] = [{"title": r["node__title"], "people": r["people"], "average": _hms(r["s"] // max(1, r["people"])), "total": _hms(r["s"])} for r in per]
        users = (
            StudyTime.objects.values("user_id", "user__phone", "user__first_name", "user__last_name")
            .annotate(total=Sum("seconds"), week=Sum("seconds", filter=Q(day__gte=week)))
            .order_by("-total")[:100]
        )
        last = dict(StudyTime.objects.values_list("user_id").annotate(d=models_max("day")).values_list("user_id", "d"))
        ctx["users"] = [
            {"id": r["user_id"], "phone": r["user__phone"], "name": f"{r['user__first_name']} {r['user__last_name']}".strip(),
             "total": _hms(r["total"]), "week": _hms(r["week"] or 0), "last": jalali_date(last.get(r["user_id"])) if last.get(r["user_id"]) else ""}
            for r in users
        ]
        ctx["books"] = ContentNode.objects.filter(depth=1, kind=ContentNode.Kind.BOOK, is_archived=False).order_by("title")
        return TemplateResponse(request, "admin/study/study_time.html", ctx)


def models_max(field):
    from django.db.models import Max

    return Max(field)
