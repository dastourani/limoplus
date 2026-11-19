"""
Sales: single books and subscriptions.

Rules (see CLAUDE.md): prices are computed only here on the server; the verified amount must equal the order amount;
paying an order and granting access happen in one transaction with the order row locked. Nothing is ever deleted —
orders keep their history and entitlements are archived instead of removed.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.catalog.models import ContentNode, Major


class Plan(models.Model):
    """A subscription offer. Prices are edited in the admin."""

    class Scope(models.TextChoices):
        MAJOR = "major", "یک رشته (دیگر فروخته نمی‌شود)"
        ALL = "all", "همه‌ی کتاب‌ها"

    title = models.CharField("عنوان", max_length=80)
    scope = models.CharField("دامنه", max_length=10, choices=Scope.choices, default=Scope.ALL,
                             help_text="فقط «همه‌ی کتاب‌ها» در اپ فروخته می‌شود.")
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


class SaleCampaign(models.Model):
    """One time-bounded, non-stackable price for a public book or an all-books subscription plan."""

    title = models.CharField("نام کمپین", max_length=120)
    book = models.ForeignKey(
        ContentNode,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_campaigns",
        verbose_name="کتاب",
        limit_choices_to={"kind": ContentNode.Kind.BOOK, "depth": 1},
    )
    plan = models.ForeignKey(
        "Plan",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="sale_campaigns",
        verbose_name="طرح اشتراک",
        limit_choices_to={"scope": "all"},
    )
    discounted_price = models.PositiveIntegerField("قیمت ویژه (تومان)")
    starts_at = models.DateTimeField("شروع کمپین")
    ends_at = models.DateTimeField("پایان کمپین")
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "کمپین تخفیف زمان‌دار"
        verbose_name_plural = "کمپین‌های تخفیف زمان‌دار"
        ordering = ["-starts_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(book__isnull=False, plan__isnull=True)
                | models.Q(book__isnull=True, plan__isnull=False),
                name="sale_campaign_one_product",
            ),
            models.CheckConstraint(condition=models.Q(discounted_price__gt=0), name="sale_campaign_price_positive"),
        ]
        indexes = [models.Index(fields=["is_active", "starts_at", "ends_at"], name="sale_campaign_window_idx")]

    def __str__(self):
        return self.title

    @property
    def regular_price(self):
        if self.book_id:
            return self.book.price
        if self.plan_id:
            return self.plan.price
        return None

    @property
    def product_title(self):
        if self.book_id:
            return self.book.title
        if self.plan_id:
            return self.plan.title
        return ""

    def clean(self):
        errors = {}
        if bool(self.book_id) == bool(self.plan_id):
            errors["book"] = "برای هر کمپین دقیقاً یک کتاب یا یک طرح اشتراک انتخاب کنید."
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors["ends_at"] = "زمان پایان باید بعد از زمان شروع باشد."

        if self.book_id:
            if self.book.kind != ContentNode.Kind.BOOK or self.book.depth != 1 or self.book.is_inbox:
                errors["book"] = "تخفیف فقط برای یک کتاب واقعی (نه فصل یا صندوق تست) ساخته می‌شود."
            if self.book.is_archived or self.book.is_inbox:
                errors["book"] = "برای کتاب بایگانی‌شده یا صندوق تست کمپین تخفیف نسازید."
            if self.book.is_free:
                errors["book"] = "رایگان‌بودن تصمیم مستقلی است؛ برای کتابی که مدیر رایگان کرده کمپین فروش نسازید."
            if self.book.is_coming_soon:
                errors["book"] = "کتاب «به‌زودی» هنوز قابل فروش نیست؛ پس از آماده‌شدن کمپین بسازید."
        if self.plan_id and self.plan.scope != Plan.Scope.ALL:
            errors["plan"] = "تخفیف فقط برای طرح اشتراک همه‌ی کتاب‌ها مجاز است."

        regular_price = self.regular_price
        if regular_price is None or regular_price <= 0:
            errors["discounted_price"] = "محصول باید قیمت عادیِ مثبت داشته باشد."
        elif self.discounted_price is not None and self.discounted_price >= regular_price:
            errors["discounted_price"] = "قیمت ویژه باید از قیمت عادی کمتر باشد؛ تخفیفِ ۱۰۰٪ یا رایگان‌کردن اینجا مجاز نیست."

        if self.is_active and self.starts_at and self.ends_at and (self.book_id or self.plan_id):
            overlapping = SaleCampaign.objects.filter(
                is_active=True,
                starts_at__lt=self.ends_at,
                ends_at__gt=self.starts_at,
            )
            overlapping = overlapping.filter(book_id=self.book_id) if self.book_id else overlapping.filter(plan_id=self.plan_id)
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            if overlapping.exists():
                errors["starts_at"] = "برای همین محصول بازه‌ی این کمپین با کمپین فعال دیگری هم‌پوشانی دارد؛ تخفیف‌ها با هم جمع نمی‌شوند."

        if errors:
            raise ValidationError(errors)


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
    amount = models.PositiveIntegerField("مبلغ نهایی (تومان)")
    # Financial snapshot: later campaign or product edits never change a pending or paid receipt.
    regular_amount = models.PositiveIntegerField("قیمت عادی زمان سفارش (تومان)", null=True, blank=True)
    discount_amount = models.PositiveIntegerField("تخفیف زمان سفارش (تومان)", default=0)
    campaign_title_snapshot = models.CharField("نام کمپین زمان سفارش", max_length=120, blank=True)
    campaign_id_snapshot = models.PositiveIntegerField("شناسه‌ی کمپین زمان سفارش", null=True, blank=True)
    # The plan's terms when the order was made: a later change to the plan doesn't change what was bought.
    plan_months = models.PositiveSmallIntegerField("مدت خریده‌شده (ماه)", null=True, blank=True)
    plan_scope = models.CharField("دامنه‌ی خریده‌شده", max_length=10, blank=True)
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
            ),
            models.CheckConstraint(
                condition=models.Q(regular_amount__isnull=True)
                | models.Q(amount=models.F("regular_amount") - models.F("discount_amount")),
                name="order_price_snapshot_matches",
            ),
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
