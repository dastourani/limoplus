"""
How far a learner is with each section: not started, «خوانده شد» (the notes were read to the end) or «تمام شد» (read,
and at least 70% of the section's questions answered, right or wrong). Rounded down, but at least one: of 2 questions
1 is enough, of 3 two, of 10 seven. A section without questions is done when it is read. The same rule finishes a
chapter (reviews.is_finished).
"""

from __future__ import annotations

import math

from apps.learning.models import Question, QuizAnswer

from .models import ExamAnswer, SectionProgress

SHARE = 0.7


def needed(total: int) -> int:
    """How many of `total` questions must be answered."""
    return 0 if total <= 0 else max(1, math.floor(SHARE * total + 1e-9))


def answered_ids(user, request=None) -> set[int]:
    """Every question this learner has answered in practice or a submitted exam (kept for the request)."""
    cached = getattr(request, "_limo_answered", None) if request is not None else None
    if cached is not None:
        return cached
    ids = set(QuizAnswer.objects.filter(user=user).values_list("question_id", flat=True))
    ids |= set(
        ExamAnswer.objects.filter(attempt__user=user, attempt__submitted_at__isnull=False, choice_order__isnull=False).values_list("question_id", flat=True)
    )
    if request is not None:
        request._limo_answered = ids
    return ids


def read_ids(user, book, request=None) -> set[int]:
    cached = getattr(request, "_limo_done", None) if request is not None else None
    if cached is not None:
        return set(cached.get(book.id, []))
    return set(SectionProgress.objects.filter(user=user, book=book, is_done=True).values_list("node_id", flat=True))


def _questions_of(read: set[int], request=None) -> dict[int, list[tuple[int, bool]]]:
    """Questions of the read sections. On a page with many books (the shelves) one query loads them for every book the
    learner has read in, and later books are answered from the request."""
    cache = getattr(request, "_limo_questions", None) if request is not None else None
    if cache is None or not read <= cache[0]:
        wanted = set(read)
        everything = getattr(request, "_limo_done", None) if request is not None else None
        if everything is not None:
            for ids in everything.values():
                wanted.update(ids)
        found: dict[int, list[tuple[int, bool]]] = {}
        for qid, node_id, is_free in Question.objects.filter(node_id__in=list(wanted), is_archived=False).values_list("id", "node_id", "is_free"):
            found.setdefault(node_id, []).append((qid, is_free))
        cache = (wanted, found)
        if request is not None:
            request._limo_questions = cache
    return {sid: cache[1][sid] for sid in read if sid in cache[1]}


def section_states(user, access, request=None) -> tuple[set[int], set[int]]:
    """(read, done) section ids of the book behind `access` (done ⊆ read)."""
    if not user.is_authenticated:
        return set(), set()
    read = read_ids(user, access.book, request)
    if not read:
        return set(), set()
    per_section: dict[int, list[int]] = {}
    for node_id, rows in _questions_of(read, request).items():
        for qid, is_free in rows:
            if access.visible(node_id) and (is_free or access.readable(node_id)):
                per_section.setdefault(node_id, []).append(qid)
    answered = answered_ids(user, request) if per_section else set()
    done = {sid for sid in read if sum(1 for q in per_section.get(sid, []) if q in answered) >= needed(len(per_section.get(sid, [])))}
    return read, done
