"""Jalali (Persian calendar) dates for the panel."""

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
