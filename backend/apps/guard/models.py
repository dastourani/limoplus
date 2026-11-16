from django.conf import settings
from django.db import models


class CopyEvent(models.Model):
    """
    One copy of lesson text. Kept as a pointer, not a copy: the section, the chapter version (ChapterRevision) and the
    offsets of the text in it, plus a hash of the text. The text itself is kept (compressed) only when the pointer cannot
    give it back exactly. `code` is the invisible fingerprint put into the copied text.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="copies", verbose_name="کاربر")
    node = models.ForeignKey("catalog.ContentNode", on_delete=models.PROTECT, related_name="+", verbose_name="بخش")
    # PROTECT: a version that a copy points to is never deleted (see catalog.maintenance.prune_revisions).
    revision = models.ForeignKey("catalog.ChapterRevision", on_delete=models.PROTECT, null=True, blank=True, related_name="copies",
                                 verbose_name="نسخه‌ی فصل")
    mode = models.CharField("حالت", max_length=10, default="full")
    start = models.PositiveIntegerField(null=True, blank=True)
    end = models.PositiveIntegerField(null=True, blank=True)
    text_hash = models.CharField(max_length=64)
    length = models.PositiveIntegerField("طول", default=0)
    packed = models.BinaryField(null=True, blank=True)  # zlib of the text, only when the pointer does not match the hash
    code = models.CharField("اثرانگشت", max_length=16, unique=True)
    platform = models.CharField("سکو", max_length=20, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "کپی متن"
        verbose_name_plural = "کپی‌های متن"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["user", "created_at"])]

    def __str__(self):
        return f"{self.user} › {self.node_id}"


class TraceHit(models.Model):
    """A fingerprint found by «ردیاب متن»: counts toward the account's risk score."""

    event = models.ForeignKey(CopyEvent, on_delete=models.PROTECT, related_name="hits")
    found_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("event", "found_by")]


class GuardSettings(models.Model):
    """One row. Bale alerts are off until the owner turns them on at the top of «ردیاب متن»."""

    bale_alerts = models.BooleanField("هشدارهای بله", default=False)
    last_summary_on = models.DateField(null=True, blank=True)

    @classmethod
    def get(cls) -> "GuardSettings":
        return cls.objects.get_or_create(pk=1)[0]


class AlertSent(models.Model):
    """So one account is not reported twice the same day for the same reason."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField(max_length=20)
    date = models.DateField()

    class Meta:
        unique_together = [("user", "reason", "date")]


class Tracker(CopyEvent):
    """Admin-only: the «ردیاب متن» page in the menu (no table of its own)."""

    class Meta:
        proxy = True
        verbose_name = "ردیاب متن"
        verbose_name_plural = "ردیاب متن"
