import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.access import AccessMap, book_of
from apps.catalog.models import ContentNode
from apps.catalog.views import NOT_FOUND, media_urls
from apps.learning.models import Flashcard, Question, QuizAnswer, Report

from .models import Bookmark, ExamAnswer, ExamAttempt, FlashcardReview, Note, SectionProgress, StudyDay

LOCKED = {"code": "locked", "message": "این مورد در نسخه‌ی کامل کتاب است."}
EXAM_MAX_QUESTIONS = 100
EXAM_GRACE = timedelta(seconds=30)


def _err(message, code, http=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code, "message": message}, status=http)


def _usable(access, item):
    return access.visible(item.node_id) and (item.is_free or access.readable(item.node_id))


def _readable_node(request, node_id):
    """(node, access) if the user may read the node, else an error Response."""
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return None, None, Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    if not access.readable(node.id):
        return node, access, Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    return node, access, None


def _note_payload(n):
    return {"id": n.id, "node_id": n.node_id, "mode": n.mode, "quote": n.quote, "body": n.body, "color": n.color,
            "created_at": n.created_at, "updated_at": n.updated_at}


# --- Reading: progress, bookmarks, notes -----------------------------------------------------------------------------


@api_view(["GET"])
def node_state(request, node_id):
    """Everything about this section that belongs to the learner."""
    node, _, error = _readable_node(request, node_id)
    if error:
        return error
    progress = SectionProgress.objects.filter(user=request.user, node=node).first()
    notes = Note.objects.filter(user=request.user, node=node, is_archived=False).order_by("created_at")
    return Response(
        {
            "bookmarked": Bookmark.objects.filter(user=request.user, node=node, is_archived=False).exists(),
            "percent": progress.percent if progress else 0,
            "is_done": progress.is_done if progress else False,
            "notes": [_note_payload(n) for n in notes],
        }
    )


@api_view(["POST"])
def save_progress(request, node_id):
    node, _, error = _readable_node(request, node_id)
    if error:
        return error
    try:
        percent = max(0, min(100, int(request.data.get("percent", 0))))
    except (TypeError, ValueError):
        percent = 0
    done = bool(request.data.get("done")) or percent >= 90
    progress, created = SectionProgress.objects.get_or_create(user=request.user, node=node, defaults={"book": book_of(node)})
    became_done = done and not progress.is_done
    progress.percent = max(progress.percent, percent)
    progress.is_done = progress.is_done or done
    progress.save()
    if created or became_done:
        StudyDay.touch(request.user, "sections")
    return Response({"percent": progress.percent, "is_done": progress.is_done})


@api_view(["POST"])
def toggle_bookmark(request, node_id):
    node, _, error = _readable_node(request, node_id)
    if error and error.status_code == 404:
        return error
    bookmark, created = Bookmark.objects.get_or_create(user=request.user, node=node)
    if not created:
        bookmark.is_archived = not bookmark.is_archived
        bookmark.save()
    return Response({"bookmarked": not bookmark.is_archived})


@api_view(["POST"])
def add_note(request, node_id):
    node, _, error = _readable_node(request, node_id)
    if error:
        return error
    quote = str(request.data.get("quote", ""))[:2000]
    body = str(request.data.get("body", ""))[:5000]
    if not quote.strip() and not body.strip():
        return _err("متن یادداشت خالی است.", "empty")
    color = request.data.get("color") if request.data.get("color") in Note.Color.values else Note.Color.YELLOW
    mode = "summary" if request.data.get("mode") == "summary" else "full"
    note = Note.objects.create(user=request.user, node=node, quote=quote, body=body, color=color, mode=mode)
    return Response(_note_payload(note), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
def edit_note(request, note_id):
    note = get_object_or_404(Note, pk=note_id, user=request.user, is_archived=False)
    if request.method == "DELETE":
        note.is_archived = True
        note.save(update_fields=["is_archived", "updated_at"])
        return Response({"deleted": True})
    if "body" in request.data:
        note.body = str(request.data["body"])[:5000]
    if request.data.get("color") in Note.Color.values:
        note.color = request.data["color"]
    note.save()
    return Response(_note_payload(note))


# --- Practice: per-question state and reset ----------------------------------------------------------------------------


@api_view(["GET"])
def practice_state(request, node_id):
    """For each question under the node: last practice answer (since the last reset) and whether the user reported it."""
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    ids = access.visible_ids_under(node)
    answers = QuizAnswer.objects.filter(user=request.user, question__node_id__in=ids, is_archived=False).order_by("answered_at")
    last = {}
    for a in answers:
        last[a.question_id] = a.was_correct
    reported = set(Report.objects.filter(user=request.user, question__node_id__in=ids).values_list("question_id", flat=True))
    return Response({"answered": {str(k): v for k, v in last.items()}, "reported": sorted(reported)})


@api_view(["POST"])
def practice_reset(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    ids = AccessMap(request.user, node).visible_ids_under(node)
    count = QuizAnswer.objects.filter(user=request.user, question__node_id__in=ids, is_archived=False).update(is_archived=True)
    return Response({"reset": count})


# --- Flashcards: Leitner boxes ------------------------------------------------------------------------------------------


@api_view(["GET"])
def flashcard_state(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    ids = AccessMap(request.user, node).visible_ids_under(node)
    reviews = FlashcardReview.objects.filter(user=request.user, flashcard__node_id__in=ids)
    reported = Report.objects.filter(user=request.user, flashcard__node_id__in=ids).values_list("flashcard_id", flat=True)
    now = timezone.now()
    return Response(
        {
            "cards": {str(r.flashcard_id): {"box": r.box, "due": r.due_at <= now} for r in reviews},
            "reported": sorted(reported),
        }
    )


@api_view(["POST"])
def review_flashcard(request, flashcard_id):
    card = get_object_or_404(Flashcard.objects.select_related("node"), pk=flashcard_id, is_archived=False)
    access = AccessMap(request.user, card.node)
    if not _usable(access, card):
        return Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    review, _ = FlashcardReview.objects.get_or_create(user=request.user, flashcard=card)
    review.record(bool(request.data.get("known")))
    review.save()
    StudyDay.touch(request.user, "cards")
    return Response({"box": review.box, "due_at": review.due_at})


# --- Reports -------------------------------------------------------------------------------------------------------------


def _report(request, **target):
    reason = request.data.get("reason")
    if reason not in Report.Reason.values:
        reason = Report.Reason.OTHER
    note = str(request.data.get("note", ""))[:1000]
    report, created = Report.objects.get_or_create(user=request.user, **target, defaults={"reason": reason, "note": note})
    if not created and report.status == Report.Status.OPEN:
        report.reason, report.note = reason, note or report.note
        report.save(update_fields=["reason", "note"])
    return Response({"reported": True, "status": report.get_status_display()})


@api_view(["POST"])
def report_question(request, question_id):
    question = get_object_or_404(Question.objects.select_related("node"), pk=question_id)
    if not _usable(AccessMap(request.user, question.node), question):
        return Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    return _report(request, question=question)


@api_view(["POST"])
def report_flashcard(request, flashcard_id):
    card = get_object_or_404(Flashcard.objects.select_related("node"), pk=flashcard_id)
    if not _usable(AccessMap(request.user, card.node), card):
        return Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    return _report(request, flashcard=card)


@api_view(["POST"])
def report_node(request, node_id):
    node, _, error = _readable_node(request, node_id)
    if error:
        return error
    return _report(request, node=node)


# --- Exams ---------------------------------------------------------------------------------------------------------------


def _question_payload(request, q):
    return {
        "id": q.id,
        "stem": media_urls(request, q.stem),
        "choices": [{"id": c.id, "text": media_urls(request, c.text)} for c in q.choices.all()],
        "difficulty": q.difficulty,
    }


def _exam_summary(a):
    return {
        "id": a.id,
        "node_id": a.node_id,
        "node_title": a.node.title,
        "question_count": len(a.question_ids),
        "negative_marking": a.negative_marking,
        "time_limit_seconds": a.time_limit_seconds,
        "started_at": a.started_at,
        "ends_at": a.ends_at,
        "submitted_at": a.submitted_at,
        "correct": a.correct,
        "wrong": a.wrong,
        "blank": a.blank,
        "score_percent": a.score_percent,
    }


@api_view(["POST"])
def start_exam(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    pool = [q for q in Question.objects.filter(node_id__in=access.visible_ids_under(node), is_archived=False) if _usable(access, q)]
    if not pool:
        return _err("برای این بخش تستی در دسترس نیست.", "no_questions")
    try:
        count = max(1, min(EXAM_MAX_QUESTIONS, int(request.data.get("count") or 20), len(pool)))
    except (TypeError, ValueError):
        count = min(20, len(pool))
    picked = random.sample(pool, count)
    seconds = sum(q.estimated_seconds or 90 for q in picked)
    try:
        if request.data.get("minutes"):
            seconds = max(60, min(4 * 3600, int(request.data["minutes"]) * 60))
    except (TypeError, ValueError):
        pass
    attempt = ExamAttempt.objects.create(
        user=request.user,
        node=node,
        question_ids=[q.id for q in picked],
        negative_marking=request.data.get("negative_marking", True) not in (False, "false", 0, "0"),
        time_limit_seconds=seconds,
    )
    return Response(_exam_detail(request, attempt), status=status.HTTP_201_CREATED)


def _exam_detail(request, attempt):
    questions = {q.id: q for q in Question.objects.filter(pk__in=attempt.question_ids).prefetch_related("choices")}
    ordered = [questions[i] for i in attempt.question_ids if i in questions]
    data = _exam_summary(attempt)
    data["questions"] = [_question_payload(request, q) for q in ordered]
    if attempt.submitted_at:
        answers = {a.question_id: a for a in attempt.answers.all()}
        review = []
        for q in ordered:
            choices = list(q.choices.all())
            answer = answers.get(q.id)
            picked = next((c for c in choices if answer and c.order == answer.choice_order), None)
            correct = next((c for c in choices if c.is_correct), None)
            review.append(
                {
                    "question_id": q.id,
                    "picked_choice_id": picked.id if picked else None,
                    "correct_choice_id": correct.id if correct else None,
                    "explanation": media_urls(request, q.explanation),
                    "quick_solution": media_urls(request, q.quick_solution),
                    "alternative_view": media_urls(request, q.alternative_view),
                }
            )
        data["review"] = review
    return data


@api_view(["GET"])
def exam_detail(request, attempt_id):
    attempt = get_object_or_404(ExamAttempt.objects.select_related("node"), pk=attempt_id, user=request.user)
    return Response(_exam_detail(request, attempt))


@api_view(["POST"])
def submit_exam(request, attempt_id):
    with transaction.atomic():
        attempt = get_object_or_404(ExamAttempt.objects.select_for_update().select_related("node"), pk=attempt_id, user=request.user)
        if attempt.submitted_at:
            return Response(_exam_detail(request, attempt))
        late = timezone.now() > attempt.ends_at + EXAM_GRACE
        raw = request.data.get("answers") or {}
        questions = Question.objects.filter(pk__in=attempt.question_ids).prefetch_related("choices")
        points = 0.0
        correct = wrong = blank = 0
        for q in questions:
            choices = list(q.choices.all())
            picked = None if late else next((c for c in choices if str(c.id) == str(raw.get(str(q.id)))), None)
            if picked is None:
                blank += 1
                ExamAnswer.objects.create(attempt=attempt, question=q, choice_order=None, was_correct=None)
                continue
            ExamAnswer.objects.create(attempt=attempt, question=q, choice_order=picked.order, was_correct=picked.is_correct)
            if picked.is_correct:
                correct += 1
                points += 1
            else:
                wrong += 1
                # Konkur rule: a wrong answer costs 1/(choices − 1), i.e. three wrong answers cancel one right one.
                if attempt.negative_marking and len(choices) > 1:
                    points -= 1 / (len(choices) - 1)
            Question.objects.filter(pk=q.pk).update(
                answer_count=F("answer_count") + 1, correct_count=F("correct_count") + (1 if picked.is_correct else 0)
            )
        total = len(attempt.question_ids) or 1
        attempt.correct, attempt.wrong, attempt.blank = correct, wrong, blank
        attempt.score_percent = round(points / total * 100, 1)
        attempt.submitted_at = timezone.now()
        attempt.save()
    StudyDay.touch(request.user, "answers", correct + wrong)
    return Response(_exam_detail(request, attempt))


@api_view(["GET"])
def my_exams(request):
    attempts = ExamAttempt.objects.filter(user=request.user, is_archived=False).select_related("node")[:50]
    return Response([_exam_summary(a) for a in attempts])


# --- Library and statistics ----------------------------------------------------------------------------------------------


def _section_ref(node):
    return {"id": node.id, "title": node.title}


@api_view(["GET"])
def library(request):
    user = request.user
    recent = SectionProgress.objects.filter(user=user).select_related("node", "book").order_by("-updated_at")
    reading, seen_books = [], set()
    for p in recent[:200]:
        if p.book_id in seen_books or p.book.is_archived or not p.book.is_published:
            continue
        seen_books.add(p.book_id)
        reading.append({"book_slug": p.book.slug, "book_title": p.book.title, "last_section": _section_ref(p.node), "updated_at": p.updated_at})
    bookmarks = Bookmark.objects.filter(user=user, is_archived=False).select_related("node").order_by("-created_at")[:100]
    notes = Note.objects.filter(user=user, is_archived=False).select_related("node").order_by("-updated_at")[:100]
    return Response(
        {
            "reading": reading,
            "bookmarks": [{**_section_ref(b.node), "created_at": b.created_at} for b in bookmarks if not b.node.is_archived],
            "notes": [{**_note_payload(n), "node_title": n.node.title} for n in notes],
        }
    )


def _streak(days: set) -> int:
    today = timezone.localdate()
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


@api_view(["GET"])
def stats(request):
    user = request.user
    answers = QuizAnswer.objects.filter(user=user)
    total_answers = answers.count()
    correct_answers = answers.filter(was_correct=True).count()
    exam_answers = ExamAnswer.objects.filter(attempt__user=user, was_correct__isnull=False)
    total_answers += exam_answers.count()
    correct_answers += exam_answers.filter(was_correct=True).count()

    days = StudyDay.objects.filter(user=user)
    day_set = set(days.values_list("date", flat=True))
    since = timezone.localdate() - timedelta(days=13)
    by_day = {d.date: d for d in days.filter(date__gte=since)}
    last_14 = []
    for i in range(14):
        date = since + timedelta(days=i)
        d = by_day.get(date)
        last_14.append({"date": date, "sections": d.sections if d else 0, "answers": d.answers if d else 0, "cards": d.cards if d else 0})

    # Per book: sections read out of the book's sections.
    books = []
    progress = SectionProgress.objects.filter(user=user, is_done=True).values("book_id").annotate(done=Count("id"))
    for row in progress:
        book = ContentNode.objects.filter(pk=row["book_id"], is_archived=False).first()
        if not book:
            continue
        total = ContentNode.objects.filter(path__startswith=book.path, kind=ContentNode.Kind.SECTION, is_archived=False, is_published=True).count()
        books.append({"slug": book.slug, "title": book.title, "done": row["done"], "total": total})

    # Weakest sections: lowest accuracy with at least 3 answers.
    per_node = (
        answers.values("question__node_id", "question__node__title")
        .annotate(n=Count("id"), ok=Count("id", filter=Q(was_correct=True)))
        .filter(n__gte=3)
    )
    weak = sorted(
        ({"id": r["question__node_id"], "title": r["question__node__title"], "answers": r["n"], "accuracy": round(r["ok"] / r["n"] * 100)} for r in per_node),
        key=lambda r: r["accuracy"],
    )[:5]

    return Response(
        {
            "sections_done": SectionProgress.objects.filter(user=user, is_done=True).count(),
            "answers": total_answers,
            "accuracy": round(correct_answers / total_answers * 100) if total_answers else None,
            "cards_reviewed": FlashcardReview.objects.filter(user=user).aggregate(n=Count("id"))["n"],
            "cards_mastered": FlashcardReview.objects.filter(user=user, box__gte=4).count(),
            "exams": ExamAttempt.objects.filter(user=user, submitted_at__isnull=False).count(),
            "streak_days": _streak(day_set),
            "study_days": len(day_set),
            "last_14_days": last_14,
            "books": books,
            "weak_sections": [w for w in weak if w["accuracy"] < 70],
        }
    )


# --- Offline reading -----------------------------------------------------------------------------------------------------

OFFLINE_VALID_DAYS = 30


@api_view(["GET"])
def offline_bundle(request, slug):
    """All sections of a book the user may read, for encrypted offline storage on the device."""
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, depth=1, slug=slug)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    sections = []
    for n in sorted(access.nodes.values(), key=lambda n: n.path):
        if n.kind != ContentNode.Kind.SECTION or not access.readable(n.id):
            continue
        sections.append({"id": n.id, "title": n.title, "summary": media_urls(request, n.summary_body), "full": media_urls(request, n.full_body)})
    if not sections:
        return Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    return Response(
        {
            "book": {"slug": book.slug, "title": book.title},
            "sections": sections,
            "downloaded_at": timezone.now(),
            "valid_until": timezone.now() + timedelta(days=OFFLINE_VALID_DAYS),
        }
    )
