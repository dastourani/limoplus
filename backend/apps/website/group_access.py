"""Time-bounded book access for manager-approved lists and teacher classrooms."""

from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ContentNode
from apps.commerce.models import Entitlement

from .models import BookAccessEvent, BookAccessMember, BookAccessRequest


def is_valid_cohort_book(book: ContentNode | None) -> bool:
    """True when the target ContentNode is an active, non-archived, non-inbox book root."""
    return bool(
        book is not None
        and book.kind == ContentNode.Kind.BOOK
        and book.depth == 1
        and not book.is_archived
        and not book.is_inbox
    )


def inclusive_date_end(ends_on):
    """Inclusive date boundary: `ends_on` lasts through 23:59:59, so Entitlement.ends_at is next day 00:00."""
    if not ends_on:
        return None
    exclusive_date = ends_on + timedelta(days=1)
    return timezone.make_aware(datetime.combine(exclusive_date, time.min))


def calculate_cohort_end_time(*, expiry_policy: str, ends_on=None, duration_days=None, now=None):
    """Shared expiry calculation across BookAccessRequest and Classroom."""
    now = now or timezone.now()
    if expiry_policy == "unlimited":
        return None
    if expiry_policy == "fixed_date":
        return inclusive_date_end(ends_on)
    if expiry_policy in ("from_activation", "from_join") and duration_days:
        return now + timedelta(days=duration_days)
    return None


def is_entitlement_active_now(entitlement: Entitlement | None, now=None) -> bool:
    """True when an entitlement row currently grants live access."""
    if entitlement is None or entitlement.is_archived:
        return False
    now = now or timezone.now()
    return bool(entitlement.starts_at <= now and (entitlement.ends_at is None or entitlement.ends_at > now))


def _approved_end(member: BookAccessMember, activated_at):
    request = member.request
    if request.status != BookAccessRequest.Status.APPROVED:
        return None
    return calculate_cohort_end_time(
        expiry_policy=request.expiry_policy,
        ends_on=request.ends_on,
        duration_days=request.duration_days,
        now=activated_at,
    )


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
            BookAccessMember.objects.select_for_update(of=("self", "request"))
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
            if member.book_id != request.book_id or not is_valid_cohort_book(member.book):
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


def activate_classroom_members(user, *, now=None, classroom_id=None) -> int:
    """Attach matching classroom memberships to this OTP-authenticated account and grant entitlement.

    Called during OTP login or invite link redemption. Enforces classroom expiry, book validity, and
    capacity atomically under row locks.
    """
    if not user or not user.pk or not user.is_active or not user.phone:
        return 0
    from .models import ClassroomMember

    now = now or timezone.now()
    activated = 0

    with transaction.atomic():
        qs = (
            ClassroomMember.objects.select_for_update(of=("self", "classroom"))
            .filter(
                phone=user.phone,
                status=ClassroomMember.Status.WAITING_OTP,
                classroom__is_active=True,
                entitlement__isnull=True,
            )
            .select_related("classroom", "classroom__book", "classroom__teacher")
            .order_by("pk")
        )
        if classroom_id is not None:
            qs = qs.filter(classroom_id=classroom_id)
        members = list(qs)

        for member in members:
            classroom = member.classroom
            if not is_valid_cohort_book(classroom.book):
                member.status = ClassroomMember.Status.EXPIRED
                member.save(update_fields=["status"])
                continue

            end_at = classroom.calculate_end_time(now)
            if end_at is not None and end_at <= now:
                member.status = ClassroomMember.Status.EXPIRED
                member.save(update_fields=["status"])
                continue

            if not classroom.has_capacity:
                # Capacity reached: do not grant an entitlement over the classroom limit.
                continue

            entitlement = Entitlement.objects.create(
                user=user,
                book=classroom.book,
                starts_at=now,
                ends_at=end_at,
                granted_by=classroom.teacher,
                note=f"کلاس اختصاصی: {classroom.title}"[:200],
            )
            member.user = user
            member.entitlement = entitlement
            member.joined_at = now
            member.status = ClassroomMember.Status.ACTIVE
            member.save(update_fields=["user", "entitlement", "joined_at", "status"])
            activated += 1

    return activated
