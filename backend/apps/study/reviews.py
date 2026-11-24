"""
«چرخه‌ی مرور فصل» and «مرور ترکیبی کتاب».

A chapter is finished when every readable section is read and at least 70% of its questions are answered, or when the
learner presses «این فصل را تمام کردم». Its review cycle then starts:

    step 0: 1 day after the chapter was finished    at least 5 questions, practice (answer shown after each)
    step 1: 7 days after it                         at least 10 questions, practice
    step 2: 30 days after it                        an exam without negative marking (answers at the end)
    step 3+: then every ~75 days, the same exam

The first three are counted from the day the chapter was finished, whatever the results (so «یک‌ماهه» is a month). A
result under 60% repeats the same step sooner (half its distance from the previous step). After the month step the
gaps follow the results: 75 days, a little longer for 90% or more, half for under 60%.

Questions come five at a time; after the minimum, «۵ تست دیگر» goes on until the chapter has none left.

Which questions: notebook ones that are due, then «شک‌دار» ones, then earlier right answers (oldest first, one per idea:
another question tied to the same flashcard rather than the same one again), then never-answered ones; at least one per
section before a second from the same section. Questions answered today and those served in the last review are left
for later when there are enough others.

From two finished chapters on, a book also gets a weekly mixed review over all its finished chapters.

Answers go through the normal practice answer, so the notebook and the statistics see them as always.
"""

from __future__ import annotations

import math
from datetime import timedelta

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.access import AccessMap
from apps.catalog.models import ContentNode
from apps.learning.models import Flashcard, Question, QuizAnswer

from .models import BookReview, ChapterReview, ExamAnswer, ExamAttempt, FlashcardReview, ReviewSession, SectionProgress

STEP_DAYS = [1, 7, 30]  # days after the chapter was finished
LATER_DAYS = 75  # after the month step, between reviews
MIN_GAP_AFTER_LATE = 2  # a step reached late still waits a couple of days after the previous review
EXAM_STEP = 2
PRACTICE_MINIMUM = {0: 5, 1: 10}
EXAM_MIN, EXAM_MAX = 15, 25
BATCH = 5
BOOK_MINIMUM = 10
BOOK_EVERY_DAYS = 7
FINISH_SHARE = 0.7
DAILY_CAP = 2
SECONDS_PER_QUESTION = 80  # «۵ تست، حدود ۷ دقیقه»
EXAM_LATE = timedelta(minutes=5)
SYNC_EVERY = timedelta(minutes=10)


# --- When a chapter is finished --------------------------------------------------------------------------------------


def _usable(access, q) -> bool:
    return access.usable(q)


def chapter_pool(access, chapter) -> list[Question]:
    ids = access.visible_ids_under(chapter)
    return [q for q in Question.objects.filter(node_id__in=ids, is_archived=False).only("id", "node_id", "is_free", "is_extra", "estimated_seconds") if _usable(access, q)]


def _sections(access, chapter) -> list[ContentNode]:
    return [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and n.path.startswith(chapter.path) and access.readable(n.id)]


def _answered_ids(user, ids) -> set[int]:
    out = set(QuizAnswer.objects.filter(user=user, question_id__in=ids).values_list("question_id", flat=True))
    out |= set(
        ExamAnswer.objects.filter(attempt__user=user, attempt__submitted_at__isnull=False, question_id__in=ids, choice_order__isnull=False)
        .values_list("question_id", flat=True)
    )
    return out


def is_finished(user, access, chapter) -> bool:
    sections = _sections(access, chapter)
    if not sections:
        return False
    read = SectionProgress.objects.filter(user=user, node_id__in=[s.id for s in sections], is_done=True).count()
    if read < len(sections):
        return False
    from .progress import core, needed

    # The same rule as a section's green tick: 70% of the core questions answered, rounded up, at least one.
    by_section: dict[int, list] = {}
    for q in chapter_pool(access, chapter):
        by_section.setdefault(q.node_id, []).append((q.id, q.is_extra))
    pool = [qid for rows in by_section.values() for qid in core(rows)]
    return not pool or len(_answered_ids(user, pool)) >= needed(len(pool))


def start_cycle(user, access, chapter, by="auto") -> ChapterReview:
    """The chapter is finished: its reviews are scheduled and its flashcards join the Leitner box."""
    now = timezone.now()
    review, created = ChapterReview.objects.get_or_create(
        user=user, chapter=chapter,
        defaults={"book": access.book, "finished_at": now, "finished_by": by, "due_on": timezone.localdate() + timedelta(days=STEP_DAYS[0])},
    )
    if not created and review.is_archived:
        review.is_archived = False
        review.save(update_fields=["is_archived"])
    if created:
        cards = Flashcard.objects.filter(node_id__in=access.visible_ids_under(chapter), is_archived=False).exclude(reviews__user=user)
        FlashcardReview.objects.bulk_create(
            [FlashcardReview(user=user, flashcard=c, box=1, due_at=now) for c in cards if _usable(access, c)], ignore_conflicts=True
        )
        finished = ChapterReview.objects.filter(user=user, book=access.book, is_archived=False).count()
        if finished >= 2:
            BookReview.objects.get_or_create(user=user, book=access.book, defaults={"due_on": timezone.localdate() + timedelta(days=BOOK_EVERY_DAYS)})
    return review


def recheck(user) -> None:
    """Something that changes the learner's day happened (a section read, a question answered, a card or review done):
    look again for finished chapters, and work out «برنامه‌ی امروز» afresh."""
    from django.core.cache import cache

    cache.delete(f"limo.review_sync.{user.pk}")
    cache.delete(f"limo.today.{user.pk}")


def sync(user, force=False) -> None:
    """Start the cycle of every chapter that became finished (in the books this learner reads). Checked at most every
    ten minutes per learner, since it looks at every book they read."""
    if not user.is_authenticated:
        return
    from django.core.cache import cache

    key = f"limo.review_sync.{user.pk}"
    if not force and cache.get(key):
        return
    cache.set(key, True, SYNC_EVERY.total_seconds())
    started = set(ChapterReview.objects.filter(user=user).values_list("chapter_id", flat=True))
    for book in ContentNode.objects.filter(pk__in=SectionProgress.objects.filter(user=user, is_done=True).values("book_id")):
        access = AccessMap(user, book)
        for chapter in access.children(book):
            if chapter.kind == ContentNode.Kind.CHAPTER and chapter.id not in started and is_finished(user, access, chapter):
                start_cycle(user, access, chapter)


# --- Picking the questions -------------------------------------------------------------------------------------------


def pick(user, pool: list[Question], n: int, exclude: set[int], avoid: set[int]) -> list[int]:
    """Up to n question ids from the pool (see the module notes for the order)."""
    from .mistakes import OPEN, SETTLING, answer_rows, is_due, notebook

    ids = [q.id for q in pool if q.id not in exclude]
    if not ids:
        return []
    by_id = {q.id: q for q in pool}
    last_at, last_ok = {}, {}
    for qid, ok, at, _ in answer_rows(user, ids):
        last_at[qid], last_ok[qid] = at, ok
    book = notebook(user, ids)
    today = timezone.localdate()
    doubtful = {
        qid for qid, at in ExamAnswer.objects.filter(attempt__user=user, question_id__in=ids, is_doubtful=True)
        .values_list("question_id", "attempt__submitted_at") if at and last_at.get(qid) and at >= last_at[qid]
    }
    concept = {}
    for qid, card in Question.flashcards.through.objects.filter(question_id__in=ids).order_by("flashcard_id").values_list("question_id", "flashcard_id"):
        concept.setdefault(qid, f"c{card}")

    def rank(qid):
        e = book.get(qid)
        if e and e["state"] in (OPEN, SETTLING) and is_due(e, today):
            return (0, -(e["at"].timestamp()))
        if qid in doubtful:
            return (1, 0)
        if qid in last_at:
            return (2, last_at[qid].timestamp())  # the longest-ago right answer first
        return (3, 0)

    candidates = sorted(ids, key=rank)
    # One per idea among the earlier right answers: a question tied to the same flashcard stands in for the others.
    seen_concepts, ordered = set(), []
    for qid in candidates:
        r = rank(qid)[0]
        key = concept.get(qid)
        if r == 2 and key:
            if key in seen_concepts:
                continue
            seen_concepts.add(key)
        ordered.append(qid)
    ordered += [q for q in candidates if q not in ordered]

    def fresh(qid):
        answered_today = qid in last_at and timezone.localdate(last_at[qid]) == today
        return qid not in avoid and not answered_today

    for allowed in (fresh, lambda qid: qid not in avoid, lambda qid: True):
        chosen = _cover_sections([q for q in ordered if allowed(q)], by_id, n)
        if len(chosen) >= min(n, len(ordered)):
            return chosen
    return chosen


def _cover_sections(ordered: list[int], by_id, n) -> list[int]:
    """At least one from each section before a second from the same one, keeping the order of importance."""
    out, used = [], set()
    for qid in ordered:
        if len(out) >= n:
            return out
        if by_id[qid].node_id not in used:
            out.append(qid)
            used.add(by_id[qid].node_id)
    for qid in ordered:
        if len(out) >= n:
            break
        if qid not in out:
            out.append(qid)
    return out


# --- Scheduling ------------------------------------------------------------------------------------------------------


def next_due(review: ChapterReview, score: float, today) -> tuple[int, object]:
    """(step, due date) after a review with this score (see the module notes)."""
    stage = review.stage
    if stage < len(STEP_DAYS):
        if score < 0.6:
            previous = STEP_DAYS[stage - 1] if stage else 0
            return stage, today + timedelta(days=max(1, (STEP_DAYS[stage] - previous) // 2))
        stage += 1
        if stage < len(STEP_DAYS):
            planned = timezone.localdate(review.finished_at) + timedelta(days=STEP_DAYS[stage])
            return stage, max(planned, today + timedelta(days=MIN_GAP_AFTER_LATE))
        return stage, today + timedelta(days=LATER_DAYS)
    if score < 0.6:
        return stage, today + timedelta(days=LATER_DAYS // 2)
    return stage + 1, today + timedelta(days=math.ceil(LATER_DAYS * (1.25 if score >= 0.9 else 1)))


def advance(review: ChapterReview, score: float, now=None) -> None:
    now = now or timezone.now()
    review.stage, review.due_on = next_due(review, score, timezone.localdate(now))
    review.last_done_at, review.last_score = now, score
    review.done_count += 1
    review.save()


def _minimum(stage: int) -> int:
    return PRACTICE_MINIMUM.get(stage, EXAM_MIN)


def _exam_size(pool_size: int) -> int:
    return min(pool_size, max(EXAM_MIN, min(EXAM_MAX, math.ceil(0.35 * pool_size))))


# --- What is due -----------------------------------------------------------------------------------------------------


def _chapter_item(review: ChapterReview, access, today) -> dict | None:
    chapter = access.nodes.get(review.chapter_id)
    if chapter is None or not access.readable(chapter.id):
        return None
    pool = chapter_pool(access, chapter)
    if not pool:
        return None
    exam = review.stage >= EXAM_STEP
    count = _exam_size(len(pool)) if exam else min(_minimum(review.stage), len(pool))
    return {
        "kind": "chapter",
        "id": review.id,
        "book_slug": access.book.slug,
        "book_title": access.book.title,
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "chapter_number": chapter.position,
        "step": review.stage,
        "is_exam": exam,
        "questions": count,
        "minutes": max(1, round(count * SECONDS_PER_QUESTION / 60)),
        "due_on": review.due_on,
        "late_days": max(0, (today - review.due_on).days),
    }


def _book_item(review: BookReview, access, today) -> dict | None:
    chapters = [access.nodes.get(c) for c in ChapterReview.objects.filter(user=review.user, book=review.book, is_archived=False).values_list("chapter_id", flat=True)]
    pool = [q for c in chapters if c is not None and access.readable(c.id) for q in chapter_pool(access, c)]
    if not pool:
        return None
    count = min(BOOK_MINIMUM, len(pool))
    return {
        "kind": "book",
        "id": review.id,
        "book_slug": access.book.slug,
        "book_title": access.book.title,
        "chapter_id": None,
        "chapter_title": "",
        "chapter_number": None,
        "chapters": len([c for c in chapters if c is not None]),
        "step": None,
        "is_exam": False,
        "questions": count,
        "minutes": max(1, round(count * SECONDS_PER_QUESTION / 60)),
        "due_on": review.due_on,
        "late_days": max(0, (today - review.due_on).days),
    }


def due_reviews(user, limit=None) -> list[dict]:
    """Reviews whose day has come, oldest first (the home page shows at most DAILY_CAP a day)."""
    if not user.is_authenticated:
        return []
    sync(user)
    today = timezone.localdate()
    maps: dict[int, AccessMap] = {}

    def access_for(book):
        if book.id not in maps:
            maps[book.id] = AccessMap(user, book)
        return maps[book.id]

    items = []
    for r in ChapterReview.objects.filter(user=user, is_archived=False, due_on__lte=today).select_related("book").order_by("due_on", "id"):
        item = _chapter_item(r, access_for(r.book), today)
        if item:
            items.append(item)
    for r in BookReview.objects.filter(user=user, due_on__lte=today).select_related("book").order_by("due_on", "id"):
        item = _book_item(r, access_for(r.book), today)
        if item:
            items.append(item)
    items.sort(key=lambda i: (i["due_on"], i["kind"] != "chapter"))
    return items[:limit] if limit else items


def book_schedule(user, book) -> dict:
    """For the book page: each chapter's review state, and the mixed review of the book."""
    if not user.is_authenticated:
        return {"chapters": {}, "book": None}
    sync(user)
    today = timezone.localdate()
    chapters = {}
    for r in ChapterReview.objects.filter(user=user, book=book, is_archived=False):
        # id: what «مرور فصل» on the book page starts (the same as the home page's tile).
        chapters[str(r.chapter_id)] = {"id": r.id, "step": r.stage, "due_on": r.due_on, "days": (r.due_on - today).days, "done": r.done_count}
    b = BookReview.objects.filter(user=user, book=book).first()
    return {"chapters": chapters, "book": {"due_on": b.due_on, "days": (b.due_on - today).days} if b else None}


# --- API -------------------------------------------------------------------------------------------------------------


def _payload(request, session: ReviewSession) -> dict:
    from .mistakes import _practice_payload

    qs = {q.id: q for q in Question.objects.filter(pk__in=session.served, is_archived=False).select_related("node").prefetch_related("choices", "questionsource_set__source")}
    answered = _session_answers(session)
    review = session.chapter_review or session.book_review
    access = AccessMap(request.user, review.book)
    pool = _session_pool(session, access)
    chapter = access.nodes.get(session.chapter_review.chapter_id) if session.chapter_review else None
    return {
        "id": session.id,
        "kind": "chapter" if session.chapter_review else "book",
        "title": (f"مرور فصل {chapter.position or ''} «{chapter.title}»".replace("  ", " ") if chapter else f"مرور ترکیبی «{access.book.title}»"),
        "book_title": access.book.title,
        "minimum": min(session.minimum, len(pool)),
        "answered": len(answered),
        "right": sum(1 for ok in answered.values() if ok),
        "more": len(pool) > len(session.served),
        "finished": bool(session.finished_at),
        "exam_id": session.exam_id,
        "questions": [_practice_payload(request, qs[i]) for i in session.served if i in qs and _usable(access, qs[i])],
    }


def _session_pool(session: ReviewSession, access) -> list[Question]:
    if session.chapter_review:
        chapter = access.nodes.get(session.chapter_review.chapter_id)
        return chapter_pool(access, chapter) if chapter and access.readable(chapter.id) else []
    chapter_ids = ChapterReview.objects.filter(user=session.user, book=session.book_review.book, is_archived=False).values_list("chapter_id", flat=True)
    out = []
    for cid in chapter_ids:
        c = access.nodes.get(cid)
        if c is not None and access.readable(c.id):
            out += chapter_pool(access, c)
    return out


def _session_answers(session: ReviewSession) -> dict[int, bool]:
    """The first practice answer to each served question since the session began."""
    out: dict[int, bool] = {}
    for qid, ok in (
        QuizAnswer.objects.filter(user=session.user, question_id__in=session.served, answered_at__gte=session.started_at)
        .order_by("answered_at", "id").values_list("question_id", "was_correct")
    ):
        out.setdefault(qid, ok)
    return out


def _review_or_404(request, kind, pk):
    if kind == "book":
        return get_object_or_404(BookReview.objects.select_related("book"), pk=pk, user=request.user)
    return get_object_or_404(ChapterReview.objects.select_related("book", "chapter"), pk=pk, user=request.user, is_archived=False)


@api_view(["GET"])
def my_reviews(request):
    items = due_reviews(request.user)
    return Response({"due": items, "today": items[:DAILY_CAP], "daily_cap": DAILY_CAP})


@api_view(["POST"])
def start_review(request):
    """Open today's sitting of a review (or continue an unfinished one). The one-month step starts an exam instead."""
    kind = "book" if request.data.get("kind") == "book" else "chapter"
    try:
        review = _review_or_404(request, kind, int(request.data.get("id")))
    except (TypeError, ValueError):
        return Response({"code": "invalid", "message": "مرور پیدا نشد."}, status=status.HTTP_400_BAD_REQUEST)
    access = AccessMap(request.user, review.book)
    lookup = {"chapter_review": review} if kind == "chapter" else {"book_review": review}
    with transaction.atomic():
        # The review row is locked so two quick taps open one sitting (and at most one exam).
        type(review).objects.select_for_update().filter(pk=review.pk).first()
        session = ReviewSession.objects.select_for_update().filter(user=request.user, finished_at__isnull=True, **lookup).first()
        if session and session.exam_id:
            exam = session.exam
            if exam is None or exam.submitted_at or timezone.now() > exam.ends_at + EXAM_LATE:
                # An exam left to run out is set aside (kept, not scored) and a fresh one is made.
                ReviewSession.objects.filter(pk=session.pk).update(finished_at=timezone.now())
                session = None
        if session is None:
            stage = review.stage if kind == "chapter" else 0
            session = ReviewSession(user=request.user, stage=stage, **lookup)
            session.minimum = BOOK_MINIMUM if kind == "book" else _minimum(stage)
            pool = _session_pool(session, access)
            if not pool:
                return Response({"code": "no_questions", "message": "برای این مرور تستی در دسترس نیست."}, status=status.HTTP_400_BAD_REQUEST)
            avoid = set(review.last_served)
            if kind == "chapter" and stage >= EXAM_STEP:
                ids = pick(request.user, pool, _exam_size(len(pool)), set(), avoid)
                session.served = ids
                session.exam = _start_exam(request.user, review.chapter, ids)
            else:
                session.served = pick(request.user, pool, BATCH, set(), avoid)
            session.save()
    return Response(_payload(request, session), status=status.HTTP_201_CREATED)


def _start_exam(user, chapter, ids) -> ExamAttempt:
    from .views import _snapshot

    questions = list(Question.objects.filter(pk__in=ids).prefetch_related("choices"))
    order = {qid: i for i, qid in enumerate(ids)}
    questions.sort(key=lambda q: order[q.id])
    seconds = sum(q.estimated_seconds or 90 for q in questions)
    return ExamAttempt.objects.create(
        user=user, node=chapter, question_ids=[q.id for q in questions], snapshot=_snapshot(questions), negative_marking=False,
        time_limit_seconds=max(300, seconds),
    )


@api_view(["GET"])
def review_session(request, session_id):
    session = get_object_or_404(ReviewSession, pk=session_id, user=request.user)
    return Response(_payload(request, session))


@api_view(["POST"])
def review_more(request, session_id):
    """«۵ تست دیگر از این فصل»."""
    with transaction.atomic():
        session = get_object_or_404(ReviewSession.objects.select_for_update(), pk=session_id, user=request.user)
        if session.exam_id:
            return Response({"code": "exam", "message": "این مرور آزمون است."}, status=status.HTTP_400_BAD_REQUEST)
        review = session.chapter_review or session.book_review
        pool = _session_pool(session, AccessMap(request.user, review.book))
        more = pick(request.user, pool, BATCH, set(session.served), set(review.last_served))
        session.served = session.served + more
        session.save(update_fields=["served"])
    return Response(_payload(request, session))


@api_view(["POST"])
def finish_review(request, session_id):
    """Counts the sitting once at least the minimum is answered, and sets the next review. Safe to call again."""
    with transaction.atomic():
        session = get_object_or_404(ReviewSession.objects.select_for_update(), pk=session_id, user=request.user)
        if not session.finished_at and not session.exam_id:
            answers = _session_answers(session)
            review = session.chapter_review or session.book_review
            pool = _session_pool(session, AccessMap(request.user, review.book))
            if answers and len(answers) >= min(session.minimum, len(pool)):
                close(session, sum(answers.values()) / len(answers))
    return Response({**_payload(request, session), **_next(session)})


def close(session: ReviewSession, score: float) -> None:
    recheck(session.user)
    now = timezone.now()
    session.finished_at, session.score = now, score
    session.save(update_fields=["finished_at", "score"])
    if session.chapter_review:
        review = session.chapter_review
        review.last_served = list(session.served)
        advance(review, score, now)
    else:
        review = session.book_review
        review.due_on = timezone.localdate(now) + timedelta(days=BOOK_EVERY_DAYS if score >= 0.6 else BOOK_EVERY_DAYS // 2)
        review.last_done_at, review.last_score, review.last_served = now, score, list(session.served)
        review.done_count += 1
        review.save()


def exam_submitted(attempt: ExamAttempt) -> None:
    """The one-month review is an exam: its result (without negative marking) moves the cycle on."""
    session = ReviewSession.objects.filter(exam=attempt, finished_at__isnull=True).first()
    if session:
        total = len(attempt.question_ids) or 1
        close(session, attempt.correct / total)


def _next(session: ReviewSession) -> dict:
    review = session.chapter_review or session.book_review
    if not session.finished_at:
        return {"next_due_on": None}
    return {"next_due_on": review.due_on, "next_in_days": (review.due_on - timezone.localdate()).days}


@api_view(["POST"])
def finish_chapter(request, node_id):
    """«این فصل را تمام کردم»: starts the chapter's review cycle now."""
    chapter = get_object_or_404(ContentNode, pk=node_id, kind=ContentNode.Kind.CHAPTER)
    access = AccessMap(request.user, chapter)
    if not access.readable(chapter.id):
        return Response({"code": "locked", "message": "این فصل در نسخه‌ی کامل کتاب است."}, status=status.HTTP_403_FORBIDDEN)
    review = start_cycle(request.user, access, chapter, by="button")
    recheck(request.user)
    return Response({"due_on": review.due_on, "days": (review.due_on - timezone.localdate()).days})
