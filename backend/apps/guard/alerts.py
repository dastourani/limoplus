"""
Bale alerts about copying and device changes. Off until the owner turns on «هشدارهای بله» in «ردیاب متن».

Instant: an account that used all of today's copies, reached a high risk score, or passed «تعویض زیاد دستگاه» (more than
DEVICE_SWITCH_ALERT new sign-ins in 7 days) (each at most once a day per account). Nightly: one summary of the last 24 hours.
"""

import logging
import threading
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.catalog.jalali import fa_digits

from .models import AlertSent, CopyEvent, GuardSettings

log = logging.getLogger(__name__)
SUMMARY_HOURS = range(2, 7)  # Tehran time, with the nightly backups


def enabled() -> bool:
    from apps.catalog.backups import bale_ready

    return GuardSettings.get().bale_alerts and bale_ready()


def _send(text: str) -> None:
    from apps.catalog.backups import _safe, send_text

    try:
        send_text(text)
    except Exception as exc:  # noqa: BLE001 — an alert must never break the request
        log.error("Bale alert failed: %s", _safe(exc))


def _send_later(text: str) -> None:
    """After the request's transaction, outside the request (Bale can be slow)."""
    transaction.on_commit(lambda: threading.Thread(target=_send, args=(text,), daemon=True).start())


def _once(user, reason: str) -> bool:
    _, created = AlertSent.objects.get_or_create(user=user, reason=reason, date=timezone.localdate())
    return created


def _who(user) -> str:
    name = f"{user.first_name} {user.last_name}".strip()
    return fa_digits(user.phone) + (f" ({name})" if name else "")


def after_copy(event: CopyEvent, used: int) -> None:
    if not enabled():
        return
    from .core import DAILY_LIMIT, risk_of

    user = event.user
    if used >= DAILY_LIMIT and _once(user, "quota"):
        _send_later(f"⚠️ لیموخوان: {_who(user)} هر {fa_digits(DAILY_LIMIT)} کپی امروز را مصرف کرد.")
    risk = risk_of(user)
    if risk["score"] >= 60 and _once(user, "risk"):
        _send_later(f"🚨 لیموخوان: امتیاز خطر {_who(user)} به {fa_digits(risk['score'])} از ۱۰۰ رسید. (پنل › ردیاب متن)")


def after_login(session) -> None:
    if not enabled():
        return
    from django.conf import settings

    from .core import new_sessions_7d

    n = new_sessions_7d([session.user_id]).get(session.user_id, 0)
    if n > settings.DEVICE_SWITCH_ALERT and _once(session.user, "device"):
        _send_later(f"📱 لیموخوان: {_who(session.user)} در ۷ روز {fa_digits(n)} بار با دستگاه تازه وارد شده (تعویض زیاد دستگاه)؛ تازه‌ترین: «{session.device_name or 'ناشناس'}».")


def summary_text(now=None) -> str | None:
    from .core import DAILY_LIMIT, device_switches, risk_table

    now = now or timezone.now()
    since = now - timedelta(days=1)
    copies = CopyEvent.objects.filter(created_at__gte=since)
    total = copies.count()
    risky = [r for r in risk_table(now) if r["score"] >= 30][:10]
    switches = device_switches(since)
    if not total and not risky and not switches:
        return None
    lines = [f"🍋 خلاصه‌ی شبانه‌ی ردیاب متن — ۲۴ ساعت گذشته: {fa_digits(total)} کپی از {fa_digits(copies.values('user_id').distinct().count())} حساب."]
    if risky:
        lines.append("حساب‌های پرخطر:")
        lines += [f"- {_who(r['user'])}: {fa_digits(r['score'])} از ۱۰۰ ({fa_digits(r['copies_7d'])} کپی در ۷ روز)" for r in risky if r["user"]]
    full = [r for r in risk_table(now) if r["full_days_30d"]]
    if full:
        lines.append(f"{fa_digits(len(full))} حساب در ۳۰ روز دست‌کم یک روز هر {fa_digits(DAILY_LIMIT)} کپی را مصرف کرده‌اند.")
    if switches:
        from apps.accounts.models import User

        people = User.objects.in_bulk([r["user_id"] for r in switches])
        lines.append("تعویض دستگاه:")
        lines += [f"- {_who(people[r['user_id']])}: {fa_digits(r['n'])} ورود تازه در ۷ روز" for r in switches if r["user_id"] in people]
    return "\n".join(lines)


def nightly(now=None) -> bool:
    """Once a night, when the alerts are on. Called by the hourly job."""
    now = now or timezone.now()
    if timezone.localtime(now).hour not in SUMMARY_HOURS or not enabled():
        return False
    settings_row = GuardSettings.get()
    today = timezone.localdate(now)
    if settings_row.last_summary_on == today:
        return False
    settings_row.last_summary_on = today
    settings_row.save(update_fields=["last_summary_on"])
    text = summary_text(now)
    if text:
        _send(text)
    return True
