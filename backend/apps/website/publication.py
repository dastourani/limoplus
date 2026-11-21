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


_NODE_VOLATILE = {"updated_at", "refreshed_at", "is_published"}
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


def record_publication_request(request: PublicationRequest, *, actor, action: str, reason=""):
    return PublicationRequestEvent.objects.create(
        request=request,
        action=action,
        actor=actor,
        reason=(reason or "")[:500],
        content_digest=request.content_digest,
    )


def review_publication_request(request_id: int, *, actor, status: str, review_note=""):
    """Record a manager decision; approval atomically releases only the exact submitted content snapshot."""
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
    if status in (PublicationRequest.Status.NEEDS_INFO, PublicationRequest.Status.APPROVED, PublicationRequest.Status.REJECTED) and not review_note:
        raise ValidationError("برای ثبت تصمیم انتشار، دلیل یا یادداشت را وارد کنید.")
    if len(review_note) > 2000:
        raise ValidationError("یادداشت تصمیم نباید بیش از ۲۰۰۰ نویسه باشد.")

    with transaction.atomic():
        item = PublicationRequest.objects.select_for_update().get(pk=request_id)
        previous_status = item.status
        if previous_status not in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO):
            raise ValidationError("این درخواست قبلاً تصمیم‌گیری نهایی شده است.")
        book = ContentNode.objects.select_for_update().get(pk=item.book_id)
        if book.is_archived or book.is_inbox:
            raise ValidationError("کتاب بایگانی‌شده یا صندوق تست قابل انتشار نیست.")

        if status == PublicationRequest.Status.APPROVED:
            if publication_content_digest(book) != item.content_digest:
                raise ValidationError("محتوا پس از ثبت درخواست تغییر کرده است؛ نسخه‌ی تازه باید دوباره برای بازبینی فرستاده شود.")
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
        item.review_note = review_note
        item.reviewed_by = actor
        item.reviewed_at = now
        item.save(update_fields=["status", "review_note", "reviewed_by", "reviewed_at"])

        if status == PublicationRequest.Status.APPROVED:
            # The public catalog release is an independent manager decision. This does not touch group requests,
            # phone lists, student accounts or entitlements.
            ContentNode.objects.filter(path__startswith=book.path, is_archived=False).update(is_published=True)

        record_publication_request(item, actor=actor, action=action, reason=review_note)
        return item
