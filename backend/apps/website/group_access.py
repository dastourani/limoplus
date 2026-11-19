"""Time-bounded book access for manager-approved, privately proposed student lists."""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ContentNode
from apps.commerce.models import Entitlement

from .models import BookAccessEvent, BookAccessMember, BookAccessRequest


def _approved_end(member: BookAccessMember, activated_at):
    request = member.request
    if request.status != BookAccessRequest.Status.APPROVED:
        return None
    if request.expiry_policy == BookAccessRequest.ExpiryPolicy.FIXED_DATE:
        if not request.ends_on:
            return None
        # The manager's selected date is inclusive; Entitlement.ends_at is an exclusive instant.
        exclusive_date = request.ends_on + timedelta(days=1)
        return timezone.make_aware(datetime.combine(exclusive_date, time.min))
    if request.expiry_policy == BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION and request.duration_days:
        return activated_at + timedelta(days=request.duration_days)
    return None


def activate_approved_members(user, *, now=None) -> int:
    """Attach matching approved numbers to this OTP-authenticated account, once, without sending a student invite.

    Call only after OTP verification and successful session-capacity checks. A proposed or unapproved row is never
    considered, and both the member and the entitlement are written in one transaction.
    """
    if not user or not user.pk or not user.is_active or not user.phone:
        return 0
    now = now or timezone.now()
    activated = 0

    with transaction.atomic():
        members = list(
            BookAccessMember.objects.select_for_update()
            .filter(
                phone=user.phone,
                status=BookAccessMember.Status.WAITING_OTP,
                request__status=BookAccessRequest.Status.APPROVED,
                entitlement__isnull=True,
            )
            .select_related("book", "request", "request__reviewed_by")
            .order_by("pk")
        )
        for member in members:
            request = member.request
            if (
                member.book_id != request.book_id
                or member.book.kind != ContentNode.Kind.BOOK
                or member.book.depth != 1
                or member.book.is_archived
                or member.book.is_inbox
            ):
                member.status = BookAccessMember.Status.EXPIRED
                member.save(update_fields=["status"])
                continue
            if not request.reviewed_by_id or not request.reviewed_at or not (request.review_note or "").strip():
                # Fail closed: an approved status without an auditable manager decision cannot grant access.
                raise ValidationError("تصمیم مستند مدیر کل برای این درخواست ثبت نشده است.")

            end_at = _approved_end(member, now)
            if end_at is None or end_at <= now:
                member.status = BookAccessMember.Status.EXPIRED
                member.save(update_fields=["status"])
                continue

            entitlement = Entitlement.objects.create(
                user=user,
                book=member.book,
                starts_at=now,
                ends_at=end_at,
                granted_by=request.reviewed_by,
                note=f"دسترسی گروهی؛ درخواست #{request.pk}"[:200],
            )
            member.user = user
            member.entitlement = entitlement
            member.activated_at = now
            member.status = BookAccessMember.Status.ACTIVE
            member.save(update_fields=["user", "entitlement", "activated_at", "status"])
            BookAccessEvent.objects.create(
                member=member,
                action=BookAccessEvent.Action.ACTIVATED,
                actor=None,  # The member's successful OTP login is the audited system event.
                reason="ورود موفق با OTP به شماره‌ی تأییدشده",
                new_ends_at=end_at,
            )
            activated += 1

    return activated
