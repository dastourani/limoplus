"""The public website (limookhan.ir): its editable texts. Pages are drawn by apps/website/views.py from the same
database as the app, so books, prices and sample tests appear by themselves."""
import hashlib
import hmac
import secrets
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def default_teacher_invitation_expiry():
    return timezone.now() + timedelta(hours=72)


class SiteSettings(models.Model):
    """One row: contact details, store links and the trust seal. Edited in the panel («تنظیمات سایت»)."""

    DEFAULT_PREPARING_HOVER_NOTE = "در صف تولید محتوا قرار دارد."
    DEFAULT_PREPARING_NOTE = (
        "قرارداد تألیف این منبع ثبت شده و در صف تولید محتوا قرار دارد. به محض آماده شدن اولین فصل، "
        "وضعیت آن به «به‌زودی» تغییر می‌کند و امکان ثبت اطلاع‌رسانی یا مطالعهٔ نمونهٔ رایگان فعال می‌شود."
    )
    DEFAULT_COMING_SOON_NOTE = (
        "با ثبت «خبرم کن» در اپلیکیشن یا وب‌اپ لیموخوان، به محض انتشار فصل اول رایگان با پیامک به شما اطلاع می‌دهیم."
    )

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
    preparing_hover_note = models.CharField(
        "متن کوتاه هاور «در حال برنامه‌ریزی»",
        max_length=160,
        blank=True,
        default=DEFAULT_PREPARING_HOVER_NOTE,
        help_text="متن کوتاه روی کارت کتاب‌های «در حال برنامه‌ریزی» هنگام هاور در صفحه‌ی اول و فهرست کتاب‌ها (برای کتاب‌هایی که توضیح اختصاصی ندارند).",
    )
    preparing_note = models.TextField(
        "متن کامل صفحه‌ی کتاب «در حال برنامه‌ریزی»",
        blank=True,
        default=DEFAULT_PREPARING_NOTE,
        help_text="در صفحه‌ی کتاب (سایت و اپ/وب‌اپ) نمایش داده می‌شود؛ اگر روی خود کتاب «توضیح اختصاصی وضعیت انتشار» بنویسید، متن همان کتاب جایگزین می‌شود.",
    )
    coming_soon_note = models.TextField(
        "متن کامل صفحه‌ی کتاب «به‌زودی»",
        blank=True,
        default=DEFAULT_COMING_SOON_NOTE,
        help_text="در صفحه‌ی کتاب (سایت و اپ/وب‌اپ) نمایش داده می‌شود؛ اگر روی خود کتاب «توضیح اختصاصی وضعیت انتشار» بنویسید، متن همان کتاب جایگزین می‌شود.",
    )
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


class TeacherApplication(models.Model):
    """A public request for review. Approval records a decision only: it never creates or grants an account or access."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بازبینی"
        NEEDS_INFO = "needs_info", "نیازمند اطلاعات تکمیلی"
        APPROVED = "approved", "تأیید درخواست (بدون دسترسی)"
        REJECTED = "rejected", "ردشده"

    class CollaborationScope(models.TextChoices):
        PUBLIC_AND_CLASS = "public_and_class", "عرضه در ویترین لیموخوان و کلاس‌های اختصاصی"
        CLASS_ONLY = "class_only", "استفاده در کلاس اختصاصی دانشجویان خودم (رایگان)"
        PUBLIC_ONLY = "public_only", "عرضهٔ عمومی در ویترین لیموخوان"

    name = models.CharField("نام و نام خانوادگی", max_length=120)
    phone = models.CharField("شماره‌ی موبایل", max_length=11, db_index=True)
    book_or_link = models.CharField("رشته و عنوان کتاب یا درس پیشنهادی", max_length=300)
    resume_url = models.URLField("لینک صفحه معرفی یا رزومه", max_length=500, blank=True, default="")
    collaboration_scope = models.CharField(
        "نحوه استفاده پیشنهادی",
        max_length=20,
        choices=CollaborationScope.choices,
        default=CollaborationScope.PUBLIC_AND_CLASS,
    )
    explanation = models.TextField("توضیحات تکمیلی یا سابقه تدریس", max_length=2000, blank=True, default="")
    sample_work = models.TextField("توضیح کوتاه نمونه‌کار یا شواهد", max_length=3000, blank=True, default="")
    status = models.CharField(
        "وضعیت",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text="تأیید فقط پذیرش این درخواست است؛ ساخت حساب و هر نوع دسترسی/دعوت باید جداگانه در مرحله‌ی بعد تصویب شود.",
    )
    review_note = models.TextField(
        "یادداشت داخلی بازبینی",
        max_length=2000,
        blank=True,
        help_text="یادداشت داخلی پنل است؛ پیام یا دعوتی برای درخواست‌دهنده ارسال نمی‌شود.",
    )
    submitted_at = models.DateTimeField("زمان ثبت", auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_teacher_applications",
        verbose_name="آخرین بازبین",
        editable=False,
    )
    reviewed_at = models.DateTimeField("زمان آخرین بازبینی", null=True, blank=True, editable=False)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "درخواست همکاری آموزشی"
        verbose_name_plural = "درخواست‌های همکاری آموزشی"
        ordering = ["-submitted_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["phone"],
                condition=models.Q(status__in=["pending", "needs_info", "approved"]),
                name="uniq_active_teacher_app_phone",
            ),
        ]
        indexes = [models.Index(fields=["status", "-submitted_at"], name="teacher_app_status_time_idx")]

    def __str__(self):
        return f"{self.name} · {self.phone}"


class TeacherInvitation(models.Model):
    """A manager-issued, hashed, one-use link for an already-approved teacher application."""

    class Status(models.TextChoices):
        ISSUED = "issued", "صادرشده"
        ACCEPTED = "accepted", "پذیرفته‌شده"
        REVOKED = "revoked", "لغوشده"
        EXPIRED = "expired", "منقضی‌شده"

    application = models.ForeignKey(
        TeacherApplication, on_delete=models.PROTECT, related_name="invitations", verbose_name="درخواست تأییدشده"
    )
    book = models.ForeignKey(
        "catalog.ContentNode", on_delete=models.PROTECT, related_name="teacher_invitations", verbose_name="کتاب"
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField("انقضای پیوند", default=default_teacher_invitation_expiry)
    status = models.CharField("وضعیت", max_length=10, choices=Status.choices, default=Status.ISSUED, db_index=True)
    can_edit_content = models.BooleanField("ویرایش پیش‌نویس", default=False)
    can_request_publication = models.BooleanField("درخواست بازبینی انتشار عمومی", default=False)
    can_request_group_access = models.BooleanField("درخواست دسترسی گروهی", default=False)
    can_view_reports = models.BooleanField("دیدن گزارش ایرادهای همین کتاب", default=False)
    can_view_aggregate_study = models.BooleanField("دیدن آمار تجمیعی مطالعه", default=False)
    can_view_aggregate_sales = models.BooleanField("دیدن آمار تجمیعی فروش", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_teacher_invitations", verbose_name="دعوت‌کننده"
    )
    created_at = models.DateTimeField("زمان صدور", auto_now_add=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="accepted_teacher_invitations", verbose_name="پذیرنده", editable=False,
    )
    accepted_at = models.DateTimeField("زمان پذیرش", null=True, blank=True, editable=False)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="revoked_teacher_invitations", verbose_name="لغوکننده", editable=False,
    )
    revoked_at = models.DateTimeField("زمان لغو", null=True, blank=True, editable=False)
    revocation_reason = models.CharField("دلیل لغو", max_length=500, blank=True)

    class Meta:
        verbose_name = "دعوت استاد"
        verbose_name_plural = "دعوت‌های استاد"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "book"], condition=models.Q(status="issued"), name="uniq_inv_app_book_issued"
            ),
        ]
        indexes = [models.Index(fields=["status", "expires_at"], name="teacher_inv_status_exp_idx")]

    @staticmethod
    def digest_token(token: str) -> str:
        return hmac.new(settings.HASH_KEY.encode(), f"teacher-invite:{token}".encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @property
    def phone(self):
        return self.application.phone

    def clean(self):
        errors = {}
        if self.application_id and self.application.status != TeacherApplication.Status.APPROVED:
            errors["application"] = "فقط درخواست تأییدشده را می‌توان به دعوت استاد وصل کرد."
        if self.book_id and (
            self.book.kind != "book" or self.book.depth != 1 or self.book.is_inbox or self.book.is_archived
        ):
            errors["book"] = "فقط یک کتاب فعال (نه فصل، بخش یا صندوق تست) را انتخاب کنید."
        if self.expires_at and self.expires_at <= timezone.now() and self._state.adding:
            errors["expires_at"] = "زمان انقضا باید در آینده باشد."
        if not any((self.can_edit_content, self.can_request_publication, self.can_request_group_access,
                    self.can_view_reports, self.can_view_aggregate_study, self.can_view_aggregate_sales)):
            errors["can_edit_content"] = "دست‌کم یک قابلیت محدود برای این کتاب انتخاب کنید."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"دعوت {self.application.phone} برای «{self.book.title}»"


class BookAccessRequest(models.Model):
    """An immutable proposed phone list; only a superuser may approve it and choose its expiry policy."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بازبینی"
        NEEDS_INFO = "needs_info", "نیازمند اطلاعات تکمیلی"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    class ExpiryPolicy(models.TextChoices):
        FIXED_DATE = "fixed_date", "تاریخ پایان مشترک"
        FROM_ACTIVATION = "from_activation", "مدت از نخستین ورود با OTP هر نفر"

    book = models.ForeignKey(
        "catalog.ContentNode", on_delete=models.PROTECT, related_name="group_access_requests", verbose_name="کتاب"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_group_access_requests", verbose_name="درخواست‌دهنده"
    )
    request_note = models.TextField("توضیح برای مدیر", blank=True, max_length=1000)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    review_note = models.TextField("یادداشت داخلی/علت تصمیم", blank=True, max_length=2000)
    expiry_policy = models.CharField("سیاست انقضا", max_length=20, choices=ExpiryPolicy.choices, blank=True)
    ends_on = models.DateField("تاریخ پایان مشترک", null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField("مدت از فعال‌سازی (روز)", null=True, blank=True)
    submitted_at = models.DateTimeField("زمان ثبت", auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="reviewed_group_access_requests", verbose_name="تصمیم‌گیرنده", editable=False,
    )
    reviewed_at = models.DateTimeField("زمان آخرین تصمیم", null=True, blank=True, editable=False)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "درخواست دسترسی گروهی"
        verbose_name_plural = "درخواست‌های دسترسی گروهی"
        ordering = ["-submitted_at", "-pk"]
        indexes = [models.Index(fields=["book", "status", "-submitted_at"], name="group_req_book_state_idx")]

    def clean(self):
        errors = {}
        if self.book_id and (
            self.book.kind != "book" or self.book.depth != 1 or self.book.is_inbox or self.book.is_archived
        ):
            errors["book"] = "فقط یک کتاب فعال (نه فصل، بخش یا صندوق تست) را انتخاب کنید."
        if self.status in (self.Status.NEEDS_INFO, self.Status.APPROVED, self.Status.REJECTED) and not (self.review_note or "").strip():
            errors["review_note"] = "برای ثبت تصمیم مدیر، دلیل یا یادداشت را وارد کنید."
        if self.status == self.Status.APPROVED:
            if self.expiry_policy == self.ExpiryPolicy.FIXED_DATE:
                if not self.ends_on or self.duration_days is not None:
                    errors["expiry_policy"] = "برای تاریخ پایان مشترک فقط «تاریخ پایان» را وارد کنید."
                elif self.ends_on < timezone.localdate():
                    errors["ends_on"] = "تاریخ پایان نمی‌تواند گذشته باشد."
            elif self.expiry_policy == self.ExpiryPolicy.FROM_ACTIVATION:
                if self.duration_days is None or self.ends_on is not None:
                    errors["expiry_policy"] = "برای مدت از فعال‌سازی فقط تعداد روز را وارد کنید."
                elif not 1 <= self.duration_days <= 3650:
                    errors["duration_days"] = "مدت باید بین ۱ تا ۳۶۵۰ روز باشد."
            else:
                errors["expiry_policy"] = "سیاست انقضای دسترسی را انتخاب کنید."
        elif self.expiry_policy or self.ends_on or self.duration_days is not None:
            errors["expiry_policy"] = "سیاست و مدت دسترسی فقط هنگام تأیید مدیر تعیین می‌شود."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"درخواست #{self.pk or 'جدید'} · {self.book}"


class BookAccessMember(models.Model):
    """One submitted phone. No account or entitlement exists until the request is approved and that phone logs in by OTP."""

    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", "در انتظار تصمیم مدیر"
        WAITING_OTP = "waiting_otp", "تأییدشده، در انتظار ورود با OTP"
        ACTIVE = "active", "فعال"
        EXPIRED = "expired", "منقضی‌شده"
        REVOKED = "revoked", "لغوشده"
        REJECTED = "rejected", "ردشده"

    request = models.ForeignKey(
        BookAccessRequest, on_delete=models.PROTECT, related_name="members", verbose_name="درخواست"
    )
    book = models.ForeignKey(
        "catalog.ContentNode", on_delete=models.PROTECT, related_name="group_access_members", verbose_name="کتاب"
    )
    phone = models.CharField("شماره‌ی نرمال‌شده", max_length=11, db_index=True)
    status = models.CharField("وضعیت شماره", max_length=16, choices=Status.choices, default=Status.PENDING_REVIEW, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="group_book_access_memberships", verbose_name="کاربر متصل", editable=False,
    )
    entitlement = models.OneToOneField(
        "commerce.Entitlement", on_delete=models.PROTECT, null=True, blank=True,
        related_name="group_access_member", verbose_name="ردیف دسترسی", editable=False,
    )
    activated_at = models.DateTimeField("زمان فعال‌سازی با OTP", null=True, blank=True, editable=False)
    created_at = models.DateTimeField("زمان ثبت شماره", auto_now_add=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="revoked_group_book_members", verbose_name="لغوکننده", editable=False,
    )
    revoked_at = models.DateTimeField("زمان لغو", null=True, blank=True, editable=False)
    revocation_reason = models.CharField("علت لغو", max_length=500, blank=True)

    class Meta:
        verbose_name = "شماره‌ی دسترسی گروهی"
        verbose_name_plural = "شماره‌های دسترسی گروهی"
        ordering = ["phone", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["request", "phone"], name="uniq_req_member_phone"),
        ]
        indexes = [models.Index(fields=["book", "phone", "status"], name="ga_member_book_phone_idx")]

    def clean(self):
        if self.request_id and self.book_id and self.request.book_id != self.book_id:
            raise ValidationError({"book": "کتاب این شماره باید با کتاب همان درخواست یکی باشد."})
        from apps.accounts.phone import InvalidPhone, normalize_phone

        try:
            self.phone = normalize_phone(self.phone)
        except InvalidPhone as exc:
            raise ValidationError({"phone": str(exc)}) from exc

    @property
    def is_active(self):
        return bool(
            self.status == self.Status.ACTIVE and self.entitlement_id
            and self.entitlement.is_archived is False
            and self.entitlement.starts_at <= timezone.now()
            and (self.entitlement.ends_at is None or self.entitlement.ends_at > timezone.now())
        )

    def __str__(self):
        return f"{self.book} · {self.phone}"


class BookAccessEvent(models.Model):
    """An append-only audit trail for a group access activation, renewal or revocation."""

    class Action(models.TextChoices):
        ACTIVATED = "activated", "فعال‌سازی با OTP"
        RENEWED = "renewed", "تمدید توسط مدیر"
        REVOKED = "revoked", "لغو توسط مدیر"

    member = models.ForeignKey(BookAccessMember, on_delete=models.PROTECT, related_name="events", verbose_name="شماره")
    action = models.CharField("رویداد", max_length=12, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="group_access_events", verbose_name="ثبت‌کننده",
    )
    reason = models.CharField("دلیل", max_length=500, blank=True)
    previous_ends_at = models.DateTimeField("پایان قبلی", null=True, blank=True)
    new_ends_at = models.DateTimeField("پایان جدید", null=True, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "رویداد دسترسی گروهی"
        verbose_name_plural = "رویدادهای دسترسی گروهی"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()} · {self.member}"


class BookAccessRequestEvent(models.Model):
    """Immutable manager decision history for a proposed private/group phone list."""

    class Action(models.TextChoices):
        SUBMITTED = "submitted", "ثبت پیشنهاد"
        NEEDS_INFO = "needs_info", "درخواست اطلاعات تکمیلی"
        APPROVED = "approved", "تأیید مدیر کل"
        REJECTED = "rejected", "رد مدیر کل"
        REOPENED = "reopened", "بازگشایی برای بازبینی"
        NOTE_UPDATED = "note_updated", "به‌روزرسانی یادداشت"

    request = models.ForeignKey(
        BookAccessRequest, on_delete=models.PROTECT, related_name="events", verbose_name="درخواست"
    )
    action = models.CharField("رویداد", max_length=16, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="group_access_request_events", verbose_name="ثبت‌کننده",
    )
    reason = models.CharField("دلیل/یادداشت تصمیم", max_length=500, blank=True)
    expiry_policy = models.CharField("سیاست انقضای مصوب", max_length=20, blank=True)
    ends_on = models.DateField("تاریخ پایان مصوب", null=True, blank=True)
    duration_days = models.PositiveSmallIntegerField("مدت مصوب (روز)", null=True, blank=True)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "رویداد تصمیم دسترسی گروهی"
        verbose_name_plural = "رویدادهای تصمیم دسترسی گروهی"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()} · درخواست #{self.request_id}"


class PublicationRequest(models.Model):
    """A teacher's request to publish one exact content snapshot; only a superuser may approve and release it."""

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار بازبینی"
        NEEDS_INFO = "needs_info", "نیازمند اصلاح یا اطلاعات"
        APPROVED = "approved", "تأیید و انتشار شد"
        REJECTED = "rejected", "ردشده"

    book = models.ForeignKey(
        "catalog.ContentNode", on_delete=models.PROTECT, related_name="publication_requests", verbose_name="کتاب"
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_publication_requests", verbose_name="درخواست‌دهنده"
    )
    request_note = models.TextField("توضیح برای مدیر", blank=True, max_length=1000)
    content_digest = models.CharField("شناسه‌ی نسخه‌ی درخواستی", max_length=64, editable=False)
    status = models.CharField("وضعیت", max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    review_note = models.TextField("یادداشت داخلی/علت تصمیم", blank=True, max_length=2000)
    submitted_at = models.DateTimeField("زمان ثبت", auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="reviewed_publication_requests", verbose_name="تصمیم‌گیرنده", editable=False,
    )
    reviewed_at = models.DateTimeField("زمان آخرین تصمیم", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "درخواست بازبینی انتشار عمومی"
        verbose_name_plural = "درخواست‌های بازبینی انتشار عمومی"
        ordering = ["-submitted_at", "-pk"]
        indexes = [models.Index(fields=["book", "status", "-submitted_at"], name="pub_req_book_state_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "requested_by", "content_digest"],
                condition=models.Q(status__in=["pending", "needs_info"]),
                name="uniq_pending_pub_req_snapshot",
            ),
        ]

    def clean(self):
        if self.book_id and (
            self.book.kind != "book" or self.book.depth != 1 or self.book.is_inbox or self.book.is_archived
        ):
            raise ValidationError({"book": "فقط یک کتاب فعال (نه فصل، بخش یا صندوق تست) را انتخاب کنید."})
        if self.content_digest and len(self.content_digest) != 64:
            raise ValidationError({"content_digest": "شناسه‌ی نسخه معتبر نیست."})

    def __str__(self):
        return f"بازبینی انتشار · {self.book} · #{self.pk or 'جدید'}"

    @classmethod
    def pending_queue_q(cls):
        return models.Q(status__in=(cls.Status.PENDING, cls.Status.NEEDS_INFO))


class PublicationRequestEvent(models.Model):
    """Append-only audit trail of submissions and independent public-release decisions."""

    class Action(models.TextChoices):
        SUBMITTED = "submitted", "ثبت نسخه برای بازبینی"
        NEEDS_INFO = "needs_info", "درخواست اصلاح یا اطلاعات"
        APPROVED = "approved", "تأیید و انتشار"
        REJECTED = "rejected", "رد انتشار"
        REOPENED = "reopened", "بازگشایی برای بازبینی"
        NOTE_UPDATED = "note_updated", "به‌روزرسانی یادداشت"

    request = models.ForeignKey(
        PublicationRequest, on_delete=models.PROTECT, related_name="events", verbose_name="درخواست انتشار"
    )
    action = models.CharField("رویداد", max_length=16, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="publication_request_events", verbose_name="ثبت‌کننده",
    )
    reason = models.CharField("دلیل/یادداشت تصمیم", max_length=500, blank=True)
    content_digest = models.CharField("شناسه‌ی نسخه", max_length=64)
    created_at = models.DateTimeField("زمان", auto_now_add=True)

    class Meta:
        verbose_name = "رویداد بازبینی انتشار"
        verbose_name_plural = "رویدادهای بازبینی انتشار"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.get_action_display()} · درخواست #{self.request_id}"


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


_INVITE_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_classroom_code(length: int = 8) -> str:
    """Generate a clean, unambiguous 8-character invitation token (no 0/O/1/I)."""
    return "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(length))


class Classroom(models.Model):
    """A teacher's course or cohort offering access to one book via an invite link or phone list."""

    class AccessType(models.TextChoices):
        FREE = "free", "رایگان کلاس"
        STUDENT_PAID = "student_paid", "پرداخت توسط دانشجو (آینده)"
        TEACHER_PAID = "teacher_paid", "اشتراک/پرداخت مدرس (آینده)"

    class ExpiryPolicy(models.TextChoices):
        FIXED_DATE = "fixed_date", "تاریخ پایان ترم / انقضای مشخص"
        FROM_JOIN = "from_join", "مدت روز مشخص از زمان پیوستن"
        UNLIMITED = "unlimited", "بدون محدودیت زمانی"

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="taught_classrooms",
        verbose_name="مدرس / استاد",
    )
    book = models.ForeignKey(
        "catalog.ContentNode",
        on_delete=models.PROTECT,
        related_name="classrooms",
        verbose_name="کتاب کلاس",
    )
    title = models.CharField(
        "عنوان کلاس یا دوره",
        max_length=150,
        help_text="مثلاً «ریاضی عمومی ۱ - دانشگاه صنعتی شریف - پاییز ۱۴۰۵»",
    )
    description = models.TextField("توضیحات و پیام خوش‌آمد استاد", blank=True)
    code = models.CharField(
        "کد دعوت کلاس",
        max_length=16,
        unique=True,
        db_index=True,
        default=generate_classroom_code,
        help_text="شناسه‌ی کوتاه برای آدرس دعوت اختصاصی: /join/CODE",
    )
    is_active = models.BooleanField(
        "لینک دعوت فعال است",
        default=True,
        help_text="در صورت غیرفعال شدن، دانشجوی جدید نمی‌تواند با این لینک ثبت‌نام کند، اما دسترسی‌های قبلی برقرار می‌ماند.",
    )
    capacity = models.PositiveIntegerField(
        "سقف ظرفیت دانشجویان",
        default=100,
        help_text="حداکثر تعداد دانشجویانی که می‌توانند به این کلاس بپیوندند (برای امنیت و کنترل سوءاستفاده).",
    )
    expiry_policy = models.CharField(
        "سیاست انقضای دسترسی",
        max_length=16,
        choices=ExpiryPolicy.choices,
        default=ExpiryPolicy.FIXED_DATE,
    )
    ends_on = models.DateField(
        "تاریخ پایان دسترسی (شمسی / میلادی)",
        null=True,
        blank=True,
        help_text="پایان این تاریخ، دسترسی کتاب منقضی می‌شود. برای سیاست «تاریخ پایان مشخص».",
    )
    duration_days = models.PositiveIntegerField(
        "مدت دسترسی پس از پیوستن (روز)",
        null=True,
        blank=True,
        help_text="تعداد روزهای مجاز مطالعه از لحظه فعال‌سازی با OTP. برای سیاست «مدت روز مشخص».",
    )
    access_type = models.CharField(
        "نوع دسترسی (آینده‌نگر)",
        max_length=20,
        choices=AccessType.choices,
        default=AccessType.FREE,
    )
    price = models.PositiveIntegerField(
        "هزینه به تومان (اختیاری برای آینده)",
        null=True,
        blank=True,
        default=0,
    )
    created_at = models.DateTimeField("زمان ساخت کلاس", auto_now_add=True)
    updated_at = models.DateTimeField("آخرین تغییر", auto_now=True)

    class Meta:
        verbose_name = "کلاس و دوره اختصاصی"
        verbose_name_plural = "کلاس‌ها و دوره‌های اختصاصی"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["teacher", "is_active", "-created_at"], name="class_teacher_active_idx"),
            models.Index(fields=["book", "is_active"], name="class_book_active_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.teacher})"

    def clean(self):
        from apps.catalog.models import ContentNode

        errors = {}
        if self.book_id and (
            self.book.kind != ContentNode.Kind.BOOK or self.book.depth != 1 or self.book.is_inbox or self.book.is_archived
        ):
            errors["book"] = "فقط یک کتاب فعال و معتبر را برای کلاس انتخاب کنید."

        if self.code:
            self.code = self.code.strip().upper()

        if self.expiry_policy == self.ExpiryPolicy.FIXED_DATE:
            if not self.ends_on:
                errors["ends_on"] = "برای تاریخ پایان مشخص، فیلد «تاریخ پایان دسترسی» الزامی است."
            elif self.is_active and self.ends_on < timezone.localdate():
                errors["ends_on"] = "تاریخ پایان کلاس فعال نمی‌تواند در گذشته باشد."
        elif self.expiry_policy == self.ExpiryPolicy.FROM_JOIN:
            if not self.duration_days or self.duration_days <= 0:
                errors["duration_days"] = "برای مدت مشخص از زمان پیوستن، تعداد روزهای مجاز را وارد کنید."

        if self.capacity <= 0:
            errors["capacity"] = "سقف ظرفیت باید عددی مثبت باشد."

        if errors:
            raise ValidationError(errors)

    def calculate_end_time(self, joined_at=None):
        """Calculate exclusive ends_at instant based on class expiry policy."""
        from .group_access import calculate_cohort_end_time

        return calculate_cohort_end_time(
            expiry_policy=self.expiry_policy,
            ends_on=self.ends_on,
            duration_days=self.duration_days,
            now=joined_at,
        )

    def is_expired(self, now=None) -> bool:
        """True when a fixed-date classroom deadline has already elapsed."""
        now = now or timezone.now()
        end_at = self.calculate_end_time(now)
        return end_at is not None and end_at <= now

    @property
    def active_members_count(self) -> int:
        now = timezone.now()
        return (
            self.members.filter(
                status=ClassroomMember.Status.ACTIVE,
                entitlement__is_archived=False,
                entitlement__starts_at__lte=now,
            )
            .filter(models.Q(entitlement__ends_at__isnull=True) | models.Q(entitlement__ends_at__gt=now))
            .count()
        )

    @property
    def has_capacity(self) -> bool:
        return self.active_members_count < self.capacity


class ClassroomMember(models.Model):
    """A student's membership in a classroom granting access to the assigned book."""

    class Status(models.TextChoices):
        WAITING_OTP = "waiting_otp", "در انتظار اولین ورود دانشجو با OTP"
        ACTIVE = "active", "فعال در کلاس"
        EXPIRED = "expired", "پایان مهلت / منقضی‌شده"
        REVOKED = "revoked", "لغوشده توسط استاد یا مدیر"

    class JoinMethod(models.TextChoices):
        LINK = "link", "پیوستن مستقیم با لینک دعوت"
        BULK_IMPORT = "bulk_import", "واردسازی شماره توسط استاد"
        MANUAL = "manual", "ثبت دستی"

    classroom = models.ForeignKey(
        Classroom,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name="کلاس",
    )
    phone = models.CharField(
        "شماره موبایل دانشجو",
        max_length=11,
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classroom_memberships",
        verbose_name="کاربر دانشجو",
        editable=False,
    )
    entitlement = models.OneToOneField(
        "commerce.Entitlement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="classroom_membership",
        verbose_name="ردیف دسترسی ایجادشده",
        editable=False,
    )
    join_method = models.CharField(
        "روش پیوستن",
        max_length=16,
        choices=JoinMethod.choices,
        default=JoinMethod.LINK,
    )
    status = models.CharField(
        "وضعیت عضویت",
        max_length=16,
        choices=Status.choices,
        default=Status.WAITING_OTP,
        db_index=True,
    )
    joined_at = models.DateTimeField(
        "زمان پیوستن به کلاس",
        null=True,
        blank=True,
        editable=False,
    )
    created_at = models.DateTimeField("زمان ثبت ردیف", auto_now_add=True)
    revoked_at = models.DateTimeField("زمان لغو", null=True, blank=True, editable=False)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="لغوکننده",
        editable=False,
    )
    revocation_reason = models.CharField("علت لغو", max_length=300, blank=True)

    class Meta:
        verbose_name = "عضویت دانشجو در کلاس"
        verbose_name_plural = "عضویت‌های دانشجویان در کلاس‌ها"
        ordering = ["-created_at", "phone"]
        constraints = [
            models.UniqueConstraint(fields=["classroom", "phone"], name="uniq_classroom_member_phone"),
        ]
        indexes = [
            models.Index(fields=["classroom", "status"], name="class_member_status_idx"),
            models.Index(fields=["phone", "status"], name="class_member_phone_idx"),
        ]

    def __str__(self):
        return f"{self.classroom.title} · {self.phone}"

    def clean(self):
        from apps.accounts.phone import InvalidPhone, normalize_phone

        try:
            self.phone = normalize_phone(self.phone)
        except InvalidPhone as exc:
            raise ValidationError({"phone": str(exc)}) from exc

    @property
    def is_active(self) -> bool:
        from .group_access import is_entitlement_active_now

        return bool(self.status == self.Status.ACTIVE and is_entitlement_active_now(self.entitlement))
