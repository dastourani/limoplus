"""
Sales: single books and subscriptions.

Rules (see CLAUDE.md): prices are computed only here on the server; the verified amount must equal the order amount;
paying an order and granting access happen in one transaction with the order row locked. Nothing is ever deleted —
orders keep their history and entitlements are archived instead of removed.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import ContentNode, Major


class Plan(models.Model):
    """A subscription offer. Prices are edited in the admin."""

    class Scope(models.TextChoices):
        MAJOR = "major", "یک رشته"
        ALL = "all", "همه‌ی رشته‌ها"

    title = models.CharField("عنوان", max_length=80)
    scope = models.CharField("دامنه", max_length=10, choices=Scope.choices)
    months = models.PositiveSmallIntegerField("مدت (ماه)", default=1)
    price = models.PositiveIntegerField("قیمت (تومان)")
    is_active = models.BooleanField("فعال", default=True)
    order = models.PositiveSmallIntegerField("ترتیب", default=0)

    class Meta:
        verbose_name = "طرح اشتراک"
        verbose_name_plural = "طرح‌های اشتراک"
        ordering = ["order", "price"]

    def __str__(self):
        return f"{self.title} ({self.price:,} تومان)"


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار پرداخت"
        PAID = "paid", "پرداخت شده"
        FAILED = "failed", "ناموفق"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders", verbose_name="کاربر")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, null=True, blank=True, related_name="orders", verbose_name="کتاب")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, null=True, blank=True, related_name="orders", verbose_name="طرح")
    major = models.ForeignKey(Major, on_delete=models.PROTECT, null=True, blank=True, related_name="orders", verbose_name="رشته‌ی اشتراک")
    title = models.CharField("شرح", max_length=200)
    amount = models.PositiveIntegerField("مبلغ (تومان)")
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.PENDING)
    track_id = models.CharField("شناسه‌ی زیبال", max_length=40, unique=True, null=True, blank=True)
    ref_number = models.CharField("شماره‌ی پیگیری", max_length=40, blank=True)
    card_number = models.CharField("کارت (ماسک‌شده)", max_length=20, blank=True)
    gateway_response = models.JSONField("پاسخ درگاه", default=dict, blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    paid_at = models.DateTimeField("پرداخت", null=True, blank=True)

    class Meta:
        verbose_name = "سفارش"
        verbose_name_plural = "سفارش‌ها"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(book__isnull=False, plan__isnull=True) | models.Q(book__isnull=True, plan__isnull=False),
                name="order_is_book_or_plan",
            )
        ]

    def __str__(self):
        return f"#{self.id} {self.title}"


class Entitlement(models.Model):
    """Access bought by a user: a book (forever) or a subscription (a major, or all majors, until ends_at)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="entitlements", verbose_name="کاربر")
    book = models.ForeignKey(ContentNode, on_delete=models.PROTECT, null=True, blank=True, related_name="entitlements", verbose_name="کتاب")
    major = models.ForeignKey(Major, on_delete=models.PROTECT, null=True, blank=True, related_name="entitlements", verbose_name="رشته")
    all_majors = models.BooleanField("همه‌ی رشته‌ها", default=False)
    starts_at = models.DateTimeField("شروع", default=timezone.now)
    ends_at = models.DateTimeField("پایان", null=True, blank=True, help_text="خالی = همیشگی")
    order = models.OneToOneField(Order, on_delete=models.PROTECT, null=True, blank=True, related_name="entitlement", verbose_name="سفارش")
    note = models.CharField("یادداشت مدیر", max_length=200, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="هدیه‌دهنده",
        help_text="برای هدیه‌ی مدیر؛ خالی یعنی خرید یا دسترسی دستی قدیمی",
    )
    is_archived = models.BooleanField("لغو شده", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دسترسی خریداری‌شده"
        verbose_name_plural = "دسترسی‌های خریداری‌شده"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_archived"])]

    def __str__(self):
        what = self.book or (self.major and f"اشتراک {self.major}") or "اشتراک همه‌ی رشته‌ها"
        return f"{self.user} — {what}"

    @property
    def is_gift(self) -> bool:
        return self.order_id is None and self.granted_by_id is not None

    @classmethod
    def active_for_any(cls, now=None):
        now = now or timezone.now()
        return cls.objects.filter(is_archived=False, starts_at__lte=now).filter(models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=now))

    @classmethod
    def active_for(cls, user, now=None):
        return cls.active_for_any(now).filter(user=user)
