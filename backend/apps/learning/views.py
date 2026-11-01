from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.access import AccessMap
from apps.catalog.models import ContentNode
from apps.catalog.views import NOT_FOUND, media_urls

from apps.study.models import StudyDay

from .models import Flashcard, Question, QuizAnswer

LOCKED = {"code": "locked", "message": "این مورد در نسخه‌ی کامل کتاب است."}


def _usable(access, item):
    """A question or flashcard is usable if its node is visible and it is free or its node is readable."""
    return access.visible(item.node_id) and (item.is_free or access.readable(item.node_id))


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
    items, locked = [], 0
    for q in questions:
        if not _usable(access, q):
            locked += 1
            continue
        items.append(
            {
                "id": q.id,
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
            }
        )
    return Response({"questions": items, "locked_count": locked})


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
    if request.user.is_authenticated:
        from apps.study.views import first_answer

        first = first_answer(request.user, question.pk)
        QuizAnswer.objects.create(user=request.user, question=question, choice_order=picked.order, was_correct=picked.is_correct)
        if first:
            Question.objects.filter(pk=question.pk).update(
                answer_count=F("answer_count") + 1, correct_count=F("correct_count") + (1 if picked.is_correct else 0)
            )
        StudyDay.touch(request.user, "answers")

    related = [f for f in question.flashcards.filter(is_archived=False) if _usable(access, f)]
    return Response(
        {
            "is_correct": picked.is_correct,
            "correct_choice_id": correct.id,
            "explanation": media_urls(request, question.explanation),
            "quick_solution": media_urls(request, question.quick_solution),
            "alternative_view": media_urls(request, question.alternative_view),
            "flashcards": [{"id": f.id, "title": f.title} for f in related],
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def node_flashcards(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    cards = Flashcard.objects.filter(node_id__in=access.visible_ids_under(node), is_archived=False).order_by("node__path", "order", "id")
    items, locked = [], 0
    for f in cards:
        if not _usable(access, f):
            locked += 1
            continue
        items.append({"id": f.id, "title": f.title, "point": media_urls(request, f.point), "formula": f.formula})
    return Response({"flashcards": items, "locked_count": locked})
