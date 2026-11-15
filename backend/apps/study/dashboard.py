"""The panel's «داشبورد آمار»: this week against the week before, a 30-day chart (active learners, sign-ups, study
time), the days that had any activity, books and the hardest tests. Everything is counted in a fixed number of
queries, whatever the number of users or books; days are local (Tehran) days."""

from datetime import timedelta

from django.db.models import Count, F, FloatField, Q, Sum
from django.db.models.functions import Cast, TruncDate
from django.utils import timezone

from apps.catalog.jalali import fa_digits, to_jalali
from apps.catalog.panel_display import fa_number, short_text

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]  # date.weekday(): Monday = 0
DAYS = 30


def day_label(d, weekday=False) -> str:
    """«۲۵ آبان», or «یکشنبه ۲۵ آبان»."""
    _, m, dd = to_jalali(d.year, d.month, d.day)
    text = f"{fa_digits(dd)} {MONTHS[m - 1]}"
    return f"{WEEKDAYS[d.weekday()]} {text}" if weekday else text


def change(now: float, before: float, shown_before: str | None = None) -> dict:
    """This week against the week before: arrow, percent and colour (more is better for every number here). Nothing
    this week is said plainly («هفته‌ی قبل: ۵») instead of a red «▼ ۱۰۰٪»."""
    if not before:
        return {"text": "", "color": "grey"}
    if not now:
        return {"text": f"هفته‌ی قبل: {shown_before or fa_number(before)}", "color": "grey"}
    pct = round(100 * (now - before) / before)
    if pct == 0:
        return {"text": "مثل هفته‌ی قبل", "color": "grey"}
    arrow = "▲" if pct > 0 else "▼"
    return {"text": f"{arrow} {fa_number(abs(pct))}٪ نسبت به هفته‌ی قبل", "color": "green" if pct > 0 else "red"}


def minutes(seconds) -> str:
    seconds = int(seconds or 0)
    if not seconds:
        return "—"
    if seconds < 60:
        return "کمتر از ۱ دقیقه"
    if seconds < 3600:
        return f"{fa_number(round(seconds / 60))} دقیقه"
    return f"{fa_number(round(seconds / 3600, 1))} ساعت"


def build() -> dict:
    from apps.accounts.models import DeviceSession, User
    from apps.catalog.models import ContentNode
    from apps.commerce.models import Entitlement, Order
    from apps.learning.models import Question, Report

    from .models import SectionProgress, StudyDay, StudyTime

    now = timezone.now()
    today = timezone.localdate()
    first = today - timedelta(days=DAYS - 1)
    days = [first + timedelta(days=i) for i in range(DAYS)]
    paid = Order.objects.filter(status=Order.Status.PAID)

    # One query per kind of number, grouped by local day.
    daily = {r["date"]: r for r in StudyDay.objects.filter(date__gte=first - timedelta(days=7)).values("date").annotate(
        users=Count("user", distinct=True), answers=Sum("answers"), sections=Sum("sections"), cards=Sum("cards"))}
    seconds = dict(StudyTime.objects.filter(day__gte=first - timedelta(days=7)).values("day").annotate(s=Sum("seconds"))
                   .values_list("day", "s"))
    signups = dict(User.objects.filter(date_joined__date__gte=first - timedelta(days=7)).annotate(d=TruncDate("date_joined"))
                   .values("d").annotate(n=Count("pk")).values_list("d", "n"))
    revenue = dict(paid.filter(paid_at__date__gte=first - timedelta(days=7)).annotate(d=TruncDate("paid_at"))
                   .values("d").annotate(s=Sum("amount")).values_list("d", "s"))

    def week(start):
        """Totals of the seven days from `start` (active learners are counted once each over the week)."""
        end = start + timedelta(days=7)
        span = [start + timedelta(days=i) for i in range(7)]
        active = StudyDay.objects.filter(date__gte=start, date__lt=end).values("user").distinct().count()
        return {
            "active": active,
            "signups": sum(signups.get(d, 0) for d in span),
            "seconds": sum(seconds.get(d, 0) or 0 for d in span),
            "answers": sum((daily.get(d) or {}).get("answers") or 0 for d in span),
            "revenue": sum(revenue.get(d, 0) or 0 for d in span),
        }

    this = week(today - timedelta(days=6))
    last = week(today - timedelta(days=13))
    def num(n):
        return fa_number(n) if n else "—"  # a lone «۰» reads like a dot

    weekly = [
        {"label": "فعال در ۷ روز", "value": num(this["active"]), **change(this["active"], last["active"])},
        {"label": "ثبت‌نام در ۷ روز", "value": num(this["signups"]), **change(this["signups"], last["signups"])},
        {"label": "زمان مطالعه در ۷ روز", "value": minutes(this["seconds"]),
         **change(this["seconds"], last["seconds"], minutes(last["seconds"]))},
        {"label": "پاسخ به تست در ۷ روز", "value": num(this["answers"]), **change(this["answers"], last["answers"])},
        {"label": "فروش ۷ روز (تومان)", "value": num(this["revenue"]), **change(this["revenue"], last["revenue"])},
    ]
    totals = [
        ("کاربران", fa_number(User.objects.count()), None),
        ("دستگاه‌های فعال", fa_number(DeviceSession.objects.filter(
            revoked_at__isnull=True, expires_at__gt=now, last_seen_at__gte=now - timedelta(days=7)).count()), None),
        ("اشتراک‌های فعال", fa_number(Entitlement.active_for_any(now).filter(book__isnull=True).count()), None),
        ("فروش کل (تومان)", fa_number(paid.aggregate(s=Sum("amount"))["s"] or 0), None),
        ("گزارش‌های باز", fa_number(Report.objects.filter(status=Report.Status.OPEN).count()), "admin:learning_report_changelist"),
    ]

    # The 30 days: drawn as an SVG (two bars a day: active and sign-ups; a line: study minutes on its own scale).
    rows = []
    for d in days:
        r = daily.get(d) or {}
        rows.append({"date": d, "active": r.get("users") or 0, "signups": signups.get(d, 0), "sections": r.get("sections") or 0,
                     "answers": r.get("answers") or 0, "cards": r.get("cards") or 0, "seconds": seconds.get(d, 0) or 0,
                     "revenue": revenue.get(d, 0) or 0})
    chart = draw_chart(rows)
    table = [{
        "day": day_label(r["date"], weekday=True), "active": num(r["active"]), "signups": num(r["signups"]),
        "time": minutes(r["seconds"]), "sections": num(r["sections"]),
        "answers": num(r["answers"]), "revenue": fa_number(r["revenue"]) if r["revenue"] else "—",
    } for r in reversed(rows) if any(r[k] for k in ("active", "signups", "sections", "answers", "cards", "seconds", "revenue"))]

    # Books, each number in one grouped query.
    books = list(ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_archived=False, is_inbox=False)
                 .values("pk", "title"))
    readers = dict(SectionProgress.objects.values("book").annotate(n=Count("user", distinct=True)).values_list("book", "n"))
    buyers = dict(Entitlement.objects.filter(book__isnull=False, is_archived=False).filter(Q(order__isnull=False) | Q(granted_by__isnull=True))
                  .values("book").annotate(n=Count("pk")).values_list("book", "n"))
    sales = dict(paid.filter(book__isnull=False).values("book").annotate(s=Sum("amount")).values_list("book", "s"))
    study = dict(StudyTime.objects.filter(day__gte=first).values("book").annotate(s=Sum("seconds")).values_list("book", "s"))
    book_rows = sorted(({
        "title": b["title"], "n_readers": readers.get(b["pk"], 0), "readers": num(readers.get(b["pk"], 0)),
        "buyers": num(buyers.get(b["pk"], 0)), "sales": num(sales.get(b["pk"], 0) or 0),
        "time": minutes(study.get(b["pk"])),
    } for b in books), key=lambda b: -b["n_readers"])

    hardest = (Question.objects.filter(answer_count__gte=10, is_archived=False)
               .annotate(rate=Cast("correct_count", FloatField()) / F("answer_count")).order_by("rate", "id")[:10])
    from apps.catalog.fresh import formula_macros

    return {
        "lp_macros": formula_macros(),
        "weekly": weekly,
        "totals": totals,
        "chart": chart,
        "table": table,
        "books": book_rows,
        "hardest": [{"id": q.id, "stem": short_text(q.stem, 160), "rate": fa_number(round(100 * q.correct_count / q.answer_count)),
                     "n": fa_number(q.answer_count)} for q in hardest],
    }


def draw_chart(rows, width=900, height=170) -> dict:
    """SVG pieces for the template. Oldest day on the right (the page reads right to left)."""
    n = len(rows)
    pad_top, pad_bottom = 14, 22
    inner = height - pad_top - pad_bottom
    slot = width / n
    people_peak = max([1] + [max(r["active"], r["signups"]) for r in rows])
    time_peak = max([1] + [r["seconds"] for r in rows])
    bars, points, labels = [], [], []
    for i, r in enumerate(rows):
        x = width - (i + 1) * slot  # day i from the right
        bw = max(2.0, slot * 0.32)
        for k, (key, color) in enumerate((("active", "#F5C518"), ("signups", "#2E9E5B"))):
            h = inner * r[key] / people_peak
            bars.append({"x": round(x + slot * 0.16 + k * bw, 1), "y": round(pad_top + inner - h, 1), "w": round(bw - 1, 1),
                         "h": round(max(h, 1.5 if r[key] else 0), 1), "color": color,
                         "tip": f"{day_label(r['date'])}: {fa_number(r[key])} {'فعال' if key == 'active' else 'ثبت‌نام'}"})
        points.append((round(x + slot / 2, 1), round(pad_top + inner - inner * r["seconds"] / time_peak, 1)))
        if i % 5 == 0 or i == n - 1:
            labels.append({"x": round(x + slot / 2, 1), "text": day_label(r["date"])})
    dots = [{"x": x, "y": y, "tip": f"{day_label(r['date'])}: {minutes(r['seconds'])} مطالعه"} for (x, y), r in zip(points, rows)]
    return {"width": width, "height": height, "bars": bars, "line": " ".join(f"{x},{y}" for x, y in points), "dots": dots,
            "labels": labels, "base": height - pad_bottom, "label_y": height - 6,
            "people_peak": fa_number(people_peak), "time_peak": minutes(time_peak)}
