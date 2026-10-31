from django.db import models
from treebeard.mp_tree import MP_Node


class Major(models.Model):
    """A field of study, e.g. Economics. Each major is its own space in the app."""

    name = models.CharField("نام", max_length=80)
    slug = models.SlugField("شناسه", unique=True)
    color = models.CharField("رنگ", max_length=7, default="#4A54C9")
    is_coming_soon = models.BooleanField("به‌زودی", default=False)
    order = models.PositiveSmallIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "رشته"
        verbose_name_plural = "رشته‌ها"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class ContentNode(MP_Node):
    """
    The content tree: book › chapter › section › … to any depth.
    A book can belong to several majors (shared books are made once).
    """

    class Kind(models.TextChoices):
        BOOK = "book", "کتاب"
        CHAPTER = "chapter", "فصل"
        SECTION = "section", "بخش"

    kind = models.CharField("نوع", max_length=10, choices=Kind.choices)
    title = models.CharField("عنوان", max_length=200)
    slug = models.SlugField("شناسه‌ی ثابت", max_length=120, allow_unicode=True, blank=True, db_index=True,
                            help_text="از فایل محتوا می‌آید؛ برای به‌روزرسانی بدون از دست رفتن داده‌ی کاربران")
    majors = models.ManyToManyField(Major, blank=True, related_name="books", verbose_name="رشته‌ها")
    summary_body = models.TextField("متن خلاصه (Markdown)", blank=True)
    full_body = models.TextField("متن جزوه (Markdown)", blank=True)
    is_free = models.BooleanField("رایگان", default=False, help_text="برای نمونه‌ی رایگان از کتاب پولی")
    position = models.PositiveSmallIntegerField("شماره‌ی فصل", null=True, blank=True)
    group = models.CharField("گروه", max_length=120, blank=True, help_text="سرتیتر گروه بخش‌ها در فهرست کتاب (از خط «# ...» در فایل فصل)")
    price = models.PositiveIntegerField("قیمت (تومان)", null=True, blank=True, help_text="فقط برای کتاب")
    is_published = models.BooleanField("منتشر شده", default=False)
    is_archived = models.BooleanField("بایگانی", default=False, help_text="به‌جای حذف؛ داده‌ی کاربران حفظ می‌شود")
    updated_at = models.DateTimeField(auto_now=True)

    node_order_by = None

    class Meta:
        verbose_name = "محتوا"
        verbose_name_plural = "محتوا (کتاب، فصل، بخش)"

    def __str__(self):
        return self.title

    def book(self):
        return self if self.kind == self.Kind.BOOK else self.get_ancestors().filter(kind=self.Kind.BOOK).first()

    def is_accessible_free(self) -> bool:
        """Free if this node or any ancestor is marked free."""
        return self.is_free or self.get_ancestors().filter(is_free=True).exists()


class Banner(models.Model):
    title = models.CharField("عنوان", max_length=120)
    subtitle = models.CharField("زیرعنوان", max_length=160, blank=True)
    image = models.ImageField("تصویر", upload_to="banners/", blank=True, help_text="اختیاری؛ ۱۲۰۰ در ۶۰۰ پیکسل (نسبت ۲ به ۱). بدون عکس، کارت متنی لیمویی نشان داده می‌شود.")
    class Target(models.TextChoices):
        NONE = "", "بدون لینک"
        BOOK = "book", "صفحه‌ی یک کتاب"
        BUY = "buy", "خرید کتاب یا اشتراک"
        REVIEW = "review", "مرور امروز (فلش‌کارت‌ها)"
        EXAM = "exam", "آزمون یک فصل"
        URL = "url", "لینک بیرونی (سایت)"

    target = models.CharField("مقصد", max_length=10, choices=Target.choices, blank=True, default="")
    target_value = models.CharField(
        "شناسه یا آدرس مقصد",
        max_length=300,
        blank=True,
        help_text="کتاب و خرید: شناسه‌ی کتاب (مثلاً bushberg). آزمون: شماره‌ی فصل در پنل. لینک بیرونی: آدرس کامل با https. مرور امروز: خالی.",
    )
    link = models.CharField("لینک (قدیمی)", max_length=300, blank=True, help_text="فقط اگر «مقصد» خالی است؛ آدرس سایت یا book/شناسه")
    majors = models.ManyToManyField(Major, blank=True, verbose_name="رشته‌های هدف", help_text="خالی یعنی همه")
    starts_at = models.DateTimeField("شروع", null=True, blank=True)
    ends_at = models.DateTimeField("پایان", null=True, blank=True)
    priority = models.PositiveSmallIntegerField("اولویت", default=0)
    is_active = models.BooleanField("فعال", default=True)
    impressions = models.PositiveIntegerField("نمایش", default=0, editable=False)
    clicks = models.PositiveIntegerField("کلیک", default=0, editable=False)

    def resolved_link(self) -> str:
        """The address the app opens: book/<slug>, buy/<slug>, review, exam/<id> or an https URL."""
        value = self.target_value.strip()
        if self.target == self.Target.URL:
            return value if value.startswith(("http://", "https://")) else ""
        if self.target in (self.Target.BOOK, self.Target.BUY, self.Target.EXAM):
            return f"{self.target}/{value}" if value else ""
        if self.target == self.Target.REVIEW:
            return "review"
        return self.link

    class Meta:
        verbose_name = "بنر"
        verbose_name_plural = "بنرها"
        ordering = ["-priority", "-id"]

    def __str__(self):
        return self.title
