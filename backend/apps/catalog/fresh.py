"""
What changed in a book, for learners.

- «مطلب تازه» (a tick in the panel when saving): the section, test or flashcard gets `refreshed_at`, and a line goes to
  the book's «تغییرات کتاب» (models.BookChange). The app shows «به‌روز شده» on it until the learner has seen it since
  (read the section, answered the test, reviewed the card). A ticked flashcard comes back into today's review once.
- «تازه»: a test or flashcard added after the learner started its section (its `added_at`), until they have answered or
  reviewed it, and for at most NEW_DAYS days. Nothing is marked for someone who has not started the section.
- «دستورهای فرمول» (models.FormulaCommand): the KaTeX macros of every formula.
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

NEW_DAYS = 14

_macros: tuple[float, dict] | None = None


def formula_macros() -> dict[str, str]:
    """{"\\R": "\\mathbb{R}"} for KaTeX (kept 20 seconds, like the labels)."""
    global _macros
    if _macros and time.monotonic() - _macros[0] < 20:
        return _macros[1]
    from django.db import DatabaseError

    from .models import FormulaCommand

    try:
        data = {c.name: c.definition for c in FormulaCommand.objects.filter(is_hidden=False)}
    except DatabaseError:
        data = {}
    _macros = (time.monotonic(), data)
    return data


def forget_macros():
    global _macros
    _macros = None


# --- Marking (the panel) -------------------------------------------------------------------------------------


def mark(book, *, nodes=(), questions=(), flashcards=(), text: str = "", where=None) -> int:
    """Mark these as «به‌روز شده» now and write the change line. Returns how many were marked."""
    from apps.learning.models import Flashcard, Question
    from apps.study.models import FlashcardReview

    from .models import BookChange, ContentNode

    now = timezone.now()
    n = ContentNode.objects.filter(pk__in=[x for x in nodes if x]).update(refreshed_at=now)
    n += Question.objects.filter(pk__in=[x for x in questions if x]).update(refreshed_at=now)
    cards = [x for x in flashcards if x]
    n += Flashcard.objects.filter(pk__in=cards).update(refreshed_at=now)
    # A card worth a second look comes back into today's review (its box stays as it is).
    FlashcardReview.objects.filter(flashcard_id__in=cards, due_at__gt=now).update(due_at=now)
    if n:
        BookChange.objects.create(book=book, node=where, text=(text or "").strip()[:300] or default_text(nodes, questions, flashcards))
    return n


def default_text(nodes, questions, flashcards) -> str:
    parts = []
    if nodes:
        parts.append(f"{fa(len(nodes))} بخش")
    if questions:
        parts.append(f"{fa(len(questions))} تست")
    if flashcards:
        parts.append(f"{fa(len(flashcards))} فلش‌کارت")
    return "به‌روزرسانی " + "، ".join(parts) if parts else "به‌روزرسانی"


def fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# --- What the learner sees -----------------------------------------------------------------------------------


def section_badges(user, nodes) -> dict[int, str]:
    """{section id: "updated"} for sections marked since this learner last read them (read before the mark)."""
    marked = {n.id: n.refreshed_at for n in nodes if getattr(n, "refreshed_at", None)}
    if not marked or not user.is_authenticated:
        return {}
    from apps.study.models import SectionProgress

    seen = dict(SectionProgress.objects.filter(user=user, node_id__in=list(marked)).values_list("node_id", "updated_at"))
    return {i: "updated" for i, at in marked.items() if i in seen and seen[i] < at}


def question_badges(user, questions) -> dict[int, str]:
    """{question id: "new" | "updated"} for one learner (see the module's note)."""
    if not user.is_authenticated:
        return {}
    from apps.learning.models import QuizAnswer
    from apps.study.models import SectionProgress

    questions = list(questions)
    ids = [q.id for q in questions]
    last = dict(QuizAnswer.objects.filter(user=user, question_id__in=ids).values("question_id").annotate(at=Max("answered_at")).values_list("question_id", "at"))
    started = dict(SectionProgress.objects.filter(user=user, node_id__in={q.node_id for q in questions}).values_list("node_id", "first_opened_at"))
    return _badges(questions, last, started)


def flashcard_badges(user, cards) -> dict[int, str]:
    if not user.is_authenticated:
        return {}
    from apps.study.models import FlashcardReview, SectionProgress

    cards = list(cards)
    last = dict(FlashcardReview.objects.filter(user=user, flashcard_id__in=[c.id for c in cards]).values_list("flashcard_id", "last_reviewed_at"))
    started = dict(SectionProgress.objects.filter(user=user, node_id__in={c.node_id for c in cards}).values_list("node_id", "first_opened_at"))
    return _badges(cards, last, started)


def _badges(items, last_seen: dict, started: dict) -> dict[int, str]:
    now = timezone.now()
    out = {}
    for x in items:
        seen = last_seen.get(x.id)
        if x.refreshed_at and seen and seen < x.refreshed_at:
            out[x.id] = "updated"
        elif (x.added_at and not seen and x.node_id in started and started[x.node_id] < x.added_at
              and now - x.added_at < timedelta(days=NEW_DAYS)):
            out[x.id] = "new"
    return out


def book_updated_on(book):
    """The date of the book's last «مطلب تازه» (shown as «آخرین به‌روزرسانی»), or None."""
    return book.changes.filter(is_hidden=False).values_list("created_at", flat=True).first()
