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

    def generate_email_verification_token(self) -> str:
        import secrets
        token = secrets.token_urlsafe(32)
        self.email_verification_token = token
        self.save(update_fields=["email_verification_token"])
        return token

    def verify_email(self):
        self.email_verified_at = timezone.now()
        self.email_verification_token = ""
        self.save(update_fields=["email_verified_at", "email_verification_token"])

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
