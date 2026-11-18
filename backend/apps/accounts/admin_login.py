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


def _safe_next(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("admin:index")


def _render_login(request, *, error="", notice="", next_url=None):
    request.current_app = admin.site.name
    next_url = _safe_next(request, next_url or request.session.get(_NEXT_SESSION) or request.GET.get("next"))
    context = {
        **admin.site.each_context(request),
        "title": "ورود به پنل مدیریت",
        "login_url": reverse("admin:login"),
        "next": next_url,
        "otp_phone": request.session.get(_PHONE_SESSION, ""),
        "error": error or request.session.pop(_ERROR_SESSION, ""),
        "notice": notice or request.session.pop(_NOTICE_SESSION, ""),
    }
    return TemplateResponse(request, "admin/login.html", context)


def _redirect_with_flash(request, *, notice="", error=""):
    if notice:
        request.session[_NOTICE_SESSION] = notice
    if error:
        request.session[_ERROR_SESSION] = error
    return HttpResponseRedirect(reverse("admin:login"))


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


def _send_otp(request, next_url):
    if _request_ip_limited(request):
        return _redirect_with_flash(request, error="درخواست‌های ورود زیاد است؛ کمی بعد دوباره تلاش کنید.")

    try:
        phone = normalize_phone(request.POST.get("phone", ""))
    except InvalidPhone as exc:
        return _render_login(request, error=str(exc), next_url=next_url)

    request.session[_PHONE_SESSION] = phone
    request.session[_NEXT_SESSION] = _safe_next(request, next_url)

    otp = code = None
    with transaction.atomic():
        ratelimit.lock(f"otp:{phone}")
        user = User.objects.select_for_update().filter(phone=phone).first()
        if user is not None and user.is_active and user.is_staff:
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
    return _redirect_with_flash(
        request,
        notice=(
            "اگر این شماره متعلق به حساب فعال پنل باشد، کد ارسال می‌شود. "
            "اگر پیامکی دریافت نکردید، شماره را بررسی و کمی بعد دوباره تلاش کنید."
        ),
    )


def _record_rejected_password(request, identifier):
    """A valid legacy password on a non-superuser is still a failed break-glass attempt."""
    ratelimit.hit(f"admin-fail-ip:{_client_ip(request)}")
    ratelimit.hit(f"admin-fail-phone:{identifier[:100]}")


def _password_login(request, next_url):
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
        return HttpResponseRedirect(destination)

    if user is not None:
        _record_rejected_password(request, identifier)
    return _render_login(
        request,
        error="ورود با گذرواژه فقط برای مسیر اضطراری مدیر کل است؛ برای حساب‌های دیگر از کد پیامکی استفاده کنید.",
        next_url=next_url,
    )


def _verify_otp(request, next_url):
    try:
        phone = normalize_phone(request.POST.get("phone", ""))
    except InvalidPhone as exc:
        return _render_login(request, error=str(exc), next_url=next_url)

    if phone != request.session.get(_PHONE_SESSION):
        return _render_login(request, error="ابتدا برای همین شماره کد ورود بگیرید.", next_url=next_url)

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
            if user is None or not user.is_active or not user.is_staff:
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
                        otp.consumed_at = timezone.now()
                        otp.save(update_fields=["consumed_at"])

    if error:
        return _render_login(request, error=error, next_url=next_url)

    destination = _safe_next(request, request.session.get(_NEXT_SESSION) or next_url)
    request.session.pop(_PHONE_SESSION, None)
    request.session.pop(_NEXT_SESSION, None)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return HttpResponseRedirect(destination)


@transaction.non_atomic_requests
@csrf_protect
@sensitive_post_parameters("password", "code")
@never_cache
def admin_login(request):
    """Django admin entry: SMS OTP for active staff, with password fallback for superusers only."""
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])

    next_url = _safe_next(
        request,
        request.POST.get("next") or request.GET.get("next") or request.session.get(_NEXT_SESSION),
    )
    if request.user.is_authenticated and request.user.is_active and request.user.is_staff:
        return HttpResponseRedirect(next_url)

    if request.method == "POST":
        action = request.POST.get("action", "password")
        if action == "send_otp":
            return _send_otp(request, next_url)
        if action == "verify_otp":
            return _verify_otp(request, next_url)
        if action in ("", "password"):
            return _password_login(request, next_url)
        return _render_login(request, error="درخواست ورود معتبر نیست.", next_url=next_url)

    notice = request.session.pop(_NOTICE_SESSION, "")
    error = request.session.pop(_ERROR_SESSION, "")
    return _render_login(request, notice=notice, error=error, next_url=next_url)
