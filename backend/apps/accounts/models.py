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
    first_name = models.CharField("نام", max_length=60, blank=True)
    last_name = models.CharField("نام خانوادگی", max_length=60, blank=True)
    is_active = models.BooleanField("فعال", default=True)
    is_staff = models.BooleanField("کارمند", default=False)
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
        return cls.objects.filter(user=user, revoked_at__isnull=True, expires_at__gt=timezone.now())

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
        return self.revoked_at is None and self.expires_at > timezone.now()

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class PanelLoginCode(models.Model):
    """«باز کردن وب اپ با حساب من» in the panel: a one-time code that signs a staff member into the web app without
    an SMS. Only its keyed hash is kept; it works once, for PANEL_LOGIN_SECONDS, and only for an active staff user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="panel_login_codes")
    code_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "کد ورود از پنل"
        verbose_name_plural = "کدهای ورود از پنل"

    @classmethod
    def issue(cls, user) -> str:
        code = secrets.token_urlsafe(32)
        cls.objects.create(user=user, code_hash=_hash(code))
        return code

    @classmethod
    def find(cls, code: str):
        return cls.objects.select_related("user").filter(code_hash=_hash(code)).first()

    @property
    def is_usable(self) -> bool:
        age = (timezone.now() - self.created_at).total_seconds()
        return self.used_at is None and age <= settings.PANEL_LOGIN_SECONDS
