"""The public website (limookhan.ir): its editable texts. Pages are drawn by apps/website/views.py from the same
database as the app, so books, prices and sample tests appear by themselves."""
from django.db import models


class SiteSettings(models.Model):
    """One row: contact details, store links and the trust seal. Edited in the panel («تنظیمات سایت»)."""

    tagline = models.CharField("جمله‌ی اصلی", max_length=120, default="کتاب درسی‌ات را مثل یک لیمو بخور، برش به برش 🍋")
    intro = models.TextField(
        "معرفی کوتاه",
        default="هر کتاب در لیموخوان یک خلاصه، یک درسنامه‌ی کامل، تست با پاسخ تشریحی و فلش‌کارت دارد. هر روز کمی بخوان؛ "
        "لیموخوان یادت می‌اندازد چه چیزی را دوباره مرور کنی.",
    )
    audience = models.CharField("برای چه کسانی", max_length=120, default="برای کنکور ارشد، دکتری و امتحان‌های دانشگاه")
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
    """«درباره‌ی ما»، «قوانین»، «حریم خصوصی»، «تماس با ما»: a title and a text («## » for a heading, «- » for a list)."""

    class Kind(models.TextChoices):
        ABOUT = "about", "درباره‌ی ما"
        CONTACT = "contact", "تماس با ما"
        TERMS = "terms", "قوانین"
        PRIVACY = "privacy", "حریم خصوصی"

    slug = models.CharField("صفحه", max_length=20, choices=Kind.choices, unique=True)
    title = models.CharField("عنوان", max_length=120)
    body = models.TextField("متن", blank=True, help_text="پاراگراف‌ها را با یک خط خالی جدا کنید. «## » اول خط: تیتر؛ «- » اول خط: فهرست.")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="آخرین تغییر")
    show_in_app = models.BooleanField("نمایش در اپ", default=False, help_text="در «حساب من» اپ هم دیده شود.")
    # Set by the «تغییر مهم است» tick on save: learners who have not opened the page since see a notice in the app.
    important_at = models.DateTimeField("آخرین تغییر مهم", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "صفحه‌ی سایت"
        verbose_name_plural = "صفحه‌های سایت"
        ordering = ["slug"]

    def __str__(self):
        return self.title


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
