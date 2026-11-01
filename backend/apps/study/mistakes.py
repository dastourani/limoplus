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


def _maps(request) -> dict[str, AccessMap]:
    """One AccessMap per book for the whole request (each loads a whole book)."""
    if not hasattr(request, "_limo_maps"):
        request._limo_maps = {}
    return request._limo_maps


def _map_for(request, node) -> AccessMap:
    maps = _maps(request)
    bpath = node.path[: ContentNode.steplen]
    if bpath not in maps:
        maps[bpath] = AccessMap(request.user, node)
    return maps[bpath]


def _mistakes(request, book_slug=""):
    cached = getattr(request, "_limo_mistakes", None)
    if cached is not None and not book_slug:
        return cached
    last = last_answers(request.user)
    ids = [qid for qid, a in last.items() if not a["ok"]]
    questions = Question.objects.filter(pk__in=ids, is_archived=False).select_related("node")
    items = []
    for q in questions:
        access = _map_for(request, q.node)
        if not (access.visible(q.node_id) and (q.is_free or access.readable(q.node_id))):
            continue
        items.append((q, access.book, last[q.id]))
    all_books = sorted({b.slug: b for _, b, _ in items}.values(), key=lambda b: b.title)
    if book_slug:
        items = [i for i in items if i[1].slug == book_slug]
    items.sort(key=lambda i: i[2]["at"], reverse=True)
    result = (items[:MAX_ITEMS], all_books)
    if not book_slug:
        request._limo_mistakes = result
    return result


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
    question = get_object_or_404(Question, pk=question_id, is_archived=False)
    if was_mistake(request.user, question.pk) is None:
        return Response({"code": "not_a_mistake", "message": "این تست در دفترچه‌ی اشتباهات شما نیست."}, status=status.HTTP_404_NOT_FOUND)
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


# --- «مطالعه‌ی امروز» and «فقط ۵ دقیقه» -------------------------------------------------------------------------------

COMEBACK_DAYS = 3
COMEBACK_CARDS = 10


def _due_cards(request, limit=300):
    from .models import FlashcardReview

    now = timezone.now()
    reviews = (
        FlashcardReview.objects.filter(user=request.user, due_at__lte=now, flashcard__is_archived=False)
        .select_related("flashcard__node")
        .order_by("box", "due_at")
    )
    out = []
    for r in reviews[:limit]:
        card = r.flashcard
        access = _map_for(request, card.node)
        if access.visible(card.node_id) and (card.is_free or access.readable(card.node_id)):
            out.append(r)
    return out


def _away_days(user) -> int:
    from .models import StudyDay

    today = timezone.localdate()
    last = StudyDay.objects.filter(user=user, date__lt=today).order_by("-date").values_list("date", flat=True).first()
    return (today - last).days if last else 0


def _continue(request):
    if hasattr(request, "_limo_continue"):
        return request._limo_continue
    from .models import SectionProgress

    found = None
    for p in SectionProgress.objects.filter(user=request.user, is_done=False).select_related("node", "book").order_by("-updated_at")[:20]:
        if _map_for(request, p.node).readable(p.node_id):
            found = p
            break
    request._limo_continue = found
    return found


@api_view(["GET"])
def today(request):
    """What to do today: due cards (fewer after a break), a few mistakes, and the section in progress."""
    away = _away_days(request.user)
    comeback = away >= COMEBACK_DAYS
    due = len(_due_cards(request))
    cards = min(due, COMEBACK_CARDS) if comeback else due
    mistakes = len(_mistakes(request)[0])
    practise = min(mistakes, 5)
    cont = _continue(request)
    minutes = round(cards * 0.4 + practise * 1.5 + (8 if cont else 0))
    return Response(
        {
            "away_days": away,
            "comeback": comeback,
            "cards": cards,
            "cards_total": due,
            "mistakes": mistakes,
            "practise": practise,
            "continue": {"id": cont.node_id, "title": cont.node.title, "book_title": cont.book.title, "book_slug": cont.book.slug} if cont else None,
            "minutes": max(minutes, 5) if (cards or practise or cont) else 0,
        }
    )


@api_view(["GET"])
def quick(request):
    """«فقط ۵ دقیقه»: up to five due cards and three questions (mistakes first, then unanswered ones of the section in progress)."""
    from apps.learning.models import Flashcard

    from .views import _grade_hints

    cards = [
        {"id": r.flashcard.id, "title": r.flashcard.title, "point": media_urls(request, r.flashcard.point), "formula": r.flashcard.formula,
         "box": r.box, "hints": _grade_hints(r.box)}
        for r in _due_cards(request, limit=60)[:5]
    ]
    if not cards:
        cont = _continue(request)
        if cont:
            fresh = Flashcard.objects.filter(node=cont.node, is_archived=False).exclude(reviews__user=request.user).order_by("order", "id")[:3]
            cards = [{"id": f.id, "title": f.title, "point": media_urls(request, f.point), "formula": f.formula, "box": 0, "hints": _grade_hints(1)} for f in fresh]
    picked = [q for q, _, _ in _mistakes(request)[0][:3]]
    if len(picked) < 3:
        cont = _continue(request)
        if cont:
            answered = set(QuizAnswer.objects.filter(user=request.user, is_archived=False).values_list("question_id", flat=True))
            access = _map_for(request, cont.node)
            for q in Question.objects.filter(node=cont.node, is_archived=False).order_by("order", "id"):
                if len(picked) >= 3:
                    break
                if q.id not in answered and q not in picked and access.visible(q.node_id) and (q.is_free or access.readable(q.node_id)):
                    picked.append(q)
    qs = {q.id: q for q in Question.objects.filter(pk__in=[q.id for q in picked]).prefetch_related("choices", "questionsource_set__source")}
    return Response({"cards": cards, "questions": [_practice_payload(request, qs[q.id]) for q in picked]})


def _practice_payload(request, q):
    return {
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
