"""Student classroom invitation landing page and verification."""

from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.catalog.panel_display import jalali_date
from .models import Classroom, ClassroomMember
from .views import _base


@require_http_methods(["GET", "POST"])
def classroom_join(request, code):
    code = code.strip().upper()
    classroom = get_object_or_404(Classroom.objects.select_related("book", "teacher"), code=code)

    if not classroom.is_active:
        return render(request, "website/classroom_join.html", {
            **_base(request),
            "classroom": classroom,
            "error_state": "inactive",
            "message": "لینک دعوت این کلاس در حال حاضر غیرفعال شده است.",
        })

    user = request.user if request.user.is_authenticated else None
    already_member = False
    if user and user.phone:
        already_member = ClassroomMember.objects.filter(
            classroom=classroom,
            phone=user.phone,
            status=ClassroomMember.Status.ACTIVE,
        ).exists()

    context = _base(request)
    context.update({
        "classroom": classroom,
        "book": classroom.book,
        "teacher": classroom.teacher,
        "already_member": already_member,
        "app_book_url": f"/book/{classroom.book.slug}",
    })

    if classroom.expiry_policy == Classroom.ExpiryPolicy.FIXED_DATE and classroom.ends_on:
        context["expiry_text"] = f"تا {jalali_date(classroom.ends_on)}"
    elif classroom.expiry_policy == Classroom.ExpiryPolicy.FROM_JOIN and classroom.duration_days:
        context["expiry_text"] = f"{classroom.duration_days} روز از زمان پیوستن"
    else:
        context["expiry_text"] = "همیشگی"

    # Logged-in student clicks "Add to Library" directly
    if request.method == "POST" and user and user.is_active:
        from .group_access import activate_classroom_members

        member, _ = ClassroomMember.objects.get_or_create(
            classroom=classroom,
            phone=user.phone,
            defaults={"join_method": ClassroomMember.JoinMethod.LINK},
        )
        if member.status != ClassroomMember.Status.ACTIVE:
            member.status = ClassroomMember.Status.WAITING_OTP
            member.save(update_fields=["status"])
        activate_classroom_members(user)
        messages.success(request, f"کتاب «{classroom.book.title}» با موفقیت به کتابخانه شما اضافه شد.")
        return redirect(f"/book/{classroom.book.slug}")

    return render(request, "website/classroom_join.html", context)


def verify_teacher_email(request, token):
    """Magic link click to verify teacher's email address."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user = get_object_or_404(User, email_verification_token=token)
    user.verify_email()
    messages.success(request, f"ایمیل {user.email} با موفقیت تأیید شد. اکنون می‌توانید خروجی‌های کتاب را مستقیماً به ایمیل خود ارسال کنید.")
    return redirect(f"/{settings.ADMIN_URL}")
