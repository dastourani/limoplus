"""«گزارش فروش» in the panel: paid orders in a Jalali range (this month, last month, this year, the last 30 days, or
from–to), against the same length of time before it; by book, by subscription plan and by day (by month for long
ranges); and the rows as a CSV file that Excel opens. Read-only: orders are never changed here."""

import csv
import io
from datetime import date, datetime, time, timedelta

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.catalog.jalali import fa_digits, from_jalali, jalali_date, jalali_datetime, jalali_month_start, to_jalali
from apps.catalog.panel_display import fa_number

from .models import Order

RANGES = [("month", "این ماه"), ("last_month", "ماه قبل"), ("30", "۳۰ روز اخیر"), ("year", "امسال"), ("custom", "از تاریخ تا تاریخ")]
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def parse_jalali(text: str):
    """«۱۴۰۵/۸/۱» or «1405-08-01» as a date; None when it is not a real date."""
    digits = (text or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    parts = [p for p in digits.replace("-", "/").replace(".", "/").split("/") if p.strip()]
    if len(parts) != 3 or not all(p.strip().isdigit() for p in parts):
        return None
    y, m, d = (int(p) for p in parts)
    if not (1300 <= y <= 1500 and 1 <= m <= 12 and 1 <= d <= (31 if m <= 6 else 30)):
        return None
    result = from_jalali(y, m, d)
    return result if to_jalali(result.year, result.month, result.day) == (y, m, d) else None  # 30 Esfand in a common year


def period(choice: str, start_text: str = "", end_text: str = "") -> tuple[date, date, str]:
    """First and last local day of the range, and its name; an unusable custom range falls back to this month."""
    today = timezone.localdate()
    this_month = jalali_month_start(today)
    if choice == "last_month":
        start = jalali_month_start(this_month - timedelta(days=1))
        return start, this_month - timedelta(days=1), "ماه قبل"
    if choice == "30":
        return today - timedelta(days=29), today, "۳۰ روز اخیر"
    if choice == "year":
        y, _, _ = to_jalali(today.year, today.month, today.day)
        return from_jalali(y, 1, 1), today, f"سال {fa_digits(y)}"
    if choice == "custom":
        start, end = parse_jalali(start_text), parse_jalali(end_text)
        if start and end and start <= end:
            return start, end, f"{jalali_date(start)} تا {jalali_date(end)}"
    return this_month, today, "این ماه"


def _bounds(start: date, end: date):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(start, time.min), tz), timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz)


def paid_in(start: date, end: date):
    lo, hi = _bounds(start, end)
    return Order.objects.filter(status=Order.Status.PAID, paid_at__gte=lo, paid_at__lt=hi)


def _num(n) -> str:
    return fa_number(n) if n else "—"


def _cell(value):
    """A CSV cell that Excel never runs as a formula (a name typed by a user could start with =, +, - or @)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _change(now, before) -> dict:
    if not before:
        return {"text": "", "color": "grey"}
    pct = round(100 * (now - before) / before)
    if pct == 0:
        return {"text": "مثل دوره‌ی قبل", "color": "grey"}
    return {"text": f"{'▲' if pct > 0 else '▼'} {fa_number(abs(pct))}٪ نسبت به دوره‌ی قبل", "color": "green" if pct > 0 else "red"}


def build(choice: str, start_text: str = "", end_text: str = "") -> dict:
    start, end, name = period(choice, start_text, end_text)
    length = (end - start).days + 1
    before_start, before_end = start - timedelta(days=length), start - timedelta(days=1)
    paid = paid_in(start, end)
    lo, hi = _bounds(start, end)
    made = Order.objects.filter(created_at__gte=lo, created_at__lt=hi)
    totals = paid.aggregate(sum=Sum("amount"), n=Count("pk"), avg=Avg("amount"))
    before = paid_in(before_start, before_end).aggregate(sum=Sum("amount"), n=Count("pk"))
    total = totals["sum"] or 0
    cards = [
        {"label": "جمع فروش (تومان)", "value": fa_number(total) if total else "—", **_change(total, before["sum"] or 0)},
        {"label": "سفارش پرداخت‌شده", "value": fa_number(totals["n"]) if totals["n"] else "—", **_change(totals["n"], before["n"])},
        {"label": "میانگین هر سفارش (تومان)", "value": fa_number(round(totals["avg"])) if totals["avg"] else "—", "text": "", "color": "grey"},
        {"label": "پرداخت ناموفق", "value": _num(made.filter(status=Order.Status.FAILED).count()), "text": "", "color": "grey"},
        {"label": "رها شده (در انتظار پرداخت)", "value": _num(made.filter(status=Order.Status.PENDING).count()), "text": "",
         "color": "grey"},
    ]

    def share(amount):
        return f"{fa_number(round(100 * amount / total))}٪" if total else "—"

    by_book = [{"name": r["book__title"], "n": fa_number(r["n"]), "sum": fa_number(r["s"]), "share": share(r["s"])}
               for r in paid.filter(book__isnull=False).values("book__title").annotate(n=Count("pk"), s=Sum("amount")).order_by("-s")]
    by_plan = [{"name": f"{r['plan__title']} ({fa_digits(r['plan_months'] or '')} ماهه)" if r["plan_months"] else r["plan__title"],
                "n": fa_number(r["n"]), "sum": fa_number(r["s"]), "share": share(r["s"])}
               for r in paid.filter(plan__isnull=False).values("plan__title", "plan_months").annotate(n=Count("pk"), s=Sum("amount")).order_by("-s")]

    # Bars: one a day up to three months, one a Jalali month beyond.
    per_day = dict(paid.annotate(d=TruncDate("paid_at")).values("d").annotate(s=Sum("amount")).values_list("d", "s"))
    bars = []
    if length <= 92:
        for i in range(length):
            d = start + timedelta(days=i)
            _, m, dd = to_jalali(d.year, d.month, d.day)
            bars.append({"label": f"{fa_digits(dd)} {MONTHS[m - 1]}", "sum": per_day.get(d, 0) or 0, "tick": i % 7 == 0})
    else:
        months: dict[tuple, int] = {}
        for d, s in per_day.items():
            y, m, _ = to_jalali(d.year, d.month, d.day)
            months[(y, m)] = months.get((y, m), 0) + (s or 0)
        y, m, _ = to_jalali(start.year, start.month, start.day)
        while from_jalali(y, m, 1) <= end:
            bars.append({"label": f"{MONTHS[m - 1]} {fa_digits(y)}", "sum": months.get((y, m), 0), "tick": True})
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    peak = max([1] + [b["sum"] for b in bars])
    for b in bars:
        b["height"] = round(100 * b["sum"] / peak, 1)
        b["tip"] = f"{b['label']}: {fa_number(b['sum'])} تومان" if b["sum"] else f"{b['label']}: بدون فروش"

    return {
        "choice": choice if choice in dict(RANGES) else "month",
        "ranges": RANGES,
        "name": name,
        "start": jalali_date(start),
        "end": jalali_date(end),
        "before": f"{jalali_date(before_start)} تا {jalali_date(before_end)}",
        "cards": cards,
        "by_book": by_book,
        "by_plan": by_plan,
        "bars": bars,
        "start_date": start,
        "end_date": end,
    }


def csv_file(start: date, end: date) -> bytes:
    """Every order made in the range (paid or not), one row each; UTF-8 with a BOM so Excel shows Persian."""
    lo, hi = _bounds(start, end)
    out = io.StringIO()
    out.write("﻿")
    writer = csv.writer(out)
    writer.writerow(["شماره", "زمان ثبت", "زمان پرداخت", "خریدار", "نام", "شرح", "کتاب", "طرح", "مبلغ (تومان)", "وضعیت", "شماره‌ی پیگیری"])
    rows = Order.objects.filter(created_at__gte=lo, created_at__lt=hi).select_related("user", "book", "plan").order_by("created_at")
    for o in rows:
        writer.writerow([_cell(x) for x in (
            o.pk, jalali_datetime(o.created_at), jalali_datetime(o.paid_at) if o.paid_at else "", o.user.phone, o.user.full_name,
            o.title, o.book.title if o.book_id else "", o.plan.title if o.plan_id else "", o.amount, o.get_status_display(),
            o.ref_number)])
    return out.getvalue().encode("utf-8")
