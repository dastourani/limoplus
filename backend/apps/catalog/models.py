import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
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
    # «صندوق تست»: one hidden book where new tests wait before they are moved to their sections (apps/catalog/inbox.py).
    # Never shown in the app, whatever its other fields say.
    is_inbox = models.BooleanField("صندوق تست", default=False, editable=False)
    # Sent with «معرفی به دوست» on the book page (a channel, a download page, later the book's page on the site).
    share_link = models.URLField("لینک اشتراک", blank=True, help_text="با دکمه‌ی اشتراک صفحه‌ی کتاب فرستاده می‌شود. خالی: لینک پیش‌فرض (تنظیمات اشتراک).")
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
    release_estimate = models.CharField(
        "زمان حدودی انتشار",
        max_length=80,
        blank=True,
        help_text="اختیاری؛ مثلاً «آذر ۱۴۰۵» یا «نیمسال دوم ۱۴۰۵». کنار دکمه‌ی «خبرم کن» در سایت و اپ نشان داده می‌شود.",
    )
    is_published = models.BooleanField("منتشر شده", default=False)
    is_archived = models.BooleanField("بایگانی", default=False, help_text="به‌جای حذف؛ داده‌ی کاربران حفظ می‌شود")
    updated_at = models.DateTimeField(auto_now=True)
    # «مطلب تازه»: the last time the panel marked this text as worth a second look («به‌روز شده» in the app).
    refreshed_at = models.DateTimeField("به‌روزرسانی مهم", null=True, blank=True, editable=False)

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
    # «خبر دادن به منتظران» in the panel (catalog/waitlist_sms.py): queued, then one SMS, never a second.
    notify_queued_at = models.DateTimeField("در صف پیامک", null=True, blank=True, editable=False)
    notified_at = models.DateTimeField("پیامک خبر فرستاده شد", null=True, blank=True, editable=False)
    notify_error = models.CharField("خطای پیامک", max_length=200, blank=True, editable=False)
    notify_text = models.CharField("متن پیامک خبر", max_length=300, blank=True, editable=False)

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
    updated_at = models.DateTimeField(auto_now=True, verbose_name="زمان")

    class Meta:
        verbose_name = "نسخه‌ی فصل"
        verbose_name_plural = "نسخه‌های فصل"
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.chapter.title} ({self.get_source_display()})"


class Banner(models.Model):
    class Template(models.TextChoices):
        LEMON = "lemon", "ساده با برش لیمو"
        SALE = "sale", "تخفیف و اشتراک (با شمارش معکوس)"
        BOOK = "book", "کتاب تازه (با جلد همان کتاب)"
        EXAM = "exam", "یادآوری و کنکور (با نقش درس)"

    title = models.CharField("عنوان", max_length=120)
    subtitle = models.CharField("زیرعنوان", max_length=160, blank=True)
    template = models.CharField("قالب", max_length=10, choices=Template.choices, default=Template.LEMON,
                                help_text="بنر از روی قالب کشیده می‌شود (مثل جلدها)؛ اگر «تصویر» بگذارید، عکس جای قالب را می‌گیرد.")
    button = models.CharField("متن دکمه", max_length=30, blank=True, help_text="مثلاً «همین حالا بخر»؛ خالی یعنی بدون دکمه")
    motif = models.CharField("نقش (قالب یادآوری)", max_length=20, blank=True, help_text="یکی از نقش‌های جلد؛ خالی یعنی «کتاب باز»")
    countdown = models.BooleanField("شمارش معکوس تا «پایان»", default=False,
                                    help_text="روی بنر می‌نویسد چقدر مانده؛ در ۲۴ ساعت آخر ساعت زنده. «پایان» را پر کنید.")
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
    majors = models.ManyToManyField(Major, blank=True, verbose_name="رشته‌های هدف (قدیمی)", help_text="دیگر استفاده نمی‌شود")
    audience_book = models.ForeignKey(
        "ContentNode", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="فقط برای خوانندگان این کتاب",
        limit_choices_to={"kind": "book", "depth": 1}, help_text="خالی یعنی همه. پر باشد: فقط کسانی که این کتاب را می‌خوانند بنر را می‌بینند.",
    )
    starts_at = models.DateTimeField("شروع", null=True, blank=True)
    ends_at = models.DateTimeField("پایان", null=True, blank=True)
    sale_campaign = models.OneToOneField(
        "commerce.SaleCampaign",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="banner",
        verbose_name="کمپین تخفیف زمان‌دار",
        help_text="برای بنر تخفیف، از کمپین‌های زمان‌دار استفاده کنید؛ بازه و قیمت از همان کمپین خوانده می‌شود.",
    )
    priority = models.PositiveSmallIntegerField("اولویت", default=0)
    is_active = models.BooleanField("فعال", default=True)
    impressions = models.PositiveIntegerField("نمایش", default=0, editable=False)
    clicks = models.PositiveIntegerField("کلیک", default=0, editable=False)

    def clean(self):
        super().clean()
        linked = bool(self.sale_campaign_id or self._state.fields_cache.get("sale_campaign"))
        is_sale_template = self.template == self.Template.SALE
        if linked != is_sale_template:
            raise ValidationError({
                "template": "بنر تخفیف فقط باید از کمپین متصل استفاده کند؛ قالب تخفیفِ مستقل یا بنر کمپین با قالب دیگر مجاز نیست."
            })

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

    @classmethod
    def visible_at(cls, now=None):
        """Active editorial banners use their own window; a discount banner always follows its campaign's window."""
        now = now or timezone.now()
        regular_window = (
            models.Q(sale_campaign__isnull=True)
            & (models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=now))
            & (models.Q(ends_at__isnull=True) | models.Q(ends_at__gte=now))
        )
        campaign_window = models.Q(
            sale_campaign__is_active=True,
            sale_campaign__starts_at__lte=now,
            sale_campaign__ends_at__gt=now,
        ) & (
            models.Q(
                sale_campaign__book__kind=ContentNode.Kind.BOOK,
                sale_campaign__book__depth=1,
                sale_campaign__book__is_published=True,
                sale_campaign__book__is_archived=False,
                sale_campaign__book__is_free=False,
                sale_campaign__book__is_inbox=False,
                sale_campaign__book__is_coming_soon=False,
                sale_campaign__book__price__gt=models.F("sale_campaign__discounted_price"),
            )
            | models.Q(
                sale_campaign__plan__scope="all",
                sale_campaign__plan__is_active=True,
                sale_campaign__plan__price__gt=models.F("sale_campaign__discounted_price"),
            )
        )
        return (
            cls.objects.filter(is_active=True)
            .filter(regular_window | campaign_window)
            .select_related("sale_campaign", "sale_campaign__book", "sale_campaign__plan")
        )

    class Meta:
        verbose_name = "بنر"
        verbose_name_plural = "بنرها"
        ordering = ["-priority", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(template="sale", sale_campaign__isnull=False)
                    | (~models.Q(template="sale") & models.Q(sale_campaign__isnull=True))
                ),
                name="sale_banner_campaign_consistent",
            )
        ]

    def __str__(self):
        return self.title


class Shelf(models.Model):
    """«قفسه»: one horizontal row of books on the home page, named by subject (e.g. ریاضی). Made and ordered in the panel.
    A book may sit on several shelves. Published books on no shelf appear in a last row, so none is ever hidden."""

    title = models.CharField("نام قفسه", max_length=80)
    order = models.PositiveSmallIntegerField("ترتیب", default=0)
    is_active = models.BooleanField("نمایش در اپ", default=True)

    class Meta:
        verbose_name = "قفسه"
        verbose_name_plural = "قفسه‌ها"
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class ShelfBook(models.Model):
    shelf = models.ForeignKey(Shelf, on_delete=models.CASCADE, related_name="items")
    book = models.ForeignKey(ContentNode, on_delete=models.CASCADE, related_name="shelf_items", verbose_name="کتاب",
                             limit_choices_to={"kind": "book", "depth": 1})
    order = models.PositiveSmallIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "کتاب قفسه"
        verbose_name_plural = "کتاب‌های قفسه"
        ordering = ["order", "id"]
        unique_together = [("shelf", "book")]

    def __str__(self):
        return self.book.title



class CleanupRun(models.Model):
    """One run of the nightly clean-up (temporary data, old chapter versions, unused pictures). The panel's «فضای سرور»
    page lists them. Learners' data is never touched."""

    at = models.DateTimeField("زمان", auto_now_add=True)
    summary = models.JSONField("نتیجه", default=dict)

    class Meta:
        verbose_name = "فضای سرور"
        verbose_name_plural = "فضای سرور"
        ordering = ["-at"]


class BackupRun(models.Model):
    """One backup: the database (nightly) or the pictures and files added since the last one (weekly), kept on the
    server's disk and sent to the admin's chat in Bale. The panel's «فضای سرور» page lists them."""

    class Kind(models.TextChoices):
        DB = "db", "پایگاه داده"
        MEDIA = "media", "عکس‌ها و فایل‌ها"

    kind = models.CharField("نوع", max_length=10, choices=Kind.choices)
    at = models.DateTimeField("زمان", auto_now_add=True)
    ok = models.BooleanField("موفق", default=False)
    files = models.JSONField("فایل‌ها", default=list, help_text="نام فایل‌های ساخته‌شده")
    size = models.BigIntegerField("حجم", default=0)
    sent = models.BooleanField("فرستاده شد", default=False)
    note = models.TextField("توضیح", blank=True)
    # For media: files changed after this moment went into this backup (the next one starts from `at`).
    since = models.DateTimeField("از زمان", null=True, blank=True)

    class Meta:
        verbose_name = "پشتیبان"
        verbose_name_plural = "پشتیبان‌ها"
        ordering = ["-at"]


class ShareSettings(models.Model):
    """One row: the link sent when a book has none of its own."""

    default_link = models.URLField("لینک پیش‌فرض", blank=True, help_text="مثلاً لینک کانال یا صفحه‌ی دانلود اپ.")

    class Meta:
        verbose_name = "پیوند معرفی اپلیکیشن"
        verbose_name_plural = "پیوند معرفی اپلیکیشن"

    def __str__(self):
        return "پیوند معرفی اپلیکیشن"

    @classmethod
    def link_for(cls, book) -> str:
        if book.share_link:
            return book.share_link
        row = cls.objects.first()
        return row.default_link if row else ""


# Icons a label can have by its title (the app draws them: app/src/lib/labelIcons.ts).
ICON_CHOICES = [
    ("", "بدون آیکون"), ("book-open", "کتاب باز (تعریف)"), ("sigma", "سیگما (قضیه، فرمول)"), ("list-checks", "فهرست تیک‌دار (نتیجه، قاعده)"),
    ("lightbulb", "لامپ (نکته)"), ("triangle-alert", "مثلث هشدار (تله)"), ("pin", "سنجاق (مهم)"), ("pen-line", "قلم (مثال)"),
    ("repeat", "تکرار (یادآوری)"), ("brain", "مغز (حفظی)"), ("target", "هدف (در یک نگاه)"), ("circle-x", "ضربدر (مثال نقض)"),
    ("chart-spline", "نمودار"), ("languages", "زبان (واژه)"), ("info", "اطلاعات"), ("star", "ستاره"),
    ("badge-check", "مهر تأیید"), ("scroll", "طومار"), ("scale", "ترازو"), ("calculator", "ماشین‌حساب"), ("square-function", "تابع"),
    ("infinity", "بی‌نهایت"), ("pi", "عدد پی"), ("radical", "رادیکال"), ("percent", "درصد"), ("ruler", "خط‌کش"),
    ("drafting-compass", "پرگار"), ("triangle", "مثلث"), ("shapes", "شکل‌ها"), ("atom", "اتم"), ("flask-conical", "ارلن (شیمی)"),
    ("microscope", "میکروسکوپ"), ("dna", "دی‌ان‌ای"), ("leaf", "برگ"), ("globe", "کره‌ی زمین"), ("zap", "برق"),
    ("magnet", "آهنربا"), ("thermometer", "دماسنج"), ("landmark", "بنای تاریخی"), ("gavel", "چکش قاضی (حقوق)"), ("coins", "سکه (اقتصاد)"),
    ("trending-up", "روند صعودی"), ("chart-column", "نمودار ستونی"), ("chart-pie", "نمودار دایره‌ای"), ("clock", "ساعت"), ("calendar", "تقویم"),
    ("quote", "نقل‌قول"), ("message-circle-question-mark", "پرسش و پاسخ"), ("circle-question-mark", "علامت سؤال"), ("circle-check", "تیک"), ("key", "کلید (نکته‌ی کلیدی)"),
    ("puzzle", "پازل"), ("layers", "لایه‌ها"), ("link", "پیوند"), ("eye", "چشم (توجه)"), ("flag", "پرچم"),
    ("bookmark", "نشان"), ("graduation-cap", "کلاه دانش‌آموختگی (کنکور)"), ("notebook-pen", "دفتر"), ("sparkles", "درخشش"), ("heart", "قلب"),
    ("shield", "سپر"), ("cpu", "تراشه"), ("code", "کد"), ("network", "شبکه"), ("map", "نقشه"),
    ("users", "گروه"), ("palette", "رنگ‌ها"), ("compass", "قطب‌نما"), ("hammer", "چکش"), ("wrench", "آچار"),
    ("search", "ذره‌بین"), ("footprints", "قدم‌به‌قدم"),
]


class Label(models.Model):
    """A label of the lesson text («برچسب»): a box «:::تعریف … :::» in the notes and a part «تعریف:» in the summary.
    The same list drives the app's renderer and the panel's buttons (see app/src/lib/labels.ts). Never deleted: a label
    in use is hidden instead, and text already using it keeps its look."""

    class Style(models.TextChoices):
        FORMAL = "formal", "رسمی (تعریف، قضیه؛ آبی)"
        NOTE = "note", "یادداشت (نکته، یادآوری؛ سبز)"
        WARN = "warn", "هشدار (تله، مثال نقض؛ نارنجی)"
        TABLE = "table", "جدول (واژه، مترادف؛ ستون‌دار)"

    class Role(models.TextChoices):
        NONE = "", "معمولی"
        GLANCE = "glance", "خلاصه‌ی بالای چکیده («در یک نگاه»)"
        IMPORTANT = "important", "همه‌ی موارد پرش به درسنامه («مهم»)"
        TERMS = "terms", "واژه‌نامه و زیرخط واژه‌ها در درسنامه («واژه»)"
        MEMORIZE = "memorize", "دکمه‌ی مرور فلش‌کارت‌ها («حفظی»)"

    name = models.CharField("نام", max_length=40, unique=True, help_text="همان که در متن نوشته می‌شود؛ مثلاً «تعریف».")
    group = models.CharField("گروه", max_length=40, blank=True, help_text="دکمه‌های پنل به این گروه‌ها دسته می‌شوند؛ مثلاً «ریاضی و علوم» یا «زبان».")
    style = models.CharField("ظاهر", max_length=10, choices=Style.choices, default=Style.NOTE)
    role = models.CharField("کار ویژه", max_length=12, choices=Role.choices, blank=True, default="",
                            help_text="بیشتر برچسب‌ها «معمولی»اند. هر کار ویژه فقط برای یک برچسب.")
    aliases = models.CharField("نام‌های دیگر", max_length=200, blank=True, help_text="املاهای دیگری که همین برچسب حساب شوند، جدا با «،». مثلاً «تله‌ها، تله‌ی تستی».")
    columns = models.CharField("ستون‌ها", max_length=200, blank=True, help_text="فقط برای ظاهر جدول: عنوان ستون‌ها جدا با «|»، مثلاً «واژه | مترادف».")
    order = models.PositiveIntegerField("ترتیب", default=0)
    is_hidden = models.BooleanField("پنهان", default=False, help_text="در دکمه‌های پنل نمی‌آید؛ متن‌هایی که از آن استفاده کرده‌اند مثل قبل نشان داده می‌شوند.")
    numbered = models.BooleanField("شماره‌دار", default=False, help_text="کادرهای این برچسب در درسنامه در کل فصل شماره می‌خورند («مثال ۳-۵»)، و با «[[#نام]]» می‌شود به آن‌ها ارجاع داد.")
    icon = models.CharField("آیکون", max_length=40, blank=True, default="", choices=ICON_CHOICES,
                            help_text="کنار عنوان کادر در درسنامه و بخش چکیده. خالی: بدون آیکون.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name="custom_labels", verbose_name="ایجادکننده (استاد)",
                                   help_text="خالی: برچسب عمومی سیستم. پر: برچسب اختصاصی این استاد.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "برچسب متن"
        verbose_name_plural = "برچسب‌های متن"

    def __str__(self):
        return self.name

    def as_json(self) -> dict:
        split = lambda text, sep: [x.strip() for x in re.split(sep, text or "") if x.strip()]  # noqa: E731
        return {"name": self.name, "group": self.group, "style": self.style, "role": self.role,
                "aliases": split(self.aliases, r"[،,]"), "columns": split(self.columns, r"\|"), "hidden": self.is_hidden,
                "numbered": self.numbered, "icon": self.icon, "is_custom": bool(self.created_by_id)}


class BookChange(models.Model):
    """«تغییرات کتاب»: one line per important update (the panel's «مطلب تازه»), shown to learners with its date."""

    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, related_name="changes", verbose_name="کتاب",
                             limit_choices_to={"kind": "book", "depth": 1})
    node = models.ForeignKey(ContentNode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="فصل یا بخش")
    text = models.CharField("شرح تغییر", max_length=300)
    created_at = models.DateTimeField("تاریخ", auto_now_add=True)
    is_hidden = models.BooleanField("پنهان", default=False, help_text="در صفحه‌ی «تغییرات کتاب» نشان داده نمی‌شود.")

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "تغییر کتاب"
        verbose_name_plural = "تغییرات کتاب‌ها"

    def __str__(self):
        return self.text


class FormulaCommand(models.Model):
    """«دستورهای فرمول»: a short command for every formula of every book, e.g. «\\R» for «\\mathbb{R}». KaTeX expands it
    (with #1, #2 for arguments), so changing one line changes every formula that uses it."""

    name = models.CharField("دستور", max_length=40, unique=True, help_text="با «\\» و فقط حروف انگلیسی، مثلاً \\R یا \\norm")
    definition = models.CharField("معنی", max_length=300, help_text="LaTeX؛ برای ورودی‌ها #1 و #2، مثلاً \\lVert #1 \\rVert")
    note = models.CharField("توضیح", max_length=120, blank=True)
    is_hidden = models.BooleanField("خاموش", default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "دستور فرمول"
        verbose_name_plural = "دستورهای فرمول"

    def __str__(self):
        return f"{self.name} = {self.definition}"

    def clean(self):
        import re

        from django.core.exceptions import ValidationError

        self.name = (self.name or "").strip()
        if not re.fullmatch(r"\\[A-Za-z]+", self.name):
            raise ValidationError({"name": "دستور با «\\» شروع می‌شود و بعد فقط حروف انگلیسی، مثلاً \\R"})
        if (self.definition or "").count("{") != (self.definition or "").count("}"):
            raise ValidationError({"definition": "تعداد «{» و «}» برابر نیست."})


class BookBoxMapping(models.Model):
    """Custom LaTeX environment mapping memory for a book: e.g. environment 'test' -> label 'تست'."""

    book = models.ForeignKey("catalog.ContentNode", on_delete=models.CASCADE, related_name="box_mappings", verbose_name="کتاب")
    environment_name = models.CharField("نام محیط LaTeX", max_length=60)
    label_name = models.CharField("کادر لیموخوان", max_length=60)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="کاربر")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "حافظه نگاشت کادر کتاب"
        verbose_name_plural = "حافظه‌های نگاشت کادر کتاب"
        constraints = [
            models.UniqueConstraint(fields=["book", "environment_name"], name="unique_book_latex_env_mapping"),
        ]

    def __str__(self):
        return f"{self.book.title}: {self.environment_name} ← {self.label_name}"

    def __str__(self):
        return f"{self.book.title}: {self.environment_name} -> {self.label_name}"

    def clean(self):
        self.environment_name = (self.environment_name or "").strip().lower()
        self.label_name = (self.label_name or "").strip()


class BookEditor(models.Model):
    """«استادِ کتاب»: a manager-approved editor for one book, in addition to the required group and staff status.

    One row per (book, user). The separately maintained `can_publish` flag is an audit/review decision only:
    final publishing remains a superuser action and the flag never grants it to a teacher.
    """

    book = models.ForeignKey(
        "catalog.ContentNode", on_delete=models.CASCADE, related_name="editors", verbose_name="کتاب"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="edited_books", verbose_name="کاربر"
    )
    can_edit_content = models.BooleanField(
        "ویرایش پیش‌نویس",
        default=True,
        help_text="فقط محتوای پیش‌نویس همین کتاب؛ انتشار نهایی همچنان با مدیر کل است.",
    )
    can_request_publication = models.BooleanField(
        "درخواست بازبینی انتشار عمومی",
        default=False,
        help_text="فقط ارسال نسخه برای بررسی؛ این مجوز انتشار یا فروش عمومی نمی‌دهد.",
    )
    can_request_group_access = models.BooleanField(
        "درخواست دسترسی گروهی",
        default=False,
        help_text="فقط پیشنهاد شماره‌ها برای بررسی مدیر؛ ساخت حساب یا اعطای دسترسی با این مجوز انجام نمی‌شود.",
    )
    can_view_reports = models.BooleanField(
        "دیدن گزارش ایرادهای همین کتاب",
        default=True,
        help_text="فقط گزارش محتوای این کتاب؛ شماره و حساب گزارش‌دهنده برای استاد پنهان می‌ماند.",
    )
    can_view_aggregate_study = models.BooleanField(
        "دیدن آمار تجمیعی مطالعه",
        default=False,
        help_text="آمار تجمیعی و بدون شناسه‌ی دانشجو؛ هرگز داده‌ی فردی را نمایش نمی‌دهد.",
    )
    can_view_aggregate_sales = models.BooleanField(
        "دیدن آمار تجمیعی فروش",
        default=False,
        help_text="فقط آمار تجمیعی همین کتاب؛ بدون نام، شماره یا سابقه‌ی خرید فردی.",
    )
    can_publish = models.BooleanField(
        "تصمیم انتشار مدیر", default=False,
        help_text="تصمیم دستی و جداگانه‌ی مدیر برای بازبینی؛ این فیلد به استاد اختیار انتشار نمی‌دهد. Publish نهایی فقط دست مدیر کل است.",
    )
    note = models.CharField("یادداشت", max_length=200, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "استاد کتاب"
        verbose_name_plural = "استادان کتاب"
        ordering = ["book__title", "user__phone"]
        constraints = [models.UniqueConstraint(fields=["book", "user"], name="uniq_book_editor")]

    def __str__(self):
        return f"{self.user} → {self.book.title}"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.book_id and (self.book.kind != ContentNode.Kind.BOOK or self.book.depth != 1):
            raise ValidationError({"book": "فقط یک کتاب (نه فصل یا بخش) می‌تواند اینجا باشد."})
        if self.book_id and self.book.is_inbox:
            raise ValidationError({"book": "صندوق تست دسترسی استاد کتاب نمی‌گیرد؛ فقط مدیر کل آن را باز می‌کند."})


class BookTeamTask(models.Model):
    """Internal task board / coordination notes between the lead teacher and teaching assistants of a book."""

    book = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="team_tasks",
        limit_choices_to={"kind": ContentNode.Kind.BOOK, "depth": 1},
        verbose_name="کتاب",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_book_tasks",
        verbose_name="نویسنده یادداشت",
    )
    text = models.CharField("متن یادداشت / وظیفه", max_length=300)
    is_done = models.BooleanField("انجام شد", default=False)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "یادداشت هماهنگی تیم کتاب"
        verbose_name_plural = "یادداشت‌های هماهنگی تیم کتاب"
        ordering = ["is_done", "-created_at"]

    def __str__(self):
        return f"{self.book.title}: {self.text[:40]}"


class BookAssistantAuditLog(models.Model):
    """Audit log for teaching assistant assignments and permission changes for a book."""

    class Action(models.TextChoices):
        ADDED = "added", "افزودن دستیار"
        UPDATED = "updated", "ویرایش دسترسی‌ها"
        REMOVED = "removed", "حذف دسترسی دستیار"

    book = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="assistant_audit_logs",
        limit_choices_to={"kind": ContentNode.Kind.BOOK, "depth": 1},
        verbose_name="کتاب",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assistant_audit_actions",
        verbose_name="اقدام‌کننده",
    )
    assistant_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assistant_audit_records",
        verbose_name="کاربر دستیار",
    )
    assistant_phone = models.CharField("شماره دستیار", max_length=20)
    action = models.CharField("نوع عملیات", max_length=20, choices=Action.choices)
    details = models.CharField("شرح تغییرات / دسترسی‌ها", max_length=300, blank=True)
    ip = models.CharField("نشانی IP", max_length=45, blank=True)
    created_at = models.DateTimeField("زمان ثبت رویداد", auto_now_add=True)

    class Meta:
        verbose_name = "لاگ ممیزی دستیار آموزشی"
        verbose_name_plural = "لاگ‌های ممیزی دستیاران آموزشی"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["book", "-created_at"]),
            models.Index(fields=["assistant_phone", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} — {self.assistant_phone} ({self.book.title})"


class AIProvider(models.Model):
    """Configuration for LLM API providers (Gemini, Groq, OpenAI, AvalAI, etc.) managed by superuser or individual teachers."""

    class ProviderType(models.TextChoices):
        GEMINI = "gemini", "Google Gemini API"
        OPENAI = "openai", "OpenAI-Compatible (Groq, OpenAI, DeepSeek, AvalAI)"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="ai_providers",
        verbose_name="استاد / مالک کلید",
        help_text="اگر خالی باشد، این مدل سراسری/عمومی بوده و توسط مدیر کل تعریف شده است.",
    )
    title = models.CharField(
        "عنوان نمایشی",
        max_length=100,
        help_text="نامی که در پنل اساتید و مدیریت نمایش داده می‌شود (مثلاً «Gemini 2.0 Flash اختصاصی» یا «مدل اشتراکی مدیر»)",
    )
    provider_type = models.CharField(
        "نوع ارائه‌دهنده",
        max_length=20,
        choices=ProviderType.choices,
        default=ProviderType.GEMINI,
    )
    api_key = models.CharField(
        "کلید API",
        max_length=255,
        help_text="کلید معتبر دریافتی از ارائه‌دهنده هوش مصنوعی (کلید به صورت امن ذخیره می‌شود)",
    )
    base_url = models.CharField(
        "آدرس پایه API (Base URL)",
        max_length=255,
        blank=True,
        default="",
        help_text="برای Gemini خالی بگذارید؛ برای Groq: https://api.groq.com/openai/v1؛ برای OpenAI: https://api.openai.com/v1",
    )
    model_name = models.CharField(
        "نام مدل",
        max_length=100,
        default="gemini-2.0-flash",
        help_text="نام دقیق مدل (مثلاً gemini-2.0-flash یا qwen-2.5-32b یا llama-3.3-70b-versatile)",
    )
    is_active = models.BooleanField(
        "فعال برای استفاده",
        default=True,
        help_text="آیا این ارائه‌دهنده در فرم تمیزکاری فایل‌ها در دسترس باشد؟",
    )
    is_default = models.BooleanField(
        "مدل پیش‌فرض",
        default=False,
        help_text="مدلی که به صورت اولیه در دراپ‌داون انتخاب شده است",
    )
    order = models.PositiveSmallIntegerField("ترتیب نمایش", default=0)
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("تاریخ ویرایش", auto_now=True)

    class Meta:
        verbose_name = "ارائه‌دهنده هوش مصنوعی"
        verbose_name_plural = "ارائه‌دهندگان هوش مصنوعی"
        ordering = ["order", "-is_default", "id"]

    def __str__(self):
        status = " (فعال)" if self.is_active else " (غیرفعال)"
        default = " [پیش‌فرض]" if self.is_default else ""
        owner_label = f" [اختصاصی: {self.owner.phone}]" if self.owner else " [سراسری مدیر]"
        return f"{self.title} — {self.model_name}{owner_label}{default}{status}"

    @property
    def is_global(self):
        return self.owner is None

    def masked_api_key(self):
        """Show only first 4 and last 4 characters for security."""
        k = (self.api_key or "").strip()
        if len(k) <= 8:
            return "••••••••"
        return f"{k[:4]}••••••••{k[-4:]}"

    def save(self, *args, **kwargs):
        if self.is_default:
            AIProvider.objects.filter(owner=self.owner).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)




class TeacherProfile(models.Model):
    """«پروفایل و بیوگرافی استاد»: تصویر، عنوان علمی، رزومه و راه‌های ارتباطی جهت نمایش در شناسنامه کتاب و اپ."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
        verbose_name="کاربر (استاد)",
    )
    academic_title = models.CharField(
        "مرتبه علمی / عنوان رسمی",
        max_length=120,
        blank=True,
        help_text="مثلاً «دانشیار دانشگاه تهران» یا «مؤلف برتر کتب حقوقی»",
    )
    avatar = models.ImageField(
        "تصویر استاد",
        upload_to="teachers/avatars/",
        blank=True,
        help_text="تصویر پرسنلی یا پرتره باکیفیت (ترجیحاً مربع، ۵۰۰×۵۰۰)",
    )
    bio = models.TextField(
        "درباره استاد / رزومه (Markdown)",
        blank=True,
        help_text="سوابق آموزشی، پژوهشی، کتب تألیفی و معرفی به دانشجویان",
    )
    contact_email = models.EmailField("ایمیل ارتباطی", blank=True)
    social_links = models.CharField(
        "شبکه‌های اجتماعی / وبگاه",
        max_length=255,
        blank=True,
        help_text="لینک وبسایت شخصی، کانال تلگرام یا لینکدین",
    )
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("زمان به‌روزرسانی", auto_now=True)

    class Meta:
        verbose_name = "پروفایل استاد"
        verbose_name_plural = "پروفایل‌های استادان"

    def __str__(self):
        name = f"{self.user.first_name} {self.user.last_name}".strip() or self.user.phone
        title = f" ({self.academic_title})" if self.academic_title else ""
        return f"{name}{title}"


class BookOpinion(models.Model):
    """«نظرات و امتیازهای کتاب»: ثبت نظر دانشجویان با ستاره ۱ تا ۵، درصد رضایت، شاخص میزان مطالعه، پاسخ استاد و ممیزی مدیر."""

    class Status(models.TextChoices):
        APPROVED = "approved", "تأییدشده و عمومی"
        PENDING = "pending", "در انتظار بازبینی"
        HIDDEN = "hidden", "پنهان‌شده / ردشده"

    book = models.ForeignKey(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="opinions",
        limit_choices_to={"kind": ContentNode.Kind.BOOK, "depth": 1},
        verbose_name="کتاب",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="catalog_opinions",
        verbose_name="دانشجو / کاربر",
    )
    rating = models.PositiveSmallIntegerField(
        "امتیاز (۱ تا ۵ ستاره)",
        default=5,
        help_text="امتیاز عددی از ۱ تا ۵ ستاره",
    )
    satisfaction_percent = models.PositiveSmallIntegerField(
        "درصد رضایت",
        default=100,
        help_text="درصد رضایت کلی کاربر از مطالعه کتاب (۰ تا ۱۰۰)",
    )
    body = models.TextField(
        "متن نظر",
        max_length=2000,
        help_text="دیدگاه کاربر درباره درسنامه‌ها، تست‌ها یا کیفیت تألیف کتاب",
    )
    # شاخص‌های اعتبار مطالعه هنگام ثبت نظر
    study_percent = models.PositiveSmallIntegerField(
        "درصد مطالعه کتاب",
        default=0,
        help_text="درصد بخش‌های خوانده‌شده کتاب توسط کاربر در زمان ثبت نظر",
    )
    test_percent = models.PositiveSmallIntegerField(
        "درصد تست‌های حل‌شده",
        default=0,
        help_text="درصد تست‌های تمرین‌شده توسط کاربر در زمان ثبت نظر",
    )
    is_pinned = models.BooleanField(
        "سنجاق‌شده در بالای لیست",
        default=False,
        help_text="نمایش ویژه در ابتدای نظرات با تصمیم استاد یا مدیر",
    )
    # پاسخ استاد به نظر دانشجو
    teacher_reply = models.TextField(
        "پاسخ استاد / مؤلف",
        blank=True,
        max_length=1500,
        help_text="پاسخ توضیحی یا تقدیر استاد از دانشجو",
    )
    teacher_replied_at = models.DateTimeField("زمان پاسخ استاد", null=True, blank=True)
    teacher_replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="استاد پاسخ‌دهنده",
    )
    # گزارش تخلف ارسالی از طرف استاد یا کاربران به مدیر کل
    report_reason = models.CharField(
        "دلیل گزارش تخلف",
        max_length=255,
        blank=True,
        help_text="توضیح استاد به مدیر کل در صورت نامناسب یا بی‌ربط بودن نظر",
    )
    reported_at = models.DateTimeField("زمان گزارش", null=True, blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="گزارش‌کننده",
    )
    status = models.CharField(
        "وضعیت انتشار",
        max_length=15,
        choices=Status.choices,
        default=Status.APPROVED,
        db_index=True,
    )
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("تاریخ ویرایش", auto_now=True)

    class Meta:
        verbose_name = "نظر و امتیاز کتاب"
        verbose_name_plural = "نظرات و امتیازهای کتاب‌ها"
        ordering = ["-is_pinned", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["book", "user"], name="uniq_user_book_opinion"),
        ]

    def __str__(self):
        return f"{self.book.title} — {self.user.phone} ({self.rating}★)"

    @property
    def display_author_name(self):
        full = f"{self.user.first_name} {self.user.last_name}".strip()
        return full if full else "کاربر لیموخوان"
