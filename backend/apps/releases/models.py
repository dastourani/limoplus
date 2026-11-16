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
    download_url = models.URLField("لینک دانلود (همه‌کاره)", max_length=500, blank=True, help_text="اگر فایل APK را همین‌جا آپلود کنید، خالی بگذارید.")
    apk = models.FileField(
        "فایل APK همه‌کاره", upload_to="apk/", blank=True,
        help_text="روی همه‌ی گوشی‌ها نصب می‌شود (حجم بیشتر). روی همین سرور نگه داشته می‌شود تا دانلود در ایران سریع باشد.",
    )
    apk_arm64 = models.FileField("فایل APK ۶۴ بیتی (arm64)", upload_to="apk/", blank=True,
                                 help_text="اختیاری؛ سبک‌تر، برای بیشتر گوشی‌های چند سال اخیر.")
    url_arm64 = models.URLField("لینک ۶۴ بیتی", max_length=500, blank=True, help_text="به‌جای فایل بالا، اگر جای دیگری است.")
    apk_32 = models.FileField("فایل APK ۳۲ بیتی", upload_to="apk/", blank=True,
                              help_text="اختیاری؛ سبک‌تر، برای گوشی‌های اندروید ۳۲ بیتی (مثل Galaxy A03).")
    url_32 = models.URLField("لینک ۳۲ بیتی", max_length=500, blank=True, help_text="به‌جای فایل بالا، اگر جای دیگری است.")
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

    def clean(self):
        from django.core.exceptions import ValidationError

        if not self.apk and not self.download_url:
            raise ValidationError("فایل APK را آپلود کنید یا لینک دانلود بدهید.")
        for name in ("apk", "apk_arm64", "apk_32"):
            f = getattr(self, name)
            if f and not f.name.lower().endswith(".apk"):
                raise ValidationError({name: "فقط فایل ‎.apk"})

    @staticmethod
    def _url(file, url):
        if file:
            from django.conf import settings

            return settings.SITE_URL.rstrip("/") + "/" + file.url.lstrip("/")
        return url

    @property
    def link(self):
        """The universal APK: the uploaded file on this server, else the given link."""
        return self._url(self.apk, self.download_url)

    @property
    def link_arm64(self):
        return self._url(self.apk_arm64, self.url_arm64)

    @property
    def link_32(self):
        return self._url(self.apk_32, self.url_32)

    def link_for(self, abis) -> str:
        """The file that fits a phone, from the processor types it reports (best first); the universal one otherwise."""
        abis = [a.strip() for a in (abis or []) if a and a.strip()]
        if "arm64-v8a" in abis and self.link_arm64:
            return self.link_arm64
        if "armeabi-v7a" in abis and "arm64-v8a" not in abis and self.link_32:
            return self.link_32
        return self.link or self.link_arm64 or self.link_32

    def __str__(self):
        return f"{self.get_platform_display()} {self.build}" + (" (اجباری)" if self.is_required else "")
