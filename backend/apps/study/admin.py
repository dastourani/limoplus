from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Q, Sum
from django.template.response import TemplateResponse
from django.utils import timezone

from apps.accounts.models import DeviceSession, User
from apps.catalog.models import ContentNode
from apps.commerce.models import Entitlement, Order
from apps.learning.models import Question, QuizAnswer, Report

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
    list_filter = ("is_done", "book")
    search_fields = ("user__phone",)


@admin.register(ExamAttempt)
class ExamAttemptAdmin(ReadOnlyAdmin):
    list_display = ("user", "node", "started_at", "correct", "wrong", "blank", "score_percent", "negative_marking")
    list_filter = ("negative_marking",)
    search_fields = ("user__phone",)


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
        now = timezone.now()
        today = timezone.localdate()
        days = [today - timedelta(days=i) for i in range(13, -1, -1)]
        users = User.objects.all()
        paid = Order.objects.filter(status=Order.Status.PAID)
        daily = {
            row["date"]: row
            for row in Dashboard.objects.filter(date__gte=days[0])
            .values("date")
            .annotate(users=Count("user", distinct=True), answers=Sum("answers"), sections=Sum("sections"), cards=Sum("cards"))
        }
        signups = {
            row["d"]: row["n"]
            for row in users.filter(date_joined__date__gte=days[0]).extra(select={"d": "date(date_joined)"}).values("d").annotate(n=Count("id"))
        }
        revenue = {
            row["d"]: row["s"]
            for row in paid.filter(paid_at__date__gte=days[0]).extra(select={"d": "date(paid_at)"}).values("d").annotate(s=Sum("amount"))
        }
        chart = []
        peak = 1
        for d in days:
            row = daily.get(d, {})
            item = {
                "date": d,
                "active": row.get("users") or 0,
                "answers": row.get("answers") or 0,
                "sections": row.get("sections") or 0,
                "signups": signups.get(d) or signups.get(str(d)) or 0,
                "revenue": revenue.get(d) or revenue.get(str(d)) or 0,
            }
            peak = max(peak, item["active"])
            chart.append(item)
        for item in chart:
            item["bar"] = round(item["active"] / peak * 100)

        books = []
        for book in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_archived=False):
            readers = SectionProgress.objects.filter(book=book).values("user").distinct().count()
            buyers = Entitlement.objects.filter(book=book, is_archived=False).count()
            sales = paid.filter(book=book).aggregate(s=Sum("amount"))["s"] or 0
            books.append({"title": book.title, "readers": readers, "buyers": buyers, "sales": sales})
        books.sort(key=lambda b: -b["readers"])

        hardest = (
            Question.objects.filter(answer_count__gte=10, is_archived=False)
            .extra(select={"rate": "CAST(correct_count AS FLOAT) / answer_count"})
            .order_by("rate")[:10]
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "داشبورد آمار",
            "opts": self.model._meta,
            "cards": [
                ("کاربران", users.count()),
                ("ثبت‌نام ۷ روز اخیر", users.filter(date_joined__gte=now - timedelta(days=7)).count()),
                ("فعال امروز", daily.get(today, {}).get("users") or 0),
                ("دستگاه‌های فعال", DeviceSession.objects.filter(revoked_at__isnull=True, expires_at__gt=now, last_seen_at__gte=now - timedelta(days=7)).count()),
                ("پاسخ به تست (کل)", QuizAnswer.objects.count()),
                ("آزمون‌های انجام‌شده", ExamAttempt.objects.filter(submitted_at__isnull=False).count()),
                ("فروش کل (تومان)", f'{paid.aggregate(s=Sum("amount"))["s"] or 0:,}'),
                ("فروش ۳۰ روز (تومان)", f'{paid.filter(paid_at__gte=now - timedelta(days=30)).aggregate(s=Sum("amount"))["s"] or 0:,}'),
                ("اشتراک‌های فعال", Entitlement.active_for_any(now).filter(book__isnull=True).count()),
                ("گزارش‌های باز", Report.objects.filter(status=Report.Status.OPEN).count()),
            ],
            "chart": chart,
            "books": books,
            "hardest": [{"id": q.id, "text": str(q), "rate": round(q.rate * 100), "n": q.answer_count} for q in hardest],
        }
        return TemplateResponse(request, "admin/study/dashboard.html", context)
