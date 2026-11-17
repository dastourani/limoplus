"""The public website (limookhan.ir): its editable texts. Pages are drawn by apps/website/views.py from the same
database as the app, so books, prices and sample tests appear by themselves."""
from django.db import models


class SiteSettings(models.Model):
    """One row: contact details, store links and the trust seal. Edited in the panel («تنظیمات سایت»)."""

    tagline = models.CharField("جمله‌ی اصلی", max_length=120, default="منبع درسی‌ات را برش‌به‌برش بخوان، مرور کن و مسلط شو 🍋")
    intro = models.TextField(
        "معرفی کوتاه",
        default="در لیموخوان هر کتاب یک درسنامه‌ی ساختارمند، چکیده‌ی مرور سریع، بانک تست کنکور با پاسخ تشریحی و فلش‌کارت‌های "
        "زمان‌بندی‌شده دارد؛ با برنامه‌ی مرور هوشمند که فراموشی را به صفر می‌رساند.",
    )
    audience = models.CharField("برای چه کسانی", max_length=120, default="ویژه‌ی داوطلبان کنکور ارشد، دکتری و امتحانات دانشگاهی")
    features_title = models.CharField("عنوان بخش چهار ویژگی", max_length=120, default="یک منبع، چهار ابزار مکمل یادگیری")
    features_sub = models.CharField("زیرعنوان بخش ویژگی‌ها", max_length=200, default="تمام ابزارهای مطالعه و مرور، یکپارچه و منطبق با سرفصل‌های کتاب")
    feat1_title = models.CharField("عنوان باکس ۱", max_length=80, default="درسنامه و چکیده‌ی دوحالته")
    feat1_body = models.TextField("متن باکس ۱", default="متن کامل درسی با کادرهای تعریف، فرمول، مثال و نکات کنکوری؛ به‌همراه چکیده‌ی یک‌صفحه‌ای برای مرور شب امتحان.")
    feat2_title = models.CharField("عنوان باکس ۲", max_length=80, default="بانک تست و دفترچه‌ی اشتباهات")
    feat2_body = models.TextField("متن باکس ۲", default="تست‌های طبقه‌بندی‌شده‌ی کنکور با پاسخ تشریحی گام‌به‌گام؛ تست‌های غلط یا شک‌دار خودکار وارد چرخه‌ی مرور می‌شوند.")
    feat3_title = models.CharField("عنوان باکس ۳", max_length=80, default="فلش‌کارت و واژه‌نامه‌ی لایتنر")
    feat3_body = models.TextField("متن باکس ۳", default="نکات کلیدی، فرمول‌ها و لغات تخصصی در ۶ جعبه‌ی مرور هوشمند (فردا، هفته‌ی بعد، ماه بعد) تا انتقال به حافظه‌ی بلندمدت.")
    feat4_title = models.CharField("عنوان باکس ۴", max_length=80, default="آمار پیشرفت و آزمون زمان‌دار")
    feat4_body = models.TextField("متن باکس ۴", default="لیموی پیشرفت هر فصل، سنجش آمادگی برای کنکورهای سال قبل و شبیه‌ساز آزمون با نمره‌ی منفی.")
    band_title = models.CharField("عنوان بخش میانی (کنار لیمو)", max_length=140, default="هر روز فقط چند دقیقه، با برنامه‌ی مرور هوشمند")
    band_sub = models.CharField("زیرعنوان بخش میانی", max_length=220, default="لیموخوان بر اساس عملکردت می‌داند امروز چه بخشی، تستی یا کارتی را باید مرور کنی")
    show_updates = models.BooleanField("نمایش بخش تازه‌ها در صفحه‌ی اول", default=True)
    show_sample_test = models.BooleanField("نمایش تست نمونه‌ی تعاملی در صفحه‌ی اول", default=True)
    show_home_faq = models.BooleanField("نمایش پرسش‌های پرتکرار در صفحه‌ی اول", default=True)
    footer_about = models.TextField("متن معرفی در فوتر سایت", default="کتاب درسی تعاملی برای دانشجوهای ایران: خلاصه، درسنامه، تست با پاسخ تشریحی و فلش‌کارت.")
    email = models.EmailField("ایمیل پشتیبانی", blank=True)
    phone = models.CharField("تلفن", max_length=40, blank=True)
    address = models.CharField("نشانی", max_length=300, blank=True)
    bazaar_url = models.URLField("لینک کافه‌بازار", blank=True)
    myket_url = models.URLField("لینک مایکت", blank=True)
    apk_url = models.URLField("لینک فایل APK", blank=True, help_text="خالی: آخرین «نسخه‌ی اپ» منتشرشده.")
    telegram_url = models.URLField("لینک تلگرام", blank=True)
    instagram_url = models.URLField("لینک اینستاگرام", blank=True)
    enamad_html = models.TextField("کد نماد اینماد", blank=True, help_text="همان کدی که سایت اینماد می‌دهد؛ پایین همه‌ی صفحه‌ها نشان داده می‌شود.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "تنظیمات سایت"
        verbose_name_plural = "تنظیمات سایت"

    def __str__(self):
        return "تنظیمات سایت"

    @classmethod
    def get(cls) -> "SiteSettings":
        row = cls.objects.order_by("id").first()
        return row or cls.objects.create()


class SitePage(models.Model):
    """«درباره‌ی ما»، «قوانین»، «حریم خصوصی»، «حفاظت از محتوا» یا هر صفحه‌ی دلخواه دیگر در سایت و اپ."""

    class Kind(models.TextChoices):
        ABOUT = "about", "درباره‌ی ما"
        CONTACT = "contact", "تماس با ما"
        TERMS = "terms", "قوانین"
        PRIVACY = "privacy", "حریم خصوصی"
        PROTECTION = "protection", "حفاظت از محتوا"

    slug = models.SlugField(
        "شناسه‌ی آدرس (لاتین)",
        max_length=40,
        unique=True,
        help_text="در آدرس /p/<slug>/ قرار می‌گیرد؛ مثلاً terms، privacy، protection یا هر نام لاتین دلخواه.",
    )
    title = models.CharField("عنوان", max_length=120)
    body = models.TextField("متن", blank=True, help_text="پاراگراف‌ها را با یک خط خالی جدا کنید. «## » اول خط: تیتر؛ «- » اول خط: فهرست.")
    order = models.PositiveIntegerField("ترتیب", default=10)
    show_in_nav = models.BooleanField("نمایش در منوی بالا", default=False, help_text="در نوار منوی بالای سایت نشان داده شود.")
    show_in_footer = models.BooleanField("نمایش در فوتر", default=True, help_text="در ستون پشتیبانی پایین سایت نشان داده شود.")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")
    show_in_app = models.BooleanField("نمایش در اپ", default=False, help_text="در «حساب من» اپ هم دیده شود.")
    # Set by the «تغییر مهم است» tick on save: learners who have not opened the page since see a notice in the app.
    important_at = models.DateTimeField("آخرین تغییر مهم", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "صفحه‌ی سایت"
        verbose_name_plural = "صفحه‌های سایت"
        ordering = ["order", "slug"]

    def __str__(self):
        return self.title


class SiteNavItem(models.Model):
    """An item in the website's top navigation bar, editable in the panel («منوی بالای سایت»). Supports 2 levels
    (a parent item with dropdown children)."""

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name="زیرمجموعه‌ی منوی",
        limit_choices_to={"parent__isnull": True},
        help_text="خالی = آیتم اصلی در نوار بالا؛ اگر یک آیتم اصلی را انتخاب کنید، به‌عنوان زیرمنوی آبشاری آن نمایش داده می‌شود.",
    )
    title = models.CharField("عنوان در منو", max_length=60)
    url = models.CharField(
        "آدرس یا مسیر",
        max_length=300,
        blank=True,
        default="#",
        help_text="نام بخش داخلی («books»، «pricing»، «download»، «faq»)، آدرس یک صفحه («page:protection») یا لینک کامل («https://...»).",
    )
    order = models.PositiveIntegerField("ترتیب", default=10)
    is_hidden = models.BooleanField("پنهان", default=False)

    class Meta:
        verbose_name = "آیتم منوی سایت"
        verbose_name_plural = "منوی بالای سایت"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.parent.title} › {self.title}" if self.parent_id else self.title


class HelpPage(models.Model):
    """«صفحه‌های راهنما»: help texts shown in the app's «حساب من» › «راهنما», written like a lesson. Never deleted: hidden instead."""

    title = models.CharField("عنوان", max_length=120)
    body = models.TextField("متن", blank=True, help_text="مثل متن درس: فرمول، فهرست، کادرها و عکس.")
    order = models.PositiveIntegerField("ترتیب", default=0)
    is_hidden = models.BooleanField("پنهان", default=False)
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")

    class Meta:
        verbose_name = "صفحه‌ی راهنما"
        verbose_name_plural = "صفحه‌های راهنما"
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


class FaqItem(models.Model):
    """«پرسش‌های پرتکرار». Never deleted: hidden instead."""

    question = models.CharField("پرسش", max_length=200)
    answer = models.TextField("پاسخ")
    order = models.PositiveIntegerField("ترتیب", default=0)
    is_hidden = models.BooleanField("پنهان", default=False)

    class Meta:
        verbose_name = "پرسش پرتکرار"
        verbose_name_plural = "پرسش‌های پرتکرار"
        ordering = ["order", "id"]

    def __str__(self):
        return self.question
