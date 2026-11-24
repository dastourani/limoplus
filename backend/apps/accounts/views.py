import logging
import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login as django_login
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import ratelimit
from .models import DeviceSession, OTPCode, PanelLoginCode, User
from .phone import InvalidPhone, normalize_phone
from .sms import SMSError, send_login_code
from config.links import app_base_url

log = logging.getLogger(__name__)

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _fa(number) -> str:
    return str(number).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


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


def _offline_revocations_for(user):
    """Books whose downloaded offline bundle must be wiped on the client's next online sync."""
    if not user or not user.is_authenticated:
        return []
    from apps.catalog.access import access_kind_from, active_rows
    from apps.catalog.models import ContentNode
    from apps.commerce.models import Entitlement

    since = timezone.now() - timedelta(days=40)
    revoked = list(
        Entitlement.objects.filter(
            user=user,
            is_archived=True,
            offline_revoked_at__isnull=False,
            offline_revoked_at__gte=since,
        )
        .select_related("book")
        .prefetch_related("book__majors")
    )
    if not revoked:
        return []

    entitlements = active_rows(user)
    latest_by_slug = {}

    def record(book, revoked_at):
        if book is None or book.is_free:
            return
        major_ids = {major.pk for major in book.majors.all()}
        if access_kind_from(entitlements, user, book.pk, major_ids):
            return
        prev = latest_by_slug.get(book.slug)
        if prev is None or revoked_at > prev:
            latest_by_slug[book.slug] = revoked_at

    all_majors_ts = None
    major_ts = {}
    for ent in revoked:
        if ent.book_id is not None:
            record(ent.book, ent.offline_revoked_at)
        elif ent.all_majors:
            if all_majors_ts is None or ent.offline_revoked_at > all_majors_ts:
                all_majors_ts = ent.offline_revoked_at
        elif ent.major_id is not None:
            prev = major_ts.get(ent.major_id)
            if prev is None or ent.offline_revoked_at > prev:
                major_ts[ent.major_id] = ent.offline_revoked_at

    if all_majors_ts is not None or major_ts:
        qs = ContentNode.objects.filter(
            kind=ContentNode.Kind.BOOK,
            depth=1,
            is_archived=False,
            is_inbox=False,
            is_free=False,
        ).prefetch_related("majors")
        if all_majors_ts is None:
            qs = qs.filter(majors__id__in=list(major_ts)).distinct()
        for book in qs:
            ts = all_majors_ts
            for m in book.majors.all():
                mts = major_ts.get(m.pk)
                if mts is not None and (ts is None or mts > ts):
                    ts = mts
            if ts is not None:
                record(book, ts)

    return [{"slug": slug, "revoked_at": ts.isoformat()} for slug, ts in sorted(latest_by_slug.items())]


def _user_payload(user):
    return {
        "id": user.id,
        "phone": user.phone,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_staff": user.is_staff,
        "offline_revocations": _offline_revocations_for(user),
    }


_APP_HASH = re.compile(r"^[A-Za-z0-9+/]{11}$")


def _otp_message(code: str, app_hash=None) -> str:
    """Short enough for one Persian SMS (70 characters). The Android app's hash on the last line lets the phone read
    the code by itself (SMS Retriever); a malformed hash is ignored."""
    text = f"لیموخوان\nکد ورود: {code}\nاین کد را به کسی ندهید"
    if settings.OTP_SMS_APP_HASH and isinstance(app_hash, str) and _APP_HASH.match(app_hash):
        text += f"\n{app_hash}"
    return text


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
        existing = User.objects.filter(phone=phone).only("is_active").first()
        if existing is not None and not existing.is_active:
            return _error("این حساب غیرفعال شده است.", "user_inactive", status.HTTP_403_FORBIDDEN)
        if ratelimit.count(ip_key) >= settings.OTP_REQUESTS_PER_IP_PER_HOUR:
            return _too_many("تعداد درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.")

        now = timezone.now()
        recent = OTPCode.objects.filter(phone=phone, created_at__gte=now - timedelta(hours=1))
        last = recent.order_by("-created_at").first()
        if last and now - last.created_at < settings.OTP_RESEND_COOLDOWN:
            wait = int((settings.OTP_RESEND_COOLDOWN - (now - last.created_at)).total_seconds()) + 1
            return _error(f"برای ارسال دوباره {_fa(wait)} ثانیه صبر کنید.", "cooldown", status.HTTP_429_TOO_MANY_REQUESTS, retry_after=wait)
        if recent.count() >= settings.OTP_MAX_PER_HOUR:
            # Say exactly when the next code can be requested (when the oldest code of the hour drops out).
            oldest = recent.order_by("created_at").first().created_at
            wait = max(60, int((oldest + timedelta(hours=1) - now).total_seconds()) + 1)
            minutes = (wait + 59) // 60
            return _too_many(
                f"تعداد درخواست کد برای این شماره زیاد است. {_fa(minutes)} دقیقه‌ی دیگر دوباره تلاش کنید.", retry_after=wait
            )

        ratelimit.hit(ip_key)
        otp, code = OTPCode.issue(phone)

    # Sent after the code is committed, so a code the user receives always exists.
    try:
        send_login_code(phone, code, _otp_message(code, request.data.get("app_hash")))
    except SMSError as exc:
        log.error("Login SMS to %s failed: %s", phone, exc)
        otp.delete()
        return _error("ارسال پیامک ممکن نشد. کمی بعد دوباره تلاش کنید.", "sms_failed", status.HTTP_502_BAD_GATEWAY)

    return Response({"sent": True, "expires_in": int(settings.OTP_LIFETIME.total_seconds())})


def _make_room(user, replace_id):
    """At most MAX_ACTIVE_SESSIONS devices: with the limit reached, the device named by replace_id is signed out;
    without one, a 409 «session_limit» lists the devices to choose from. Locks the user row, so two devices signing in
    at once cannot pass the limit. Returns None when there is room (call inside the request's transaction)."""
    User.objects.select_for_update().filter(pk=user.pk).first()
    active = list(DeviceSession.active_for(user).order_by("last_seen_at"))
    limit = settings.MAX_ACTIVE_SESSIONS
    if len(active) < limit:
        return None
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
    return None


class VerifySerializer(serializers.Serializer):
    phone = serializers.CharField()
    code = serializers.CharField(max_length=10)
    teacher_invitation = serializers.CharField(required=False, allow_blank=True, max_length=100)
    device_name = serializers.CharField(required=False, allow_blank=True, default="")
    platform = serializers.CharField(required=False, allow_blank=True, default="")
    replace_session_id = serializers.IntegerField(required=False)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def verify_otp(request):
    # DRF passes its own Request wrapper, so Django's sensitive_post_parameters decorator raises TypeError here.
    # Mark the underlying HttpRequest directly to keep credentials out of Django error reports.
    request._request.sensitive_post_parameters = ("phone", "code", "teacher_invitation")
    data = VerifySerializer(data=request.data)
    if not data.is_valid():
        return _error("اطلاعات ارسالی کامل نیست.", "invalid_request", errors=data.errors)
    try:
        phone = normalize_phone(data.validated_data["phone"])
    except InvalidPhone as exc:
        return _error(str(exc), "invalid_phone")
    code = data.validated_data["code"].strip().translate(_PERSIAN_DIGITS)

    invitation_token = data.validated_data.get("teacher_invitation", "").strip()
    invitation = None
    if invitation_token:
        from apps.website.models import TeacherApplication, TeacherInvitation

        invitation = (
            TeacherInvitation.objects.select_for_update()
            .select_related("application", "book")
            .filter(token_hash=TeacherInvitation.digest_token(invitation_token))
            .first()
        )
        now = timezone.now()
        if invitation is None or invitation.status != TeacherInvitation.Status.ISSUED:
            return _error("این دعوت دیگر قابل استفاده نیست.", "invitation_unavailable")
        if invitation.expires_at <= now:
            invitation.status = TeacherInvitation.Status.EXPIRED
            invitation.save(update_fields=["status"])
            return _error("مهلت این دعوت به پایان رسیده است.", "invitation_unavailable")
        if invitation.application.status != TeacherApplication.Status.APPROVED:
            invitation.status = TeacherInvitation.Status.REVOKED
            invitation.revoked_at = now
            invitation.revocation_reason = "درخواست استاد از وضعیت تأیید خارج شد."
            invitation.save(update_fields=["status", "revoked_at", "revocation_reason"])
            return _error("این دعوت دیگر قابل استفاده نیست.", "invitation_unavailable")
        if (
            invitation.book.kind != "book" or invitation.book.depth != 1
            or invitation.book.is_archived or invitation.book.is_inbox
        ):
            invitation.status = TeacherInvitation.Status.REVOKED
            invitation.revoked_at = now
            invitation.revocation_reason = "کتاب دعوت دیگر فعال نیست."
            invitation.save(update_fields=["status", "revoked_at", "revocation_reason"])
            return _error("این دعوت دیگر قابل استفاده نیست.", "invitation_unavailable")
        if invitation.application.phone != phone:
            return _error("شماره با دعوت‌نامه مطابقت ندارد.", "invitation_phone_mismatch")

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

    if invitation is not None:
        try:
            with transaction.atomic():
                user, _ = User.objects.get_or_create(phone=phone)
                if not user.is_active:
                    return _error("این حساب غیرفعال شده است.", "user_inactive", status.HTTP_403_FORBIDDEN)
                from apps.website.group_access import activate_approved_members, activate_classroom_members
                from apps.website.invitations import accept_teacher_invitation

                accept_teacher_invitation(invitation, user)
                now = timezone.now()
                otp.consumed_at = now
                otp.save(update_fields=["consumed_at"])
                activate_approved_members(user, now=now)
                activate_classroom_members(user, now=now)
                # This special OTP flow creates the staff account and a Django admin session only after the invited
                # phone has been verified. It does not consume an app-device slot or grant a DeviceSession token.
                django_login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        except ValidationError as exc:
            message = " ".join(exc.messages)
            return _error(message, "invitation_unavailable")
        return Response({"accepted": True, "user": _user_payload(user)})

    try:
        with transaction.atomic():
            user, _ = User.objects.get_or_create(phone=phone)
    except IntegrityError:
        user = User.objects.get(phone=phone)
    if not user.is_active:
        return _error("این حساب غیرفعال شده است.", "user_inactive", status.HTTP_403_FORBIDDEN)

    refused = _make_room(user, data.validated_data.get("replace_session_id"))
    if refused is not None:
        return refused

    now = timezone.now()
    otp.consumed_at = now
    otp.save(update_fields=["consumed_at"])
    from apps.website.group_access import activate_approved_members, activate_classroom_members

    activate_approved_members(user, now=now)
    activate_classroom_members(user, now=now)
    session, token = DeviceSession.start(user, data.validated_data["device_name"], data.validated_data["platform"])
    return Response({"token": token, "session_id": session.id, "user": _user_payload(user)})


class PanelLoginSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=80)
    device_name = serializers.CharField(required=False, allow_blank=True, default="")
    platform = serializers.CharField(required=False, allow_blank=True, default="")
    replace_session_id = serializers.IntegerField(required=False)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def panel_login(request):
    """The web app's half of «باز کردن وب اپ با حساب من»: a one-time code from the panel becomes a session, like a
    verified SMS code (the same device limit). A wrong or used code counts as a wrong guess for the IP (the same
    counter as wrong SMS codes). Sessions made this way are ordinary sessions: revoke them in «نشست‌ها» if staff
    rights are taken away."""
    data = PanelLoginSerializer(data=request.data)
    if not data.is_valid():
        return _error("اطلاعات ارسالی کامل نیست.", "invalid_request", errors=data.errors)
    ip_wrong_key = f"otp-wrong-ip:{_client_ip(request)}"
    if ratelimit.count(ip_wrong_key) >= settings.OTP_WRONG_PER_IP_PER_HOUR:
        return _too_many("تلاش‌های ناموفق زیاد است. کمی بعد دوباره تلاش کنید.")
    found = PanelLoginCode.find(data.validated_data["code"].strip())
    if found is not None:
        found = PanelLoginCode.objects.select_for_update().select_related("user").get(pk=found.pk)
    if found is None or not found.is_usable or not found.user.is_active or (found.staff_only and not found.user.is_staff):
        ratelimit.hit(ip_wrong_key)
        return _error("این پیوند ورود دیگر کار نمی‌کند. از پنل دوباره «باز کردن وب اپ» را بزنید.", "panel_code_invalid")
    user = found.user
    refused = _make_room(user, data.validated_data.get("replace_session_id"))
    if refused is not None:
        return refused  # the code stays usable (for its minute) so a device can be chosen and the call repeated
    found.used_at = timezone.now()
    found.save(update_fields=["used_at"])
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


def open_app(request):
    """The panel's «باز کردن وب اپ با حساب من»: a fresh one-time code, handed to the web app in the address's fragment
    (after «#», so it never reaches a server log or a Referer) at APP_URL/panel-login. POST only, staff only."""
    from django.contrib.admin.views.decorators import staff_member_required
    from django.http import HttpResponseNotAllowed, HttpResponseRedirect

    @staff_member_required
    def inner(request):
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        code = PanelLoginCode.issue(request.user)
        base = app_base_url()
        response = HttpResponseRedirect(f"{base}/panel-login#{code}")
        response["Cache-Control"] = "no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response

    return inner(request)
