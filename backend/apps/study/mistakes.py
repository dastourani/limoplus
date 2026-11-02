"""
«دفترچه‌ی اشتباهات»: every question the learner got wrong (or left blank in an exam).

A question goes through two steps before it leaves the notebook, because one right answer may only mean the learner
remembers the answer:
- «منتظر جبران» (open): the latest answer was wrong.
- «نیازمند تثبیت» (settling): answered right since, but not yet right again on a later day. It is due again
  SETTLE_DAYS days after that first right answer; a right answer on or after that day takes it out («تثبیت شد»).
A wrong answer at any point puts it back to the start. Built from the answer history, so nothing new is recorded.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

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
SETTLE_DAYS = 3

OPEN, SETTLING, SETTLED = "open", "settling", "settled"


def _day(at) -> date:
    return timezone.localdate(at)


def answer_rows(user, question_ids=None, since=None):
    """(question id, ok, at, source) for every practice and submitted exam answer; ok is None for a blank in an exam."""
    practice = QuizAnswer.objects.filter(user=user)
    exams = ExamAnswer.objects.filter(attempt__user=user, attempt__submitted_at__isnull=False)
    if question_ids is not None:
        practice = practice.filter(question_id__in=question_ids)
        exams = exams.filter(question_id__in=question_ids)
    if since is not None:
        practice = practice.filter(answered_at__gte=since)
        exams = exams.filter(attempt__submitted_at__gte=since)
    rows = [(qid, ok, at, "practice") for qid, ok, at in practice.values_list("question_id", "was_correct", "answered_at")]
    rows += [(qid, ok, at, "exam") for qid, ok, at in exams.values_list("question_id", "was_correct", "attempt__submitted_at") if at]
    rows.sort(key=lambda r: r[2])
    return rows


def _entry(answers) -> dict | None:
    """The notebook state of one question from its answers (oldest first), or None if never wrong."""
    wrong_at = [i for i, (ok, _, _) in enumerate(answers) if not ok]
    if not wrong_at:
        return None
    last_wrong = wrong_at[-1]
    ok, at, source = answers[-1]
    entry = {"ok": ok, "at": at, "source": source, "wrong": len(wrong_at), "wrong_at": answers[last_wrong][1],
             "state": OPEN, "due": None}
    after = answers[last_wrong + 1:]
    if after:
        due = _day(after[0][1]) + timedelta(days=SETTLE_DAYS)
        entry["due"] = due
        entry["state"] = SETTLED if any(_day(a) >= due for _, a, _ in after) else SETTLING
    return entry


def notebook(user, question_ids=None) -> dict[int, dict]:
    """question id → its notebook entry (see _entry), for every question the learner ever got wrong."""
    by_q: dict[int, list] = {}
    for qid, ok, at, source in answer_rows(user, question_ids):
        by_q.setdefault(qid, []).append((ok, at, source))
    out = {}
    for qid, answers in by_q.items():
        e = _entry(answers)
        if e:
            out[qid] = e
    return out


def in_notebook(e: dict | None) -> bool:
    return bool(e) and e["state"] != SETTLED


def is_due(e: dict, today: date | None = None) -> bool:
    """Open, or settling and its day has come: what practice from the notebook asks."""
    return e["state"] == OPEN or (e["state"] == SETTLING and (today or timezone.localdate()) >= e["due"])


def entry_for(user, question_id) -> dict | None:
    return notebook(user, [question_id]).get(question_id)


IMPROVEMENT_DAYS = 30


def improvement(user, days=IMPROVEMENT_DAYS) -> dict:
    """«چقدر واقعاً بهتر شده‌ام؟»: of the questions got wrong in the last `days` days, how many were answered right later
    and how many are settled (right again on a later day)."""
    since = timezone.now() - timedelta(days=days)
    by_q: dict[int, list] = {}
    for qid, ok, at, source in answer_rows(user):
        by_q.setdefault(qid, []).append((ok, at, source))
    wrong = fixed = settled = 0
    for answers in by_q.values():
        recent = [i for i, (ok, at, _) in enumerate(answers) if not ok and at >= since]
        if not recent:
            continue
        wrong += 1
        if any(ok for ok, _, _ in answers[recent[0] + 1:]):
            fixed += 1
        e = _entry(answers)
        if e and e["state"] == SETTLED:
            settled += 1
    return {"days": days, "wrong": wrong, "fixed": fixed, "settled": settled}


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
    book = notebook(request.user)
    ids = [qid for qid, e in book.items() if in_notebook(e)]
    questions = Question.objects.filter(pk__in=ids, is_archived=False).select_related("node")
    items = []
    for q in questions:
        access = _map_for(request, q.node)
        if not (access.visible(q.node_id) and (q.is_free or access.readable(q.node_id))):
            continue
        items.append((q, access.book, book[q.id]))
    all_books = sorted({b.slug: b for _, b, _ in items}.values(), key=lambda b: b.title)
    if book_slug:
        items = [i for i in items if i[1].slug == book_slug]
    # Open ones first, then settling ones whose day has come, then the rest; newest first within each.
    today = timezone.localdate()
    items.sort(key=lambda i: i[2]["at"], reverse=True)
    items.sort(key=lambda i: 0 if i[2]["state"] == OPEN else 1 if is_due(i[2], today) else 2)
    result = (items[:MAX_ITEMS], all_books)
    if not book_slug:
        request._limo_mistakes = result
    return result


def due_items(items):
    today = timezone.localdate()
    return [i for i in items if is_due(i[2], today)]


@api_view(["GET"])
def my_mistakes(request):
    items, books = _mistakes(request, request.query_params.get("book") or "")
    reasons = dict(MistakeNote.objects.filter(user=request.user, question_id__in=[q.id for q, _, _ in items]).values_list("question_id", "reason"))
    today = timezone.localdate()
    return Response(
        {
            "count": len(items),
            "open": sum(1 for _, _, a in items if a["state"] == OPEN),
            "settling": sum(1 for _, _, a in items if a["state"] == SETTLING),
            "due": sum(1 for _, _, a in items if is_due(a, today)),
            "settle_days": SETTLE_DAYS,
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
                    "state": a["state"],
                    "due_on": a["due"],
                    "is_due": is_due(a, today),
                    "reason": reasons.get(q.id, ""),
                    # The answer key changed after this learner's last answer.
                    "corrected": bool(q.key_changed_at and a["at"] < q.key_changed_at),
                }
                for q, book, a in items
            ],
            "books": [{"slug": b.slug, "title": b.title} for b in books],
            "reasons": [{"key": k, "label": v} for k, v in MistakeNote.Reason.choices],
        }
    )


@api_view(["GET"])
def mistake_questions(request):
    """The notebook's questions whose turn it is (open, or settling and due), shaped like a section's practice questions."""
    items, _ = _mistakes(request, request.query_params.get("book") or "")
    items = due_items(items)
    qs = Question.objects.filter(pk__in=[q.id for q, _, _ in items]).prefetch_related("choices", "questionsource_set__source")
    by_id = {q.id: q for q in qs}
    return Response({"questions": [_practice_payload(request, by_id[q.id]) for q, _, _ in items], "locked_count": 0})


@api_view(["POST"])
def mistake_reason(request, question_id):
    question = get_object_or_404(Question, pk=question_id, is_archived=False)
    if not in_notebook(entry_for(request.user, question.pk)):
        return Response({"code": "not_a_mistake", "message": "این تست در دفترچه‌ی اشتباهات شما نیست."}, status=status.HTTP_404_NOT_FOUND)
    reason = str(request.data.get("reason") or "")
    if reason and reason not in MistakeNote.Reason.values:
        return Response({"code": "invalid_reason", "message": "علت انتخاب‌شده معتبر نیست."}, status=status.HTTP_400_BAD_REQUEST)
    note, _ = MistakeNote.objects.get_or_create(user=request.user, question=question)
    note.reason = reason
    note.save(update_fields=["reason", "updated_at"])
    return Response({"reason": note.reason})


def fixed_info(user, question_id, now=None) -> dict | None:
    """Called before a right answer is saved, for a question in the notebook: what this answer does to it.
    step «settling»: first right answer, it comes back in SETTLE_DAYS days; «settled»: it leaves the notebook;
    «early»: settling and its day has not come yet, so nothing changes."""
    e = entry_for(user, question_id)
    if not in_notebook(e):
        return None
    now = now or timezone.now()
    days = (now - e["wrong_at"]).days
    if e["state"] == OPEN:
        return {"step": "settling", "days": days, "due_in": SETTLE_DAYS}
    if timezone.localdate(now) >= e["due"]:
        return {"step": "settled", "days": days}
    return {"step": "early", "days": days, "due_in": (e["due"] - timezone.localdate(now)).days}


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
    """«کارهای امروز»: one tile per job, in this order: the chapter reviews due (at most two), the flashcards due (fewer
    after a break), and five questions from the mistakes notebook. A job done today leaves the list.
    Kept for five minutes per learner, and worked out again at once after anything they do (reviews.recheck)."""
    from django.core.cache import cache

    key = f"limo.today.{request.user.pk}.{timezone.localdate()}"
    alias = f"limo.today.{request.user.pk}"
    if cache.get(alias) == key:
        cached = cache.get(key)
        if cached is not None:
            return Response(cached)
    data = _today_data(request)
    cache.set(key, data, 300)
    cache.set(alias, key, 300)
    return Response(data)


def _today_data(request) -> dict:
    from .reviews import DAILY_CAP, due_reviews

    away = _away_days(request.user)
    comeback = away >= COMEBACK_DAYS
    cards_due = len(_due_cards(request))
    cards = min(cards_due, COMEBACK_CARDS) if comeback else cards_due
    mistakes = len(due_items(_mistakes(request)[0]))
    practised = _notebook_answered_today(request.user)
    practise = 0 if practised >= NOTEBOOK_DAILY else min(mistakes, NOTEBOOK_DAILY - practised)
    cont = _continue(request)
    reviews_due = due_reviews(request.user)
    todays = reviews_due[:DAILY_CAP]

    tasks = [{**r, "kind": "review", "review_kind": r["kind"]} for r in todays]
    if cards:
        tasks.append({"kind": "cards", "count": cards, "total": cards_due, "comeback": comeback, "minutes": max(1, round(cards * 0.4))})
    if practise:
        tasks.append({"kind": "notebook", "count": practise, "total": mistakes, "minutes": max(1, round(practise * 1.5))})
    minutes = sum(t["minutes"] for t in tasks)
    return (
        {
            "away_days": away,
            "comeback": comeback,
            "cards": cards,
            "cards_total": cards_due,
            "mistakes": mistakes,
            "practise": practise,
            "continue": {"id": cont.node_id, "title": cont.node.title, "book_title": cont.book.title, "book_slug": cont.book.slug} if cont else None,
            # «مرور فصل ۲ «…» از …: ۵ تست، حدود ۷ دقیقه» (at most two a day, the oldest first).
            "reviews": todays,
            "reviews_waiting": max(0, len(reviews_due) - len(todays)),
            "tasks": tasks,
            "minutes": minutes,
        }
    )


NOTEBOOK_DAILY = 5


def _notebook_answered_today(user) -> int:
    """Questions from the notebook answered today in practice (not counting the wrong answer that put one there)."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ids = set(QuizAnswer.objects.filter(user=user, answered_at__gte=start).values_list("question_id", flat=True))
    if not today_ids:
        return 0
    earlier_wrong = set(
        QuizAnswer.objects.filter(user=user, question_id__in=today_ids, answered_at__lt=start, was_correct=False).values_list("question_id", flat=True)
    ) | set(
        ExamAnswer.objects.filter(attempt__user=user, question_id__in=today_ids, attempt__submitted_at__lt=start)
        .exclude(was_correct=True).values_list("question_id", flat=True)
    )
    return len(earlier_wrong)


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
    picked = [q for q, _, _ in due_items(_mistakes(request)[0])[:3]]
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
        "fixed_order": q.keeps_order,
        "corrected": q.correction(),
    }
