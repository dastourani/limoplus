import math
import random
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Max, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.numbering import resolve as resolve_refs
from apps.catalog.places import chapter_number
from apps.catalog.access import AccessMap, access_kind_from, access_until, active_rows, book_of
from apps.catalog.models import ContentNode
from apps.catalog.views import NOT_FOUND, media_urls
from apps.learning.models import Flashcard, Question, QuestionSource, QuizAnswer, Report

from .models import Bookmark, ExamAnswer, ExamAttempt, FlashcardReview, LibraryBook, Note, SectionProgress, StudyDay

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
    # A section finished long ago and opened again leaves «نیاز به مرور» (apps/study/needs.py) at once.
    from .needs import OLD_DAYS

    reopened = not created and progress.is_done and progress.updated_at < timezone.now() - timedelta(days=OLD_DAYS)
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
    if became_done or reopened:
        from .reviews import recheck

        recheck(request.user)
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
    from .models import FlashcardReviewOp

    op = str(request.data.get("op") or "")[:40].replace(",", "")
    seen = [x for x in review.last_op.split(",") if x]
    if op and (op in seen or FlashcardReviewOp.objects.filter(review=review, op=op).exists()):
        # The same review sent again after a dropped connection (the review row is locked, so copies queue up here).
        return Response({"box": review.box, "due_at": review.due_at, "mastered": review.box >= FlashcardReview.MASTERED_BOX})
    if op:
        review.last_op = ",".join((seen + [op])[-5:])
        FlashcardReviewOp.objects.create(review=review, op=op)
    grade = request.data.get("grade")
    if grade is None and "known" in request.data:
        grade = request.data.get("known") in (True, "true", 1, "1")
    review.record(grade)
    review.save()
    StudyDay.touch(request.user, "cards")
    from .reviews import recheck

    recheck(request.user)
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
                      "node_id": card.node_id, "node_title": card.node.title, "chapter_number": chapter_number(request, card.node),
                      "box": r.box, "hints": _grade_hints(r.box)})
    limit = 50
    return Response({"count": len(cards), "flashcards": cards[:limit]})


# --- Reports -------------------------------------------------------------------------------------------------------------


REPORTS_PER_DAY = 5
NOTE_MAX = 200
NOTE_MIN = 10
QUOTE_MAX = 1000


def _report(request, **target):
    """One report. Rules: a known reason; a required note of 10–200 characters (at least 3 distinct characters, so
    random taps cannot spam the panel); at most 5 new reports a day. The same words reported again while still open
    update that report instead."""
    if not getattr(request.user, "can_report", True):
        return Response({"detail": "امکان ارسال گزارش اشکال برای حساب شما بسته شده است."}, status=status.HTTP_403_FORBIDDEN)
    reason = request.data.get("reason")
    if reason not in Report.Reason.values:
        reason = Report.Reason.OTHER
    note = str(request.data.get("note") or "").strip()
    if len(note) > NOTE_MAX:
        return Response({"detail": f"توضیح حداکثر {NOTE_MAX} نویسه است."}, status=status.HTTP_400_BAD_REQUEST)
    distinct = len({c for c in note if not c.isspace()})
    if len(note) < NOTE_MIN or distinct < 3:
        return Response({"detail": f"برای ارسال گزارش، دست‌کم {NOTE_MIN} نویسه بنویس چه اشکالی دیدی."}, status=status.HTTP_400_BAD_REQUEST)
    quote = str(request.data.get("quote") or "").strip()[:QUOTE_MAX]
    mode = request.data.get("mode") if request.data.get("mode") in ("full", "summary") else ""
    box = str(request.data.get("box") or "").strip()[:80]
    # The lesson text can have many reports (one per quote); a test or a card has one per learner, opened again if it
    # was closed.
    mine = Report.objects.filter(user=request.user, **target)
    report = mine.filter(status=Report.Status.OPEN, quote=quote).first() if "node" in target else mine.first()
    if report:
        report.reason, report.note = reason, note or report.note
        report.mode, report.box, report.quote = mode or report.mode, box or report.box, quote or report.quote
        if report.status != Report.Status.OPEN:
            report.status, report.resolved_at, report.thanked_at = Report.Status.OPEN, None, None
        report.save(update_fields=["reason", "note", "mode", "box", "quote", "status", "resolved_at", "thanked_at"])
    else:
        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        if Report.objects.filter(user=request.user, created_at__gte=today).count() >= REPORTS_PER_DAY:
            return Response({"detail": f"امروز {REPORTS_PER_DAY} گزارش فرستاده‌ای؛ ممنون! بقیه را فردا بفرست."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            with transaction.atomic():
                report = Report.objects.create(user=request.user, reason=reason, note=note, quote=quote, mode=mode, box=box, **target)
        except IntegrityError:  # the same test or card sent twice at once
            report = mine.first()
    return Response({"reported": True, "status": report.get_status_display()})


@api_view(["POST"])
def reports_fixed(request):
    """«اصلاح شد، ممنون»: the learner's reports fixed since last asked (marked as told, so each is said once)."""
    fixed = list(Report.objects.filter(user=request.user, status=Report.Status.FIXED, thanked_at__isnull=True)
                 .select_related("question", "flashcard", "node").order_by("resolved_at")[:10])
    out = []
    for r in fixed:
        what = r.quote or (r.question and r.question.stem) or (r.flashcard and r.flashcard.title) or (r.node and r.node.title) or ""
        out.append({"id": r.id, "about": what[:80]})
    Report.objects.filter(pk__in=[r.pk for r in fixed], thanked_at__isnull=True).update(thanked_at=timezone.now())
    return Response({"fixed": out})


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


def _snapshot_solutions(q: dict) -> list[dict]:
    """The solutions kept with an exam; older exams kept «راه‌حل سریع» and «زاویه‌ی دیگر» as two fields."""
    if "solutions" in q:
        return [{"title": x.get("title", ""), "body": x.get("body", "")} for x in q["solutions"] or []]
    old = [("راه‌حل سریع", q.get("quick_solution")), ("زاویه‌ی دیگر", q.get("alternative_view"))]
    return [{"title": t, "body": b} for t, b in old if b]


def _snapshot(questions) -> dict:
    return {
        str(q.id): {
            "stem": q.stem,
            "difficulty": q.difficulty,
            "choices": [{"id": c.id, "text": c.text, "ok": c.is_correct} for c in q.choices.all()],
            "explanation": q.explanation,
            "solutions": q.solutions or [],
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
        "focused": a.focused,
    }


@api_view(["GET"])
def exam_info(request, node_id):
    """How many questions an exam on this book, chapter or section can have: the setup offers sizes up to that."""
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    pool = [q for q in Question.objects.filter(node_id__in=access.visible_ids_under(node), is_archived=False).only("id", "node_id", "is_free") if _usable(access, q)]
    # «فقط تست‌های کنکور»: which years have tests here, and how many.
    years: dict[int, int] = {}
    for qid, year in QuestionSource.objects.filter(question_id__in=[q.id for q in pool], source__year__gt=0).values_list("question_id", "source__year").distinct():
        years[year] = years.get(year, 0) + 1
    konkur = QuestionSource.objects.filter(question_id__in=[q.id for q in pool], source__year__gt=0).values("question_id").distinct().count()
    out = {"questions": min(len(pool), EXAM_MAX_QUESTIONS), "title": node.title,
           "konkur": konkur, "years": [{"year": y, "count": n} for y, n in sorted(years.items(), reverse=True)]}
    source = request.query_params.get("source")
    if source and str(source).isdigit():
        # Before a past konkur: how many of its tests are from chapters not studied yet, and which chapters.
        from .readiness import chapter_label, chapter_of, studied_chapters

        mine = set(QuestionSource.objects.filter(source_id=int(source), question_id__in=[q.id for q in pool]).values_list("question_id", flat=True))
        studied = studied_chapters(request.user, access)
        unread, chapters = 0, {}
        for q in pool:
            if q.id not in mine:
                continue
            c = chapter_of(access, q.node_id)
            if not c or c.id not in studied:
                unread += 1
                if c:
                    chapters[c.id] = chapter_label(c)
        out["source"] = {"count": len(mine), "unread": unread, "unread_chapters": list(chapters.values())}
    return Response(out)


def _exam_filter(pool, data):
    """«فقط تست‌های کنکور» (optionally some years only) or one past exam (`source`): the pool narrowed to those."""
    source = data.get("source")
    konkur = data.get("konkur_only") in (True, "true", 1, "1") or bool(data.get("years")) or bool(source)
    if not konkur:
        return pool, False
    rows = QuestionSource.objects.filter(question_id__in=[q.id for q in pool], source__year__gt=0)
    years = [int(y) for y in (data.get("years") or []) if str(y).isdigit()]
    if years:
        rows = rows.filter(source__year__in=years)
    if source:
        rows = rows.filter(source_id=int(source) if str(source).isdigit() else 0)
    ids = set(rows.values_list("question_id", flat=True))
    return [q for q in pool if q.id in ids], bool(source)


def _only_studied(request, access, pool):
    """«فقط فصل‌های خوانده‌شده»: the tests of the chapters the learner has studied."""
    from .readiness import chapter_of, studied_chapters

    studied = studied_chapters(request.user, access)
    return [q for q in pool if (c := chapter_of(access, q.node_id)) and c.id in studied]


def _without_similar(picked, pool):
    """Two tests marked «مشابه» never sit in the same exam: the second is swapped for another of the pool."""
    ids = {q.id for q in picked}
    links = {}
    for a, b in Question.similar_to.through.objects.filter(from_question_id__in=[q.id for q in pool]).values_list("from_question_id", "to_question_id"):
        links.setdefault(a, set()).add(b)
        links.setdefault(b, set()).add(a)
    if not links:
        return picked
    kept, taken = [], set()
    spare = [q for q in pool if q.id not in ids]
    random.shuffle(spare)
    for q in picked:
        if links.get(q.id, set()) & taken:
            while spare:
                alt = spare.pop()
                if not links.get(alt.id, set()) & taken:
                    kept.append(alt)
                    taken.add(alt.id)
                    break
            continue
        kept.append(q)
        taken.add(q.id)
    return kept


def _pick_focused(user, pool, count):
    """«تمرکز روی اشتباه‌هایم»: up to half of the exam from the learner's weak questions, in this order: wrong ones
    still in the mistakes notebook, then ones marked «شک‌دار» in an exam, then ones never answered; the rest at random.
    An exam of every question there is is the same either way. Returns (questions in random order, how many were weak)."""
    from .mistakes import in_notebook, notebook
    from .progress import answered_ids

    if count >= len(pool):
        return random.sample(pool, len(pool)), 0
    ids = [q.id for q in pool]
    book = notebook(user, ids)
    wrong = [q for q in pool if in_notebook(book.get(q.id))]
    doubtful_ids = set(
        ExamAnswer.objects.filter(attempt__user=user, attempt__submitted_at__isnull=False, is_doubtful=True, question_id__in=ids).values_list("question_id", flat=True)
    )
    answered = answered_ids(user)
    taken: set[int] = set()
    weak: list = []
    mistakes = 0  # from the notebook or «شک‌دار»: what the report card calls «از اشتباه‌های قبلی تو»
    for n, group in enumerate((wrong, [q for q in pool if q.id in doubtful_ids], [q for q in pool if q.id not in answered])):
        group = [q for q in group if q.id not in taken]
        random.shuffle(group)
        for q in group:
            if len(weak) >= count // 2:
                break
            weak.append(q)
            taken.add(q.id)
            if n < 2:
                mistakes += 1
    rest = [q for q in pool if q.id not in taken]
    picked = weak + random.sample(rest, count - len(weak))
    random.shuffle(picked)
    return picked, mistakes


@api_view(["POST"])
def start_exam(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    pool = [q for q in Question.objects.filter(node_id__in=access.visible_ids_under(node), is_archived=False) if _usable(access, q)]
    pool, one_exam = _exam_filter(pool, request.data)
    if request.data.get("only_studied") in (True, "true", 1, "1"):
        pool = _only_studied(request, access, pool)
    if not pool:
        return _err("برای این انتخاب تستی در دسترس نیست.", "no_questions")
    try:
        count = max(1, min(EXAM_MAX_QUESTIONS, int(request.data.get("count") or 20), len(pool)))
    except (TypeError, ValueError):
        count = min(20, len(pool))
    if one_exam:
        count = min(EXAM_MAX_QUESTIONS, len(pool))  # a past exam is taken whole
    focus = request.data.get("focus_mistakes") in (True, "true", 1, "1")
    picked, focused = (_pick_focused(request.user, pool, count) if focus else (random.sample(pool, count), 0))
    if not one_exam:
        picked = _without_similar(picked, pool)
    seconds = sum(q.estimated_seconds or 90 for q in picked)
    try:
        if request.data.get("minutes"):
            seconds = max(60, min(4 * 3600, int(request.data["minutes"]) * 60))
    except (TypeError, ValueError):
        pass
    picked = list(Question.objects.filter(pk__in=[q.id for q in picked]).prefetch_related("choices"))
    if one_exam:
        # In the order of the real exam (its question numbers).
        numbers = dict(QuestionSource.objects.filter(source_id=int(request.data["source"]), question_id__in=[q.id for q in picked]).values_list("question_id", "number"))
        picked.sort(key=lambda q: (numbers.get(q.id) or 10_000, q.id))
    else:
        random.shuffle(picked)
    attempt = ExamAttempt.objects.create(
        user=request.user,
        node=node,
        question_ids=[q.id for q in picked],
        snapshot=_snapshot(picked),
        negative_marking=request.data.get("negative_marking", True) not in (False, "false", 0, "0"),
        time_limit_seconds=seconds,
        focused=focused,
    )
    return Response(_exam_detail(request, attempt), status=status.HTTP_201_CREATED)


def _exam_detail(request, attempt):
    ordered = _exam_questions(attempt)
    data = _exam_summary(attempt)
    # «نسبت به دفعه‌ی قبل بهتر شدی»: the score of the learner's previous finished exam on the same chapter.
    if attempt.submitted_at:
        data["previous_score"] = (
            ExamAttempt.objects.filter(user=attempt.user, node=attempt.node, submitted_at__isnull=False, started_at__lt=attempt.started_at, is_archived=False)
            .order_by("-started_at")
            .values_list("score_percent", flat=True)
            .first()
        )
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
                    "explanation": media_urls(request, resolve_refs(request, nodes.get(qid), q["explanation"])),
                    "solutions": [{"title": x["title"], "body": media_urls(request, resolve_refs(request, nodes.get(qid), x["body"]))}
                                  for x in _snapshot_solutions(q)],
                    # The answer key was corrected after this exam began; the exam keeps the key it was taken with.
                    "corrected": (
                        {"at": current[qid][1], "note": current[qid][2]}
                        if qid in current and current[qid][1] and current[qid][1] > attempt.started_at
                        else None
                    ),
                }
            )
        data["review"] = review
        data["by_chapter"] = _by_chapter(request, attempt, answers, nodes)
    return data


def _by_chapter(request, attempt, answers, nodes) -> list[dict]:
    """The exam's results by chapter, in book order: questions, right, wrong, blank and the share right. «weakest» marks
    the chapter with the lowest share (of those with at least two questions), for «تمرین همین فصل»."""
    from .readiness import chapter_label, chapter_of

    access = AccessMap(request.user, attempt.node)
    rows: dict[int, dict] = {}
    for qid in attempt.question_ids:
        c = chapter_of(access, nodes.get(qid))
        if not c:
            continue
        r = rows.setdefault(c.id, {"chapter_id": c.id, "title": chapter_label(c), "position": c.position or 0,
                                   "total": 0, "right": 0, "wrong": 0, "blank": 0})
        a = answers.get(qid)
        r["total"] += 1
        key = "blank" if not a or a.was_correct is None else "right" if a.was_correct else "wrong"
        r[key] += 1
    out = sorted(rows.values(), key=lambda r: r["position"])
    for r in out:
        r["percent"] = round(100 * r["right"] / r["total"]) if r["total"] else 0
        r["weakest"] = False
    candidates = [r for r in out if r["total"] >= 2] or out
    if len(out) > 1 and candidates:
        min(candidates, key=lambda r: (r["percent"], -r["total"]))["weakest"] = True
    return out


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
        doubts = {str(x) for x in (request.data.get("doubts") or []) if str(x).isdigit()}
        points = 0.0
        correct = wrong = blank = 0
        existing = set(Question.objects.filter(pk__in=attempt.question_ids).values_list("pk", flat=True))
        for qid, q in _exam_questions(attempt):
            if qid not in existing:
                continue
            choices = q["choices"]
            at = None if late else next((i for i, c in enumerate(choices) if str(c["id"]) == str(raw.get(str(qid)))), None)
            doubtful = str(qid) in doubts
            if at is None:
                blank += 1
                ExamAnswer.objects.create(attempt=attempt, question_id=qid, choice_order=None, was_correct=None, is_doubtful=doubtful)
                continue
            ok = bool(choices[at]["ok"])
            first = first_answer(request.user, qid, exclude_attempt=attempt)
            ExamAnswer.objects.create(attempt=attempt, question_id=qid, choice_order=at, was_correct=ok, is_doubtful=doubtful)
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
        from .reviews import exam_submitted, recheck

        exam_submitted(attempt)
        recheck(request.user)
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
    # «آزمون ۳»: each exam's place among the learner's exams on the same chapter (oldest = 1), so equal titles differ.
    numbers: dict[int, int] = {}
    seen: dict[int, int] = {}
    for pk, node_id in ExamAttempt.objects.filter(user=request.user, is_archived=False).order_by("started_at", "id").values_list("pk", "node_id"):
        seen[node_id] = seen.get(node_id, 0) + 1
        numbers[pk] = seen[node_id]
    stats = done.aggregate(count=Count("id"), average=Avg("score_percent"), best=Max("score_percent"))
    rows = list(attempts[(page - 1) * EXAM_PAGE : page * EXAM_PAGE + 1])
    return Response(
        {
            "results": [
                _exam_summary(a) | {"book_title": books.get(a.node.path[:steplen]).title if a.node.path[:steplen] in books else "", "number": numbers.get(a.pk)}
                for a in rows[:EXAM_PAGE]
            ],
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


def _chapter_of(access, node):
    """«فصل ۳: مشتق» for a section (from the book's map, no query); a chapter's own page is its chapter."""
    chapter = next((c for c in access.nodes.values() if c.kind == ContentNode.Kind.CHAPTER and node.path.startswith(c.path)), None)
    return {"number": chapter.position, "title": chapter.title} if chapter else None


def _next_section(access, node):
    sections = sorted((n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)), key=lambda n: n.path)
    ids = [n.id for n in sections]
    if node.id not in ids or ids.index(node.id) + 1 >= len(ids):
        return None
    nxt = sections[ids.index(node.id) + 1]
    chapter = next((c for c in access.nodes.values() if c.kind == ContentNode.Kind.CHAPTER and nxt.path.startswith(c.path)), None)
    here = next((c for c in access.nodes.values() if c.kind == ContentNode.Kind.CHAPTER and node.path.startswith(c.path)), None)
    new_chapter = bool(chapter and here and chapter.id != here.id)
    # A new chapter starts at its introduction page (when the learner may open it).
    start = chapter if new_chapter and access.readable(chapter.id) else nxt
    return {
        "id": start.id,
        "title": nxt.title,
        "locked": not access.readable(nxt.id),
        "new_chapter": new_chapter,
        "chapter_title": chapter.title if chapter else "",
        "chapter_number": chapter.position if chapter else None,
        "finished_chapter_number": here.position if here else None,
    }


def _available_library_books(user):
    """The whole books a learner can currently keep on their own shelf, with the same access rules as reading.

    A sample chapter of a paid book is not a personal copy: books enter this shelf when the whole book is free or an
    active purchase, subscription, staff/editor role, or manager-granted access covers it. An unpublished book is
    considered only for a currently active private grant.
    """
    if not user.is_authenticated:
        return []

    from django.db.models import Q

    from apps.commerce.models import Entitlement

    private_unpublished_ids = Entitlement.active_for(user).filter(
        book__kind=ContentNode.Kind.BOOK,
        book__depth=1,
        book__is_published=False,
        book__is_archived=False,
        book__is_inbox=False,
        order__isnull=True,
        granted_by__isnull=False,
    ).values("book_id")
    candidates = (
        ContentNode.objects.filter(
            kind=ContentNode.Kind.BOOK,
            depth=1,
            is_archived=False,
            is_inbox=False,
        )
        .filter(Q(is_published=True) | Q(pk__in=private_unpublished_ids))
        .prefetch_related("majors")
        .order_by("position", "title", "pk")
    )
    entitlements = active_rows(user)
    available = []
    for book in candidates:
        major_ids = {major.pk for major in book.majors.all()}
        access_kind = access_kind_from(entitlements, user, book.pk, major_ids)
        if not (book.is_free or access_kind):
            continue
        access = AccessMap(user, book, light=True, kind=access_kind)
        if access.visible(book.pk) and access.readable(book.pk):
            available.append((book, access))
    return available


def _library_payload(request):
    """Every currently accessible whole book, with its saved shelf state (or a useful inferred first state)."""
    available = _available_library_books(request.user)
    if not available:
        return []

    book_ids = [book.pk for book, _ in available]
    states = {
        row.book_id: row
        for row in LibraryBook.objects.filter(user=request.user, book_id__in=book_ids)
    }
    progress_rows = SectionProgress.objects.filter(user=request.user, book_id__in=book_ids).values("book_id").annotate(
        latest=Max("updated_at")
    )
    progress_latest = {row["book_id"]: row["latest"] for row in progress_rows}
    from apps.catalog.views import _prefetch_user_rows, book_card

    _prefetch_user_rows(request)
    items = []
    for book, access in available:
        state = states.get(book.pk)
        default_status = LibraryBook.Status.READING if book.pk in progress_latest else LibraryBook.Status.LATER
        items.append(
            {
                "book_id": book.pk,
                "status": state.status if state else default_status,
                "hidden": state.is_hidden if state else False,
                "position": state.position if state else 0,
                "book": book_card(request, book, access),
                "_book_position": book.position if book.position is not None else 2**31,
                "_latest_progress": progress_latest.get(book.pk),
            }
        )
    status_order = {
        LibraryBook.Status.READING: 0,
        LibraryBook.Status.LATER: 1,
        LibraryBook.Status.FINISHED: 2,
    }
    items.sort(
        key=lambda item: (
            item["hidden"],
            status_order.get(item["status"], 9),
            item["position"],
            item["_book_position"],
            item["book"]["title"].casefold(),
            item["book_id"],
        )
    )
    for item in items:
        item.pop("_book_position", None)
        item.pop("_latest_progress", None)
    return items


@api_view(["GET"])
def library(request):
    user = request.user
    hidden_book_ids = set(LibraryBook.objects.filter(user=user, is_hidden=True).values_list("book_id", flat=True))
    recent = SectionProgress.objects.filter(user=user).select_related("node", "book").order_by("-updated_at")
    reading, seen_books, maps = [], set(), {}
    for p in recent[:200]:
        if p.book_id in hidden_book_ids or p.book_id in seen_books or p.book.is_archived or not p.book.is_published:
            continue
        from apps.catalog.views import book_card

        if p.book_id not in maps:
            maps[p.book_id] = AccessMap(user, p.book)
        access = maps[p.book_id]
        # A section hidden or no longer readable: fall back to the next accessible section of that book.
        # In particular, an expired group entitlement must not leave an old paid section looking like active reading.
        if not access.visible(p.node_id) or not access.readable(p.node_id):
            continue
        seen_books.add(p.book_id)
        reading.append(
            {
                "book_slug": p.book.slug,
                "book_title": p.book.title,
                "last_section": _section_ref(p.node),
                "chapter": _chapter_of(access, p.node),
                # How far into that section (0–100), to open it where the reader left off on another device.
                "percent": p.percent,
                "position": p.position,
                "mode": p.mode,
                "updated_at": p.updated_at,
                "book": book_card(request, p.book, access),
                # Section finished: «ادامه بده» opens the next one (the first of the next chapter at a chapter's end).
                "next": _next_section(access, p.node) if p.is_done else None,
            }
        )
    bookmarks = Bookmark.objects.filter(user=user, is_archived=False).select_related("node").order_by("-created_at")[:100]
    notes = Note.objects.filter(user=user, is_archived=False).select_related("node").order_by("-updated_at")[:100]
    return Response(
        {
            "reading": reading,
            "books": _library_payload(request),
            "bookmarks": [{**_section_ref(b.node), "created_at": b.created_at} for b in bookmarks if not b.node.is_archived],
            "notes": [{**_note_payload(n), "node_title": n.node.title} for n in notes],
            "mistakes": _notebook_counts(request),
        }
    )


def _library_book_for_user(user, book_id):
    book = ContentNode.objects.filter(
        pk=book_id,
        kind=ContentNode.Kind.BOOK,
        depth=1,
        is_archived=False,
        is_inbox=False,
    ).first()
    if not book:
        return None
    access = AccessMap(user, book, light=True)
    return book if access.visible(book.pk) and access.readable(book.pk) else None


def _next_library_position(user, shelf_status):
    """Append after both explicitly ordered and as-yet-unsaved books already in this accessible shelf."""
    available = _available_library_books(user)
    book_ids = [book.pk for book, _ in available]
    if not book_ids:
        return 0
    states = {
        state.book_id: state
        for state in LibraryBook.objects.filter(user=user, book_id__in=book_ids)
    }
    reading_ids = set(
        SectionProgress.objects.filter(user=user, book_id__in=book_ids).values_list("book_id", flat=True).distinct()
    )
    current = []
    for book, _ in available:
        state = states.get(book.pk)
        if state and state.is_hidden:
            continue
        item_status = state.status if state else (
            LibraryBook.Status.READING if book.pk in reading_ids else LibraryBook.Status.LATER
        )
        if item_status == shelf_status:
            current.append(state.position if state else 0)
    return max(len(current), max(current, default=-1) + 1)


@api_view(["PATCH"])
def library_book(request, book_id):
    """Update only this learner's shelf status/visibility. Entitlements and all reading data are never touched."""
    if not isinstance(request.data, dict):
        return _err("درخواست معتبر نیست.", "invalid_library_update")
    unknown = set(request.data) - {"status", "hidden"}
    if unknown or not request.data or not (set(request.data) & {"status", "hidden"}):
        return _err("تنظیم قفسه معتبر نیست.", "invalid_library_update")
    shelf_status = request.data.get("status")
    if "status" in request.data and shelf_status not in LibraryBook.Status.values:
        return _err("یکی از قفسه‌های معتبر را انتخاب کنید.", "invalid_library_status")
    if "hidden" in request.data and type(request.data["hidden"]) is not bool:
        return _err("وضعیت پنهان‌بودن معتبر نیست.", "invalid_library_visibility")

    book = _library_book_for_user(request.user, book_id)
    if not book:
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    defaults_status = shelf_status or (
        LibraryBook.Status.READING
        if SectionProgress.objects.filter(user=request.user, book=book).exists()
        else LibraryBook.Status.LATER
    )
    with transaction.atomic():
        # Serialize creation and updates for this learner, including the case where no shelf row exists yet.
        type(request.user).objects.select_for_update().only("pk").get(pk=request.user.pk)
        state, _ = LibraryBook.objects.select_for_update().get_or_create(
            user=request.user,
            book=book,
            defaults={"status": defaults_status, "position": _next_library_position(request.user, defaults_status)},
        )
        if shelf_status and state.status != shelf_status:
            state.status = shelf_status
            state.position = _next_library_position(request.user, shelf_status)
        if "hidden" in request.data:
            state.is_hidden = request.data["hidden"]
        state.save()
    return Response({"book_id": state.book_id, "status": state.status, "hidden": state.is_hidden, "position": state.position})


@api_view(["PATCH"])
def reorder_library(request):
    """Persist a complete order for one active shelf; stale or foreign book ids are rejected without partial changes."""
    if not isinstance(request.data, dict) or set(request.data) != {"status", "book_ids"}:
        return _err("ترتیب قفسه معتبر نیست.", "invalid_library_order")
    shelf_status = request.data.get("status")
    book_ids = request.data.get("book_ids")
    if shelf_status not in LibraryBook.Status.values:
        return _err("یکی از قفسه‌های معتبر را انتخاب کنید.", "invalid_library_status")
    if (
        not isinstance(book_ids, list)
        or len(book_ids) > 1000
        or any(type(book_id) is not int or book_id < 1 for book_id in book_ids)
        or len(set(book_ids)) != len(book_ids)
    ):
        return _err("فهرست کتاب‌ها معتبر نیست.", "invalid_library_order")

    with transaction.atomic():
        # Pair with the update endpoint's user-row lock so concurrent status changes cannot partially apply a reorder.
        type(request.user).objects.select_for_update().only("pk").get(pk=request.user.pk)
        available = _available_library_books(request.user)
        available_ids = [book.pk for book, _ in available]
        states = {
            state.book_id: state
            for state in LibraryBook.objects.select_for_update().filter(user=request.user, book_id__in=available_ids)
        }
        reading_ids = set(
            SectionProgress.objects.filter(user=request.user, book_id__in=available_ids)
            .values_list("book_id", flat=True)
            .distinct()
        )
        expected = set()
        for book_id in available_ids:
            state = states.get(book_id)
            if state and state.is_hidden:
                continue
            item_status = state.status if state else (
                LibraryBook.Status.READING if book_id in reading_ids else LibraryBook.Status.LATER
            )
            if item_status == shelf_status:
                expected.add(book_id)
        if set(book_ids) != expected or len(book_ids) != len(expected):
            return _err("فهرست قفسه تغییر کرده است؛ صفحه را تازه کنید.", "stale_library_order", status.HTTP_409_CONFLICT)

        now = timezone.now()
        to_update, to_create = [], []
        for position, book_id in enumerate(book_ids):
            state = states.get(book_id)
            if state:
                state.position = position
                state.updated_at = now
                to_update.append(state)
            else:
                to_create.append(
                    LibraryBook(user=request.user, book_id=book_id, status=shelf_status, position=position)
                )
        if to_update:
            LibraryBook.objects.bulk_update(to_update, ["position", "updated_at"])
        if to_create:
            LibraryBook.objects.bulk_create(to_create)
    return Response({"status": shelf_status, "book_ids": book_ids})


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


def _year(user, days) -> dict:
    """The «days of study» grid (like GitHub's): the last 53 weeks, only the days with something done (the app fills in
    the rest). Each day: sections, answers (and how many right), cards, exams and seconds of study; plus the longest run
    of days in a row and where it lies."""
    from django.db.models import Sum
    from django.db.models.functions import TruncDate

    from apps.learning.models import QuizAnswer

    from .models import ExamAttempt, StudyTime

    since = timezone.localdate() - timedelta(days=370)
    out = {}

    def day_of(d):
        return out.setdefault(d, {"date": d, "sections": 0, "answers": 0, "correct": 0, "cards": 0, "exams": 0, "seconds": 0})

    for d in days.filter(date__gte=since):
        day_of(d.date).update(sections=d.sections, answers=d.answers, cards=d.cards)
    for day, seconds in StudyTime.objects.filter(user=user, day__gte=since).values_list("day").annotate(s=Sum("seconds")):
        day_of(day)["seconds"] = seconds or 0
    tz = timezone.get_current_timezone()
    for day, n in (
        QuizAnswer.objects.filter(user=user, was_correct=True, answered_at__date__gte=since)
        .annotate(d=TruncDate("answered_at", tzinfo=tz)).values_list("d").annotate(n=Count("id")).order_by()
    ):
        if day in out:
            out[day]["correct"] = n
    for day, n in (
        ExamAttempt.objects.filter(user=user, submitted_at__isnull=False, submitted_at__date__gte=since)
        .annotate(d=TruncDate("submitted_at", tzinfo=tz)).values_list("d").annotate(n=Count("id")).order_by()
    ):
        day_of(day)["exams"] = n
    longest = run = 0
    previous = None
    longest_end = None
    for day in sorted(days.values_list("date", flat=True)):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        if run >= longest:  # ties: the most recent run
            longest, longest_end = run, day
        previous = day
    # Where the longest run lies, for the frame the app draws around it (only when longer than one day).
    longest_from = longest_end - timedelta(days=longest - 1) if longest > 1 else None
    return {
        "since": since,
        "days": [out[k] for k in sorted(out)],
        "longest_streak": longest,
        "longest_from": longest_from,
        "longest_to": longest_end if longest > 1 else None,
    }


def _time(user):
    from .time import totals

    return totals(user)


def _improvement(user):
    from .mistakes import improvement

    return improvement(user)




def _insights(user, books) -> dict:
    """For the stats page's cards: when each book in progress will be finished at the pace of the last 14 days, and
    the learner's best time of day (from the tests answered in the last 60 days)."""
    today = timezone.localdate()
    since = timezone.now() - timedelta(days=14)
    step = ContentNode.steplen
    recent: dict[str, int] = {}
    for path in SectionProgress.objects.filter(user=user, is_done=True, updated_at__gte=since, node__kind=ContentNode.Kind.SECTION) \
            .values_list("node__path", flat=True):
        recent[path[:step]] = recent.get(path[:step], 0) + 1
    slugs = {b.path: b.slug for b in ContentNode.objects.filter(depth=1, path__in=list(recent))}
    forecast = []
    for b in books:
        left = b["total"] - b["done"]
        path = next((p for p, sl in slugs.items() if sl == b["slug"]), "")
        pace = recent.get(path, 0) / 14  # sections a day
        if left > 0 and pace > 0:
            days_left = math.ceil(left / pace)
            if days_left <= 365:
                forecast.append({"slug": b["slug"], "title": b["title"], "left": left, "days": days_left,
                                 "finish_on": today + timedelta(days=days_left)})
    forecast.sort(key=lambda f: f["days"])

    best = None
    hours = [timezone.localtime(t).hour for t in QuizAnswer.objects.filter(
        user=user, answered_at__gte=timezone.now() - timedelta(days=60)).values_list("answered_at", flat=True)[:5000]]
    if len(hours) >= 20:
        windows = [sum(1 for h in hours if h // 2 == w) for w in range(12)]
        w = max(range(12), key=lambda i: windows[i])
        best = {"from": w * 2, "to": w * 2 + 2, "share": round(100 * windows[w] / len(hours))}
    return {"forecast": forecast[:3], "best_hours": best}


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

    # Per book: sections read out of the book's sections. Both sides count the same thing (published, not archived
    # sections, placed by their tree path), so the share never passes 100% when a section is moved, archived or
    # unpublished, and chapter introductions (read too) are not counted.
    from django.db.models.functions import Substr

    step = ContentNode.steplen
    counted = {"kind": ContentNode.Kind.SECTION, "is_archived": False, "is_published": True}
    done_by_book: dict[str, int] = {}
    for path in SectionProgress.objects.filter(user=user, is_done=True, **{f"node__{k}": v for k, v in counted.items()}) \
            .values_list("node__path", flat=True):
        done_by_book[path[:step]] = done_by_book.get(path[:step], 0) + 1
    totals = dict(ContentNode.objects.filter(**counted).annotate(root=Substr("path", 1, step))
                  .filter(root__in=list(done_by_book)).order_by().values("root").annotate(n=Count("id")).values_list("root", "n"))
    books = []
    for book in ContentNode.objects.filter(path__in=list(done_by_book), depth=1, is_archived=False).order_by("path"):
        total = totals.get(book.path, 0)
        books.append({"slug": book.slug, "title": book.title, "done": min(done_by_book[book.path], total), "total": total})
    sections_done = sum(b["done"] for b in books)

    # «N از M لغت»: books whose word cards the learner has started.
    from .progress import WORD_PREFIX, word_counts

    words = []
    started = (
        FlashcardReview.objects.filter(user=user, flashcard__slug__startswith=WORD_PREFIX, flashcard__is_archived=False)
        .values_list("flashcard__node__path", flat=True)
        .distinct()
    )
    roots = sorted({p[: ContentNode.steplen] for p in started})
    for book in ContentNode.objects.filter(path__in=roots, kind=ContentNode.Kind.BOOK, is_archived=False):
        access = AccessMap(user, book)
        counts = word_counts(user, access, book) if access.visible(book.id) else None
        if counts:
            words.append({"slug": book.slug, "title": book.title, **counts})

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
            "sections_done": sections_done,
            "answers": total_answers,
            "accuracy": round(correct_answers / total_answers * 100) if total_answers else None,
            "cards_reviewed": FlashcardReview.objects.filter(user=user).aggregate(n=Count("id"))["n"],
            "cards_mastered": FlashcardReview.objects.filter(user=user, box__gte=4).count(),
            "exams": ExamAttempt.objects.filter(user=user, submitted_at__isnull=False).count(),
            "streak_days": _streak(day_set),
            "study_days": len(day_set),
            "last_14_days": last_14,
            "year": _year(user, days),
            "insights": _insights(user, books),
            "books": books,
            "words": words,
            "weak_sections": [w for w in weak if w["accuracy"] < 70],
            "improvement": _improvement(user),
            "time": _time(user),
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


@api_view(["GET", "POST"])
def known_words(request, slug):
    """«مرور واژه‌ها»: GET the words of this book the learner knows; POST {term, known} (or {terms: [...], known}) to
    mark or unmark. Kept on the account, so the cards continue on another device."""
    from .models import WordKnown

    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    if not AccessMap(request.user, book).visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    if request.method == "POST":
        terms = request.data.get("terms")
        if terms is None:
            terms = [request.data.get("term", "")]
        if not isinstance(terms, list):
            return Response({"code": "invalid", "message": "واژه نامعتبر است."}, status=status.HTTP_400_BAD_REQUEST)
        known = bool(request.data.get("known", True))
        for term in terms[:500]:
            term = str(term or "").strip()[:120]
            if term:
                WordKnown.objects.update_or_create(user=request.user, book=book, term=term, defaults={"known": known})
    words = list(WordKnown.objects.filter(user=request.user, book=book, known=True).values_list("term", flat=True))
    return Response({"known": words})
