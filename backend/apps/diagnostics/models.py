from django.db import models
from django.utils import timezone


class ErrorGroup(models.Model):
    class Source(models.TextChoices):
        SERVER = "server", "سرور"
        CLIENT = "client", "اپ / وب‌اپ"
        HEALTH = "health", "بررسی سلامت"

    class Kind(models.TextChoices):
        EXCEPTION = "exception", "خطای فنی سرور"
        CLIENT_ERROR = "client_error", "خطای کلاینت"
        OFFLINE = "offline", "بستهٔ آفلاین"
        INVARIANT = "invariant", "نقض قاعدهٔ محصول"
        NETWORK = "network", "شبکه / سرور"

    class Status(models.TextChoices):
        OPEN = "open", "باز"
        INVESTIGATING = "investigating", "در حال بررسی"
        RESOLVED = "resolved", "برطرف شد"
        IGNORED = "ignored", "نادیده گرفته‌شده"

    class Severity(models.TextChoices):
        CRITICAL = "critical", "بحرانی"
        ERROR = "error", "خطا"
        WARNING = "warning", "هشدار"

    fingerprint = models.CharField(max_length=64, unique=True)
    source = models.CharField("منبع", max_length=12, choices=Source.choices, db_index=True)
    kind = models.CharField("دسته", max_length=20, choices=Kind.choices, db_index=True)
    code = models.CharField("کد", max_length=80, db_index=True)
    title = models.CharField("عنوان", max_length=240)
    route = models.CharField("مسیر", max_length=200, blank=True)
    expected = models.TextField("انتظار محصول", blank=True)
    observed = models.TextField("مشاهدهٔ واقعی", blank=True)
    status = models.CharField("وضعیت", max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    severity = models.CharField("شدت", max_length=12, choices=Severity.choices, default=Severity.ERROR, db_index=True)
    event_count = models.PositiveIntegerField("تعداد رخداد", default=0)
    install_count = models.PositiveIntegerField("نصب‌های درگیر", default=0)
    user_count = models.PositiveIntegerField("کاربران درگیر", default=0)
    first_seen_at = models.DateTimeField("نخستین مشاهده", default=timezone.now)
    last_seen_at = models.DateTimeField("آخرین مشاهده", default=timezone.now, db_index=True)
    first_build = models.CharField("اولین نسخه", max_length=80, blank=True)
    last_build = models.CharField("آخرین نسخه", max_length=80, blank=True)
    resolved_at = models.DateTimeField("زمان رفع", null=True, blank=True)
    last_bale_alert_at = models.DateTimeField(null=True, blank=True)
    admin_note = models.TextField("یادداشت مدیر", blank=True)

    class Meta:
        verbose_name = "گروه خطا"
        verbose_name_plural = "گروه‌های خطا و مغایرت"
        ordering = ["-last_seen_at", "-id"]

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title}"


class ErrorEvent(models.Model):
    group = models.ForeignKey(ErrorGroup, on_delete=models.CASCADE, related_name="events", verbose_name="گروه")
    event_id = models.CharField("شناسهٔ رخداد", max_length=64, unique=True)
    request_id = models.CharField("شناسهٔ درخواست", max_length=64, blank=True, db_index=True)
    op_id = models.CharField("شناسهٔ عملیات", max_length=64, blank=True)
    install_id = models.CharField("شناسهٔ نصب", max_length=64, blank=True, db_index=True)
    user_ref = models.CharField("شناسهٔ غیرمستقیم کاربر", max_length=32, blank=True, db_index=True)
    platform = models.CharField("سکو", max_length=20, blank=True)
    channel = models.CharField("کانال", max_length=20, blank=True)
    app_build = models.CharField("بیلد / نسخه", max_length=40, blank=True)
    server_version = models.CharField("نسخهٔ سرور", max_length=40, blank=True)
    version_mismatch = models.BooleanField("اختلاف نسخهٔ وب", default=False)
    is_offline = models.BooleanField("آفلاین بوده", default=False)
    route = models.CharField("مسیر", max_length=200, blank=True)
    operation = models.CharField("عملیات", max_length=80, blank=True)
    expected = models.TextField("انتظار", blank=True)
    observed = models.TextField("مشاهده", blank=True)
    evidence = models.JSONField("شواهد مجاز", default=dict, blank=True)
    created_at = models.DateTimeField("زمان", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "نمونهٔ رخداد"
        verbose_name_plural = "نمونه‌های رخداد"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.event_id} ({self.group.code})"


class ErrorAffectedActor(models.Model):
    """Tracks unique installs and pseudonymous users per ErrorGroup without retaining unbounded raw events."""

    group = models.ForeignKey(ErrorGroup, on_delete=models.CASCADE, related_name="actors")
    actor_key = models.CharField(max_length=80)
    actor_type = models.CharField(max_length=10)
    first_seen_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("group", "actor_key")]


class HealthCheckRun(models.Model):
    class CheckKey(models.TextChoices):
        ALL = "all", "همهٔ بررسی‌ها"
        PAYMENTS = "payments", "پرداخت و دسترسی"
        REVIEWS = "reviews", "جلسه‌های مرور"
        OFFLINE = "offline", "سلامت بسته‌های آفلاین"

    check_key = models.CharField("نوع بررسی", max_length=40, choices=CheckKey.choices, db_index=True)
    completed = models.BooleanField("تکمیل موفق", default=True)
    checked_count = models.PositiveIntegerField("تعداد بررسی‌شده", default=0)
    issues_found = models.PositiveIntegerField("مغایرت یافت‌شده", default=0)
    pending_count = models.PositiveIntegerField("در انتظار وضعیت", default=0)
    summary = models.TextField("خلاصه", blank=True)
    details = models.JSONField("جزئیات", default=dict, blank=True)
    duration_ms = models.PositiveIntegerField("مدت (میلی‌ثانیه)", default=0)
    ran_at = models.DateTimeField("زمان اجرا", default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "اجرای بررسی سلامت"
        verbose_name_plural = "تاریخچهٔ بررسی‌های سلامت"
        ordering = ["-ran_at", "-id"]

    def __str__(self):
        return f"{self.get_check_key_display()} ({self.ran_at:%Y-%m-%d %H:%M})"
