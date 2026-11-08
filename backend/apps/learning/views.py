from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.numbering import resolve as resolve_refs
from apps.catalog.places import chapter_number
from apps.catalog.access import AccessMap
from apps.catalog.models import ContentNode
from apps.catalog.views import NOT_FOUND, media_urls

from apps.study.models import StudyDay

from .models import ExamSource, Flashcard, Question, QuestionSource, QuizAnswer

LOCKED = {"code": "locked", "message": "این مورد در نسخه‌ی کامل کتاب است."}


def _usable(access, item):
    """A question or flashcard is usable if its node is visible and it is free or its node is readable."""
    return access.visible(item.node_id) and (item.is_free or access.readable(item.node_id))


def _share_place(access, q) -> dict:
    node = access.nodes.get(q.node_id)
    chapter = next((n for n in access.nodes.values() if n.kind == ContentNode.Kind.CHAPTER and node and node.path.startswith(n.path)), None)
    return {"book": access.book.title, "chapter": chapter.title if chapter else "", "chapter_number": chapter.position if chapter else None}


CARDS_PER_MISTAKE = 3


@api_view(["GET"])
@permission_classes([AllowAny])
def node_questions(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    questions = (
        Question.objects.filter(node_id__in=access.visible_ids_under(node), is_archived=False)
        .prefetch_related("choices", "questionsource_set__source")
        .order_by("node__path", "order", "id")
    )
    if request.query_params.get("ids"):
        # «تست‌های این نکته»: only these (the tests linked to one flashcard).
        questions = questions.filter(pk__in=[int(x) for x in request.query_params["ids"].split(",") if x.strip().isdigit()])
    items, locked = [], 0
    usable = []
    for q in questions:
        if not _usable(access, q):
            locked += 1
            continue
        usable.append(q)
    from apps.study.progress import core

    by_section: dict[int, list] = {}
    for q in usable:
        by_section.setdefault(q.node_id, []).append((q.id, q.is_extra))
    counted = {qid for rows in by_section.values() for qid in core(rows)}
    from apps.catalog.fresh import formula_macros, question_badges

    badges = question_badges(request.user, usable)
    for q in usable:
        items.append(
            {
                "id": q.id,
                "node_id": q.node_id,
                # Shown above «سؤال ۱ از ۴»: the section the question belongs to.
                "node_title": access.nodes[q.node_id].title if q.node_id in access.nodes else "",
                "chapter_number": chapter_number(request, access.nodes.get(q.node_id)),
                "shareable": q.is_sample,
                # Printed on the shared picture: the book and chapter it comes from.
                "share_place": _share_place(access, q) if q.is_sample else None,
                "stem": media_urls(request, q.stem),
                # Correct answers are never sent before the learner answers.
                "choices": [{"id": c.id, "text": media_urls(request, c.text)} for c in q.choices.all()],
                "difficulty": q.difficulty,
                "measured_difficulty": q.measured_difficulty,
                "domain": q.domain,
                "kind": q.kind,
                "estimated_seconds": q.estimated_seconds,
                "is_original": q.is_original,
                "sources": [{"name": qs.source.name, "year": qs.source.year, "number": qs.number} for qs in q.questionsource_set.all()],
                "fixed_order": q.keeps_order,
                "corrected": q.correction(),
                # «تست تکمیلی»: extra practice, shown after the section's own tests and not counted in its progress.
                "extra": q.id not in counted,
                # «تازه» (added since the learner started the section) or «به‌روز شده» (the panel's «مطلب تازه»).
                "badge": badges.get(q.id),
            }
        )
    return Response({"questions": items, "locked_count": locked, "macros": formula_macros()})


def source_label(q) -> str:
    """«کنکور ارشد اقتصاد ۱۴۰۱» (the first real exam of the question), or "" for an original one."""
    for qs in q.questionsource_set.all():
        if qs.source.year:
            return f"{qs.source.name} {str(qs.source.year).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))}"
    return ""


def similar_of(access, question) -> list[dict]:
    """Tests marked «مشابه» of this one, both ways, that the learner may open."""
    found = {}
    for q in (*question.similar_to.all(), *question.similar_from.all()):
        if q.pk != question.pk and not q.is_archived and access.visible(q.node_id) and _usable(access, q):
            found[q.pk] = q
    return [{"id": q.id, "node_id": q.node_id, "source": source_label(q)} for q in found.values()]


@api_view(["POST"])
@permission_classes([AllowAny])
def answer(request, question_id):
    question = get_object_or_404(Question.objects.select_related("node"), pk=question_id, is_archived=False)
    access = AccessMap(request.user, question.node)
    if not access.visible(question.node_id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    if not _usable(access, question):
        return Response(LOCKED, status=status.HTTP_403_FORBIDDEN)
    from apps.study.views import in_open_exam

    if in_open_exam(request.user, question.id):
        return Response({"code": "in_exam", "message": "این سؤال در آزمون در حال اجرای شماست؛ پاسخش بعد از پایان آزمون نشان داده می‌شود."}, status=status.HTTP_409_CONFLICT)
    choices = list(question.choices.all())
    picked = next((c for c in choices if str(c.id) == str(request.data.get("choice_id"))), None)
    correct = next((c for c in choices if c.is_correct), None)
    if picked is None or correct is None:
        return Response({"code": "invalid_choice", "message": "گزینه‌ی انتخاب‌شده معتبر نیست."}, status=status.HTTP_400_BAD_REQUEST)

    # Only signed-in learners count toward measured difficulty (guests could skew it).
    fixed, answered_before = None, False
    if request.user.is_authenticated:
        from apps.study.mistakes import fixed_info
        from apps.study.views import first_answer

        # A question from the mistakes notebook answered right: «اشتباهی که برطرف شد».
        fixed = fixed_info(request.user, question.pk) if picked.is_correct else None
        first = first_answer(request.user, question.pk)
        if question.key_changed_at:
            answered_before = QuizAnswer.objects.filter(user=request.user, question=question, answered_at__lt=question.key_changed_at).exists()
        QuizAnswer.objects.create(user=request.user, question=question, choice_order=picked.order, was_correct=picked.is_correct)
        from apps.study.reviews import recheck

        recheck(request.user)
        if first:
            Question.objects.filter(pk=question.pk).update(
                answer_count=F("answer_count") + 1, correct_count=F("correct_count") + (1 if picked.is_correct else 0)
            )
        StudyDay.touch(request.user, "answers")

    related = [f for f in question.flashcards.filter(is_archived=False) if _usable(access, f)]
    # A wrong answer brings its key points back: up to three linked cards join today's review («مرور امروز»).
    queued = 0
    if request.user.is_authenticated and not picked.is_correct and related:
        from django.utils import timezone

        from apps.study.models import FlashcardReview

        now = timezone.now()
        for card in related[:CARDS_PER_MISTAKE]:
            review, created = FlashcardReview.objects.get_or_create(user=request.user, flashcard=card, defaults={"box": 1, "due_at": now})
            if created or review.due_at > now:
                if not created:
                    FlashcardReview.objects.filter(pk=review.pk).update(due_at=now)
                queued += 1
    return Response(
        {
            "is_correct": picked.is_correct,
            "correct_choice_id": correct.id,
            # «[[#sin-hamarz]]» → «مثال ۳-۵», a tap opens it in the notes (apps/catalog/numbering.py).
            "explanation": media_urls(request, resolve_refs(request, question.node, question.explanation)),
            # Extra solutions, each under its own title («راه‌حل تستی», «حل دیگر», …).
            "solutions": [{"title": x.get("title", ""), "body": media_urls(request, resolve_refs(request, question.node, x.get("body", "")))}
                          for x in question.solutions or []],
            # Tapping one opens the book's cards at it (a link never leaves the book).
            "flashcards": [{"id": f.id, "title": f.title} for f in related],
            # «مشابه»: the same test with a change in another exam («نسخه‌ی دیگری از این تست در کنکور ۱۴۰۱ آمده»).
            "similar": similar_of(access, question),
            "book_id": access.book.id,
            "cards_queued": queued,
            "node_id": question.node_id,
            "fixed": fixed,
            "corrected": ({**question.correction(), "answered_before": answered_before} if question.key_changed_at else None),
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def node_flashcards(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    cards = (
        Flashcard.objects.filter(node_id__in=access.visible_ids_under(node), is_archived=False)
        .prefetch_related("questions")
        .order_by("node__path", "order", "id")
    )
    if request.query_params.get("ids"):
        # From «فلش‌کارت مرتبط» under a test's answer: these cards only.
        cards = cards.filter(pk__in=[int(x) for x in request.query_params["ids"].split(",") if x.strip().isdigit()])
    if request.query_params.get("done") == "1":
        # «مرور فلش‌کارت‌های کتاب»: only sections the learner has finished (green tick); nothing for a guest.
        from apps.study.progress import section_states

        cards = cards.filter(node_id__in=section_states(request.user, access, request)[1])
    items, locked = [], 0
    from apps.catalog.fresh import flashcard_badges, formula_macros

    cards = list(cards)
    badges = flashcard_badges(request.user, cards)
    for f in cards:
        if not _usable(access, f):
            locked += 1
            continue
        items.append({"id": f.id, "badge": badges.get(f.id), "title": f.title, "point": media_urls(request, f.point), "formula": f.formula,
                      "node_id": f.node_id, "node_title": access.nodes[f.node_id].title if f.node_id in access.nodes else "",
                      "chapter_number": chapter_number(request, access.nodes.get(f.node_id)),
                      # «تست‌های این نکته»: the linked tests the learner may practise.
                      "question_ids": [q.id for q in f.questions.all() if not q.is_archived and _usable(access, q)]})
    return Response({"flashcards": items, "locked_count": locked, "book_id": access.book.id, "macros": formula_macros()})


@api_view(["GET"])
@permission_classes([AllowAny])
def book_samples(request, slug):
    """The book's shareable questions (marked in the panel) this learner may see, to send up to five as one picture."""
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    questions = (
        Question.objects.filter(node_id__in=access.visible_ids_under(book), is_sample=True, is_archived=False)
        .select_related("node").prefetch_related("choices", "questionsource_set__source")
        .order_by("node__path", "order", "id")
    )
    from apps.study.mistakes import _practice_payload

    out = [{**_practice_payload(request, q), "shareable": True, "share_place": _share_place(access, q)} for q in questions if _usable(access, q)]
    return Response({"book": book.title, "questions": out})


# --- «کنکورهای سال‌های قبل» -------------------------------------------------------------------------------------


def _past_pool(access):
    """The book's tests with a real exam source (with a year) that the learner may practise."""
    return [
        q for q in Question.objects.filter(node_id__in=access.visible_ids_under(access.book), is_archived=False, questionsource__source__year__gt=0)
        .distinct().select_related("node").prefetch_related("questionsource_set__source", "choices")
        if _usable(access, q)
    ]


@api_view(["GET"])
@permission_classes([AllowAny])
def book_past_exams(request, slug):
    """«کنکورهای سال‌های قبل»: every exam (name and year) that has tests in this book, newest first, with how many.
    Built from the tests' «منبع:» lines; a test that came in several exams counts in each."""
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    groups: dict[int, dict] = {}
    pool = _past_pool(access)
    for q in pool:
        for qs in q.questionsource_set.all():
            if not qs.source.year:
                continue
            g = groups.setdefault(qs.source_id, {"id": qs.source_id, "name": qs.source.name, "year": qs.source.year, "count": 0, "seconds": 0})
            g["count"] += 1
            g["seconds"] += q.estimated_seconds or 90
    every = Question.objects.filter(node_id__in=access.visible_ids_under(book), is_archived=False, questionsource__source__year__gt=0).distinct().count()
    items = sorted(groups.values(), key=lambda g: (-g["year"], g["name"]))
    # «تکراری‌ها و مشابه‌ها»: the exams by name (a field's konkur, every year), with how many repeats each has.
    names = sorted({g["name"] for g in items})
    # «locked»: past-exam tests in parts of the book this learner has not bought.
    return Response({"exams": [{**g, "minutes": max(1, round(g["seconds"] / 60))} for g in items],
                     "years": sorted({g["year"] for g in items}, reverse=True),
                     "names": [{"name": n, "repeats": len(_repeat_groups(pool, [n]))} for n in names],
                     "repeats": len(_repeat_groups(pool, names)),
                     "total": len(pool), "locked": max(0, every - len(pool))})


def _repeat_groups(pool, names) -> list[list]:
    """Tests of the chosen konkurs (by name, any year) that came back: one test in two or more exams («تکراری», the
    other exam may be another konkur), or tests linked as «مشابه». Each group: its tests, oldest exam first."""
    names = set(names)
    by_id = {q.id: q for q in pool}

    def all_exams(q):
        return sorted((qs.source.year, qs.source.name) for qs in q.questionsource_set.all() if qs.source.year)

    def exams(q):
        return [e for e in all_exams(q) if e[1] in names]

    groups, seen = [], set()
    links: dict[int, set] = {}
    for a, b in Question.similar_to.through.objects.filter(from_question_id__in=list(by_id)).values_list("from_question_id", "to_question_id"):
        if b in by_id:
            links.setdefault(a, set()).add(b)
            links.setdefault(b, set()).add(a)
    for q in sorted(pool, key=lambda q: (exams(q) or [(9999, "")])[0]):
        if q.id in seen:
            continue
        # The test and every test «مشابه» to it, directly or through another.
        family, todo = [], [q.id]
        while todo:
            i = todo.pop()
            if i in seen:
                continue
            seen.add(i)
            family.append(by_id[i])
            todo.extend(links.get(i, ()))
        if not any(exams(x) for x in family):
            continue
        if len(family) > 1 or len(all_exams(q)) > 1:
            groups.append(sorted(family, key=lambda x: (all_exams(x) or [(9999, "")])[0]))
    return groups


@api_view(["GET"])
@permission_classes([AllowAny])
def book_past_repeats(request, slug):
    """«تکراری‌ها و مشابه‌ها» of the chosen konkurs (?names=a|b; none: all), as practice questions, each group together,
    with the exams each test came in."""
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    from apps.catalog.fresh import formula_macros
    from apps.study.mistakes import _practice_payload

    pool = _past_pool(access)
    wanted = [n for n in (request.query_params.get("names") or "").split("|") if n.strip()]
    names = wanted or sorted({qs.source.name for q in pool for qs in q.questionsource_set.all() if qs.source.year})
    out = []
    for n, group in enumerate(_repeat_groups(pool, names), start=1):
        for q in group:
            where = "، ".join(f"{qs.source.name} {fa(qs.source.year)}" for qs in q.questionsource_set.all() if qs.source.year)
            out.append({**_practice_payload(request, q), "group": n, "group_note": f"گروه {fa(n)}: {where}"})
    return Response({"questions": out, "locked_count": 0, "groups": len(set(x["group"] for x in out)),
                     "title": "تکراری‌ها و مشابه‌ها", "macros": formula_macros()})


def fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


@api_view(["GET"])
@permission_classes([AllowAny])
def book_past_questions(request, slug):
    """The tests of one past exam in this book, in the exam's own order (its question numbers), as practice questions."""
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    from apps.study.mistakes import _practice_payload

    source = get_object_or_404(ExamSource, pk=request.query_params.get("source") or 0)
    rows = (QuestionSource.objects.filter(source=source, question__node_id__in=access.visible_ids_under(book), question__is_archived=False)
            .select_related("question__node").prefetch_related("question__choices", "question__questionsource_set__source"))
    ordered = sorted(rows, key=lambda r: (r.number or 10_000, r.question.node.path, r.question.order))
    questions = [_practice_payload(request, r.question) for r in ordered if _usable(access, r.question)]
    from apps.catalog.fresh import formula_macros

    return Response({"questions": questions, "locked_count": len(ordered) - len(questions), "title": f"{source.name} {source.year}",
                     "macros": formula_macros()})
