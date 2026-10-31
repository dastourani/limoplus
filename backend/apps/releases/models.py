from django.db import models


class AppRelease(models.Model):
    """
    A published build of the app. The app compares its own build number with these: a newer build is offered, and a
    build marked as required cuts off every older build (they are asked to update and the API refuses them).
    """

    ANDROID = "android"
    PLATFORMS = [(ANDROID, "اندروید")]

    platform = models.CharField("سیستم", max_length=20, choices=PLATFORMS, default=ANDROID)
    build = models.PositiveIntegerField("شماره‌ی ساخت", help_text="همان عدد نسخه‌ی آزمایشی، مثلاً ۱۰ برای limoplus-test-10")
    version_name = models.CharField("نام نسخه", max_length=40, blank=True, help_text="اختیاری؛ مثلاً ۱٫۰٫۳")
    notes = models.TextField("تغییرات این نسخه", blank=True, help_text="هر خط یک مورد؛ به کاربر نشان داده می‌شود")
    download_url = models.URLField("لینک دانلود", max_length=500)
    is_required = models.BooleanField(
        "به‌روزرسانی اجباری",
        default=False,
        help_text="اگر تیک بخورد، نسخه‌های قدیمی‌تر دیگر به سرور وصل نمی‌شوند و کاربر باید نسخه‌ی جدید را نصب کند.",
    )
    is_published = models.BooleanField("منتشر شده", default=True)
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "نسخه‌ی اپ"
        verbose_name_plural = "نسخه‌های اپ"
        ordering = ["-build"]
        constraints = [models.UniqueConstraint(fields=["platform", "build"], name="unique_release_build")]

    def __str__(self):
        return f"{self.get_platform_display()} {self.build}" + (" (اجباری)" if self.is_required else "")
