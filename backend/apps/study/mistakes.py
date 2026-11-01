"""
«دفترچه‌ی اشتباهات»: every question whose latest answer by the learner (practice or exam) was wrong or left blank in
an exam. Answering it right later takes it out (and the app shows «اشتباهی که برطرف شد»). The learner may note why
they got it wrong. Built from the answer history, so nothing new has to be recorded when answering.
"""

from __future__ import annotations

import re
from datetime import datetime

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.access import AccessMap
from apps.catalog.models import ContentNode
from apps.catalog.views import media_urls
from apps.learning.models import Question, QuizAnswer

from .models import ExamAnswer, MistakeNote

MAX_ITEMS = 300


def last_answers(user, question_ids=None) -> dict[int, dict]:
    """question id → {"ok": bool|None (None = blank in an exam), "at": datetime, "wrong": times wrong, "source"}."""
    out: dict[int, dict] = {}

    def add(qid, ok, at, source):
        if at is None:
            return
        cur = out.get(qid)
        wrong = (cur["wrong"] if cur else 0) + (0 if ok else 1)
        if cur is None or at >= cur["at"]:
            out[qid] = {"ok": ok, "at": at, "wrong": wrong, "source": source}
        else:
            cur["wrong"] = wrong

    practice = QuizAnswer.objects.filter(user=user)
    exams = ExamAnswer.objects.filter(attempt__user=user, attempt__submitted_at__isnull=False)
    if question_ids is not None:
        practice = practice.filter(question_id__in=question_ids)
        exams = exams.filter(question_id__in=question_ids)
    for qid, ok, at in practice.values_list("question_id", "was_correct", "answered_at"):
        add(qid, ok, at, "practice")
    for qid, ok, at in exams.values_list("question_id", "was_correct", "attempt__submitted_at"):
        add(qid, ok, at, "exam")
    return out


def was_mistake(user, question_id) -> datetime | None:
    """When the learner last got this question wrong, if that is their latest answer; else None."""
    last = last_answers(user, [question_id]).get(question_id)
    return last["at"] if last and not last["ok"] else None


def _plain(text: str, limit=160) -> str:
    """A short start of the question: images dropped, formulas kept whole (the app draws them)."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text or "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = limit
    if text[:cut].count("$") % 2:  # don't stop inside a formula
        end = text.find("$", cut)
        cut = end + 1 if end >= 0 else text.rfind("$", 0, cut)
    return text[:cut].rstrip() + "…"


def _mistakes(request, book_slug=""):
    last = last_answers(request.user)
    ids = [qid for qid, a in last.items() if not a["ok"]]
    questions = Question.objects.filter(pk__in=ids, is_archived=False).select_related("node")
    steplen = ContentNode.steplen
    maps: dict[str, AccessMap] = {}
    books: dict[str, ContentNode] = {}
    items = []
    for q in questions:
        bpath = q.node.path[:steplen]
        if bpath not in maps:
            maps[bpath] = AccessMap(request.user, q.node)
            books[bpath] = maps[bpath].book
        access = maps[bpath]
        if not (access.visible(q.node_id) and (q.is_free or access.readable(q.node_id))):
            continue
        items.append((q, books[bpath], last[q.id]))
    all_books = sorted({b.slug: b for _, b, _ in items}.values(), key=lambda b: b.title)
    if book_slug:
        items = [i for i in items if i[1].slug == book_slug]
    items.sort(key=lambda i: i[2]["at"], reverse=True)
    return items[:MAX_ITEMS], all_books


@api_view(["GET"])
def my_mistakes(request):
    items, books = _mistakes(request, request.query_params.get("book") or "")
    reasons = dict(MistakeNote.objects.filter(user=request.user, question_id__in=[q.id for q, _, _ in items]).values_list("question_id", "reason"))
    return Response(
        {
            "count": len(items),
            "items": [
                {
                    "question_id": q.id,
                    "text": _plain(q.stem),
                    "node_id": q.node_id,
                    "node_title": q.node.title,
                    "book_slug": book.slug,
                    "book_title": book.title,
                    "wrong_count": a["wrong"],
                    "blank": a["ok"] is None,
                    "source": a["source"],
                    "last_at": a["at"],
                    "reason": reasons.get(q.id, ""),
                }
                for q, book, a in items
            ],
            "books": [{"slug": b.slug, "title": b.title} for b in books],
            "reasons": [{"key": k, "label": v} for k, v in MistakeNote.Reason.choices],
        }
    )


@api_view(["GET"])
def mistake_questions(request):
    """The notebook's questions in the same shape as a section's practice questions (answers are not sent)."""
    items, _ = _mistakes(request, request.query_params.get("book") or "")
    qs = Question.objects.filter(pk__in=[q.id for q, _, _ in items]).prefetch_related("choices", "questionsource_set__source")
    by_id = {q.id: q for q in qs}
    out = []
    for q0, _, _ in items:
        q = by_id[q0.id]
        out.append(
            {
                "id": q.id,
                "node_id": q.node_id,
                "stem": media_urls(request, q.stem),
                "choices": [{"id": c.id, "text": media_urls(request, c.text)} for c in q.choices.all()],
                "difficulty": q.difficulty,
                "measured_difficulty": q.measured_difficulty,
                "domain": q.domain,
                "kind": q.kind,
                "estimated_seconds": q.estimated_seconds,
                "is_original": q.is_original,
                "sources": [{"name": s.source.name, "year": s.source.year, "number": s.number} for s in q.questionsource_set.all()],
            }
        )
    return Response({"questions": out, "locked_count": 0})


@api_view(["POST"])
def mistake_reason(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    reason = str(request.data.get("reason") or "")
    if reason and reason not in MistakeNote.Reason.values:
        return Response({"code": "invalid_reason", "message": "علت انتخاب‌شده معتبر نیست."}, status=status.HTTP_400_BAD_REQUEST)
    note, _ = MistakeNote.objects.get_or_create(user=request.user, question=question)
    note.reason = reason
    note.save(update_fields=["reason", "updated_at"])
    return Response({"reason": note.reason})


def fixed_info(user, question_id, now=None) -> dict | None:
    """Called before a right answer is saved: if the question was in the notebook, how long ago it went wrong."""
    when = was_mistake(user, question_id)
    if when is None:
        return None
    days = ((now or timezone.now()) - when).days
    return {"days": days}
