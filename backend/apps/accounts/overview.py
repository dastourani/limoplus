"""«خلاصه» at the top of a user's page in the panel: what they can read, what they paid, how they study, and links to
the full lists (orders, access, reports, sessions) filtered to this user. Read-only: nothing here changes data."""

from datetime import timedelta

from django.db.models import Avg, Count, Max, Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from apps.catalog.jalali import jalali_date
from apps.catalog.panel_display import badges, fa_duration, fa_number


def _card(title, body, link=None):
    more = format_html('<a class="lp-ov-more" href="{}">{}</a>', link[0], link[1]) if link else ""
    return format_html('<section class="lp-ov-card"><h3>{}{}</h3>{}</section>', title, more, body)


def _rows(rows):
    if not rows:
        return format_html('<p class="lp-quiet">{}</p>', "هنوز چیزی نیست.")
    return format_html("<table class='lp-ov-table'>{}</table>", format_html_join("", "<tr>{}</tr>", (
        (format_html_join("", "<td>{}</td>", ((c,) for c in row)),) for row in rows)))


def _stat(label, value):
    return format_html('<div class="lp-ov-stat"><b>{}</b><span>{}</span></div>', value, label)


def _risk_stat(user):
    """«امتیاز خطر» from apps.guard (copies of lesson text, fingerprints found, device changes)."""
    from apps.guard.core import risk_of

    r = risk_of(user)
    color = {"high": "red", "mid": "yellow", "low": "green"}[r["level"]]
    value = format_html('<a href="{}">{}</a>', reverse("admin:guard_tracker_changelist"),
                        badges((f"{fa_number(r['score'])} از ۱۰۰", color)))
    return _stat("امتیاز خطر (کپی)", value)


def user_overview(user):
    from apps.commerce.admin import entitlement_left, entitlement_scope, entitlement_source, toman, when
    from apps.commerce.models import Entitlement, Order
    from apps.learning.models import QuizAnswer, Report
    from apps.study.models import ExamAttempt, FlashcardReview, Note, SectionProgress, StudyDay, StudyTime

    now = timezone.now()
    today = timezone.localdate()

    # What they can read.
    access = Entitlement.objects.filter(user=user).select_related("book", "major", "order", "granted_by").order_by("is_archived", "-created_at")[:12]
    access_rows = [(entitlement_scope(e), entitlement_left(e, now), entitlement_source(e)) for e in access]
    gift = reverse("admin:commerce_entitlement_add") + f"?user={user.pk}"
    access_card = _card("دسترسی‌ها", _rows(access_rows), (reverse("admin:commerce_entitlement_changelist") + f"?q={user.phone}", "همه"))

    # What they paid.
    orders = Order.objects.filter(user=user).order_by("-created_at")
    color = {Order.Status.PAID: "green", Order.Status.PENDING: "yellow", Order.Status.FAILED: "red"}
    order_rows = [(o.title, toman(o.amount), badges((o.get_status_display(), color.get(o.status, "grey"))), when(o.created_at))
                  for o in orders[:8]]
    paid = orders.filter(status=Order.Status.PAID).aggregate(n=Count("pk"), total=Sum("amount"))
    orders_card = _card(
        format_html("سفارش‌ها <span class='lp-quiet'>({} پرداخت‌شده، جمع {})</span>", fa_number(paid["n"]), toman(paid["total"] or 0)),
        _rows(order_rows), (reverse("admin:commerce_order_changelist") + f"?q={user.phone}", "همه"))

    # How they study.
    times = StudyTime.objects.filter(user=user)
    total = times.aggregate(s=Sum("seconds"))["s"]
    month = times.filter(day__gte=today - timedelta(days=30)).aggregate(s=Sum("seconds"))["s"]
    week = times.filter(day__gte=today - timedelta(days=7)).aggregate(s=Sum("seconds"))["s"]
    days = StudyDay.objects.filter(user=user)
    last_day = days.order_by("-date").values_list("date", flat=True).first()
    answers = QuizAnswer.objects.filter(user=user).aggregate(n=Count("pk"), right=Count("pk", filter=Q(was_correct=True)))
    exams = ExamAttempt.objects.filter(user=user, submitted_at__isnull=False).aggregate(n=Count("pk"), avg=Avg("score_percent"))
    stats = [
        _stat("کل زمان مطالعه", fa_duration(total)),
        _stat("۳۰ روز گذشته", fa_duration(month)),
        _stat("۷ روز گذشته", fa_duration(week)),
        _stat("روزهای مطالعه", fa_number(days.count())),
        _stat("آخرین روز مطالعه", jalali_date(last_day) if last_day else "—"),
        _stat("بخش‌های خوانده‌شده", fa_number(SectionProgress.objects.filter(user=user, is_done=True).count())),
        _stat("تست‌های پاسخ‌داده", fa_number(answers["n"]) + (
            f" ({fa_number(round(100 * answers['right'] / answers['n']))}٪ درست)" if answers["n"] else "")),
        _stat("آزمون‌ها", fa_number(exams["n"]) + (f" (میانگین {fa_number(round(exams['avg']))}٪)" if exams["avg"] is not None else "")),
        _stat("فلش‌کارت‌های در جعبه", fa_number(FlashcardReview.objects.filter(user=user).count())),
        _stat("یادداشت و هایلایت", fa_number(Note.objects.filter(user=user, is_archived=False).count())),
        _risk_stat(user),
    ]
    study_card = _card("مطالعه", format_html('<div class="lp-ov-stats">{}</div>', format_html_join("", "{}", ((x,) for x in stats))))

    # Books they are reading, newest first.
    books = (SectionProgress.objects.filter(user=user).values("book__title")
             .annotate(done=Count("pk", filter=Q(is_done=True)), opened=Count("pk"), last=Max("updated_at"))
             .order_by("-last")[:8])
    book_rows = [(b["book__title"], f"{fa_number(b['done'])} بخش خوانده، {fa_number(b['opened'])} بخش باز شده") for b in books]
    book_rows = [(r[0], r[1], jalali_date(b["last"])) for r, b in zip(book_rows, books)]
    reading_card = _card("کتاب‌هایی که می‌خواند", _rows(book_rows))

    reports = Report.objects.filter(user=user)
    links = format_html(
        '<p class="lp-ov-links"><a class="button" href="{}">هدیه دادن کتاب یا اشتراک</a> '
        '<a href="{}">گزارش‌های خطای او ({})</a>، <a href="{}">نشست‌ها</a>، <a href="{}">آزمون‌ها</a></p>',
        gift,
        reverse("admin:learning_report_changelist") + f"?q={user.phone}", fa_number(reports.count()),
        reverse("admin:accounts_devicesession_changelist") + f"?q={user.phone}",
        reverse("admin:study_examattempt_changelist") + f"?q={user.phone}",
    )
    return format_html('<div class="lp-ov">{}<div class="lp-ov-grid">{}{}{}{}</div></div>',
                       links, study_card, access_card, orders_card, reading_card)
