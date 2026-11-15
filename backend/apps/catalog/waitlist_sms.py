"""«خبر دادن به منتظران»: when a coming-soon book opens, the panel sends one SMS to each learner who pressed «خبرم کن».

- Off until WAITLIST_SMS_ENABLED=True (backend/.env).
- The admin sees a confirmation page first (how many people, the text, how many SMS parts) and confirms.
- Each request gets at most one SMS, ever: a row is claimed (notified_at set) in one UPDATE before its SMS is sent, so
  pressing the button twice, two server processes or the hourly retry never send a second one. An SMS that certainly
  did not go out (SMSNotSent) clears the claim and keeps the error, so the button sends it again; when it is unclear
  (the provider's answer timed out) the claim stays: better no second SMS than two.
- The confirmed text is stored on each queued row, so the hourly retry (another process) sends the same text.
- Sending runs in a background thread, a second apart, so the panel does not wait; rows queued by a process that was
  restarted half-way are finished by the hourly job (nightly --loop).
"""

import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

log = logging.getLogger(__name__)

PAUSE_SECONDS = 1.0
STUCK_AFTER = timedelta(minutes=15)


def waiting(book):
    """The requests still to be told: active, not told yet, by learners who can sign in."""
    from .models import BookWaitlist

    return BookWaitlist.objects.filter(book=book, is_active=True, notified_at__isnull=True, user__is_active=True)


def book_link(book) -> str:
    base = settings.APP_URL if str(settings.APP_URL).startswith("http") else settings.SITE_URL
    link = f"{base.rstrip('/')}/book/{book.slug}"
    return link.removeprefix("https://").removeprefix("http://")


def default_text(book) -> str:
    return f"کتاب «{book.title}» در لیموخوان منتشر شد:\n{book_link(book)}"


def sms_parts(text: str) -> int:
    """How many SMS one message takes (Persian text: 70 characters alone, 67 per part when longer)."""
    n = len(text)
    return 1 if n <= 70 else -(-n // 67)


def problems(book) -> list[str]:
    """Why sending is not allowed now (empty: allowed)."""
    out = []
    if not settings.WAITLIST_SMS_ENABLED:
        out.append("ارسال پیامک خبر خاموش است. برای روشن کردن، در متغیرهای سرور WAITLIST_SMS_ENABLED=True بگذارید.")
    if book.is_coming_soon:
        out.append("کتاب هنوز «به‌زودی» است. اول تیک «به‌زودی» را بردارید و کتاب را منتشر کنید.")
    if not book.is_published or book.is_archived:
        out.append("کتاب منتشر نشده است (یا بایگانی است).")
    return out


def queue(book, text: str, start: bool = True) -> int:
    """Mark everyone still waiting as queued with this text and start sending once this request's transaction is
    committed (the sending thread must see the queued rows). Returns how many were queued."""
    from django.db import transaction

    from .models import BookWaitlist

    if problems(book):
        return 0
    now = timezone.now()
    ids = list(waiting(book).values_list("pk", flat=True))
    BookWaitlist.objects.filter(pk__in=ids, notified_at__isnull=True).update(notify_queued_at=now, notify_error="", notify_text=text[:300])
    if start and ids:
        transaction.on_commit(lambda: threading.Thread(
            target=_send_in_background, args=(book.pk,), daemon=True, name=f"waitlist-sms-{book.pk}").start())
    return len(ids)


def _send_in_background(book_id: int):
    try:
        send_queued(book_id)
    except Exception:  # noqa: BLE001 — the hourly job finishes what is left
        log.exception("waitlist SMS for book %s stopped", book_id)
    finally:
        close_old_connections()


def send_queued(book_id: int, pause: float | None = None, older_than=None) -> dict:
    """Send to every queued, untold request of this book. `older_than`: only rows queued before then (the hourly
    retry of a stopped run). Returns counts."""
    from apps.accounts.sms import SMSError, SMSNotSent, send_sms

    from .models import BookWaitlist, ContentNode

    book = ContentNode.objects.filter(pk=book_id).first()
    done = {"sent": 0, "failed": 0}
    if book is None or problems(book):
        return done
    pause = PAUSE_SECONDS if pause is None else pause
    rows = waiting(book).filter(notify_queued_at__isnull=False)
    if older_than is not None:
        rows = rows.filter(notify_queued_at__lt=older_than)
    for row_id, phone, text in list(rows.values_list("pk", "user__phone", "notify_text")):
        # Claim the row: only the process whose UPDATE changed it sends.
        claimed = BookWaitlist.objects.filter(pk=row_id, notified_at__isnull=True, is_active=True).update(notified_at=timezone.now())
        if not claimed:
            continue
        try:
            send_sms(phone, text or default_text(book))
            done["sent"] += 1
        except SMSNotSent as exc:
            BookWaitlist.objects.filter(pk=row_id).update(notified_at=None, notify_queued_at=None, notify_error=str(exc)[:200])
            done["failed"] += 1
        except SMSError as exc:  # it may have gone out: keep the claim, so it is never sent twice
            BookWaitlist.objects.filter(pk=row_id).update(notify_error=("نامعلوم: " + str(exc))[:200])
            done["failed"] += 1
        if pause:
            time.sleep(pause)
    return done


def retry_stuck() -> int:
    """For the hourly job: finish runs that a restart stopped (queued more than 15 minutes ago, not yet sent)."""
    from .models import BookWaitlist

    before = timezone.now() - STUCK_AFTER
    books = set(BookWaitlist.objects.filter(notify_queued_at__lt=before, notified_at__isnull=True, is_active=True)
                .values_list("book_id", flat=True))
    sent = 0
    for book_id in books:
        sent += send_queued(book_id, older_than=before)["sent"]
    return sent
