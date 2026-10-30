from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import ratelimit
from .models import DeviceSession, OTPCode, User
from .phone import InvalidPhone, normalize_phone
from .sms import SMSError, send_sms

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _error(message, code, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    return Response({"code": code, "message": message, **extra}, status=http_status)


def _too_many(message, **extra):
    return _error(message, "rate_limited", status.HTTP_429_TOO_MANY_REQUESTS, **extra)


def _client_ip(request):
    """The direct peer, or the address added by our own proxies (never the client-supplied part)."""
    hops = settings.TRUSTED_PROXY_COUNT
    if hops > 0:
        forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.META.get("REMOTE_ADDR", "")


def _session_payload(session, current=None):
    return {
        "id": session.id,
        "device_name": session.device_name or "دستگاه ناشناس",
        "platform": session.platform,
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "is_current": current is not None and session.id == current.id,
    }


def _user_payload(user):
    return {
        "id": user.id,
        "phone": user.phone,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@transaction.non_atomic_requests
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def request_otp(request):
    try:
        phone = normalize_phone(request.data.get("phone", ""))
    except InvalidPhone as exc:
        return _error(str(exc), "invalid_phone")

    ip_key = f"otp-req-ip:{_client_ip(request)}"
    with transaction.atomic():
        ratelimit.lock(f"otp:{phone}")
        if ratelimit.count(ip_key) >= settings.OTP_REQUESTS_PER_IP_PER_HOUR:
            return _too_many("تعداد درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.")

        now = timezone.now()
        recent = OTPCode.objects.filter(phone=phone, created_at__gte=now - timedelta(hours=1))
        last = recent.order_by("-created_at").first()
        if last and now - last.created_at < settings.OTP_RESEND_COOLDOWN:
            wait = int((settings.OTP_RESEND_COOLDOWN - (now - last.created_at)).total_seconds()) + 1
            return _error(f"برای ارسال دوباره {wait} ثانیه صبر کنید.", "cooldown", status.HTTP_429_TOO_MANY_REQUESTS, retry_after=wait)
        if recent.count() >= settings.OTP_MAX_PER_HOUR:
            return _too_many("تعداد درخواست کد برای این شماره زیاد است. یک ساعت دیگر تلاش کنید.")

        ratelimit.hit(ip_key)
        otp, code = OTPCode.issue(phone)

    # Sent after the code is committed, so a code the user receives always exists.
    try:
        send_sms(phone, f"لیمو پلاس\nکد ورود شما: {code}\nاین کد را به کسی ندهید.")
    except SMSError:
        otp.delete()
        return _error("ارسال پیامک ممکن نشد. کمی بعد دوباره تلاش کنید.", "sms_failed", status.HTTP_502_BAD_GATEWAY)

    return Response({"sent": True, "expires_in": int(settings.OTP_LIFETIME.total_seconds())})


class VerifySerializer(serializers.Serializer):
    phone = serializers.CharField()
    code = serializers.CharField(max_length=10)
    device_name = serializers.CharField(required=False, allow_blank=True, default="")
    platform = serializers.CharField(required=False, allow_blank=True, default="")
    replace_session_id = serializers.IntegerField(required=False)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def verify_otp(request):
    data = VerifySerializer(data=request.data)
    if not data.is_valid():
        return _error("اطلاعات ارسالی کامل نیست.", "invalid_request", errors=data.errors)
    try:
        phone = normalize_phone(data.validated_data["phone"])
    except InvalidPhone as exc:
        return _error(str(exc), "invalid_phone")
    code = data.validated_data["code"].strip().translate(_PERSIAN_DIGITS)

    ip_wrong_key = f"otp-wrong-ip:{_client_ip(request)}"
    if ratelimit.count(ip_wrong_key) >= settings.OTP_WRONG_PER_IP_PER_HOUR:
        return _too_many("تلاش‌های ناموفق زیاد است. کمی بعد دوباره تلاش کنید.")

    ratelimit.lock(f"otp:{phone}")
    day_ago = timezone.now() - timedelta(hours=24)
    wrong_today = OTPCode.objects.filter(phone=phone, created_at__gte=day_ago).aggregate(n=Sum("attempts"))["n"] or 0
    if wrong_today >= settings.OTP_MAX_WRONG_PER_DAY:
        return _too_many("ورود با این شماره به دلیل تلاش‌های ناموفق تا ۲۴ ساعت بسته شد.")

    otp = OTPCode.objects.select_for_update().filter(phone=phone).order_by("-created_at").first()
    if otp is None or not otp.is_usable:
        return _error("کد منقضی شده است. کد جدید بگیرید.", "otp_expired")
    if not otp.matches(code):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        ratelimit.hit(ip_wrong_key)
        left = max(0, settings.OTP_MAX_ATTEMPTS - otp.attempts)
        return _error("کد اشتباه است.", "otp_wrong", attempts_left=left)

    try:
        with transaction.atomic():
            user, _ = User.objects.get_or_create(phone=phone)
    except IntegrityError:
        user = User.objects.get(phone=phone)
    if not user.is_active:
        return _error("این حساب غیرفعال شده است.", "user_inactive", status.HTTP_403_FORBIDDEN)

    # Lock the user row so two devices verifying at once cannot exceed the limit.
    User.objects.select_for_update().filter(pk=user.pk).first()
    active = list(DeviceSession.active_for(user).order_by("last_seen_at"))
    limit = settings.MAX_ACTIVE_SESSIONS
    if len(active) >= limit:
        replace_id = data.validated_data.get("replace_session_id")
        target = next((s for s in active if s.id == replace_id), None)
        if target is None:
            return _error(
                f"حداکثر {limit} دستگاه هم‌زمان مجاز است. یکی را خارج کنید.",
                "session_limit",
                status.HTTP_409_CONFLICT,
                sessions=[_session_payload(s) for s in active],
            )
        target.revoke()
        # If the limit was lowered, also sign out the least recently used extras.
        others = [s for s in active if s.id != target.id]
        for extra in others[: max(0, len(others) - (limit - 1))]:
            extra.revoke()

    otp.consumed_at = timezone.now()
    otp.save(update_fields=["consumed_at"])
    session, token = DeviceSession.start(user, data.validated_data["device_name"], data.validated_data["platform"])
    return Response({"token": token, "session_id": session.id, "user": _user_payload(user)})


@api_view(["POST"])
def logout(request):
    request.device_session.revoke()
    return Response({"logged_out": True})


class ProfileSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


@api_view(["GET", "PATCH"])
def me(request):
    user = request.user
    if request.method == "PATCH":
        data = ProfileSerializer(data=request.data, partial=True)
        if not data.is_valid():
            return _error("اطلاعات وارد شده درست نیست.", "invalid_request", errors=data.errors)
        for field, value in data.validated_data.items():
            setattr(user, field, value)
        user.save(update_fields=list(data.validated_data) or None)
    return Response(_user_payload(user))


@api_view(["GET"])
def sessions(request):
    current = request.device_session
    return Response([_session_payload(s, current) for s in DeviceSession.active_for(request.user)])


@api_view(["POST"])
def revoke_session(request, session_id):
    session = DeviceSession.active_for(request.user).filter(pk=session_id).first()
    if session is None:
        return _error("این نشست پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
    session.revoke()
    return Response({"revoked": True})
