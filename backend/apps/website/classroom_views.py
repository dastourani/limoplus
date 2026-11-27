"""Student classroom invitation landing page and verification."""

import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as django_login
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from apps.accounts import ratelimit
from apps.accounts.models import OTPCode, PanelLoginCode, User
from apps.accounts.phone import InvalidPhone, normalize_phone
from apps.accounts.views import _PERSIAN_DIGITS, _client_ip
from apps.catalog.panel_display import jalali_date

from .group_access import activate_approved_members, activate_classroom_members, is_valid_cohort_book
from .models import Classroom, ClassroomMember
from .views import _base, app_url


def _web_app_book_handoff(user: User, book) -> str:
    """Build an absolute web-app URL with a single-use login fragment so a cross-domain classroom join opens the
    book signed in on the web app without a second SMS login."""
    code = PanelLoginCode.issue(user, staff_only=False)
    return app_url(f"panel-login?next=/book/{book.slug}#{code}")


def _classroom_error(classroom: Classroom, now=None) -> tuple[str, str] | None:
    """Return (error_state, message) when the classroom itself cannot accept enrollments."""
    if not classroom.is_active or not is_valid_cohort_book(classroom.book):
        return "inactive", "لینک دعوت این کلاس در حال حاضر غیرفعال شده است."
    if classroom.is_expired(now):
        return "expired", "مهلت استفاده از لینک دعوت این کلاس به پایان رسیده است."
    return None


def _member_error(member: ClassroomMember | None, classroom: Classroom) -> tuple[str, str] | None:
    """Return (error_state, message) for an existing member who cannot (re)enroll, or None."""
    if member is None:
        return ("full", "ظرفیت این کلاس تکمیل شده است.") if not classroom.has_capacity else None
    if member.status == ClassroomMember.Status.REVOKED:
        return "revoked", "دسترسی شما به این کلاس توسط استاد یا مدیر لغو شده است."
    if member.status == ClassroomMember.Status.EXPIRED:
        return "expired", "مهلت دسترسی شما به این کلاس به پایان رسیده است."
    if member.status == ClassroomMember.Status.ACTIVE:
        if not member.is_active:
            return "expired", "مهلت دسترسی شما به کتاب این کلاس به پایان رسیده است."
        return None
    # WAITING_OTP: can still activate only if classroom has capacity
    if not classroom.has_capacity:
        return "full", "ظرفیت این کلاس تکمیل شده است."
    return None


def _handle_web_otp_verify(request, classroom: Classroom):
    """Verify SMS OTP for an anonymous learner on the classroom page, enroll them, and start a web session."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "code": "invalid_request", "message": "درخواست نامعتبر است."}, status=400)

    if payload.get("action") != "verify_otp":
        return JsonResponse({"ok": False, "code": "invalid_request", "message": "عملیات پشتیبانی نمی‌شود."}, status=400)

    err = _classroom_error(classroom)
    if err is not None:
        return JsonResponse({"ok": False, "code": err[0], "message": err[1]}, status=400)

    try:
        phone = normalize_phone(str(payload.get("phone", "")))
    except InvalidPhone as exc:
        return JsonResponse({"ok": False, "code": "invalid_phone", "message": str(exc)}, status=400)

    code = str(payload.get("code", "")).strip().translate(_PERSIAN_DIGITS)
    if not code:
        return JsonResponse({"ok": False, "code": "invalid_code", "message": "کد پیامک‌شده را وارد کنید."}, status=400)

    ip_wrong_key = f"otp-wrong-ip:{_client_ip(request)}"
    if ratelimit.count(ip_wrong_key) >= settings.OTP_WRONG_PER_IP_PER_HOUR:
        return JsonResponse({"ok": False, "code": "rate_limited", "message": "تلاش‌های ناموفق زیاد است. کمی بعد دوباره تلاش کنید."}, status=429)

    with transaction.atomic():
        ratelimit.lock(f"otp:{phone}")
        day_ago = timezone.now() - timedelta(hours=24)
        wrong_today = OTPCode.objects.filter(phone=phone, created_at__gte=day_ago).aggregate(n=Sum("attempts"))["n"] or 0
        if wrong_today >= settings.OTP_MAX_WRONG_PER_DAY:
            return JsonResponse(
                {"ok": False, "code": "rate_limited", "message": "ورود با این شماره به دلیل تلاش‌های ناموفق تا ۲۴ ساعت بسته شد."},
                status=429,
            )

        otp = OTPCode.objects.select_for_update().filter(phone=phone).order_by("-created_at").first()
        if otp is None or not otp.is_usable:
            return JsonResponse({"ok": False, "code": "otp_expired", "message": "کد منقضی شده است. کد جدید بگیرید."}, status=400)
        if not otp.matches(code):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            ratelimit.hit(ip_wrong_key)
            return JsonResponse({"ok": False, "code": "otp_wrong", "message": "کد اشتباه است."}, status=400)

        try:
            with transaction.atomic():
                user, _ = User.objects.get_or_create(phone=phone)
        except IntegrityError:
            user = User.objects.get(phone=phone)
        if not user.is_active:
            return JsonResponse({"ok": False, "code": "user_inactive", "message": "این حساب غیرفعال شده است."}, status=403)

        now = timezone.now()
        locked_classroom = (
            Classroom.objects.select_for_update(of=("self",))
            .select_related("book", "teacher")
            .get(pk=classroom.pk)
        )
        err = _classroom_error(locked_classroom, now=now)
        if err is not None:
            return JsonResponse({"ok": False, "code": err[0], "message": err[1]}, status=400)

        member = (
            ClassroomMember.objects.select_for_update(of=("self",))
            .select_related("entitlement")
            .filter(classroom=locked_classroom, phone=user.phone)
            .first()
        )
        member_err = _member_error(member, locked_classroom)
        if member_err is not None:
            status_code = 403 if member_err[0] == "revoked" else 400
            return JsonResponse({"ok": False, "code": member_err[0], "message": member_err[1]}, status=status_code)

        if member is None:
            member = ClassroomMember.objects.create(
                classroom=locked_classroom,
                phone=user.phone,
                join_method=ClassroomMember.JoinMethod.LINK,
                status=ClassroomMember.Status.WAITING_OTP,
            )

        otp.consumed_at = now
        otp.save(update_fields=["consumed_at"])
        activate_approved_members(user, now=now)
        activate_classroom_members(user, now=now)

        member.refresh_from_db()
        if not member.is_active:
            return JsonResponse(
                {"ok": False, "code": "activation_failed", "message": "امکان فعال‌سازی دسترسی این کلاس وجود ندارد."},
                status=400,
            )

    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    response = JsonResponse({"ok": True, "redirect": _web_app_book_handoff(user, locked_classroom.book)})
    response["Cache-Control"] = "no-store"
    return response


@sensitive_post_parameters("phone", "code")
@require_http_methods(["GET", "POST"])
def classroom_join(request, code):
    code = code.strip().upper()
    classroom = get_object_or_404(Classroom.objects.select_related("book", "teacher"), code=code)

    if request.method == "POST" and "application/json" in (request.content_type or ""):
        return _handle_web_otp_verify(request, classroom)

    now = timezone.now()
    class_err = _classroom_error(classroom, now=now)

    user = request.user if request.user.is_authenticated else None
    member = None
    if user and user.phone:
        member = (
            ClassroomMember.objects.filter(classroom=classroom, phone=user.phone)
            .select_related("entitlement")
            .first()
        )

    # Logged-in student clicks "Add to Library" directly
    if request.method == "POST" and user and user.is_active:
        with transaction.atomic():
            locked_classroom = (
                Classroom.objects.select_for_update(of=("self",))
                .select_related("book", "teacher")
                .get(pk=classroom.pk)
            )
            post_err = _classroom_error(locked_classroom, now=now)
            if post_err is not None:
                messages.error(request, post_err[1])
                return redirect(request.path)

            locked_member = (
                ClassroomMember.objects.select_for_update(of=("self",))
                .select_related("entitlement")
                .filter(classroom=locked_classroom, phone=user.phone)
                .first()
            )
            member_err = _member_error(locked_member, locked_classroom)
            if member_err is not None:
                messages.error(request, member_err[1])
                return redirect(request.path)

            if locked_member is None:
                locked_member = ClassroomMember.objects.create(
                    classroom=locked_classroom,
                    phone=user.phone,
                    join_method=ClassroomMember.JoinMethod.LINK,
                    status=ClassroomMember.Status.WAITING_OTP,
                )

            if locked_member.status == ClassroomMember.Status.WAITING_OTP:
                activate_classroom_members(user, now=now, classroom_id=locked_classroom.pk)
                locked_member.refresh_from_db()

            if locked_member.is_active:
                if request.POST.get("action") != "open_app":
                    messages.success(request, f"کتاب «{locked_classroom.book.title}» با موفقیت به کتابخانه شما اضافه شد.")
                response = redirect(_web_app_book_handoff(user, locked_classroom.book))
                response["Cache-Control"] = "no-store"
                response["Referrer-Policy"] = "no-referrer"
                return response

            messages.error(request, "امکان فعال‌سازی دسترسی این کلاس وجود ندارد؛ مهلت یا ظرفیت کلاس را بررسی کنید.")
            return redirect(request.path)

    error_state = None
    error_message = None
    already_member = False

    if class_err is not None:
        error_state, error_message = class_err
    else:
        member_err = _member_error(member, classroom)
        if member_err is not None:
            error_state, error_message = member_err
        elif member is not None and member.is_active:
            already_member = True

    context = _base(request)
    context.update({
        "classroom": classroom,
        "book": classroom.book,
        "teacher": classroom.teacher,
        "already_member": already_member,
        "error_state": error_state,
        "message": error_message,
        "app_book_url": app_url(f"book/{classroom.book.slug}"),
        "deep_link_url": f"limookhan://book/{classroom.book.slug}",
    })

    if classroom.expiry_policy == Classroom.ExpiryPolicy.FIXED_DATE and classroom.ends_on:
        context["expiry_text"] = f"تا {jalali_date(classroom.ends_on)}"
    elif classroom.expiry_policy == Classroom.ExpiryPolicy.FROM_JOIN and classroom.duration_days:
        context["expiry_text"] = f"{classroom.duration_days} روز از زمان پیوستن"
    else:
        context["expiry_text"] = "همیشگی"

    return render(request, "website/classroom_join.html", context)


def verify_teacher_email(request, token):
    """Magic link click to verify teacher's email address."""
    from django.contrib.auth import get_user_model
    from django.urls import reverse

    User = get_user_model()
    acting_id = request.user.pk if request.user.is_authenticated else None
    user, state = User.consume_email_verification(token, acting_user_id=acting_id)
    if state == "wrong_user":
        return render(
            request,
            "website/teacher_notice_error.html",
            {
                **_base(request),
                "title": "عدم تطابق حساب کاربری",
                "message": "این پیوند تأیید متعلق به حساب کاربری دیگری است. برای تأیید آن ابتدا از حساب فعلی خارج شوید.",
                "teacher_login_url": reverse("teacher-login"),
            },
            status=403,
        )
    if user is None or state != "ok":
        msg = (
            "مهلت اعتبار این پیوند تأیید به پایان رسیده است. لطفاً در پنل استادی، گزینهٔ «ارسال مجدد» یا «ویرایش ایمیل» را بزنید."
            if state == "expired"
            else "این پیوند تأیید نامعتبر است، قبلاً استفاده شده یا به نشانی ایمیل دیگری تعلق داشته است."
        )
        return render(
            request,
            "website/teacher_notice_error.html",
            {
                **_base(request),
                "title": "پیوند تأیید ایمیل معتبر نیست",
                "message": msg,
                "teacher_login_url": reverse("teacher-login"),
            },
            status=400,
        )

    if request.user.is_authenticated and request.user.is_active and request.user.is_staff:
        messages.success(
            request,
            f"ایمیل {user.email} با موفقیت تأیید شد. اکنون اعلان‌های میز تألیف و خروجی‌های کتاب به این نشانی ارسال می‌شوند.",
        )
        return redirect("admin:index")
    request.session["admin_login_notice"] = (
        f"ایمیل {user.email} با موفقیت تأیید شد. برای ورود به پنل اساتید، شمارهٔ خود را وارد کنید."
    )
    return redirect("teacher-login")
