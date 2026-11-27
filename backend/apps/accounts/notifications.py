from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import logging
import secrets
from urllib.parse import quote

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, connections, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from .models import TeacherNotification

log = logging.getLogger(__name__)
_EMAIL_NOTIFY_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="teacher-email")


def _sending_stale_timeout() -> timedelta:
    seconds = max(30, int(getattr(settings, "TEACHER_NOTIFICATION_SENDING_TIMEOUT_SECONDS", 300)))
    return timedelta(seconds=seconds)


def retryable_notifications_queryset(*, include_skipped: bool = False):
    statuses = [
        TeacherNotification.Status.PENDING,
        TeacherNotification.Status.FAILED,
    ]
    if include_skipped:
        statuses.append(TeacherNotification.Status.SKIPPED_NO_EMAIL)
    stale_cutoff = timezone.now() - _sending_stale_timeout()
    return TeacherNotification.objects.filter(
        Q(status__in=statuses)
        | Q(status=TeacherNotification.Status.SENDING, last_attempt_at__lte=stale_cutoff)
        | Q(status=TeacherNotification.Status.SENDING, last_attempt_at__isnull=True)
    ).order_by("created_at", "pk")


def _build_email_bodies(notif: TeacherNotification, action_url: str) -> tuple[str, str]:
    text_body = (
        f"استاد گرامی سلام،\n\n"
        f"{notif.headline}\n\n"
        f"{notif.cta_label}:\n"
        f"{action_url}\n\n"
        f"جزئیات کامل، سوابق و امکان پاسخگویی فقط در پنل استادی لیموخوان نمایش داده می‌شود.\n\n"
        f"با احترام،\n"
        f"تیم لیموخوان"
    )
    safe_headline = escape(notif.headline)
    safe_cta = escape(notif.cta_label or "مشاهده در میز تألیف")
    safe_url = escape(action_url)
    safe_title = escape(notif.subject)
    html_body = (
        '<!doctype html><html lang="fa" dir="rtl"><body style="margin:0;padding:24px;'
        'background:#f8fafc;font-family:Tahoma,Arial,sans-serif;color:#0f172a;direction:rtl;">'
        '<div style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;'
        'border-radius:12px;padding:24px;">'
        f'<div style="font-size:13px;color:#0f766e;font-weight:bold;margin-bottom:8px;">لیموخوان · میز تألیف</div>'
        f'<h2 style="margin:0 0 12px;font-size:17px;line-height:1.6;color:#0f172a;">{safe_title}</h2>'
        f'<p style="margin:0 0 20px;font-size:14px;line-height:1.8;color:#334155;">{safe_headline}</p>'
        f'<p style="margin:0 0 20px;">'
        f'<a href="{safe_url}" style="display:inline-block;background:#0f766e;color:#ffffff;'
        'text-decoration:none;font-weight:bold;font-size:14px;padding:11px 20px;border-radius:8px;">'
        f'{safe_cta}</a></p>'
        '<p style="margin:0;font-size:12px;line-height:1.7;color:#64748b;">'
        'جزئیات کامل و امکان بررسی یا پاسخ فقط پس از ورود امن در پنل استادی نمایش داده می‌شود.'
        '</p></div></body></html>'
    )
    return text_body, html_body


def _recipient_still_has_access(notif: TeacherNotification) -> tuple[bool, str]:
    from apps.catalog import access

    user = notif.recipient
    if not user or not user.is_active or not user.is_staff or user.is_superuser:
        return False, "حساب کاربری استاد فعال نیست."

    if notif.event_type.startswith("pub_"):
        from apps.catalog.models import BookEditor, ContentNode

        if not access.is_book_teacher(user):
            return False, "دسترسی استادی شما در سامانه فعال نیست."
        if not notif.book_id or not ContentNode.objects.filter(
            pk=notif.book_id,
            kind=ContentNode.Kind.BOOK,
            depth=1,
            is_archived=False,
            is_inbox=False,
        ).exists():
            return False, "کتاب مرتبط در دسترس نیست."
        if not BookEditor.objects.filter(
            book_id=notif.book_id,
            user=user,
            can_request_publication=True,
        ).exists():
            return False, "دسترسی درخواست انتشار این کتاب برای استاد فعال نیست."
        return True, ""

    if notif.event_type.startswith("access_"):
        from apps.catalog.models import BookEditor
        from apps.website.models import BookAccessRequest

        if not access.is_book_teacher(user):
            return False, "دسترسی استادی شما در سامانه فعال نیست."
        if not notif.book_id or not BookEditor.objects.filter(
            book_id=notif.book_id,
            user=user,
            can_request_group_access=True,
        ).exists():
            return False, "دسترسی درخواست گروهی این کتاب برای استاد فعال نیست."
        if not notif.object_id or not BookAccessRequest.objects.filter(
            pk=notif.object_id,
            requested_by=user,
        ).exists():
            return False, "درخواست دسترسی گروهی مرتبط یافت نشد."
        return True, ""

    if notif.event_type.startswith("payout_"):
        from apps.commerce.models import PayoutRequest

        if not notif.object_id or not PayoutRequest.objects.filter(
            pk=notif.object_id,
            teacher=user,
        ).exists():
            return False, "درخواست تسویه حساب مرتبط یافت نشد."
        return True, ""

    return False, "نوع اعلان نامعتبر است."


def dispatch_teacher_notification(notification_id: int, *, force: bool = False) -> bool:
    """Atomically claim a TeacherNotification, send email outside DB locks, and commit only for that attempt."""
    payload = None
    attempt_token = ""
    with transaction.atomic():
        notif = (
            TeacherNotification.objects.select_for_update()
            .select_related("recipient")
            .filter(pk=notification_id)
            .first()
        )
        if notif is None:
            return False
        if notif.status == TeacherNotification.Status.SENT and not force:
            return True

        now = timezone.now()
        if notif.status == TeacherNotification.Status.SENDING:
            is_stale = (
                notif.last_attempt_at is None
                or (now - notif.last_attempt_at) >= _sending_stale_timeout()
            )
            if not is_stale:
                return False

        has_access, reason = _recipient_still_has_access(notif)
        if not has_access:
            notif.status = TeacherNotification.Status.FAILED
            notif.dispatch_token = ""
            notif.last_attempt_at = now
            notif.last_error = reason
            notif.save(update_fields=["status", "dispatch_token", "last_attempt_at", "last_error"])
            return False

        recipient = notif.recipient
        if not recipient.is_email_verified:
            notif.status = TeacherNotification.Status.SKIPPED_NO_EMAIL
            notif.dispatch_token = ""
            notif.recipient_email = ""
            notif.last_attempt_at = now
            notif.last_error = "استاد ایمیل کاری تأییدشده ندارد؛ پیام در پنل نمایش داده می‌شود."
            notif.save(
                update_fields=[
                    "status",
                    "dispatch_token",
                    "recipient_email",
                    "last_attempt_at",
                    "last_error",
                ]
            )
            return False

        attempt_token = secrets.token_hex(16)
        target_email = recipient.email.strip()
        base_url = getattr(settings, "SITE_URL", "http://localhost:8000").rstrip("/")
        action_url = f"{base_url}{notif.notice_path()}"
        text_body, html_body = _build_email_bodies(notif, action_url)

        notif.status = TeacherNotification.Status.SENDING
        notif.dispatch_token = attempt_token
        notif.attempt_count += 1
        notif.last_attempt_at = now
        notif.recipient_email = target_email
        notif.save(
            update_fields=[
                "status",
                "dispatch_token",
                "attempt_count",
                "last_attempt_at",
                "recipient_email",
            ]
        )
        payload = {
            "subject": notif.subject,
            "text_body": text_body,
            "html_body": html_body,
            "target_email": target_email,
        }

    # Network I/O runs completely outside any DB transaction or row lock.
    send_error = ""
    sent_ok = False
    try:
        msg = EmailMultiAlternatives(
            subject=payload["subject"],
            body=payload["text_body"],
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[payload["target_email"]],
        )
        msg.attach_alternative(payload["html_body"], "text/html")
        sent_count = msg.send(fail_silently=False)
        if sent_count and sent_count > 0:
            sent_ok = True
        else:
            send_error = "سرور ایمیل پیامی را نپذیرفت (sent=0)."
    except Exception as exc:
        log.exception("Failed sending teacher notification #%s to %s", notification_id, payload["target_email"])
        send_error = f"{exc.__class__.__name__}: {exc}"[:1000]

    with transaction.atomic():
        if sent_ok:
            updated = TeacherNotification.objects.filter(
                pk=notification_id,
                status=TeacherNotification.Status.SENDING,
                dispatch_token=attempt_token,
            ).update(
                status=TeacherNotification.Status.SENT,
                dispatch_token="",
                sent_at=timezone.now(),
                last_error="",
            )
            return bool(updated)
        TeacherNotification.objects.filter(
            pk=notification_id,
            status=TeacherNotification.Status.SENDING,
            dispatch_token=attempt_token,
        ).update(
            status=TeacherNotification.Status.FAILED,
            dispatch_token="",
            last_error=send_error,
        )
        return False


def _dispatch_in_worker(notification_id: int) -> None:
    try:
        connections.close_all()
        dispatch_teacher_notification(notification_id)
    except Exception:
        log.exception("Unexpected worker error dispatching notification #%s", notification_id)
    finally:
        connections.close_all()


def queue_teacher_notification(
    *,
    recipient,
    event_type: str,
    dedupe_key: str,
    source_ref: str = "",
    book_id: int | None = None,
    book_title: str = "",
    object_id: int | None = None,
    subject: str,
    headline: str,
    cta_label: str = "مشاهده در میز تألیف",
    is_reminder: bool = False,
    created_by=None,
) -> TeacherNotification | None:
    """Create at most one notification row per `dedupe_key` and schedule post-commit email delivery."""
    if not recipient or recipient.is_superuser or not recipient.is_active or not recipient.is_staff:
        return None

    initial_status = (
        TeacherNotification.Status.PENDING
        if recipient.is_email_verified
        else TeacherNotification.Status.SKIPPED_NO_EMAIL
    )
    initial_error = (
        ""
        if recipient.is_email_verified
        else "استاد ایمیل کاری تأییدشده ندارد؛ پیام در پنل نمایش داده می‌شود."
    )

    try:
        notif, created = TeacherNotification.objects.get_or_create(
            dedupe_key=dedupe_key,
            defaults={
                "recipient": recipient,
                "recipient_email": recipient.email.strip() if recipient.is_email_verified else "",
                "event_type": event_type,
                "source_ref": source_ref[:80],
                "book_id": book_id,
                "book_title": (book_title or "")[:200],
                "object_id": object_id,
                "subject": subject[:200],
                "headline": headline[:300],
                "cta_label": cta_label[:80],
                "is_reminder": bool(is_reminder),
                "status": initial_status,
                "last_error": initial_error,
                "created_by": created_by,
            },
        )
    except IntegrityError:
        notif = TeacherNotification.objects.filter(dedupe_key=dedupe_key).first()
        created = False

    if created:
        def _schedule(nid=notif.pk):
            if getattr(settings, "TESTING", False):
                dispatch_teacher_notification(nid)
            else:
                _EMAIL_NOTIFY_EXECUTOR.submit(_dispatch_in_worker, nid)

        transaction.on_commit(_schedule)
    return notif


def retry_teacher_notifications(queryset=None) -> dict[str, int]:
    """Retry unsent (pending/failed/skipped or stale sending) notifications; returns counts."""
    if queryset is None:
        queryset = retryable_notifications_queryset(include_skipped=True)
    stats = {"attempted": 0, "sent": 0, "failed": 0, "skipped_no_email": 0, "in_progress": 0}
    for notif_id in queryset.values_list("pk", flat=True):
        stats["attempted"] += 1
        dispatch_teacher_notification(notif_id)
        latest = TeacherNotification.objects.filter(pk=notif_id).values_list("status", flat=True).first()
        if latest == TeacherNotification.Status.SENT:
            stats["sent"] += 1
        elif latest == TeacherNotification.Status.SKIPPED_NO_EMAIL:
            stats["skipped_no_email"] += 1
        elif latest == TeacherNotification.Status.SENDING:
            stats["in_progress"] += 1
        else:
            stats["failed"] += 1
    return stats


def notify_publication_offer(pub_req, *, event, actor, is_reminder: bool = False):
    book = pub_req.book
    if is_reminder:
        event_type = TeacherNotification.EventType.PUB_OFFER_REMINDER
        dedupe_key = f"pub:{pub_req.pk}:reminder:ev:{event.pk}"
        subject = f"یادآوری: پیشنهاد انتشار کتاب «{book.title}»"
        headline = f"یادآوری: پیشنهاد انتشار کتاب «{book.title}» در میز تألیف شما آمادهٔ بررسی است."
    else:
        event_type = TeacherNotification.EventType.PUB_OFFER_SENT
        dedupe_key = f"pub:{pub_req.pk}:offer:v{pub_req.sent_offer_version}"
        subject = f"پیشنهاد انتشار کتاب «{book.title}»"
        headline = f"پیشنهاد انتشار کتاب «{book.title}» در میز تألیف شما آمادهٔ بررسی است."

    return queue_teacher_notification(
        recipient=pub_req.requested_by,
        event_type=event_type,
        dedupe_key=dedupe_key,
        source_ref=f"publication:{pub_req.pk}",
        book_id=book.pk,
        book_title=book.title,
        object_id=pub_req.pk,
        subject=subject,
        headline=headline,
        cta_label="مشاهده در میز تألیف",
        is_reminder=is_reminder,
        created_by=actor,
    )


def notify_publication_decision(pub_req, *, event, actor):
    from apps.website.models import PublicationRequest

    book = pub_req.book
    if pub_req.status == PublicationRequest.Status.NEEDS_INFO:
        event_type = TeacherNotification.EventType.PUB_NEEDS_INFO
        subject = f"نیاز به اصلاح محتوای کتاب «{book.title}»"
        headline = f"پیام اصلاح محتوای کتاب «{book.title}» در میز تألیف شما ثبت شده است."
    elif pub_req.status == PublicationRequest.Status.APPROVED:
        event_type = TeacherNotification.EventType.PUB_APPROVED
        subject = f"درخواست انتشار کتاب «{book.title}» تأیید شد"
        headline = f"درخواست انتشار کتاب «{book.title}» تأیید شد. وضعیت اثر در میز تألیف شما قابل مشاهده است."
    elif pub_req.status == PublicationRequest.Status.REJECTED:
        event_type = TeacherNotification.EventType.PUB_REJECTED
        subject = f"نتیجهٔ درخواست انتشار کتاب «{book.title}»"
        headline = f"نتیجهٔ بررسی درخواست انتشار کتاب «{book.title}» در میز تألیف شما ثبت شده است."
    else:
        return None

    return queue_teacher_notification(
        recipient=pub_req.requested_by,
        event_type=event_type,
        dedupe_key=f"pub:{pub_req.pk}:review:ev:{event.pk}",
        source_ref=f"publication:{pub_req.pk}",
        book_id=book.pk,
        book_title=book.title,
        object_id=pub_req.pk,
        subject=subject,
        headline=headline,
        cta_label="مشاهده در میز تألیف",
        is_reminder=False,
        created_by=actor,
    )


def notify_book_access_decision(access_req, *, event, actor):
    from apps.website.models import BookAccessRequest

    book = access_req.book
    if access_req.status == BookAccessRequest.Status.APPROVED:
        event_type = TeacherNotification.EventType.ACCESS_APPROVED
        subject = f"تأیید درخواست دسترسی گروهی کتاب «{book.title}»"
        headline = f"درخواست دسترسی گروهی شما برای کتاب «{book.title}» تأیید شد."
    elif access_req.status == BookAccessRequest.Status.NEEDS_INFO:
        event_type = TeacherNotification.EventType.ACCESS_NEEDS_INFO
        subject = f"نیاز به تکمیل درخواست دسترسی گروهی کتاب «{book.title}»"
        headline = f"دربارهٔ درخواست دسترسی گروهی کتاب «{book.title}» پیامی در پنل استادی ثبت شده است."
    elif access_req.status == BookAccessRequest.Status.REJECTED:
        event_type = TeacherNotification.EventType.ACCESS_REJECTED
        subject = f"نتیجهٔ درخواست دسترسی گروهی کتاب «{book.title}»"
        headline = f"نتیجهٔ درخواست دسترسی گروهی کتاب «{book.title}» در پنل استادی ثبت شده است."
    else:
        return None

    return queue_teacher_notification(
        recipient=access_req.requested_by,
        event_type=event_type,
        dedupe_key=f"access:{access_req.pk}:ev:{event.pk}",
        source_ref=f"access:{access_req.pk}",
        book_id=book.pk,
        book_title=book.title,
        object_id=access_req.pk,
        subject=subject,
        headline=headline,
        cta_label="مشاهده در میز تألیف",
        is_reminder=False,
        created_by=actor,
    )


def notify_book_access_message(access_req, *, event, actor, is_reminder: bool = True):
    book = access_req.book
    return queue_teacher_notification(
        recipient=access_req.requested_by,
        event_type=TeacherNotification.EventType.ACCESS_MESSAGE,
        dedupe_key=f"access:{access_req.pk}:msg:ev:{event.pk}",
        source_ref=f"access:{access_req.pk}",
        book_id=book.pk,
        book_title=book.title,
        object_id=access_req.pk,
        subject=f"پیام تازه دربارهٔ دسترسی گروهی کتاب «{book.title}»",
        headline=f"دربارهٔ درخواست دسترسی گروهی کتاب «{book.title}» پیام تازه‌ای در پنل ثبت شده است.",
        cta_label="مشاهده در میز تألیف",
        is_reminder=is_reminder,
        created_by=actor,
    )


def notify_payout_decision(payout, *, actor=None):
    from apps.commerce.models import PayoutRequest

    if payout.status == PayoutRequest.Status.PAID:
        event_type = TeacherNotification.EventType.PAYOUT_PAID
        subject = "واریز تسویه حساب حق‌التألیف"
        headline = "درخواست تسویه حساب شما پرداخت شد. کد رهگیری و جزئیات واریز در پنل قابل مشاهده است."
    elif payout.status == PayoutRequest.Status.REJECTED:
        event_type = TeacherNotification.EventType.PAYOUT_REJECTED
        subject = "نتیجهٔ درخواست تسویه حساب"
        headline = "نتیجهٔ بررسی درخواست تسویه حساب شما در بخش مالی پنل ثبت شده است."
    else:
        return None

    return queue_teacher_notification(
        recipient=payout.teacher,
        event_type=event_type,
        dedupe_key=f"payout:{payout.pk}:status:{payout.status}",
        source_ref=f"payout:{payout.pk}",
        book_id=None,
        book_title="",
        object_id=payout.pk,
        subject=subject,
        headline=headline,
        cta_label="مشاهده در میز تألیف",
        is_reminder=False,
        created_by=actor,
    )


def _notice_denied_response(request, message: str, *, title: str = "عدم دسترسی به پیام", status: int = 403) -> HttpResponse:
    from apps.website.views import _base

    return render(
        request,
        "website/teacher_notice_error.html",
        {
            **_base(request),
            "title": title,
            "message": message,
            "teacher_login_url": reverse("teacher-login"),
        },
        status=status,
    )


def teacher_notice_redirect(request, notification_id: int, token: str):
    """Verify recipient identity and live access, routing unauthenticated visits straight to teacher OTP login."""
    notif = TeacherNotification.objects.select_related("recipient").filter(pk=notification_id).first()
    if notif is None or not notif.matches_notice_token(token):
        return _notice_denied_response(
            request,
            "این پیوند نامعتبر است یا دیگر قابل استفاده نیست.",
            status=403,
        )

    if not request.user.is_authenticated:
        next_param = quote(request.get_full_path(), safe="")
        return redirect(f"{reverse('teacher-login')}?next={next_param}")

    if request.user.pk != notif.recipient_id:
        return _notice_denied_response(
            request,
            "این پیوند متعلق به حساب کاربری دیگری است و در حساب فعلی قابل مشاهده نیست.",
            status=403,
        )

    has_access, reason = _recipient_still_has_access(notif)
    if not has_access:
        return _notice_denied_response(
            request,
            reason or "دسترسی شما به این بخش در حال حاضر فعال نیست.",
            status=403,
        )

    if notif.event_type.startswith("pub_"):
        return redirect(reverse("admin:catalog_book_request_publication", args=[notif.book_id]) + "#pub-offer")
    if notif.event_type.startswith("access_"):
        return redirect(reverse("admin:website_bookaccessrequest_change", args=[notif.object_id]))
    if notif.event_type.startswith("payout_"):
        return redirect(reverse("admin:commerce_payoutrequest_change", args=[notif.object_id]))

    return _notice_denied_response(request, "مقصد این پیام در دسترس نیست.", status=403)
