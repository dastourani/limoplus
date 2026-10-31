from django.conf import settings
from django.db import models

from apps.catalog.models import ContentNode


class ExamSource(models.Model):
    """An official exam a question appeared in, e.g. Master's entrance exam 1401."""

    name = models.CharField("نام آزمون", max_length=120)
    year = models.PositiveSmallIntegerField("سال (شمسی)")
    group = models.CharField("گروه/رشته", max_length=120, blank=True)
    booklet = models.CharField("دفترچه", max_length=60, blank=True)

    class Meta:
        verbose_name = "منبع کنکور"
        verbose_name_plural = "منابع کنکور"
        ordering = ["-year", "name"]
        unique_together = [("name", "year", "group", "booklet")]

    def __str__(self):
        return f"{self.name} {self.year}"


class Flashcard(models.Model):
    """A key point, not a question: a short title on the front, the point on the back."""

    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="flashcards", verbose_name="بخش")
    slug = models.SlugField("شناسه در فایل محتوا", max_length=120, allow_unicode=True)
    title = models.CharField("عنوان (رو)", max_length=160)
    point = models.TextField("نکته (پشت)")
    formula = models.CharField("فرمول (LaTeX)", max_length=300, blank=True)
    order = models.PositiveIntegerField("ترتیب در بخش", default=0)
    is_free = models.BooleanField("رایگان", default=False)
    is_archived = models.BooleanField("بایگانی", default=False)

    class Meta:
        verbose_name = "فلش‌کارت"
        verbose_name_plural = "فلش‌کارت‌ها"
        unique_together = [("node", "slug")]

    def __str__(self):
        return self.title


class Question(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "easy", "آسان"
        MEDIUM = "medium", "متوسط"
        HARD = "hard", "سخت"

    class Domain(models.TextChoices):
        GENERAL = "general", "عمومی رشته"
        SPECIALIZED = "specialized", "تخصصی"

    class Kind(models.TextChoices):
        RECALL = "recall", "حفظی"
        CONCEPT = "concept", "مفهومی"
        CALC = "calc", "محاسباتی"
        ANALYSIS = "analysis", "تحلیلی"

    node = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="questions", verbose_name="بخش")
    slug = models.SlugField("شناسه در فایل محتوا", max_length=120, allow_unicode=True)
    stem = models.TextField("صورت سؤال (Markdown)")
    explanation = models.TextField("پاسخ تشریحی")
    quick_solution = models.TextField("راه‌حل سریع (تستی)", blank=True)
    alternative_view = models.TextField("زاویه‌ی دیگر", blank=True)
    difficulty = models.CharField("سطح اعلام‌شده", max_length=10, choices=Difficulty.choices)
    domain = models.CharField("حوزه", max_length=12, choices=Domain.choices, blank=True)
    kind = models.CharField("نوع", max_length=10, choices=Kind.choices, blank=True)
    estimated_seconds = models.PositiveSmallIntegerField("زمان تخمینی (ثانیه)", null=True, blank=True)
    order = models.PositiveIntegerField("ترتیب در بخش", default=0)
    is_original = models.BooleanField("تألیفی", default=False)
    sources = models.ManyToManyField(ExamSource, through="QuestionSource", blank=True, verbose_name="منابع کنکور")
    flashcards = models.ManyToManyField(Flashcard, blank=True, related_name="questions", verbose_name="فلش‌کارت‌های مرتبط")
    is_free = models.BooleanField("رایگان", default=False)
    is_archived = models.BooleanField("بایگانی", default=False)
    # Filled by the system from real answers (after enough attempts).
    answer_count = models.PositiveIntegerField(default=0, editable=False)
    correct_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        verbose_name = "تست"
        verbose_name_plural = "تست‌ها"
        unique_together = [("node", "slug")]

    def __str__(self):
        return self.stem[:60]

    @property
    def measured_difficulty(self):
        """Share of correct answers, once at least 30 people answered."""
        if self.answer_count < 30:
            return None
        return self.correct_count / self.answer_count


class QuestionSource(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    source = models.ForeignKey(ExamSource, on_delete=models.PROTECT)
    number = models.PositiveSmallIntegerField("شماره سؤال", null=True, blank=True)

    class Meta:
        verbose_name = "منبع سؤال"
        verbose_name_plural = "منابع سؤال"
        unique_together = [("question", "source")]


class Choice(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="choices")
    text = models.TextField("متن گزینه")
    is_correct = models.BooleanField("درست", default=False)
    order = models.PositiveSmallIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "گزینه"
        verbose_name_plural = "گزینه‌ها"
        ordering = ["order"]

    def __str__(self):
        return self.text[:40]


class Report(models.Model):
    """A learner's report of a mistake in a question, flashcard or text."""

    class Reason(models.TextChoices):
        WRONG_ANSWER = "wrong_answer", "جواب غلط"
        FORMULA = "formula", "فرمول نادرست"
        UNCLEAR = "unclear", "مبهم"
        TYPO = "typo", "غلط تایپی"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        OPEN = "open", "گزارش داده شد"
        FIXED = "fixed", "اصلاح شد"
        REJECTED = "rejected", "بررسی شد، درست بود"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    flashcard = models.ForeignKey(Flashcard, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    node = models.ForeignKey(ContentNode, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    reason = models.CharField("دلیل", max_length=20, choices=Reason.choices)
    note = models.TextField("توضیح", blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "گزارش ایراد"
        verbose_name_plural = "گزارش‌های ایراد"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(question__isnull=False, flashcard__isnull=True, node__isnull=True)
                    | models.Q(question__isnull=True, flashcard__isnull=False, node__isnull=True)
                    | models.Q(question__isnull=True, flashcard__isnull=True, node__isnull=False)
                ),
                name="report_has_exactly_one_target",
            ),
            models.UniqueConstraint(fields=["user", "question"], condition=models.Q(question__isnull=False), name="one_report_per_question"),
            models.UniqueConstraint(fields=["user", "flashcard"], condition=models.Q(flashcard__isnull=False), name="one_report_per_flashcard"),
        ]


class QuizAnswer(models.Model):
    """One answer by a signed-in learner. Stores a snapshot, so later content edits never change history."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quiz_answers")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="answers")
    choice_order = models.PositiveSmallIntegerField()
    was_correct = models.BooleanField()
    answered_at = models.DateTimeField(auto_now_add=True)
    # "Start the tests again" archives earlier answers for practice; history and statistics keep them.
    is_archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = "پاسخ"
        verbose_name_plural = "پاسخ‌ها"
        indexes = [models.Index(fields=["user", "question"])]
