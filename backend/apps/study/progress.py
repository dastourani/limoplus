"""
How far a learner is with each section (the circle beside it in the book page, and its wedge in the chapter's lemon):

- empty: neither of the two below
- half («خوانده شد»): the notes were read to the end, OR at least 70% of the section's questions were answered
- done («تمام شد»): both

70% is rounded up, and at least one: of 2 questions both, of 3 three, of 4 three, of 10 seven. Answers count right or
wrong. A section without questions is done when it is read. The same count finishes a chapter (reviews.is_finished).
"""

from __future__ import annotations

import math

from apps.learning.models import Question, QuizAnswer

from .models import ExamAnswer, SectionProgress

SHARE = 0.7


def needed(total: int) -> int:
    """How many of `total` questions must be answered."""
    return 0 if total <= 0 else max(1, math.ceil(SHARE * total - 1e-9))


def answered_ids(user, request=None) -> set[int]:
    """Every question this learner has answered in practice or a submitted exam (kept for the request)."""
    return _answered(user, request)[0]


def _answered(user, request=None) -> tuple[set[int], set[int]]:
    """(question ids, their section ids) answered in practice or a submitted exam."""
    cached = getattr(request, "_limo_answered2", None) if request is not None else None
    if cached is not None:
        return cached
    rows = set(QuizAnswer.objects.filter(user=user).values_list("question_id", "question__node_id"))
    rows |= set(
        ExamAnswer.objects.filter(attempt__user=user, attempt__submitted_at__isnull=False, choice_order__isnull=False).values_list(
            "question_id", "question__node_id"
        )
    )
    result = ({q for q, _ in rows}, {n for _, n in rows})
    if request is not None:
        request._limo_answered2 = result
    return result


def read_ids(user, book, request=None) -> set[int]:
    cached = getattr(request, "_limo_done", None) if request is not None else None
    if cached is not None:
        return set(cached.get(book.id, []))
    return set(SectionProgress.objects.filter(user=user, book=book, is_done=True).values_list("node_id", flat=True))


def _questions_of(sections: set[int], request=None) -> dict[int, list[tuple[int, bool]]]:
    """Questions of these sections. On a page with many books (the shelves) one query loads them for every section the
    learner has read or answered in, and later books are answered from the request."""
    cache = getattr(request, "_limo_questions", None) if request is not None else None
    if cache is None or not sections <= cache[0]:
        wanted = set(sections)
        everything = getattr(request, "_limo_done", None) if request is not None else None
        if everything is not None:
            for ids in everything.values():
                wanted.update(ids)
        if request is not None and getattr(request, "_limo_answered2", None) is not None:
            wanted |= request._limo_answered2[1]
        found: dict[int, list[tuple[int, bool]]] = {}
        for qid, node_id, is_free in Question.objects.filter(node_id__in=list(wanted), is_archived=False).values_list("id", "node_id", "is_free"):
            found.setdefault(node_id, []).append((qid, is_free))
        cache = (wanted, found)
        if request is not None:
            request._limo_questions = cache
    return {sid: cache[1][sid] for sid in sections if sid in cache[1]}


def section_states(user, access, request=None) -> tuple[set[int], set[int]]:
    """(started, done) section ids of the book behind `access`: started = read or tested (done ⊆ started)."""
    if not user.is_authenticated:
        return set(), set()
    read = read_ids(user, access.book, request)
    answered, answered_sections = _answered(user, request)
    in_book = {n for n in answered_sections if n in access.nodes}
    if not read and not in_book:
        return set(), set()
    per_section: dict[int, list[int]] = {}
    for node_id, rows in _questions_of(read | in_book, request).items():
        for qid, is_free in rows:
            if access.visible(node_id) and (is_free or access.readable(node_id)):
                per_section.setdefault(node_id, []).append(qid)
    tested = {
        sid for sid, qs in per_section.items() if qs and sum(1 for q in qs if q in answered) >= needed(len(qs))
    }
    # A section without questions needs only reading.
    done = {sid for sid in read if sid in tested or not per_section.get(sid)}
    started = read | tested
    return started, done
