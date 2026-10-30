"""
A learner's own data: reading progress, bookmarks, highlights and notes, flashcard boxes, exams and daily activity.

All of it attaches to stable ids (content node, question, flashcard), never to text positions alone, so content edits
do not break it. Nothing is hard-deleted: removing a bookmark or note archives it.
"""

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import ContentNode
from apps.learning.models import Flashcard, Question

User = settings.AUTH_USER_MODEL


class SectionProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="section_progress")
    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    percent = models.PositiveSmallIntegerField("درصد خوانده‌شده", default=0)
    is_done = models.BooleanField("خوانده شد", default=False)
    first_opened_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "پیشرفت مطالعه"
        verbose_name_plural = "پیشرفت مطالعه"
        unique_together = [("user", "node")]
        indexes = [models.Index(fields=["user", "-updated_at"]), models.Index(fields=["user", "book"])]


class Bookmark(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookmarks")
    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = "نشان"
        verbose_name_plural = "نشان‌ها"
        unique_together = [("user", "node")]


class Note(models.Model):
    """A highlight (quote only) or a note (quote and/or body). The quote re-finds the place after content edits."""

    class Color(models.TextChoices):
        YELLOW = "yellow", "زرد"
        GREEN = "green", "سبز"
        BLUE = "blue", "آبی"
        PINK = "pink", "صورتی"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notes")
    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    mode = models.CharField(max_length=10, default="full")  # which text: full or summary
    quote = models.TextField("متن انتخاب‌شده", blank=True)
    body = models.TextField("یادداشت", blank=True)
    color = models.CharField(max_length=10, choices=Color.choices, default=Color.YELLOW)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = "یادداشت/هایلایت"
        verbose_name_plural = "یادداشت‌ها و هایلایت‌ها"
        indexes = [models.Index(fields=["user", "node"])]


class FlashcardReview(models.Model):
    """Leitner box (1–5) of a card for a learner. Box 1 is due now; higher boxes come back later."""

    INTERVAL_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 15}

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="flashcard_reviews")
    flashcard = models.ForeignKey(Flashcard, on_delete=models.PROTECT, related_name="reviews")
    box = models.PositiveSmallIntegerField(default=1)
    due_at = models.DateTimeField(default=timezone.now)
    review_count = models.PositiveIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "مرور فلش‌کارت"
        verbose_name_plural = "مرور فلش‌کارت‌ها"
        unique_together = [("user", "flashcard")]

    def record(self, known: bool):
        self.box = min(5, self.box + 1) if known else 1
        now = timezone.now()
        self.due_at = now + timedelta(days=self.INTERVAL_DAYS[self.box])
        self.review_count += 1
        self.last_reviewed_at = now


class ExamAttempt(models.Model):
    """A timed exam over a book, chapter or section. Graded on the server; optional negative marking."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="exam_attempts")
    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    question_ids = models.JSONField(default=list)
    negative_marking = models.BooleanField(default=True)
    time_limit_seconds = models.PositiveIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    correct = models.PositiveSmallIntegerField(default=0)
    wrong = models.PositiveSmallIntegerField(default=0)
    blank = models.PositiveSmallIntegerField(default=0)
    score_percent = models.FloatField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = "آزمون"
        verbose_name_plural = "آزمون‌ها"
        ordering = ["-started_at"]

    @property
    def ends_at(self):
        return self.started_at + timedelta(seconds=self.time_limit_seconds)


class ExamAnswer(models.Model):
    attempt = models.ForeignKey(ExamAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="+")
    choice_order = models.PositiveSmallIntegerField(null=True, blank=True)  # null = left blank
    was_correct = models.BooleanField(null=True)

    class Meta:
        unique_together = [("attempt", "question")]


class StudyDay(models.Model):
    """One row per learner per day they studied: drives streaks and the admin's daily-activity numbers."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_days")
    date = models.DateField()
    sections = models.PositiveIntegerField(default=0)
    answers = models.PositiveIntegerField(default=0)
    cards = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "روز مطالعه"
        verbose_name_plural = "روزهای مطالعه"
        unique_together = [("user", "date")]
        indexes = [models.Index(fields=["date"])]

    @classmethod
    def touch(cls, user, field: str, amount: int = 1):
        if not user.is_authenticated:
            return
        today = timezone.localdate()
        row, _ = cls.objects.get_or_create(user=user, date=today)
        cls.objects.filter(pk=row.pk).update(**{field: models.F(field) + amount})


class Dashboard(StudyDay):
    """Admin-only: an analytics page listed in the admin menu (no table of its own)."""

    class Meta:
        proxy = True
        verbose_name = "داشبورد آمار"
        verbose_name_plural = "داشبورد آمار"
