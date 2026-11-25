from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import ContentNode


class ExamSource(models.Model):
    """An official exam a question appeared in, e.g. Master's entrance exam 1401."""

    name = models.CharField("نام آزمون", max_length=120)
    year = models.PositiveSmallIntegerField("سال (شمسی)")
    group = models.CharField("گروه/رشته", max_length=120, blank=True)
    booklet = models.CharField("دفترچه", max_length=60, blank=True)

    class Meta:
        verbose_name = "منبع تست"
        verbose_name_plural = "منابع تست‌ها"
        ordering = ["-year", "name"]
        unique_together = [("name", "year", "group", "booklet")]

    def __str__(self):
        return f"{self.name} {self.year}" if self.year else self.name


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
    # «تازه»: when it was added (empty for cards older than this field); «به‌روز شده»: the panel's «مطلب تازه».
    added_at = models.DateTimeField("زمان افزوده شدن", null=True, blank=True, default=timezone.now, editable=False)
    refreshed_at = models.DateTimeField("به‌روزرسانی مهم", null=True, blank=True, editable=False)

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
    # Old fields, copied into «solutions» by migration 0011 and no longer used (kept so the migration can be undone).
    quick_solution = models.TextField("راه‌حل سریع (قدیمی)", blank=True, editable=False)
    alternative_view = models.TextField("زاویه‌ی دیگر (قدیمی)", blank=True, editable=False)
    # Any number of extra solutions, each with the title the panel gives it: [{"title": "راه‌حل تستی", "body": "…"}].
    solutions = models.JSONField("راه‌حل‌ها", default=list, blank=True)
    difficulty = models.CharField("سطح اعلام‌شده", max_length=10, choices=Difficulty.choices)
    domain = models.CharField("حوزه", max_length=12, choices=Domain.choices, blank=True)
    kind = models.CharField("نوع", max_length=10, choices=Kind.choices, blank=True)
    estimated_seconds = models.PositiveSmallIntegerField("زمان تخمینی (ثانیه)", null=True, blank=True)
    order = models.PositiveIntegerField("ترتیب در بخش", default=0)
    is_original = models.BooleanField("تألیفی", default=False)
    sources = models.ManyToManyField(ExamSource, through="QuestionSource", blank=True, verbose_name="منابع تست‌ها")
    flashcards = models.ManyToManyField(Flashcard, blank=True, related_name="questions", verbose_name="فلش‌کارت‌های مرتبط")
    # «مشابه:» in the file: the same test that came back in another exam with a change. One way (the file that says it);
    # the app shows both ways (similar_to and similar_from).
    similar_to = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="similar_from", verbose_name="تست‌های مشابه")
    # Set in the panel, not in the file: up to ten per book may be shared as an image from the app.
    is_sample = models.BooleanField("نمونه‌ی قابل اشتراک", default=False)
    # «ترتیب گزینه‌ها: ثابت» in the file: the app never shuffles these choices (e.g. «گزینه‌های ۱ و ۳»).
    fixed_order = models.BooleanField("ترتیب گزینه‌ها ثابت", default=False)
    # «تست تکمیلی»: in the chapter's question bank (more practice, exams, reviews), not among the section's own tests,
    # so it never counts toward the section's progress circle.
    is_extra = models.BooleanField("تست تکمیلی", default=False, help_text="در بانک تست؛ در دایره‌ی پیشرفت بخش حساب نمی‌شود.")
    # Set by the importer when the right choice moves to another choice: the app shows «اصلاح‌شده».
    key_changed_at = models.DateTimeField("تاریخ اصلاح پاسخ‌نامه", null=True, blank=True, editable=False)
    added_at = models.DateTimeField("زمان افزوده شدن", null=True, blank=True, default=timezone.now, editable=False)
    refreshed_at = models.DateTimeField("به‌روزرسانی مهم", null=True, blank=True, editable=False)
    key_change_note = models.CharField("شرح اصلاح پاسخ‌نامه", max_length=400, blank=True, editable=False)
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
    def keeps_order(self) -> bool:
        """True if the app must show the choices as written (set in the file, or a choice refers to other choices)."""
        from .order import refers_to_choices

        return self.fixed_order or refers_to_choices(c.text for c in self.choices.all())

    def correction(self) -> dict | None:
        if not self.key_changed_at:
            return None
        return {"at": self.key_changed_at, "note": self.key_change_note}

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
        WRONG_ANSWER = "wrong_answer", "جواب یا مطلب نادرست"
        EXPLANATION = "explanation", "پاسخ تشریحی نادرست"
        FORMULA = "formula", "فرمول نادرست"
        UNCLEAR = "unclear", "مبهم"
        TYPO = "typo", "غلط تایپی"
        TRANSLATION = "translation", "ترجمه‌ی نادرست"
        IMAGE = "image", "عکس یا نمودار نادرست"
        OTHER = "other", "سایر"

    class Status(models.TextChoices):
        OPEN = "open", "گزارش داده شد"
        FIXED = "fixed", "اصلاح شد"
        REJECTED = "rejected", "بررسی شد، درست بود"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports", verbose_name="کاربر")
    question = models.ForeignKey(Question, on_delete=models.CASCADE, null=True, blank=True, related_name="reports", verbose_name="تست")
    flashcard = models.ForeignKey(Flashcard, on_delete=models.CASCADE, null=True, blank=True, related_name="reports", verbose_name="فلش‌کارت")
    node = models.ForeignKey(ContentNode, on_delete=models.CASCADE, null=True, blank=True, related_name="reports", verbose_name="بخش")
    reason = models.CharField("دلیل", max_length=20, choices=Reason.choices)
    note = models.TextField("توضیح", blank=True)
    # A report on the lesson text is made by selecting the words (or holding a picture): what was selected, in which
    # mode (notes or summary) and in which box («تعریف»، «لاتین › ترجمه»، «عکس»…).
    quote = models.TextField("متن انتخاب‌شده", blank=True)
    mode = models.CharField("حالت", max_length=10, blank=True, choices=[("full", "درسنامه"), ("summary", "چکیده")])
    box = models.CharField("کادر", max_length=80, blank=True)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="زمان")
    resolved_at = models.DateTimeField(null=True, blank=True)
    # When the learner was told «اصلاح شد، ممنون» in the app (once).
    thanked_at = models.DateTimeField(null=True, blank=True)

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
    review_session = models.ForeignKey(
        "study.ReviewSession", null=True, blank=True, on_delete=models.SET_NULL, related_name="quiz_answers"
    )

    class Meta:
        verbose_name = "پاسخ"
        verbose_name_plural = "پاسخ‌ها"
        indexes = [models.Index(fields=["user", "question"])]
        constraints = [
            models.UniqueConstraint(
                fields=["review_session", "question"],
                condition=models.Q(review_session__isnull=False),
                name="unique_answer_per_review_question",
            )
        ]
