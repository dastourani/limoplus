from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q, Sum
from django.template.response import TemplateResponse
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.filters import BookFKFilter
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


@admin.register(Note)
class NoteAdmin(ReadOnlyAdmin):
    list_display = ("user", "node", "color", "created_at", "is_archived")
    search_fields = ("user__phone",)


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
