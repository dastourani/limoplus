from datetime import timedelta
import hashlib
import hmac
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


def _hash(value: str) -> str:
    """Keyed hash: codes and tokens are never stored in readable form."""
    return hmac.new(settings.HASH_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


class UserManager(BaseUserManager):
    def create_user(self, phone, **extra):
        user = self.model(phone=phone, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, phone, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        user = self.model(phone=phone, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    """A learner or a staff member. Learners sign in with an SMS code only."""

    phone = models.CharField("شماره موبایل", max_length=11, unique=True)
    email = models.EmailField("ایمیل", blank=True)
    email_verified_at = models.DateTimeField("زمان تأیید ایمیل", null=True, blank=True)
    email_verification_token = models.CharField("توکن تأیید ایمیل", max_length=64, blank=True, db_index=True)
    email_verification_target = models.EmailField("ایمیل در انتظار تأیید", blank=True)
    email_verification_sent_at = models.DateTimeField("زمان ارسال لینک تأیید", null=True, blank=True)
    email_verification_nonce = models.CharField("شناسه درخواست تأیید ایمیل", max_length=32, blank=True, db_index=True)
    first_name = models.CharField("نام", max_length=60, blank=True)
    last_name = models.CharField("نام خانوادگی", max_length=60, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    is_staff = models.BooleanField("کارمند", default=False)
    can_copy = models.BooleanField(
        "امکان کپی متن",
        default=True,
        help_text="اگر برداشته شود، حساب و کتاب‌هایش باز می‌ماند ولی دیگر نمی‌تواند متن درس را کپی کند.",
    )
    can_report = models.BooleanField(
        "امکان ارسال گزارش",
        default=True,
        help_text="اگر برداشته شود، حساب باز می‌ماند ولی دیگر نمی‌تواند گزارش اشکال بفرستد.",
    )
    admin_note = models.CharField("یادداشت مدیر / علت محدودیت", max_length=300, blank=True)
    date_joined = models.DateTimeField("تاریخ عضویت", default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "phone"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "کاربر"
        verbose_name_plural = "کاربران"

    def __str__(self):
        return self.phone

    @property
    def is_email_verified(self) -> bool:
        return bool(self.email and self.email_verified_at)

    @staticmethod
    def email_verification_digest(public_token: str, *, email: str, nonce: str) -> str:
        normalized = (email or "").strip().lower()
        return _hash(f"email-verify:{normalized}:{nonce}:{public_token}")

    def _prepare_email_verification_fields(self) -> str:
        target = (self.email or "").strip().lower()
        nonce = secrets.token_hex(8)
        raw_secret = secrets.token_urlsafe(32)
        public_token = f"{nonce}.{raw_secret}"
        self.email_verification_nonce = nonce
        self.email_verification_target = target
        self.email_verification_sent_at = timezone.now()
        self.email_verification_token = self.email_verification_digest(public_token, email=target, nonce=nonce)
        return public_token

    def generate_email_verification_token(self) -> str:
        from django.db import transaction

        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=self.pk)
            locked.email = self.email
            public_token = locked._prepare_email_verification_fields()
            locked.save(
                update_fields=[
                    "email_verification_token",
                    "email_verification_target",
                    "email_verification_sent_at",
                    "email_verification_nonce",
                ]
            )
            self.email_verification_token = locked.email_verification_token
            self.email_verification_target = locked.email_verification_target
            self.email_verification_sent_at = locked.email_verification_sent_at
            self.email_verification_nonce = locked.email_verification_nonce
            return public_token

    def begin_email_change(self, new_email: str) -> str:
        """Atomically replace the working email, revoke prior verification, and issue a single-use bound token."""
        from django.db import transaction

        normalized = (new_email or "").strip().lower()
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=self.pk)
            locked.email = normalized
            locked.email_verified_at = None
            public_token = locked._prepare_email_verification_fields()
            locked.save(
                update_fields=[
                    "email",
                    "email_verified_at",
                    "email_verification_token",
                    "email_verification_target",
                    "email_verification_sent_at",
                    "email_verification_nonce",
                ]
            )
            self.email = locked.email
            self.email_verified_at = locked.email_verified_at
            self.email_verification_token = locked.email_verification_token
            self.email_verification_target = locked.email_verification_target
            self.email_verification_sent_at = locked.email_verification_sent_at
            self.email_verification_nonce = locked.email_verification_nonce
            return public_token

    @classmethod
    def consume_email_verification(
        cls,
        raw_token: str,
        *,
        acting_user_id: int | None = None,
    ) -> tuple["User | None", str]:
        """Atomically validate and consume a single-use verification token bound to the exact target email."""
        from django.db import transaction

        token = (raw_token or "").strip()
        if not token or "." not in token:
            return None, "invalid"
        nonce, _ = token.split(".", 1)
        if not nonce:
            return None, "invalid"

        with transaction.atomic():
            user = cls.objects.select_for_update().filter(email_verification_nonce=nonce).first()
            if (
                user is None
                or not user.email_verification_token
                or not user.email_verification_target
                or not user.email_verification_nonce
            ):
                return None, "invalid"

            target_email = user.email_verification_target.strip().lower()
            current_email = (user.email or "").strip().lower()
            if not target_email or current_email != target_email:
                return None, "invalid"

            expected = cls.email_verification_digest(
                token,
                email=target_email,
                nonce=nonce,
            )
            if not hmac.compare_digest(user.email_verification_token, expected):
                return None, "invalid"

            if acting_user_id is not None and user.pk != acting_user_id:
                return user, "wrong_user"

            expiry_hours = max(1, int(getattr(settings, "EMAIL_VERIFICATION_EXPIRY_HOURS", 24)))
            if not user.email_verification_sent_at or (
                timezone.now() - user.email_verification_sent_at > timedelta(hours=expiry_hours)
            ):
                return None, "expired"

            now = timezone.now()
            updated = cls.objects.filter(
                pk=user.pk,
                email=target_email,
                email_verification_nonce=nonce,
                email_verification_token=expected,
            ).update(
                email_verified_at=now,
                email_verification_token="",
                email_verification_target="",
                email_verification_sent_at=None,
                email_verification_nonce="",
            )
            if updated != 1:
                return None, "invalid"

            user.email_verified_at = now
            user.email_verification_token = ""
            user.email_verification_target = ""
            user.email_verification_sent_at = None
            user.email_verification_nonce = ""
            return user, "ok"

    def verify_email(self):
        self.email_verified_at = timezone.now()
        self.email_verification_token = ""
        self.email_verification_target = ""
        self.email_verification_sent_at = None
        self.email_verification_nonce = ""
        self.save(
            update_fields=[
                "email_verified_at",
                "email_verification_token",
                "email_verification_target",
                "email_verification_sent_at",
                "email_verification_nonce",
            ]
        )

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    full_name.fget.short_description = "نام"


class OTPCode(models.Model):
    phone = models.CharField(max_length=11, db_index=True)
    code_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کد ورود"
        verbose_name_plural = "کدهای ورود"
        indexes = [models.Index(fields=["phone", "-created_at"])]

    @classmethod
    def issue(cls, phone: str) -> tuple["OTPCode", str]:
        code = "".join(secrets.choice("0123456789") for _ in range(settings.OTP_LENGTH))
        otp = cls.objects.create(
            phone=phone,
            code_hash=_hash(f"{phone}:{code}"),
            expires_at=timezone.now() + settings.OTP_LIFETIME,
        )
        return otp, code

    @property
    def is_usable(self) -> bool:
        return (
            self.consumed_at is None
            and self.expires_at > timezone.now()
            and self.attempts < settings.OTP_MAX_ATTEMPTS
        )

    def matches(self, code: str) -> bool:
        return hmac.compare_digest(self.code_hash, _hash(f"{self.phone}:{code}"))


class RateBucket(models.Model):
    """Counter per key per hour, shared by all server processes (rate limits)."""

    key = models.CharField(max_length=120)
    window_start = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("key", "window_start")]
        indexes = [models.Index(fields=["window_start"])]


class DeviceSession(models.Model):
    """One signed-in device. At most MAX_ACTIVE_SESSIONS active per user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_sessions", verbose_name="کاربر")
    token_hash = models.CharField(max_length=64, unique=True)
    device_name = models.CharField("دستگاه", max_length=120, blank=True)
    platform = models.CharField("سکو", max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="زمان ورود")
    last_seen_at = models.DateTimeField(default=timezone.now, verbose_name="آخرین استفاده")
    expires_at = models.DateTimeField(verbose_name="انقضا")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="زمان خروج")

    class Meta:
        verbose_name = "نشست"
        verbose_name_plural = "نشست‌ها"
        ordering = ["-last_seen_at"]

    def __str__(self):
        return f"{self.user} · {self.device_name or 'دستگاه ناشناس'}"

    @classmethod
    def active_for(cls, user):
        """Signed in: not signed out, not expired, and used within SESSION_IDLE_DAYS (a phone left in a drawer for a
        month stops holding one of the two places)."""
        now = timezone.now()
        return cls.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=now,
                                  last_seen_at__gt=now - settings.SESSION_IDLE)

    @classmethod
    def start(cls, user, device_name="", platform="") -> tuple["DeviceSession", str]:
        token = secrets.token_urlsafe(32)
        session = cls.objects.create(
            user=user,
            token_hash=_hash(token),
            device_name=device_name[:120],
            platform=platform[:20],
            expires_at=timezone.now() + settings.SESSION_TOKEN_LIFETIME,
        )
        return session, token

    @classmethod
    def find_by_token(cls, token: str):
        return cls.objects.select_related("user").filter(token_hash=_hash(token)).first()

    @property
    def is_active(self) -> bool:
        now = timezone.now()
        return self.revoked_at is None and self.expires_at > now and self.last_seen_at > now - settings.SESSION_IDLE

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class PanelLoginCode(models.Model):
    """A one-time code that signs a user from the panel or website (classroom join) into the web app without a second
    SMS. Only its keyed hash is kept; it works once, for PANEL_LOGIN_SECONDS, and when `staff_only=True` only for an
    active staff user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="panel_login_codes")
    code_hash = models.CharField(max_length=64, unique=True)
    staff_only = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کد ورود از پنل"
        verbose_name_plural = "کدهای ورود از پنل"

    @classmethod
    def issue(cls, user, *, staff_only: bool = True) -> str:
        code = secrets.token_urlsafe(32)
        cls.objects.create(user=user, code_hash=_hash(code), staff_only=staff_only)
        return code

    @classmethod
    def find(cls, code: str):
        return cls.objects.select_related("user").filter(code_hash=_hash(code)).first()

    @property
    def is_usable(self) -> bool:
        age = (timezone.now() - self.created_at).total_seconds()
        return self.used_at is None and age <= settings.PANEL_LOGIN_SECONDS


class TeacherNotification(models.Model):
    """Persistent, deduplicated record of an official manager-to-teacher notification and its email delivery state."""

    class EventType(models.TextChoices):
        PUB_OFFER_SENT = "pub_offer_sent", "ارسال پیشنهاد مالی انتشار"
        PUB_OFFER_REMINDER = "pub_offer_reminder", "یادآوری پیشنهاد مالی انتشار"
        PUB_NEEDS_INFO = "pub_needs_info", "درخواست اصلاح محتوای کتاب"
        PUB_APPROVED = "pub_approved", "تأیید درخواست انتشار کتاب"
        PUB_REJECTED = "pub_rejected", "رد درخواست انتشار کتاب"
        ACCESS_APPROVED = "access_approved", "تأیید درخواست دسترسی گروهی"
        ACCESS_NEEDS_INFO = "access_needs_info", "نیازمند تکمیل درخواست دسترسی گروهی"
        ACCESS_REJECTED = "access_rejected", "رد درخواست دسترسی گروهی"
        ACCESS_MESSAGE = "access_message", "پیام دربارهٔ درخواست دسترسی گروهی"
        PAYOUT_PAID = "payout_paid", "واریز تسویه حساب"
        PAYOUT_REJECTED = "payout_rejected", "رد درخواست تسویه حساب"

    class Status(models.TextChoices):
        PENDING = "pending", "در انتظار ارسال"
        SENT = "sent", "ارسال‌شده"
        FAILED = "failed", "ناموفق (نیازمند تلاش مجدد)"
        SKIPPED_NO_EMAIL = "skipped_no_email", "بدون ایمیل تأییدشده (ثبت در پنل)"

    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="teacher_notifications",
        verbose_name="استاد گیرنده",
    )
    recipient_email = models.EmailField("نشانی ایمیل استفاده‌شده", blank=True)
    event_type = models.CharField("نوع رویداد", max_length=32, choices=EventType.choices, db_index=True)
    dedupe_key = models.CharField("کلید یکتایی رویداد", max_length=160, unique=True)
    source_ref = models.CharField("مرجع درخواست", max_length=80, blank=True, db_index=True)
    book_id = models.PositiveBigIntegerField("شناسه کتاب", null=True, blank=True, db_index=True)
    book_title = models.CharField("عنوان کتاب", max_length=200, blank=True)
    object_id = models.PositiveBigIntegerField("شناسه رکورد مرتبط", null=True, blank=True)
    subject = models.CharField("عنوان ایمیل", max_length=200)
    headline = models.CharField("پیام اعلان", max_length=300)
    cta_label = models.CharField("عنوان دکمه", max_length=80, default="مشاهده در میز تألیف")
    is_reminder = models.BooleanField("یادآوری عمدی مدیر", default=False)
    status = models.CharField(
        "وضعیت ارسال",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempt_count = models.PositiveSmallIntegerField("تعداد تلاش", default=0)
    last_attempt_at = models.DateTimeField("زمان آخرین تلاش", null=True, blank=True)
    sent_at = models.DateTimeField("زمان ارسال موفق", null=True, blank=True)
    last_error = models.TextField("جزئیات آخرین خطا", blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_teacher_notifications",
        verbose_name="ثبت‌کننده",
    )
    created_at = models.DateTimeField("زمان ثبت", auto_now_add=True)

    class Meta:
        verbose_name = "اعلان ایمیلی استاد"
        verbose_name_plural = "اعلان‌های ایمیلی اساتید"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="teacher_notif_status_idx"),
            models.Index(fields=["recipient", "-created_at"], name="teacher_notif_rcpt_idx"),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} · {self.recipient} ({self.get_status_display()})"

    def notice_token(self) -> str:
        return _hash(f"teacher-notice:{self.pk}:{self.recipient_id}:{self.dedupe_key}")[:24]

    def matches_notice_token(self, token: str) -> bool:
        return bool(token) and hmac.compare_digest(self.notice_token(), token)

    def notice_path(self) -> str:
        from django.urls import reverse

        return reverse("teacher-notice", args=[self.pk, self.notice_token()])

