"""Jalali (Persian calendar) dates for the panel."""

import datetime

from django.utils import timezone

_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_days[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


def jalali_datetime(value) -> str:
    """e.g. «۱۴۰۵/۸/۹ ساعت ۱۷:۰۴» in the server's time zone."""
    if value is None:
        return ""
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    y, m, d = to_jalali(local.year, local.month, local.day)
    return f"{y}/{m}/{d} ساعت {local.hour:02d}:{local.minute:02d}".translate(_FA)


def jalali_date(value) -> str:
    """A date as «۱۴۰۵/۸/۹»; datetimes are first reduced in the project's local time zone."""
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        value = value.date()
    y, m, d = to_jalali(value.year, value.month, value.day)
    return f"{y}/{m}/{d}".translate(_FA)


def fa_digits(text: str) -> str:
    return str(text).translate(_FA)


def from_jalali(jy: int, jm: int, jd: int):
    """A Jalali date as a datetime.date (the inverse of to_jalali)."""
    import datetime

    jy += 1595
    days = -355668 + 365 * jy + (jy // 33) * 8 + ((jy % 33) + 3) // 4 + jd + ((jm - 1) * 31 if jm < 7 else (jm - 7) * 30 + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    months = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and gd > months[gm]:
        gd -= months[gm]
        gm += 1
    return datetime.date(gy, gm + 1, gd)


def jalali_month_start(value):
    """The Gregorian date of the first day of the Jalali month that `value` (a date) is in."""
    y, m, _ = to_jalali(value.year, value.month, value.day)
    return from_jalali(y, m, 1)
