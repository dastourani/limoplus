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
    # Where the reader is now (not the furthest point): for «ادامه بده» on any device.
    position = models.PositiveSmallIntegerField("جای فعلی (درصد)", default=0)
    mode = models.CharField("حالت", max_length=10, default="full")
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
    """
    Spaced review of a card (Leitner boxes 1–6). Grades:
      again — not remembered: box 1, shown again in this session
      hard  — remembered with effort: same box, back tomorrow
      good  — remembered: one box up
      easy  — effortless: two boxes up
    The wait grows with the box, so well-known cards take less and less time. Box 4+ counts as mastered.
    """

    INTERVAL_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 15, 6: 30}
    MAX_BOX = 6
    MASTERED_BOX = 4
    GRADES = ("again", "hard", "good", "easy")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="flashcard_reviews")
    flashcard = models.ForeignKey(Flashcard, on_delete=models.PROTECT, related_name="reviews")
    box = models.PositiveSmallIntegerField(default=1)
    due_at = models.DateTimeField(default=timezone.now)
    review_count = models.PositiveIntegerField(default=0)
    last_reviewed_at = models.DateTimeField(null=True, blank=True)
    # Ids of the last few reviews sent by the app (comma-separated), so a review re-sent after a dropped connection
    # counts once, even if another review of the card came in between.
    last_op = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "مرور فلش‌کارت"
        verbose_name_plural = "مرور فلش‌کارت‌ها"
        unique_together = [("user", "flashcard")]

    @classmethod
    def next_step(cls, box: int, grade: str) -> tuple[int, timedelta]:
        """(new box, wait until the next review) for a grade — also used to label the buttons in the app."""
        if grade == "again":
            return 1, timedelta(0)
        if grade == "hard":
            return box, timedelta(days=1)
        up = 2 if grade == "easy" else 1
        new_box = min(cls.MAX_BOX, box + up)
        return new_box, timedelta(days=cls.INTERVAL_DAYS[new_box])

    def record(self, grade):
        # Older app versions send known=true/false.
        if grade is True:
            grade = "good"
        elif grade is False:
            grade = "again"
        if grade not in self.GRADES:
            grade = "good"
        self.box, wait = self.next_step(self.box, grade)
        now = timezone.now()
        self.due_at = now + wait
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
    # The questions as they were when the exam started (stem, choices with ids and the right one, explanations), so
    # editing the content later changes neither the grading nor the report card of this exam.
    snapshot = models.JSONField(default=dict, blank=True)

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
    # «شک‌دار»: the learner marked it during the exam as not sure; such questions come back in the chapter reviews.
    is_doubtful = models.BooleanField(default=False)

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


class MistakeNote(models.Model):
    """Why the learner got a question wrong (their own pick, optional), for the mistakes notebook."""

    class Reason(models.TextChoices):
        UNKNOWN = "unknown", "بلد نبودم"
        FORGOT = "forgot", "فراموش کردم"
        CARELESS = "careless", "بی‌دقتی"
        TIME = "time", "کمبود وقت"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mistake_notes")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=10, choices=Reason.choices, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "علت اشتباه"
        verbose_name_plural = "علت‌های اشتباه"
        unique_together = [("user", "question")]


class ChapterReview(models.Model):
    """«چرخه‌ی مرور فصل» for one learner and one finished chapter: which step it is at and when the next review is due.
    Steps (gap after the previous one): 1 day, 7 days, 30 days, then every ~75 days; a weak result brings it back sooner."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chapter_reviews")
    chapter = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    finished_at = models.DateTimeField("فصل تمام شد")
    finished_by = models.CharField(max_length=10, default="auto")  # auto | button
    stage = models.PositiveSmallIntegerField(default=0)
    due_on = models.DateField()
    last_done_at = models.DateTimeField(null=True, blank=True)
    last_score = models.FloatField(null=True, blank=True)
    done_count = models.PositiveSmallIntegerField(default=0)
    # Questions served in the last review, so the next one asks others (a wrong one may come back).
    last_served = models.JSONField(default=list, blank=True)
    is_archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = "مرور فصل"
        verbose_name_plural = "مرورهای فصل"
        unique_together = [("user", "chapter")]


class BookReview(models.Model):
    """«مرور ترکیبی کتاب»: a weekly review mixing every finished chapter of one book (from two finished chapters on)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="book_reviews")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    due_on = models.DateField()
    last_done_at = models.DateTimeField(null=True, blank=True)
    last_score = models.FloatField(null=True, blank=True)
    done_count = models.PositiveSmallIntegerField(default=0)
    last_served = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "مرور ترکیبی کتاب"
        verbose_name_plural = "مرورهای ترکیبی کتاب"
        unique_together = [("user", "book")]


class ReviewSession(models.Model):
    """One sitting of a chapter or book review. Answers go through the normal practice answer (so the mistakes notebook
    and statistics see them); the session only remembers which questions it served. The one-month step is an exam."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="review_sessions")
    chapter_review = models.ForeignKey(ChapterReview, on_delete=models.CASCADE, null=True, blank=True, related_name="sessions")
    book_review = models.ForeignKey(BookReview, on_delete=models.CASCADE, null=True, blank=True, related_name="sessions")
    stage = models.PositiveSmallIntegerField(default=0)
    minimum = models.PositiveSmallIntegerField(default=5)
    served = models.JSONField(default=list, blank=True)
    exam = models.OneToOneField(ExamAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="review_session")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    score = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = "نوبت مرور"
        verbose_name_plural = "نوبت‌های مرور"
        ordering = ["-started_at"]


class FlashcardReviewOp(models.Model):
    """Every review id the app sent for a card, so a review re-sent after a dropped connection counts once however many
    other reviews came in between. Old ones (a month) are cleared by the nightly clean-up; a resend never waits that long."""

    review = models.ForeignKey(FlashcardReview, on_delete=models.CASCADE, related_name="ops")
    op = models.CharField(max_length=40)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("review", "op")]
        indexes = [models.Index(fields=["created_at"])]



class StudyTime(models.Model):
    """Seconds a learner spent in the app on one section (or chapter, for an exam) on one day, by activity. Stored
    exactly; only what is shown is rounded, so nothing is lost by rounding. Counted only while the screen is open and
    the learner is active (no touch or scroll for two minutes stops the count)."""

    class Kind(models.TextChoices):
        READ = "read", "جزوه"
        QUIZ = "quiz", "تست"
        CARDS = "cards", "فلش‌کارت"
        EXAM = "exam", "آزمون"
        REVIEW = "review", "مرور"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_times")
    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="+")
    day = models.DateField()
    kind = models.CharField(max_length=10, choices=Kind.choices)
    seconds = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "زمان مطالعه"
        verbose_name_plural = "زمان مطالعه"
        unique_together = [("user", "node", "day", "kind")]
        indexes = [models.Index(fields=["user", "day"]), models.Index(fields=["book", "user"])]
