"""Measured difficulty: recount each question from every learner's first answer only (practice or exam)."""

from django.db import migrations


def recount(apps, schema_editor):
    Question = apps.get_model("learning", "Question")
    QuizAnswer = apps.get_model("learning", "QuizAnswer")
    ExamAnswer = apps.get_model("study", "ExamAnswer")
    first = {}  # (user, question) -> (when, correct)
    for user, q, when, ok in QuizAnswer.objects.values_list("user_id", "question_id", "answered_at", "was_correct").iterator():
        key = (user, q)
        if key not in first or when < first[key][0]:
            first[key] = (when, ok)
    rows = ExamAnswer.objects.filter(choice_order__isnull=False).values_list("attempt__user_id", "question_id", "attempt__submitted_at", "was_correct")
    for user, q, when, ok in rows.iterator():
        if when is None:
            continue
        key = (user, q)
        if key not in first or when < first[key][0]:
            first[key] = (when, ok)
    counts = {}
    for (_, q), (_, ok) in first.items():
        n, c = counts.get(q, (0, 0))
        counts[q] = (n + 1, c + (1 if ok else 0))
    for q in Question.objects.all().only("id", "answer_count", "correct_count"):
        n, c = counts.get(q.id, (0, 0))
        if (q.answer_count, q.correct_count) != (n, c):
            q.answer_count, q.correct_count = n, c
            q.save(update_fields=["answer_count", "correct_count"])


class Migration(migrations.Migration):
    dependencies = [
        ("learning", "0005_number_existing_items"),
        ("study", "0002_keep_terms_and_snapshots"),
    ]

    # Going back keeps the recounted numbers (they are statistics, not user data).
    operations = [migrations.RunPython(recount, migrations.RunPython.noop)]
