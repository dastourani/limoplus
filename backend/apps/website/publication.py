"""Version fingerprints and approval helpers for public book releases.

Public release is deliberately separate from private/group access. A release request snapshots the actual
book tree, notes, tests, choices, sources and flashcards; a manager cannot publish it if any of that content
changed after the request was submitted.
"""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import ContentNode
from apps.learning.models import Choice, Flashcard, Question, QuestionSource

from .models import PublicationRequest, PublicationRequestEvent


_NODE_VOLATILE = {
    "updated_at",
    "refreshed_at",
    "is_published",
    "single_sale_only",
    "campaign_discount_cap_percent",
}
_QUESTION_VOLATILE = {"added_at", "refreshed_at", "answer_count", "correct_count"}
_FLASHCARD_VOLATILE = {"added_at", "refreshed_at"}


def _field_rows(queryset, *, exclude=()):
    excluded = set(exclude)
    rows = []
    for obj in queryset:
        row = {}
        for field in obj._meta.concrete_fields:
            if field.name in excluded:
                continue
            value = getattr(obj, field.attname)
            if value.__class__.__name__ == "FieldFile":
                value = value.name
            row[field.name] = value
        rows.append(row)
    return rows


def publication_content_digest(book: ContentNode) -> str:
    """A stable SHA-256 of a book's public-facing content, excluding learner counters and release state."""
    if book.kind != ContentNode.Kind.BOOK or book.depth != 1:
        raise ValidationError("فقط ریشه‌ی یک کتاب را می‌توان برای انتشار عمومی ثبت کرد.")

    nodes = list(ContentNode.objects.filter(path__startswith=book.path).order_by("path", "pk"))
    node_ids = [node.pk for node in nodes]
    questions = list(Question.objects.filter(node_id__in=node_ids).order_by("node__path", "order", "pk"))
    question_ids = [question.pk for question in questions]
    flashcards = list(Flashcard.objects.filter(node_id__in=node_ids).order_by("node__path", "order", "pk"))

    major_links = list(book.majors.order_by("pk").values_list("pk", flat=True))
    flashcard_through = Question._meta.get_field("flashcards").remote_field.through
    similar_through = Question._meta.get_field("similar_to").remote_field.through
    question_flashcards = list(
        flashcard_through.objects.filter(question_id__in=question_ids)
        .order_by("question_id", "flashcard_id")
        .values_list("question_id", "flashcard_id")
    ) if question_ids else []
    similar_links = list(
        similar_through.objects.filter(from_question_id__in=question_ids)
        .order_by("from_question_id", "to_question_id")
        .values_list("from_question_id", "to_question_id")
    ) if question_ids else []

    source_rows = []
    for relation in QuestionSource.objects.filter(question_id__in=question_ids).select_related("source").order_by("question_id", "source_id"):
        source_rows.append({
            "question_id": relation.question_id,
            "source_id": relation.source_id,
            "number": relation.number,
            "name": relation.source.name,
            "year": relation.source.year,
            "group": relation.source.group,
            "booklet": relation.source.booklet,
        })

    payload = {
        "nodes": _field_rows(nodes, exclude=_NODE_VOLATILE),
        "book_majors": major_links,
        "questions": _field_rows(questions, exclude=_QUESTION_VOLATILE),
        "choices": _field_rows(Choice.objects.filter(question_id__in=question_ids).order_by("question_id", "order", "pk")),
        "question_sources": source_rows,
        "flashcards": _field_rows(flashcards, exclude=_FLASHCARD_VOLATILE),
        "question_flashcards": question_flashcards,
        "similar_tests": similar_links,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def record_publication_request(
    request: PublicationRequest,
    *,
    actor,
    action: str,
    reason="",
    offer_version=None,
    offer_digest="",
    offer_snapshot=None,
):
    return PublicationRequestEvent.objects.create(
        request=request,
        action=action,
        actor=actor,
        reason=(reason or "")[:500],
        content_digest=request.content_digest,
        offer_version=offer_version,
        offer_digest=offer_digest or "",
        offer_snapshot=offer_snapshot or {},
    )


def send_publication_offer(
    request_id: int,
    *,
    actor,
    platform_fee_percent: int,
    prep_mode: str,
    distribution_scope: str,
    campaign_discount_cap: int = 30,
    rate_validity_note: str = "",
    technical_deliverable: str = "",
    technical_export_disabled: bool = False,
    offer_note: str = "",
) -> PublicationRequest:
    """Explicitly publish a versioned offer to the teacher; draft saves never invoke this."""
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionError("فقط مدیر کل می‌تواند پیشنهاد مالی و شرایط انتشار را برای استاد ارسال کند.")
    if platform_fee_percent is None or not (10 <= int(platform_fee_percent) <= 40):
        raise ValidationError("سهم پلتفرم از فروش تکی این کتاب باید بین ۱۰ تا ۴۰ درصد باشد.")
    if prep_mode not in dict(PublicationRequest.OfferPrepMode.choices):
        raise ValidationError("نوع خدمات آماده‌سازی پیشنهادی را انتخاب کنید.")
    if distribution_scope not in dict(PublicationRequest.DistributionScope.choices):
        raise ValidationError("نوع عرضه پیشنهادی را انتخاب کنید.")
    if campaign_discount_cap is None or not (0 <= int(campaign_discount_cap) <= 80):
        raise ValidationError("سقف مجاز تخفیف کمپین باید بین ۰ تا ۸۰ درصد باشد.")
    offer_note = (offer_note or "").strip()
    if not offer_note:
        raise ValidationError("متن باکس شرایط و پیام مدیر به استاد را برای ارسال پیشنهاد وارد کنید.")

    with transaction.atomic():
        item = PublicationRequest.objects.select_for_update().get(pk=request_id)
        if item.status not in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO):
            raise ValidationError("برای درخواست نهایی‌شده امکان ارسال پیشنهاد جدید وجود ندارد.")

        item.offer_platform_fee_percent = int(platform_fee_percent)
        item.offer_prep_mode = prep_mode
        item.offer_distribution_scope = distribution_scope
        item.offer_campaign_discount_cap = int(campaign_discount_cap)
        item.offer_rate_validity_note = (rate_validity_note or PublicationRequest.DEFAULT_RATE_VALIDITY_NOTE).strip()
        item.offer_technical_deliverable = (technical_deliverable or PublicationRequest.DEFAULT_TECH_DELIVERABLE).strip()
        item.offer_technical_export_disabled = bool(technical_export_disabled)
        item.offer_note = offer_note

        payload = item.build_draft_offer_payload()
        digest = item.compute_offer_digest(payload)
        now = timezone.now()

        if item.has_sent_offer and item.sent_offer_digest == digest:
            # Re-sending identical terms is a reminder of the same version; preserve existing version & acceptance.
            item.offer_sent_at = now
            item.offer_sent_by = actor
            item.status = PublicationRequest.Status.PENDING
            item.save(update_fields=["offer_sent_at", "offer_sent_by", "status"])
        else:
            item.sent_offer_version = (item.sent_offer_version or 0) + 1
            item.sent_offer_digest = digest
            item.sent_offer_snapshot = {**payload, "version": item.sent_offer_version, "digest": digest}
            item.offer_sent_at = now
            item.offer_sent_by = actor
            item.status = PublicationRequest.Status.PENDING
            item.teacher_response = ""
            item.teacher_response_note = ""
            item.save()

        record_publication_request(
            item,
            actor=actor,
            action=PublicationRequestEvent.Action.OFFER_SENT,
            reason=offer_note,
            offer_version=item.sent_offer_version,
            offer_digest=digest,
            offer_snapshot=item.sent_offer_snapshot,
        )
        return item


def respond_to_publication_offer(
    request_id: int,
    *,
    actor,
    decision: str,
    note: str = "",
    expected_offer_digest: str = "",
    expected_offer_version: int | None = None,
) -> PublicationRequest:
    """Record an authorized book teacher's response strictly bound to the exact offer version and digest."""
    from apps.catalog import access
    from apps.catalog.models import BookEditor

    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionError("برای پاسخ به پیشنهاد باید وارد حساب خود شوید.")
    if actor.is_superuser:
        raise PermissionError("مدیر کل نمی‌تواند از طرف استاد به پیشنهاد مالی پاسخ دهد؛ فقط استاد مجاز کتاب باید پاسخ دهد.")
    if decision not in (
        PublicationRequest.TeacherResponse.ACCEPTED,
        PublicationRequest.TeacherResponse.REVISION_REQUESTED,
    ):
        raise ValidationError("نوع پاسخ به پیشنهاد معتبر نیست.")

    note = (note or "").strip()
    if decision == PublicationRequest.TeacherResponse.REVISION_REQUESTED and not note:
        raise ValidationError("برای درخواست بازنگری، نظر یا مورد اصلاحی خود را بنویسید.")
    if len(note) > 1000:
        raise ValidationError("متن پاسخ نباید بیش از ۱۰۰۰ نویسه باشد.")

    with transaction.atomic():
        item = PublicationRequest.objects.select_for_update().select_related("book").get(pk=request_id)
        if item.offer_sent_by_id and actor.pk == item.offer_sent_by_id:
            raise PermissionError("فرستندهٔ پیشنهاد نمی‌تواند جای استاد به پیشنهاد خودش پاسخ دهد.")
        has_right = (
            access.is_book_teacher(actor)
            and BookEditor.objects.filter(book=item.book, user=actor, can_request_publication=True).exists()
        )
        if not has_right:
            raise PermissionError("شما دسترسی پاسخ به پیشنهاد انتشار این کتاب را ندارید.")
        if item.status not in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO):
            raise ValidationError("این درخواست قبلاً نهایی شده است.")
        if not item.has_sent_offer:
            raise ValidationError("هنوز پیشنهاد رسمی از سوی مدیر کل ارسال نشده است.")
        try:
            parsed_version = None if expected_offer_version in (None, "") else int(expected_offer_version)
        except (TypeError, ValueError):
            parsed_version = None
        if (
            not expected_offer_digest
            or parsed_version is None
            or expected_offer_digest != item.sent_offer_digest
            or parsed_version != int(item.sent_offer_version)
        ):
            raise ValidationError(
                "نسخهٔ پیشنهاد پس از بازکردن صفحه تغییر کرده یا مشخصات نسخه ناقص است؛ لطفاً صفحه را تازه کرده و نسخهٔ فعلی را بررسی کنید."
            )

        now = timezone.now()
        item.teacher_response = decision
        item.teacher_response_note = note
        item.teacher_responded_by = actor
        item.teacher_responded_at = now

        if decision == PublicationRequest.TeacherResponse.ACCEPTED:
            item.accepted_offer_version = item.sent_offer_version
            item.accepted_offer_digest = item.sent_offer_digest
            item.accepted_offer_snapshot = {
                **(item.sent_offer_snapshot or {}),
                "accepted_by_id": actor.pk,
                "accepted_by_phone": getattr(actor, "phone", ""),
                "accepted_at": now.isoformat(),
            }
            action = PublicationRequestEvent.Action.OFFER_ACCEPTED
        else:
            action = PublicationRequestEvent.Action.OFFER_REVISION

        item.save(
            update_fields=[
                "teacher_response",
                "teacher_response_note",
                "teacher_responded_by",
                "teacher_responded_at",
                "accepted_offer_version",
                "accepted_offer_digest",
                "accepted_offer_snapshot",
            ]
        )
        record_publication_request(
            item,
            actor=actor,
            action=action,
            reason=note,
            offer_version=item.sent_offer_version,
            offer_digest=item.sent_offer_digest,
            offer_snapshot=item.sent_offer_snapshot,
        )
        return item


def incompatible_campaigns_for_book(book: ContentNode, discount_cap_percent: int | None) -> list[tuple[object, float]]:
    """Return active or upcoming SaleCampaign rows for `book` whose discount exceeds `discount_cap_percent`."""
    if discount_cap_percent is None or not book or not book.price or book.price <= 0:
        return []
    from decimal import Decimal
    from apps.commerce.models import SaleCampaign

    now = timezone.now()
    cap_dec = Decimal(discount_cap_percent)
    conflicts = []
    campaigns = SaleCampaign.objects.filter(book=book, is_active=True, ends_at__gt=now).order_by("starts_at", "pk")
    for c in campaigns:
        if c.discounted_price is not None and c.discounted_price < book.price:
            pct = (Decimal(book.price - c.discounted_price) * Decimal(100)) / Decimal(book.price)
            if pct > cap_dec:
                conflicts.append((c, float(round(pct, 1))))
    return conflicts


def _sync_accepted_terms_to_book_and_commerce(item: PublicationRequest, book: ContentNode) -> None:
    """Apply the teacher-accepted commercial terms atomically onto live catalog & royalty rules."""
    from apps.commerce.models import BookRoyaltyRule

    snapshot = item.accepted_offer_snapshot or item.sent_offer_snapshot or {}
    fee = int(snapshot["platform_fee_percent"])
    scope = snapshot.get("distribution_scope") or PublicationRequest.DistributionScope.STANDARD
    cap = snapshot.get("campaign_discount_cap")
    cap_value = None if cap is None else int(cap)

    rule, _ = BookRoyaltyRule.objects.get_or_create(book=book)
    rule.is_custom_split = True
    rule.custom_platform_share_percent = fee
    note_line = (
        f"توافق انتشار نسخه #{item.accepted_offer_version} "
        f"(سهم پلتفرم {fee}٪ / نوع عرضه: {snapshot.get('distribution_scope_label') or scope} / "
        f"سقف کمپین: {cap_value if cap_value is not None else '—'}٪)"
    )
    rule.notes = f"{note_line}\n{rule.notes}".strip() if rule.notes else note_line
    rule.save(update_fields=["is_custom_split", "custom_platform_share_percent", "notes", "updated_at"])

    ContentNode.objects.filter(pk=book.pk).update(
        single_sale_only=(scope == PublicationRequest.DistributionScope.SINGLE_SALE_ONLY),
        campaign_discount_cap_percent=cap_value,
        technical_export_disabled=bool(snapshot.get("technical_export_disabled")),
    )


def review_publication_request(request_id: int, *, actor, status: str, review_note="", content_feedback=""):
    """Record a manager decision; approval atomically releases only the exact submitted content + accepted offer."""
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionError("فقط مدیر کل می‌تواند انتشار عمومی را بررسی کند.")
    allowed = {
        PublicationRequest.Status.PENDING,
        PublicationRequest.Status.NEEDS_INFO,
        PublicationRequest.Status.APPROVED,
        PublicationRequest.Status.REJECTED,
    }
    if status not in allowed:
        raise ValidationError("وضعیت تصمیم معتبر نیست.")
    review_note = (review_note or "").strip()
    content_feedback = (content_feedback or "").strip()
    if status in (PublicationRequest.Status.NEEDS_INFO, PublicationRequest.Status.REJECTED) and not content_feedback:
        raise ValidationError("برای درخواست اصلاح محتوا یا رد انتشار، پیام قابل مشاهده برای استاد را وارد کنید.")
    if status == PublicationRequest.Status.APPROVED and not review_note and not content_feedback:
        raise ValidationError("برای ثبت تصمیم انتشار، یادداشت تصمیم یا پیام بررسی را وارد کنید.")
    if len(review_note) > 2000 or len(content_feedback) > 2000:
        raise ValidationError("متن یادداشت یا پیام بررسی نباید بیش از ۲۰۰۰ نویسه باشد.")

    with transaction.atomic():
        item = PublicationRequest.objects.select_for_update().get(pk=request_id)
        previous_status = item.status
        if previous_status not in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO):
            raise ValidationError("این درخواست قبلاً تصمیم‌گیری نهایی شده است.")
        book = ContentNode.objects.select_for_update().get(pk=item.book_id)
        if book.is_archived or book.is_inbox:
            raise ValidationError("کتاب بایگانی‌شده یا صندوق تست قابل انتشار نیست.")

        event_offer_version = None
        event_offer_digest = ""
        event_offer_snapshot = None

        if status == PublicationRequest.Status.APPROVED:
            if publication_content_digest(book) != item.content_digest:
                raise ValidationError("محتوا پس از ثبت درخواست تغییر کرده است؛ نسخه‌ی تازه باید دوباره برای بازبینی فرستاده شود.")
            if not item.has_sent_offer:
                raise ValidationError("پیش از تأیید و انتشار عمومی، ابتدا پیشنهاد مالی (۱۰ تا ۴۰ درصد) را برای استاد ارسال کنید.")
            if item.has_unsent_offer_changes:
                raise ValidationError(
                    "تغییرات جدید پیشنهاد هنوز برای استاد ارسال نشده است؛ ابتدا دکمه «ارسال پیشنهاد به استاد» را بزنید تا استاد نسخهٔ تازه را بپذیرد."
                )
            if not item.is_current_offer_accepted:
                raise ValidationError(
                    "استاد هنوز آخرین نسخهٔ پیشنهاد مالی و شرایط عرضه را نپذیرفته است؛ انتشار عمومی تا پذیرش نسخهٔ فعلی متوقف است."
                )
            accepted_cap = (item.accepted_offer_snapshot or item.sent_offer_snapshot or {}).get("campaign_discount_cap")
            conflicts = incompatible_campaigns_for_book(book, accepted_cap)
            if conflicts:
                summary_txt = "، ".join(f"«{c.title}» ({pct}٪)" for c, pct in conflicts)
                raise ValidationError(
                    f"کمپین فعال یا زمان‌بندی‌شدهٔ ناسازگار با سقف تخفیف توافق‌شده ({accepted_cap}٪) وجود دارد: {summary_txt}. پیش از تأیید انتشار، کمپین را اصلاح یا غیرفعال کنید."
                )
            event_offer_version = item.accepted_offer_version
            event_offer_digest = item.accepted_offer_digest
            event_offer_snapshot = item.accepted_offer_snapshot
            action = PublicationRequestEvent.Action.APPROVED
        elif status == PublicationRequest.Status.NEEDS_INFO:
            action = PublicationRequestEvent.Action.NEEDS_INFO
        elif status == PublicationRequest.Status.REJECTED:
            action = PublicationRequestEvent.Action.REJECTED
        elif previous_status == PublicationRequest.Status.NEEDS_INFO:
            action = PublicationRequestEvent.Action.REOPENED
        else:
            action = PublicationRequestEvent.Action.NOTE_UPDATED

        now = timezone.now()
        item.status = status
        item.content_feedback = content_feedback
        item.review_note = review_note
        item.reviewed_by = actor
        item.reviewed_at = now
        item.save(update_fields=["status", "content_feedback", "review_note", "reviewed_by", "reviewed_at"])

        if status == PublicationRequest.Status.APPROVED:
            _sync_accepted_terms_to_book_and_commerce(item, book)
            # The public catalog release is an independent manager decision. This does not touch group requests,
            # phone lists, student accounts or entitlements.
            ContentNode.objects.filter(path__startswith=book.path, is_archived=False).update(is_published=True)

        record_publication_request(
            item,
            actor=actor,
            action=action,
            reason=content_feedback or review_note,
            offer_version=event_offer_version,
            offer_digest=event_offer_digest,
            offer_snapshot=event_offer_snapshot,
        )
        return item
