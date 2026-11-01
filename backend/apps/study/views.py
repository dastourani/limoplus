import random
from datetime import timedelta

from django.db import transaction
from django.db.models import Avg, Count, F, Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.access import AccessMap, access_until, book_of
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
            "position": progress.position if progress else 0,
            "mode": progress.mode if progress else "full",
            "at": progress.updated_at if progress else None,
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
    # The reader's current place and mode (optional; older app versions don't send them).
    if "position" in request.data:
        try:
            progress.position = max(0, min(100, int(request.data.get("position"))))
        except (TypeError, ValueError):
            pass
    if request.data.get("mode") in ("full", "summary"):
        progress.mode = request.data["mode"]
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
            "cards": {str(r.flashcard_id): {"box": r.box, "due": r.due_at <= now, "hints": _grade_hints(r.box)} for r in reviews},
            "new_hints": _grade_hints(1),
            "mastered_box": FlashcardReview.MASTERED_BOX,
            "reported": sorted(reported),
        }
    )


@api_view(["POST"])
def review_flashcard(request, flashcard_id):
    card = get_object_or_404(Flashcard.objects.select_related("node"), pk=flashcard_id, is_archived=False)
    access = AccessMap(request.user, card.node)
    if not _usable(access, card):
        return Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    with transaction.atomic():
        FlashcardReview.objects.get_or_create(user=request.user, flashcard=card)
        # Locked, so two copies of the same review arriving together can't both pass the check below.
        review = FlashcardReview.objects.select_for_update().get(user=request.user, flashcard=card)
        return _review(request, review)


def _review(request, review):
    op = str(request.data.get("op") or "")[:40].replace(",", "")
    seen = [x for x in review.last_op.split(",") if x]
    if op and op in seen:  # the same review sent again after a dropped connection
        return Response({"box": review.box, "due_at": review.due_at, "mastered": review.box >= FlashcardReview.MASTERED_BOX})
    if op:
        review.last_op = ",".join((seen + [op])[-5:])
    grade = request.data.get("grade")
    if grade is None and "known" in request.data:
        grade = request.data.get("known") in (True, "true", 1, "1")
    review.record(grade)
    review.save()
    StudyDay.touch(request.user, "cards")
    return Response({"box": review.box, "due_at": review.due_at, "mastered": review.box >= FlashcardReview.MASTERED_BOX})


def _grade_hints(box: int) -> dict:
    """Days until the next review for each button, shown under the buttons."""
    return {g: FlashcardReview.next_step(box, g)[1].days for g in FlashcardReview.GRADES}


@api_view(["GET"])
def due_flashcards(request):
    """«مرور امروز»: cards due for review across all books the learner can use (cards already seen at least once)."""
    now = timezone.now()
    reviews = (
        FlashcardReview.objects.filter(user=request.user, due_at__lte=now, flashcard__is_archived=False)
        .select_related("flashcard__node")
        .order_by("box", "due_at")
    )
    maps, cards = {}, []
    for r in reviews[:300]:
        card = r.flashcard
        book_path = card.node.path[: ContentNode.steplen]
        if book_path not in maps:
            maps[book_path] = AccessMap(request.user, card.node)
        if not _usable(maps[book_path], card):
            continue
        cards.append({"id": card.id, "title": card.title, "point": media_urls(request, card.point), "formula": card.formula,
                      "box": r.box, "hints": _grade_hints(r.box)})
    limit = 50
    return Response({"count": len(cards), "flashcards": cards[:limit]})


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


def in_open_exam(user, question_id) -> bool:
    """True while the question is part of the user's running exam (practice must not reveal its answer then)."""
    if not user.is_authenticated:
        return False
    now = timezone.now()
    running = ExamAttempt.objects.filter(user=user, submitted_at__isnull=True, started_at__gte=now - timedelta(hours=5))
    for attempt in running.only("question_ids", "started_at", "time_limit_seconds"):
        if question_id in attempt.question_ids and now <= attempt.ends_at + EXAM_GRACE:
            return True
    return False


# --- Exams ---------------------------------------------------------------------------------------------------------------


def _snapshot(questions) -> dict:
    return {
        str(q.id): {
            "stem": q.stem,
            "difficulty": q.difficulty,
            "choices": [{"id": c.id, "text": c.text, "ok": c.is_correct} for c in q.choices.all()],
            "explanation": q.explanation,
            "quick_solution": q.quick_solution,
            "alternative_view": q.alternative_view,
            "fixed": q.keeps_order,
        }
        for q in questions
    }


def _exam_questions(attempt) -> list[tuple[int, dict]]:
    """(question id, its content) in exam order: from the snapshot, or for exams started before snapshots, as now."""
    if attempt.snapshot:
        return [(qid, attempt.snapshot[str(qid)]) for qid in attempt.question_ids if str(qid) in attempt.snapshot]
    current = _snapshot(Question.objects.filter(pk__in=attempt.question_ids).prefetch_related("choices"))
    return [(qid, current[str(qid)]) for qid in attempt.question_ids if str(qid) in current]


def first_answer(user, question_id, exclude_attempt=None) -> bool:
    """Measured difficulty counts each learner's first answer to a question only (repeats know the answer)."""
    from apps.learning.models import QuizAnswer

    if QuizAnswer.objects.filter(user=user, question_id=question_id).exists():
        return False
    earlier = ExamAnswer.objects.filter(attempt__user=user, question_id=question_id, choice_order__isnull=False)
    if exclude_attempt is not None:
        earlier = earlier.exclude(attempt=exclude_attempt)
    return not earlier.exists()


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
    picked = list(Question.objects.filter(pk__in=[q.id for q in picked]).prefetch_related("choices"))
    random.shuffle(picked)
    attempt = ExamAttempt.objects.create(
        user=request.user,
        node=node,
        question_ids=[q.id for q in picked],
        snapshot=_snapshot(picked),
        negative_marking=request.data.get("negative_marking", True) not in (False, "false", 0, "0"),
        time_limit_seconds=seconds,
    )
    return Response(_exam_detail(request, attempt), status=status.HTTP_201_CREATED)


def _exam_detail(request, attempt):
    ordered = _exam_questions(attempt)
    data = _exam_summary(attempt)
    data["questions"] = [
        {
            "id": qid,
            "stem": media_urls(request, q["stem"]),
            "choices": [{"id": c["id"], "text": media_urls(request, c["text"])} for c in q["choices"]],
            "difficulty": q["difficulty"],
            "fixed_order": bool(q.get("fixed")),
        }
        for qid, q in ordered
    ]
    if attempt.submitted_at:
        answers = {a.question_id: a for a in attempt.answers.all()}
        # Where each question is taught now, for «این نکته در جزوه» (the section may have moved since the exam).
        current = {
            pk: (node_id, changed, note)
            for pk, node_id, changed, note in Question.objects.filter(pk__in=[qid for qid, _ in ordered]).values_list(
                "pk", "node_id", "key_changed_at", "key_change_note"
            )
        }
        nodes = {pk: v[0] for pk, v in current.items()}
        review = []
        for qid, q in ordered:
            answer = answers.get(qid)
            # choice_order is the place of the picked choice in the exam's own copy of the question.
            picked = q["choices"][answer.choice_order] if answer and answer.choice_order is not None and answer.choice_order < len(q["choices"]) else None
            correct = next((c for c in q["choices"] if c["ok"]), None)
            review.append(
                {
                    "question_id": qid,
                    "node_id": nodes.get(qid),
                    "picked_choice_id": picked["id"] if picked else None,
                    "correct_choice_id": correct["id"] if correct else None,
                    "explanation": media_urls(request, q["explanation"]),
                    "quick_solution": media_urls(request, q["quick_solution"]),
                    "alternative_view": media_urls(request, q["alternative_view"]),
                    # The answer key was corrected after this exam began; the exam keeps the key it was taken with.
                    "corrected": (
                        {"at": current[qid][1], "note": current[qid][2]}
                        if qid in current and current[qid][1] and current[qid][1] > attempt.started_at
                        else None
                    ),
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
        points = 0.0
        correct = wrong = blank = 0
        existing = set(Question.objects.filter(pk__in=attempt.question_ids).values_list("pk", flat=True))
        for qid, q in _exam_questions(attempt):
            if qid not in existing:
                continue
            choices = q["choices"]
            at = None if late else next((i for i, c in enumerate(choices) if str(c["id"]) == str(raw.get(str(qid)))), None)
            if at is None:
                blank += 1
                ExamAnswer.objects.create(attempt=attempt, question_id=qid, choice_order=None, was_correct=None)
                continue
            ok = bool(choices[at]["ok"])
            first = first_answer(request.user, qid, exclude_attempt=attempt)
            ExamAnswer.objects.create(attempt=attempt, question_id=qid, choice_order=at, was_correct=ok)
            if ok:
                correct += 1
                points += 1
            else:
                wrong += 1
                # Konkur rule: a wrong answer costs 1/(choices − 1), i.e. three wrong answers cancel one right one.
                if attempt.negative_marking and len(choices) > 1:
                    points -= 1 / (len(choices) - 1)
            if first:
                Question.objects.filter(pk=qid).update(answer_count=F("answer_count") + 1, correct_count=F("correct_count") + (1 if ok else 0))
        total = len(attempt.question_ids) or 1
        attempt.correct, attempt.wrong, attempt.blank = correct, wrong, blank
        attempt.score_percent = round(points / total * 100, 1)
        attempt.submitted_at = timezone.now()
        attempt.save()
    StudyDay.touch(request.user, "answers", correct + wrong)
    return Response(_exam_detail(request, attempt))


EXAM_PAGE = 10


@api_view(["GET"])
def my_exams(request):
    """The learner's exams, newest first. Without ?page: the old plain list (last 50). With ?page=N (and optional
    ?book=slug): ten per page, plus a summary of all of them and the books they were taken in."""
    attempts = ExamAttempt.objects.filter(user=request.user, is_archived=False).select_related("node").defer("snapshot")
    if "page" not in request.query_params:
        return Response([_exam_summary(a) for a in attempts[:50]])
    steplen = ContentNode.steplen
    books = {n.path: n for n in ContentNode.objects.filter(depth=1, path__in={p[:steplen] for p in attempts.values_list("node__path", flat=True)})}
    slug = request.query_params.get("book") or ""
    chosen = next((b for b in books.values() if b.slug == slug), None)
    if chosen:
        attempts = attempts.filter(node__path__startswith=chosen.path)
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except ValueError:
        page = 1
    done = attempts.filter(submitted_at__isnull=False)
    stats = done.aggregate(count=Count("id"), average=Avg("score_percent"), best=Max("score_percent"))
    rows = list(attempts[(page - 1) * EXAM_PAGE : page * EXAM_PAGE + 1])
    return Response(
        {
            "results": [_exam_summary(a) | {"book_title": books.get(a.node.path[:steplen]).title if a.node.path[:steplen] in books else ""} for a in rows[:EXAM_PAGE]],
            "has_more": len(rows) > EXAM_PAGE,
            "summary": {
                "count": stats["count"],
                "average": round(stats["average"], 1) if stats["average"] is not None else None,
                "best": stats["best"],
                # Oldest to newest, for the small trend chart.
                "trend": [round(x, 1) for x in reversed(list(done.values_list("score_percent", flat=True)[:12]))],
            },
            "books": [{"slug": b.slug, "title": b.title} for b in sorted(books.values(), key=lambda b: b.title)],
        }
    )


# --- Library and statistics ----------------------------------------------------------------------------------------------


def _section_ref(node):
    return {"id": node.id, "title": node.title}


@api_view(["GET"])
def library(request):
    user = request.user
    recent = SectionProgress.objects.filter(user=user).select_related("node", "book").order_by("-updated_at")
    reading, seen_books, maps = [], set(), {}
    for p in recent[:200]:
        if p.book_id in seen_books or p.book.is_archived or not p.book.is_published:
            continue
        from apps.catalog.views import book_card

        if p.book_id not in maps:
            maps[p.book_id] = AccessMap(user, p.book)
        access = maps[p.book_id]
        # A section hidden since: fall back to the next most recent one of the same book.
        if not access.visible(p.node_id):
            continue
        seen_books.add(p.book_id)
        reading.append(
            {
                "book_slug": p.book.slug,
                "book_title": p.book.title,
                "last_section": _section_ref(p.node),
                # How far into that section (0–100), to open it where the reader left off on another device.
                "percent": p.percent,
                "position": p.position,
                "mode": p.mode,
                "updated_at": p.updated_at,
                "book": book_card(request, p.book, access),
            }
        )
    bookmarks = Bookmark.objects.filter(user=user, is_archived=False).select_related("node").order_by("-created_at")[:100]
    notes = Note.objects.filter(user=user, is_archived=False).select_related("node").order_by("-updated_at")[:100]
    return Response(
        {
            "reading": reading,
            "bookmarks": [{**_section_ref(b.node), "created_at": b.created_at} for b in bookmarks if not b.node.is_archived],
            "notes": [{**_note_payload(n), "node_title": n.node.title} for n in notes],
            "mistakes": _notebook_counts(request),
        }
    )


def _notebook_counts(request, book_slug=""):
    from .mistakes import OPEN, SETTLING, _mistakes, due_items

    items, _ = _mistakes(request, book_slug)
    return {
        "count": len(items),
        "open": sum(1 for _, _, e in items if e["state"] == OPEN),
        "settling": sum(1 for _, _, e in items if e["state"] == SETTLING),
        "due": len(due_items(items)),
    }


def _streak(days: set) -> int:
    today = timezone.localdate()
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def _improvement(user):
    from .mistakes import improvement

    return improvement(user)


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
            "improvement": _improvement(user),
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
    valid_until = timezone.now() + timedelta(days=OFFLINE_VALID_DAYS)
    # A subscription-only reader keeps offline access no longer than the subscription.
    ends = access_until(request.user, book)
    if ends and ends < valid_until:
        valid_until = ends
    return Response({"book": {"slug": book.slug, "title": book.title}, "sections": sections, "downloaded_at": timezone.now(), "valid_until": valid_until})
