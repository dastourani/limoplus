"""OTP-backed Django admin sign-in, with a superuser-only password break-glass path."""

import logging
from datetime import timedelta

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate, login
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters

from . import ratelimit
from .models import OTPCode, User
from .phone import InvalidPhone, normalize_phone
from .sms import SMSError, send_login_code
from .views import _client_ip, _otp_message

log = logging.getLogger(__name__)

_PHONE_SESSION = "admin_login_phone"
_NEXT_SESSION = "admin_login_next"
_NOTICE_SESSION = "admin_login_notice"
_ERROR_SESSION = "admin_login_error"
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _explicit_safe_next(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ""


def _safe_next(request, candidate):
    return _explicit_safe_next(request, candidate) or reverse("admin:index")


def _login_url(mode):
    return reverse("teacher-login" if mode == "teacher" else "admin:login")


def _is_eligible_for_mode(user, mode: str) -> bool:
    if user is None or not user.is_active or not user.is_staff:
        return False
    if mode == "admin":
        return bool(user.is_superuser)
    if mode == "teacher":
        return not user.is_superuser
    return False


def _set_panel_role_cookie(response, user):
    response.set_cookie(
        "lp_panel_role",
        "admin" if user.is_superuser else "teacher",
        max_age=60 * 60 * 24 * 365,
        httponly=True,
        samesite="Lax",
    )
    return response


def _render_login(request, *, mode="admin", error="", notice="", next_url=None, wrong_role=False):
    request.current_app = admin.site.name
    is_teacher = mode == "teacher"
    raw_next = next_url if next_url is not None else (request.session.get(_NEXT_SESSION) or request.GET.get("next") or "")
    context = {
        **admin.site.each_context(request),
        "title": "ورود اساتید و مؤلفان" if is_teacher else "ورود به پنل مدیریت",
        "site_header": "لیموخوان",
        "login_url": _login_url(mode),
        "is_teacher_login": is_teacher,
        "wrong_role": wrong_role,
        "next": _explicit_safe_next(request, raw_next),
        "otp_phone": request.session.get(_PHONE_SESSION, ""),
        "error": error or request.session.pop(_ERROR_SESSION, ""),
        "notice": notice or request.session.pop(_NOTICE_SESSION, ""),
    }
    return TemplateResponse(request, "admin/login.html", context)


def _redirect_with_flash(request, *, mode="admin", notice="", error=""):
    if notice:
        request.session[_NOTICE_SESSION] = notice
    if error:
        request.session[_ERROR_SESSION] = error
    return HttpResponseRedirect(_login_url(mode))


def _request_ip_limited(request):
    """Count every send-code attempt, including unknown accounts, without revealing whether an account exists."""
    ip = _client_ip(request)
    key = f"otp-req-ip:{ip}"
    with transaction.atomic():
        ratelimit.lock(f"admin-otp-request-ip:{ip}")
        if ratelimit.count(key) >= settings.OTP_REQUESTS_PER_IP_PER_HOUR:
            return True
        ratelimit.hit(key)
    return False


def _send_otp(request, next_url, *, mode="admin"):
    if _request_ip_limited(request):
        return _redirect_with_flash(request, mode=mode, error="درخواست‌های ورود زیاد است؛ کمی بعد دوباره تلاش کنید.")

    try:
        phone = normalize_phone(request.POST.get("phone", ""))
    except InvalidPhone as exc:
        return _render_login(request, mode=mode, error=str(exc), next_url=next_url)

    request.session[_PHONE_SESSION] = phone
    explicit_next = _explicit_safe_next(request, next_url)
    if explicit_next:
        request.session[_NEXT_SESSION] = explicit_next
    else:
        request.session.pop(_NEXT_SESSION, None)

    otp = code = None
    with transaction.atomic():
        ratelimit.lock(f"otp:{phone}")
        user = User.objects.select_for_update().filter(phone=phone).first()
        if _is_eligible_for_mode(user, mode):
            now = timezone.now()
            recent = OTPCode.objects.filter(phone=phone, created_at__gte=now - timedelta(hours=1))
            last = recent.order_by("-created_at").first()
            can_resend = not last or now - last.created_at >= settings.OTP_RESEND_COOLDOWN
            under_hourly_limit = recent.count() < settings.OTP_MAX_PER_HOUR
            if can_resend and under_hourly_limit:
                otp, code = OTPCode.issue(phone)

    if otp is not None:
        try:
            send_login_code(phone, code, _otp_message(code))
        except SMSError as exc:
            log.error("Admin login SMS to %s failed: %s", phone, exc)
            otp.delete()

    # Same response for an unknown/non-staff number, a throttled number, and a sent code.
    notice = (
        "درخواست کد برای این شماره ثبت شد. اگر حساب استادی شما فعال شده باشد، "
        "پیامک تا لحظاتی دیگر می‌رسد."
        if mode == "teacher"
        else "درخواست کد ثبت شد. اگر این شماره متعلق به حساب فعال مدیر کل باشد، "
        "پیامک تا لحظاتی دیگر می‌رسد."
    )
    return _redirect_with_flash(
        request,
        mode=mode,
        notice=notice,
    )


def _record_rejected_password(request, identifier):
    """A valid legacy password on a non-superuser is still a failed break-glass attempt."""
    ratelimit.hit(f"admin-fail-ip:{_client_ip(request)}")
    ratelimit.hit(f"admin-fail-phone:{identifier[:100]}")


def _password_login(request, next_url, *, mode="admin"):
    raw_identifier = (request.POST.get("username") or "").strip()
    try:
        identifier = normalize_phone(raw_identifier)
    except InvalidPhone:
        identifier = raw_identifier
    user = authenticate(request, username=identifier, password=request.POST.get("password", ""))
    if user is not None and user.is_active and user.is_staff and user.is_superuser:
        destination = _safe_next(request, next_url)
        request.session.pop(_PHONE_SESSION, None)
        request.session.pop(_NEXT_SESSION, None)
        login(request, user)
        return _set_panel_role_cookie(HttpResponseRedirect(destination), user)

    if user is not None:
        _record_rejected_password(request, identifier)
    return _render_login(
        request,
        mode=mode,
        error="ورود با گذرواژه فقط برای مسیر اضطراری مدیر کل است؛ برای حساب‌های دیگر از کد پیامکی استفاده کنید.",
        next_url=next_url,
    )


def _verify_otp(request, next_url, *, mode="admin"):
    try:
        phone = normalize_phone(request.POST.get("phone", ""))
    except InvalidPhone as exc:
        return _render_login(request, mode=mode, error=str(exc), next_url=next_url)

    if phone != request.session.get(_PHONE_SESSION):
        return _render_login(request, mode=mode, error="ابتدا برای همین شماره کد ورود بگیرید.", next_url=next_url)

    code = (request.POST.get("code") or "").strip().translate(_DIGITS)
    ip_key = f"otp-wrong-ip:{_client_ip(request)}"
    user = None
    error = ""
    with transaction.atomic():
        ratelimit.lock(f"admin-otp-verify-ip:{_client_ip(request)}")
        if ratelimit.count(ip_key) >= settings.OTP_WRONG_PER_IP_PER_HOUR:
            error = "تلاش‌های ناموفق زیاد است. کمی بعد دوباره تلاش کنید."
        else:
            ratelimit.lock(f"otp:{phone}")
            user = User.objects.select_for_update().filter(phone=phone).first()
            if not _is_eligible_for_mode(user, mode):
                ratelimit.hit(ip_key)
                error = "کد نامعتبر یا منقضی است؛ دوباره تلاش کنید یا کد تازه بگیرید."
            else:
                day_ago = timezone.now() - timedelta(hours=24)
                wrong_today = (
                    OTPCode.objects.filter(phone=phone, created_at__gte=day_ago).aggregate(n=Sum("attempts"))["n"] or 0
                )
                if wrong_today >= settings.OTP_MAX_WRONG_PER_DAY:
                    error = "ورود با این شماره به دلیل تلاش‌های ناموفق تا ۲۴ ساعت بسته شد."
                else:
                    otp = OTPCode.objects.select_for_update().filter(phone=phone).order_by("-created_at").first()
                    if otp is None or not otp.is_usable:
                        ratelimit.hit(ip_key)
                        error = "کد نامعتبر یا منقضی است؛ دوباره تلاش کنید یا کد تازه بگیرید."
                    elif len(code) != settings.OTP_LENGTH or not code.isdigit() or not otp.matches(code):
                        otp.attempts += 1
                        otp.save(update_fields=["attempts"])
                        ratelimit.hit(ip_key)
                        error = "کد اشتباه است."
                    else:
                        now = timezone.now()
                        otp.consumed_at = now
                        otp.save(update_fields=["consumed_at"])
                        from apps.website.group_access import activate_approved_members, activate_classroom_members

                        activate_approved_members(user, now=now)
                        activate_classroom_members(user, now=now)

    if error:
        return _render_login(request, mode=mode, error=error, next_url=next_url)

    destination = _safe_next(request, request.session.get(_NEXT_SESSION) or next_url)
    request.session.pop(_PHONE_SESSION, None)
    request.session.pop(_NEXT_SESSION, None)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return _set_panel_role_cookie(HttpResponseRedirect(destination), user)


def _panel_login(request, *, mode):
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])

    raw_next = request.POST.get("next") or request.GET.get("next") or request.session.get(_NEXT_SESSION) or ""
    next_url = _safe_next(request, raw_next)
    if request.user.is_authenticated and request.user.is_active and request.user.is_staff:
        if not _is_eligible_for_mode(request.user, mode):
            error = (
                "ورود مدیر کل فقط از مسیر مدیریت انجام می‌شود."
                if mode == "teacher"
                else "ورود به مسیر مدیریت فقط برای مدیر کل است؛ برای ورود به پنل اساتید از درگاه اساتید استفاده کنید."
            )
            return _render_login(
                request,
                mode=mode,
                error=error,
                next_url="",
                wrong_role=True,
            )
        return HttpResponseRedirect(next_url)

    if request.method == "POST":
        action = request.POST.get("action", "send_otp" if mode == "teacher" else "password")
        if action == "send_otp":
            return _send_otp(request, raw_next, mode=mode)
        if action == "verify_otp":
            return _verify_otp(request, raw_next, mode=mode)
        if action == "reset_phone":
            request.session.pop(_PHONE_SESSION, None)
            explicit_next = _explicit_safe_next(request, raw_next)
            target = _login_url(mode)
            if explicit_next:
                from django.utils.http import urlencode

                target = f"{target}?{urlencode({'next': explicit_next})}"
            return HttpResponseRedirect(target)
        if action in ("", "password"):
            if mode == "teacher":
                return _render_login(
                    request,
                    mode=mode,
                    error="ورود اساتید و مؤلفان فقط با کد تأیید پیامکی انجام می‌شود.",
                    next_url=raw_next,
                )
            return _password_login(request, raw_next, mode=mode)
        return _render_login(request, mode=mode, error="درخواست ورود معتبر نیست.", next_url=raw_next)

    notice = request.session.pop(_NOTICE_SESSION, "")
    error = request.session.pop(_ERROR_SESSION, "")
    return _render_login(request, mode=mode, notice=notice, error=error, next_url=raw_next)


@transaction.non_atomic_requests
@csrf_protect
@sensitive_post_parameters("password", "code")
@never_cache
def admin_login(request):
    """Django admin entry: SMS OTP for active staff, with password fallback for superusers only."""
    return _panel_login(request, mode="admin")


@transaction.non_atomic_requests
@csrf_protect
@sensitive_post_parameters("code")
@never_cache
def teacher_login(request):
    """Dedicated teacher & author entry: SMS OTP only, without any password break-glass form."""
    return _panel_login(request, mode="teacher")
