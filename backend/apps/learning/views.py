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

from .models import Flashcard, Question, QuizAnswer

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
            "quick_solution": media_urls(request, resolve_refs(request, question.node, question.quick_solution)),
            "alternative_view": media_urls(request, resolve_refs(request, question.node, question.alternative_view)),
            # Tapping one opens the book's cards at it (a link never leaves the book).
            "flashcards": [{"id": f.id, "title": f.title} for f in related],
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
