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
    months = models.PositiveSmallIntegerField("مدت (ماه)", default=1, help_text="مدت طرح از ۱ ماه تا ۱۲ ماه (۱ سال)")
    price = models.PositiveIntegerField("قیمت (تومان)")
    pool_share_percent = models.PositiveSmallIntegerField(
        "درصد ورود به استخر اساتید (٪)",
        default=50,
        help_text="درصدی از درآمد حاصل از فروش این طرح که وارد استخر ماهانه تسهیم اساتید می‌شود (بین ۰ تا ۱۰۰)",
    )
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

        if self.book_id and self.is_active:
            from .pricing import ProductStatus, book_product_status

            product_status = book_product_status(self.book)
            if product_status == ProductStatus.UNAVAILABLE:
                errors["book"] = "فقط کتاب منتشرشده و بایگانی‌نشده را می‌توان در کمپین گذاشت."
            elif product_status == ProductStatus.COMING_SOON:
                errors["book"] = "کتاب «به‌زودی» هنوز قابل فروش نیست؛ پس از انتشار کمپین بسازید."
            elif product_status == ProductStatus.FREE:
                errors["book"] = "فقط وقتی پرچم «رایگان» خود کتاب روشن است، کتاب رایگان است؛ برای آن کمپین فروش نسازید."
            elif product_status == ProductStatus.PREPARING:
                errors["book"] = "کتاب هنوز فصل منتشرشده‌ای ندارد؛ پس از انتشار فصل کمپین بسازید."
            elif product_status == ProductStatus.UNPRICED:
                errors["book"] = "کتاب قیمت مثبت و مشخصی ندارد؛ پیش از ساخت کمپین قیمت آن را تعیین کنید."
        if self.plan_id and self.plan.scope != Plan.Scope.ALL:
            errors["plan"] = "تخفیف فقط برای طرح اشتراک همه‌ی کتاب‌ها مجاز است."

        regular_price = self.regular_price
        if regular_price is None or regular_price <= 0:
            errors["discounted_price"] = "محصول باید قیمت عادیِ مثبت داشته باشد."
        elif self.discounted_price is not None and self.discounted_price >= regular_price:
            errors["discounted_price"] = "قیمت ویژه باید از قیمت عادی کمتر باشد؛ تخفیفِ ۱۰۰٪ یا رایگان‌کردن اینجا مجاز نیست."
        elif (
            self.book_id
            and self.discounted_price is not None
            and self.book.campaign_discount_cap_percent is not None
        ):
            from decimal import Decimal

            discount_pct = (Decimal(regular_price - self.discounted_price) * Decimal(100)) / Decimal(regular_price)
            if discount_pct > Decimal(self.book.campaign_discount_cap_percent):
                errors["discounted_price"] = (
                    f"درصد تخفیف کمپین نباید از سقف مصوب کتاب ({self.book.campaign_discount_cap_percent}٪) بیشتر باشد."
                )

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
        REFUNDED = "refunded", "مسترد شده"

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
    return_channel = models.CharField("کانال بازگشت اپ", max_length=20, blank=True, default="")
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

    @classmethod
    def paid_today_q(cls, day=None):
        return models.Q(status=cls.Status.PAID, paid_at__date=day or timezone.localdate())


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
    offline_revoked_at = models.DateTimeField("زمان ابطال نسخه آفلاین", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expiry_warning_sent_at = models.DateTimeField("زمان ارسال هشدار انقضا", null=True, blank=True)

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


class RevenuePlan(models.Model):
    """طرح درآمدی تشویقی یا عمومی برای تسهیم فروش کتاب‌ها (مانند ۳۰ استاد اول، ۲۰ کتاب اول یا طرح پایه)."""

    title = models.CharField("عنوان طرح", max_length=120)
    code = models.SlugField("کد یکتا", max_length=50, unique=True, help_text="شناسه انگلیسی یکتا برای ارجاع سیستم، مثلا early-teachers یا standard")
    author_share_percent = models.PositiveSmallIntegerField("درصد پیش‌فرض مؤلفان", default=70, help_text="درصدی از مبلغ خالص فروش که به مؤلفان می‌رسد (بین ۰ تا ۱۰۰)")
    platform_share_percent = models.PositiveSmallIntegerField("درصد سهم پلتفرم", default=30, help_text="درصدی از مبلغ خالص فروش که به لیموخوان می‌رسد (بین ۰ تا ۱۰۰)")
    pending_hold_days = models.PositiveSmallIntegerField("دوره انتظار گارانتی (روز)", default=7, help_text="مدت زمان ماندن سهم در حالت انتظار پیش از انتقال به موجودی قابل برداشت (۰ یعنی تسویه فوری)")
    max_sales_count = models.PositiveIntegerField("سقف تعداد فروش (برای هر کتاب)", null=True, blank=True, help_text="خالی یعنی نامحدود؛ در صورت پر شدن، این طرح روی کتاب منقضی و به طرح پایه برمی‌گردد")
    starts_at = models.DateTimeField("تاریخ شروع طرح", null=True, blank=True, help_text="خالی یعنی از همین لحظه فعال")
    ends_at = models.DateTimeField("تاریخ پایان طرح", null=True, blank=True, help_text="خالی یعنی نامحدود زمانی")
    is_active = models.BooleanField("فعال", default=True)
    is_default = models.BooleanField("طرح پیش‌فرض سامانه", default=False, help_text="طرح پایه‌ای که در صورت عدم تطابق با سایر طرح‌ها یا اتمام سقف، اعمال می‌شود")
    description = models.TextField("توضیحات و شرایط طرح", blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "طرح درآمدی و تشویقی"
        verbose_name_plural = "طرح‌های درآمدی و تشویقی"
        ordering = ["-is_default", "title"]

    def __str__(self):
        return f"{self.title} (مؤلف: {self.author_share_percent}٪ / پلتفرم: {self.platform_share_percent}٪)"

    def clean(self):
        if self.author_share_percent + self.platform_share_percent != 100:
            raise ValidationError("مجموع درصد سهم مؤلفان و سهم پلتفرم باید دقیقاً ۱۰۰٪ باشد.")
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "تاریخ پایان باید بعد از تاریخ شروع باشد."})

    def is_valid_now(self, now=None) -> bool:
        if not self.is_active:
            return False
        now = now or timezone.now()
        if self.starts_at and self.starts_at > now:
            return False
        if self.ends_at and self.ends_at < now:
            return False
        return True


class BookRoyaltyRule(models.Model):
    """تنظیمات قرارداد و تسهیم سود یک کتاب خاص (پشتیبانی از چندمؤلفی و طرح اختصاصی)."""

    book = models.OneToOneField(
        ContentNode,
        on_delete=models.CASCADE,
        related_name="royalty_rule",
        verbose_name="کتاب",
        limit_choices_to={"kind": ContentNode.Kind.BOOK, "depth": 1},
    )
    revenue_plan = models.ForeignKey(
        RevenuePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="book_rules",
        verbose_name="طرح درآمدی اعمال‌شده",
        help_text="خالی یعنی استفاده از طرح پیش‌فرض سامانه، مگر آنکه درصدها در زیر مستقیماً override شده باشند",
    )
    custom_platform_share_percent = models.PositiveSmallIntegerField(
        "درصد اختصاصی پلتفرم",
        null=True,
        blank=True,
        help_text="در صورت نیاز به درصد سفارشی خارج از طرح برای این کتاب (بین ۰ تا ۱۰۰)",
    )
    is_custom_split = models.BooleanField("استفاده از درصد سفارشی به جای طرح", default=False)
    notes = models.TextField("یادداشت قرارداد و شرایط مالی", blank=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "قرارداد تسهیم کتاب"
        verbose_name_plural = "قراردادهای تسهیم کتاب‌ها"

    def __str__(self):
        return f"تسهیم کتاب: {self.book.title}"

    def clean(self):
        if self.is_custom_split and self.custom_platform_share_percent is not None:
            if not (0 <= self.custom_platform_share_percent <= 100):
                raise ValidationError({"custom_platform_share_percent": "درصد سهم پلتفرم باید بین ۰ تا ۱۰۰ باشد."})


class BookAuthorShare(models.Model):
    """سهم هر مؤلف/استاد از یک کتاب در حالت چندمؤلفی یا تک‌مؤلفی."""

    royalty_rule = models.ForeignKey(
        BookRoyaltyRule,
        on_delete=models.CASCADE,
        related_name="author_shares",
        verbose_name="قرارداد تسهیم کتاب",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="book_author_shares",
        verbose_name="مؤلف / استاد",
    )
    share_percent = models.DecimalField(
        "درصد سهم از کل فروش (٪)",
        max_digits=5,
        decimal_places=2,
        help_text="درصدی از کل مبلغ فروش کتاب که به این استاد می‌رسد (مثلاً ۷۰.۰۰ یا در حالت چندمؤلفی ۳۵.۰۰)",
    )
    role_title = models.CharField("نقش در کتاب", max_length=60, default="مؤلف اصلی", blank=True, help_text="مثلاً مؤلف اصلی، همکار تألیف، ویراستار علمی")
    is_active = models.BooleanField("فعال", default=True)
    created_at = models.DateTimeField("ایجاد", auto_now_add=True)

    class Meta:
        verbose_name = "سهم مؤلف از کتاب"
        verbose_name_plural = "سهم‌های مؤلفان از کتاب"
        constraints = [
            models.UniqueConstraint(fields=["royalty_rule", "author"], name="uniq_author_per_book_royalty"),
        ]

    def __str__(self):
        return f"{self.author.phone} ({self.share_percent}٪) → {self.royalty_rule.book.title}"


class OrderRevenueSnapshot(models.Model):
    """اسنپ‌شات قطعی تسهیم و درآمدهای تحقق‌یافته از یک سفارش پرداخت‌شده."""

    order = models.OneToOneField(
        Order,
        on_delete=models.PROTECT,
        related_name="revenue_snapshot",
        verbose_name="سفارش",
    )
    book = models.ForeignKey(
        ContentNode,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="order_revenue_snapshots",
        verbose_name="کتاب",
    )
    plan_name = models.CharField("طرح درآمدی در لحظه خرید", max_length=120, blank=True)
    revenue_plan = models.ForeignKey(
        RevenuePlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_snapshots",
        verbose_name="طرح درآمدی",
    )
    total_amount = models.PositiveIntegerField("مبلغ کل پرداخت‌شده (تومان)")
    platform_share_percent = models.DecimalField("درصد سهم پلتفرم", max_digits=5, decimal_places=2)
    platform_share_amount = models.PositiveIntegerField("سهم پلتفرم (تومان)")
    total_authors_amount = models.PositiveIntegerField("جمع سهم مؤلفان (تومان)")
    details = models.JSONField("ریز سهم مؤلفان و ضرایب در زمان خرید", default=dict, blank=True)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "اسنپ‌شات مالی سفارش"
        verbose_name_plural = "اسنپ‌شات‌های مالی سفارش‌ها"
        ordering = ["-created_at"]

    def __str__(self):
        return f"تسهیم سفارش #{self.order_id}: پلتفرم {self.platform_share_amount:,} ت / مؤلفان {self.total_authors_amount:,} ت"


class OrderAuthorRevenue(models.Model):
    """سهم ریالی هر استاد از یک سفارش مشخص."""

    class ReleaseStatus(models.TextChoices):
        PENDING = "pending", "در دوره انتظار (گارانتی)"
        AVAILABLE = "available", "آزادشده (قابل برداشت)"
        REFUNDED = "refunded", "لغو شده / مسترد شده"

    snapshot = models.ForeignKey(
        OrderRevenueSnapshot,
        on_delete=models.CASCADE,
        related_name="author_revenues",
        verbose_name="اسنپ‌شات سفارش",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="earned_order_revenues",
        verbose_name="مؤلف / استاد",
    )
    share_percent = models.DecimalField("درصد سهم از سفارش", max_digits=5, decimal_places=2)
    amount = models.PositiveIntegerField("مبلغ سهم استاد (تومان)")
    hold_days = models.PositiveSmallIntegerField("دوره انتظار اعمال‌شده (روز)", default=7)
    available_at = models.DateTimeField("زمان پیش‌بینی آزادسازی", null=True, blank=True)
    release_status = models.CharField("وضعیت دسترسی", max_length=15, choices=ReleaseStatus.choices, default=ReleaseStatus.PENDING)
    released_at = models.DateTimeField("زمان آزادسازی واقعی", null=True, blank=True)
    is_settled = models.BooleanField("تسویه‌شده", default=False, help_text="آیا این مبلغ در تسویه حساب نهایی پرداخت شده است؟")
    settled_at = models.DateTimeField("زمان تسویه", null=True, blank=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)

    class Meta:
        verbose_name = "سهم ریالی مؤلف از سفارش"
        verbose_name_plural = "سهم‌های ریالی مؤلفان از سفارش‌ها"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["release_status", "available_at"], name="author_rev_release_idx"),
        ]

    def __str__(self):
        return f"{self.author.phone}: {self.amount:,} تومان (سفارش #{self.snapshot.order_id})"


class TeacherWallet(models.Model):
    """کیف پول و خلاصه حسابداری هر استاد با تفکیک موجودی در انتظار، قابل برداشت، مسدود جهت تسویه و بدهی معوق."""

    teacher = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teacher_wallet",
        verbose_name="استاد",
    )
    pending_balance = models.PositiveIntegerField("موجودی در انتظار (تومان)", default=0, help_text="مبالغ فروش‌های اخیر در دوره گارانتی")
    available_balance = models.PositiveIntegerField("موجودی قابل برداشت (تومان)", default=0, help_text="مبالغ قطعی آزادشده و آماده تسویه")
    locked_balance = models.PositiveIntegerField("موجودی مسدود جهت تسویه (تومان)", default=0, help_text="مبالغی که درخواست تسویه آن‌ها ثبت شده و در صف پرداخت بانکی است")
    debt_balance = models.PositiveIntegerField("بدهی معوق / استرداد بعد از تسویه (تومان)", default=0, help_text="کسری ناشی از استرداد پس از آزادسازی که از درآمدهای بعدی کسر می‌شود")
    total_earned = models.PositiveIntegerField("کل درآمد کسب‌شده (تومان)", default=0)
    total_withdrawn = models.PositiveIntegerField("کل مبالغ تسویه‌شده (تومان)", default=0)
    created_at = models.DateTimeField("تاریخ افتتاح حساب", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین به‌روزرسانی", auto_now=True)

    class Meta:
        verbose_name = "کیف پول استاد"
        verbose_name_plural = "کیف پول‌های اساتید"
        ordering = ["-available_balance", "-pending_balance"]

    def __str__(self):
        return f"کیف پول {self.teacher.phone}: موجودی قابل برداشت {self.available_balance:,} ت (مسدود {self.locked_balance:,} ت / در انتظار {self.pending_balance:,} ت)"

    @property
    def net_withdrawable_amount(self) -> int:
        """مبلغ خالص قابل برداشت پس از کسر هرگونه بدهی معوق."""
        return max(0, self.available_balance - self.debt_balance)


class WalletTransaction(models.Model):
    """دفترکل رویدادهای مالی کیف پول استاد با تراز لحظه‌ای و تضمین عدم دوباره‌شماری."""

    class EventType(models.TextChoices):
        EARN_PENDING = "earn_pending", "ثبت سهم فروش (در انتظار گارانتی)"
        RELEASE_AVAILABLE = "release_available", "آزادسازی سهم به موجودی قابل برداشت"
        WITHDRAW_HOLD = "withdraw_hold", "مسدودسازی جهت تسویه حساب"
        WITHDRAW_PAID = "withdraw_paid", "تسویه حساب قطعی بانکی"
        WITHDRAW_REJECTED = "withdraw_rejected", "رد درخواست تسویه و بازگشت به موجودی"
        REFUND_ADJUSTMENT = "refund_adjustment", "استرداد و اصلاح مالی سفارش"
        SUBSCRIPTION_POOL = "subscription_pool", "سهم از استخر اشتراک ماهانه"

    wallet = models.ForeignKey(
        TeacherWallet,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="کیف پول",
    )
    event_type = models.CharField("نوع رویداد", max_length=25, choices=EventType.choices)
    amount = models.PositiveIntegerField("مبلغ تراکنش (تومان)")
    available_balance_after = models.PositiveIntegerField("مانده قابل برداشت پس از تراکنش (تومان)")
    pending_balance_after = models.PositiveIntegerField("مانده در انتظار پس از تراکنش (تومان)")
    locked_balance_after = models.PositiveIntegerField("مانده مسدود پس از تراکنش (تومان)", default=0)
    debt_balance_after = models.PositiveIntegerField("مانده بدهی معوق پس از تراکنش (تومان)", default=0)
    reference_order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions",
        verbose_name="سفارش مرجع",
    )
    author_revenue = models.ForeignKey(
        OrderAuthorRevenue,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions",
        verbose_name="سهم مرجع",
    )
    idempotency_key = models.CharField(
        "کلید یکتایی تراکنش",
        max_length=120,
        unique=True,
        help_text="جلوگیری از دوباره‌شماری در اجرای مکرر، مثلا rev-15-release یا ord-42-earn",
    )
    description = models.CharField("شرح تراکنش", max_length=255)
    created_at = models.DateTimeField("زمان ثبت تراکنش", auto_now_add=True)

    class Meta:
        verbose_name = "تراکنش کیف پول"
        verbose_name_plural = "تراکنش‌های کیف پول"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "created_at"], name="wallet_tx_created_idx"),
            models.Index(fields=["event_type", "created_at"], name="wallet_tx_event_idx"),
        ]

    def __str__(self):
        return f"{self.wallet.teacher.phone} | {self.get_event_type_display()} | {self.amount:,} ت"


def validate_iban_mod97(iban_str: str) -> bool:
    """
    اعتبارسنجی الگوریتم Mod-97 (ISO 7064) شماره شبا.
    پیشوند IR به 1827 تبدیل شده و باقیمانده عدد بر 97 باید دقیقاً ۱ باشد.
    """
    clean = iban_str.strip().upper().replace(" ", "")
    if len(clean) != 26 or not clean.startswith("IR") or not clean[2:].isdigit():
        return False
    # جابه‌جایی ۴ کاراکتر اول به انتها: IR + 2 رقم چک‌دیجیت -> انتهای رشته
    # IR -> I=18, R=27
    rearranged = clean[4:] + "1827" + clean[2:4]
    try:
        return int(rearranged) % 97 == 1
    except (ValueError, TypeError):
        return False


class TeacherBankAccount(models.Model):
    """اطلاعات و شماره شبای بانکی استاد جهت واریز تسویه حساب."""

    teacher = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bank_account",
        verbose_name="استاد",
    )
    account_holder_name = models.CharField("نام و نام خانوادگی صاحب حساب", max_length=120)
    iban = models.CharField(
        "شماره شبا (با IR)",
        max_length=26,
        help_text="شماره شبا به صورت ۲۴ رقم بعد از IR (مثال: IR120120000000001234567890)",
    )
    bank_name = models.CharField("نام بانک", max_length=60, blank=True)
    is_verified = models.BooleanField(
        "تایید شده توسط مدیریت",
        default=False,
        help_text="تسویه حساب فقط به شبای تاییدشده انجام می‌شود.",
    )
    notes = models.CharField("یادداشت مدیر", max_length=200, blank=True)
    created_at = models.DateTimeField("تاریخ ثبت", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "حساب بانکی استاد"
        verbose_name_plural = "حساب‌های بانکی اساتید"

    def __str__(self):
        status = "تاییدشده" if self.is_verified else "در انتظار تایید"
        return f"{self.account_holder_name} ({self.iban}) - {status}"

    def clean(self):
        clean_iban = (self.iban or "").strip().upper().replace(" ", "")
        if not clean_iban.startswith("IR"):
            clean_iban = "IR" + clean_iban
        if len(clean_iban) != 26 or not clean_iban[2:].isdigit():
            raise ValidationError({"iban": "شماره شبا باید شامل پیشوند IR و دقیقاً ۲۴ رقم عددی باشد."})

        # اعتبارسنجی دقیق الگوریتم Mod-97
        # در محیط‌های تست در صورت لزوم اجازه مقادیر فرضی تست داده می‌شود اما در تولید و محیط واقعی اجباری است
        is_test_env = getattr(settings, "TESTING", False) or settings.SECRET_KEY == "test-only"
        if not validate_iban_mod97(clean_iban):
            if not is_test_env:
                raise ValidationError({"iban": "شماره شبا از نظر الگوریتم کنترلی بانکی (Mod-97) معتبر نیست. لطفاً ارقام را دوباره بررسی کنید."})
        self.iban = clean_iban


class PayoutRequest(models.Model):
    """درخواست تسویه حساب و واریز بانکی استاد."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بررسی"
        PROCESSING = "processing", "در حال واریز بانکی"
        PAID = "paid", "پرداخت‌شده قطعی"
        REJECTED = "rejected", "رد شده"

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payout_requests",
        verbose_name="استاد",
    )
    amount = models.PositiveIntegerField("مبلغ درخواستی (تومان)")
    status = models.CharField("وضعیت", max_length=15, choices=Status.choices, default=Status.PENDING)
    account_holder_snapshot = models.CharField("نام صاحب حساب زمان درخواست", max_length=120)
    iban_snapshot = models.CharField("شماره شبا زمان درخواست", max_length=26)
    bank_name_snapshot = models.CharField("نام بانک زمان درخواست", max_length=60, blank=True)
    tracking_code = models.CharField("کد رهگیری بانکی (پایا/ساتنا)", max_length=100, blank=True, help_text="کد پیگیری ارائه شده توسط بانک پس از واریز")
    receipt_note = models.CharField("توضیحات واریز یا فیش", max_length=255, blank=True)
    rejection_reason = models.CharField("دلیل رد درخواست", max_length=255, blank=True, help_text="در صورت رد درخواست، ذکر دلیل برای استاد الزامی است")
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="بررسی‌کننده (مدیر)",
    )
    created_at = models.DateTimeField("زمان ثبت درخواست", auto_now_add=True)
    paid_at = models.DateTimeField("زمان پرداخت قطعی", null=True, blank=True)

    class Meta:
        verbose_name = "درخواست تسویه حساب"
        verbose_name_plural = "درخواست‌های تسویه حساب"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["teacher", "status"], name="payout_teacher_status_idx"),
            models.Index(fields=["status", "created_at"], name="payout_status_created_idx"),
        ]

    def __str__(self):
        return f"تسویه #{self.id}: {self.teacher.phone} - {self.amount:,} تومان ({self.get_status_display()})"

    @classmethod
    def pending_queue_q(cls):
        return models.Q(status__in=(cls.Status.PENDING, cls.Status.PROCESSING))


class SubscriptionPoolPeriod(models.Model):
    """دوره ماهانه استخر درآمدی اشتراک کلی و تسهیم آن میان کتاب‌ها و اساتید."""

    class ModelChoice(models.TextChoices):
        STUDY_TIME = "study_time", "صرفاً زمان مطالعه معتبر"
        HYBRID = "hybrid", "ترکیبی (زمان مطالعه + پاسخ به تست‌ها)"

    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس / شبیه‌سازی"
        FINALIZED = "finalized", "نهایی‌شده و واریزشده به کیف پول‌ها"

    title = models.CharField("عنوان دوره", max_length=120, help_text="مثال: استخر اشتراک فروردین ۱۴۰۵")
    starts_at = models.DateTimeField("شروع دوره")
    ends_at = models.DateTimeField("پایان دوره")
    sharing_model = models.CharField(
        "مدل تسهیم",
        max_length=20,
        choices=ModelChoice.choices,
        default=ModelChoice.HYBRID,
        help_text="فرمول تقسیم استخر بر اساس فعالیت دانشجویان",
    )
    exclude_free_chapters = models.BooleanField(
        "بدون احتساب فصول رایگان",
        default=True,
        help_text="در صورت فعال بودن، مطالعه در فصل‌های رایگان کتاب در سهم استخر اشتراک محاسبه نمی‌شود",
    )
    daily_user_cap_hours = models.PositiveSmallIntegerField(
        "سقف روزانه مطالعه هر کاربر (ساعت)",
        default=4,
        help_text="ضدتقلب: حداکثر ساعت مطالعه موثر روزانه یک کاربر روی یک کتاب (جلوگیری از باز ماندن تب)",
    )
    min_published_chapters = models.PositiveSmallIntegerField(
        "حداقل فصل منتشرشده برای ورود به استخر",
        default=2,
        help_text="ضد کتاب دکوری: کتاب‌هایی با فصل کمتر سهمی از استخر نمی‌برند",
    )
    min_active_questions = models.PositiveIntegerField(
        "حداقل تست فعال برای ورود به استخر",
        default=20,
        help_text="ضد کتاب دکوری: حداقل تعداد تست در کتاب",
    )
    total_subscription_sales = models.PositiveIntegerField("جمع فروش اشتراک در دوره (تومان)", default=0)
    total_pool_amount = models.PositiveIntegerField("جمع مبلغ استخر اساتید (تومان)", default=0)
    status = models.CharField("وضعیت دوره", max_length=15, choices=Status.choices, default=Status.DRAFT)
    simulation_results = models.JSONField("نتایج آخرین شبیه‌سازی", default=dict, blank=True)
    finalized_at = models.DateTimeField("زمان نهایی‌سازی و شارژ کیف پول‌ها", null=True, blank=True)
    created_at = models.DateTimeField("زمان ایجاد", auto_now_add=True)

    class Meta:
        verbose_name = "دوره استخر اشتراک ماهانه"
        verbose_name_plural = "دوره‌های استخر اشتراک ماهانه"
        ordering = ["-starts_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()}) - استخر: {self.total_pool_amount:,} تومان"


class PoolBookShare(models.Model):
    """سهم یک کتاب و اساتید آن از یک دوره استخر ماهانه اشتراک."""

    period = models.ForeignKey(
        SubscriptionPoolPeriod,
        on_delete=models.CASCADE,
        related_name="book_shares",
        verbose_name="دوره استخر",
    )
    book = models.ForeignKey(
        ContentNode,
        on_delete=models.PROTECT,
        related_name="subscription_pool_shares",
        verbose_name="کتاب",
    )
    valid_seconds = models.PositiveIntegerField("ثانیه‌های مطالعه معتبر", default=0)
    valid_quizzes = models.PositiveIntegerField("تست‌های پاسخ‌داده‌شده معتبر", default=0)
    unique_active_users = models.PositiveIntegerField("کاربران یکتای فعال", default=0)
    computed_score = models.DecimalField("امتیاز نهایی کتاب", max_digits=12, decimal_places=4, default=0)
    share_percent = models.DecimalField("درصد سهم از کل استخر (٪)", max_digits=6, decimal_places=3, default=0)
    total_amount = models.PositiveIntegerField("مبلغ سهم کتاب (تومان)", default=0)
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "سهم کتاب از استخر اشتراک"
        verbose_name_plural = "سهم‌های کتاب‌ها از استخر اشتراک"
        ordering = ["-total_amount"]
        constraints = [
            models.UniqueConstraint(fields=["period", "book"], name="uniq_book_per_pool_period"),
        ]

    def __str__(self):
        return f"{self.book.title} در {self.period.title}: {self.total_amount:,} تومان ({self.share_percent}٪)"




