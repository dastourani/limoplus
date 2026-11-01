from django.conf import settings
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
    # Book only.
    author = models.CharField("نویسنده", max_length=200, blank=True)
    edition = models.CharField("ویرایش", max_length=80, blank=True, help_text="مثلاً «ویرایش چهارم»")
    cover = models.ImageField(
        "عکس جلد", upload_to="covers/", blank=True, help_text="عمودی، ۸۰۰ در ۱۲۰۰ پیکسل (نسبت ۲ به ۳)؛ بدون عکس، جلد لیمویی نشان داده می‌شود."
    )
    about = models.TextField("درباره‌ی کتاب (Markdown)", blank=True)
    title_en = models.CharField("نام انگلیسی", max_length=200, blank=True, help_text="روی جلد، زیر نام کتاب؛ مثلاً Medical Imaging")

    class Motif(models.TextChoices):
        CT = "ct", "حلقه‌ی CT و مقیاس هانسفیلد (تصویربرداری)"
        BRAIN = "brain", "نیم‌رخ مغز (نوروآناتومی)"
        AP = "ap", "پتانسیل عمل (نوروفیزیولوژی)"
        NEURON = "neuron", "نورون (علوم اعصاب)"
        PIXELS = "pixels", "پیکسل و پنجره‌ی ۳×۳ (پردازش تصویر)"
        SYSTEM = "system", "ورودی، h(t)، خروجی (سیگنال‌ها و سیستم‌ها)"
        FOURIER = "fourier", "سری فوریه (ریاضی مهندسی)"
        WORDS = "words", "ریشه‌ی واژه‌ها (زبان تخصصی)"
        CALCULUS = "calculus", "مشتق و انتگرال (ریاضی عمومی ۱، حسابان)"
        SURFACE = "surface", "رویه‌ی سه‌بعدی (ریاضی عمومی ۲، توابع چندمتغیره)"
        SLOPEFIELD = "slopefield", "میدان شیب (معادلات دیفرانسیل)"
        VECTORS = "vectors", "بردارها (جبر خطی، مکانیک)"
        NEWTON = "newton", "روش نیوتن (محاسبات عددی، آنالیز عددی)"
        CONTOUR = "contour", "منحنی‌های تراز و کمینه (بهینه‌سازی)"
        SIMPLEX = "simplex", "ناحیه‌ی شدنی (تحقیق در عملیات، برنامه‌ریزی خطی)"
        GRAPH = "graph", "گراف (ریاضیات گسسته، ساختمان داده، الگوریتم)"
        COMPLEX = "complex", "صفحه‌ی مختلط (متغیرهای مختلط)"
        BELL = "bell", "منحنی زنگوله‌ای (آمار و احتمال)"
        SURVIVAL = "survival", "منحنی بقا (آمار حیاتی، اپیدمیولوژی)"
        REGRESSION = "regression", "رگرسیون (آمار، روش تحقیق، اقتصادسنجی)"
        PROJECTILE = "projectile", "پرتابه (فیزیک ۱، مکانیک)"
        ATOM = "atom", "اتم (فیزیک، فیزیک پزشکی، فیزیک هسته‌ای)"
        MOLECULE = "molecule", "مولکول (شیمی عمومی و آلی)"
        DNA = "dna", "مارپیچ DNA (بیوشیمی، ژنتیک، زیست مولکولی)"
        ECG = "ecg", "نوار قلب (فیزیولوژی، سیگنال‌های حیاتی)"
        HEART = "heart", "قلب (آناتومی، قلب و عروق)"
        FEEDBACK = "feedback", "حلقه‌ی بازخورد (کنترل خطی، سیستم‌های کنترل)"
        CIRCUIT = "circuit", "مدار RLC (مدار الکتریکی، الکترونیک)"
        MRI = "mri", "اسپین و میدان (MRI، تشدید مغناطیسی)"
        ULTRASOUND = "ultrasound", "موج و پژواک (سونوگرافی، آکوستیک)"
        BIOMECH = "biomech", "اهرم بازو (بیومکانیک)"
        NETWORK = "network", "شبکه‌ی عصبی (هوش مصنوعی، یادگیری ماشین)"
        MICROSCOPE = "microscope", "میکروسکوپ (بافت‌شناسی، پاتولوژی، سلولی)"
        MICROBE = "microbe", "ویروس و آنتی‌بادی (میکروب‌شناسی، ایمنی‌شناسی)"
        DOSE = "dose", "منحنی دوز و پاسخ (فارماکولوژی)"
        CODE = "code", "آکولاد کد (برنامه‌نویسی، کامپیوتر)"
        BOOK = "book", "کتاب باز (هر درس دیگر)"
        CUSTOM = "custom", "طرح سفارشی (فایل SVG خودتان)"

    cover_motif = models.CharField("نقش جلد", max_length=20, choices=Motif.choices, default=Motif.CT,
                                   help_text="نقش خطی وسط جلد؛ بقیه‌ی جلد (رنگ، نام، نویسنده) خودکار است. اگر «عکس جلد» بگذارید، عکس به‌جای این جلد نشان داده می‌شود.")
    cover_drawing = models.TextField("طرح سفارشی جلد", blank=True, editable=False, help_text="طرح خطی پاک‌سازی‌شده‌ی یک فایل SVG")
    is_coming_soon = models.BooleanField("به‌زودی", default=False, help_text="کتاب با جلد کم‌رنگ و دکمه‌ی «خبرم کن» در قفسه دیده می‌شود ولی باز نمی‌شود.")
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


class Book(ContentNode):
    """Books only (the top of the content tree), for the panel's «کتاب‌ها» page."""

    class Meta:
        proxy = True
        verbose_name = "کتاب"
        verbose_name_plural = "کتاب‌ها"


class Section(ContentNode):
    """Sections only, for searching and filtering notes and summaries in the panel."""

    class Meta:
        proxy = True
        verbose_name = "بخش (جزوه و خلاصه)"
        verbose_name_plural = "بخش‌ها (جزوه و خلاصه)"


class BookWaitlist(models.Model):
    """«خبرم کن»: a learner wants to know when a coming-soon book opens."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="book_waits", verbose_name="کاربر")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="waitlist", verbose_name="کتاب")
    is_active = models.BooleanField("فعال", default=True)
    # One change of mind is allowed: after cancelling once and asking again, the request stays on.
    cancel_count = models.PositiveSmallIntegerField("دفعات لغو", default=0)
    created_at = models.DateTimeField("زمان", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def can_cancel(self) -> bool:
        return self.is_active and self.cancel_count == 0

    class Meta:
        verbose_name = "درخواست «خبرم کن»"
        verbose_name_plural = "درخواست‌های «خبرم کن»"
        unique_together = [("user", "book")]


class ChapterRevision(models.Model):
    """A saved copy of a whole chapter as a chapter.md text, taken after every change from the panel or a file."""

    class Source(models.TextChoices):
        PANEL = "panel", "ویرایش در پنل"
        FILE = "file", "بارگذاری فایل"
        RESTORE = "restore", "بازگرداندن نسخه"

    chapter = models.ForeignKey(ContentNode, on_delete=models.CASCADE, related_name="revisions", verbose_name="فصل")
    text = models.TextField("متن فصل")
    source = models.CharField("منشأ", max_length=10, choices=Source.choices)
    note = models.CharField("توضیح", max_length=300, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="کاربر")
    created_at = models.DateTimeField("زمان", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "نسخه‌ی فصل"
        verbose_name_plural = "نسخه‌های فصل"
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.chapter.title} ({self.get_source_display()})"


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
