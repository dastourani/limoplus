"""Public, spam-limited teacher-application intake. Review never grants access by itself."""

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from apps.accounts import ratelimit
from apps.accounts.views import _client_ip

from .forms import TeacherApplicationForm
from .models import TeacherApplication
from .views import _base

_SUBMITTED_SESSION_KEY = "teacher_application_submitted"


def _ip_is_limited(request):
    ip = _client_ip(request)
    key = f"teacher-application-ip:{ip}"
    with transaction.atomic():
        ratelimit.lock(f"teacher-application-ip:{ip}")
        if ratelimit.count(key) >= settings.TEACHER_APPLICATIONS_PER_IP_PER_HOUR:
            return True
        ratelimit.hit(key)
    return False


def _store_if_new(form):
    """Keep one pending/approved request per normalised phone and throttle repeats across IPs."""
    phone = form.cleaned_data["phone"]
    key = f"teacher-application-phone:{phone}"
    active_statuses = (
        TeacherApplication.Status.PENDING,
        TeacherApplication.Status.NEEDS_INFO,
        TeacherApplication.Status.APPROVED,
    )
    with transaction.atomic():
        ratelimit.lock(f"teacher-application-phone:{phone}")
        if ratelimit.count(key) >= settings.TEACHER_APPLICATIONS_PER_PHONE_PER_HOUR:
            return
        ratelimit.hit(key)
        if TeacherApplication.objects.filter(phone=phone, status__in=active_statuses).exists():
            return
        application = form.save(commit=False)
        application.phone = phone
        application.save()
        from apps.catalog.backups import notify_bale_after_commit
        resume_line = f"\nرزومه/معرفی: {application.resume_url}" if application.resume_url else ""
        scope_display = application.get_collaboration_scope_display() or "اعلام نشده"
        notify_bale_after_commit(
            f"🎓 درخواست جدید همکاری آموزشی\n"
            f"نام: {application.name}\n"
            f"شماره تماس: {application.phone}\n"
            f"کتاب/درس: {application.book_or_link}\n"
            f"نحوه استفاده: {scope_display}{resume_line}",
            log_label=f"Bale teacher application alert for #{application.id}",
        )


def _render_form(request, form, *, submitted=False, rate_limited=False, status=200):
    return render(
        request,
        "website/teacher_application.html",
        _base(request, application_form=form, submitted=submitted, rate_limited=rate_limited),
        status=status,
    )


@never_cache
@require_http_methods(["GET", "POST"])
def teacher_application(request):
    if request.method == "GET":
        submitted = bool(request.session.pop(_SUBMITTED_SESSION_KEY, False))
        return _render_form(request, TeacherApplicationForm(), submitted=submitted)

    form = TeacherApplicationForm(request.POST)
    if _ip_is_limited(request):
        return _render_form(request, form, rate_limited=True, status=429)

    if form.is_valid():
        # Bots filling the off-screen honeypot get the same confirmation, but no row is stored.
        if not form.cleaned_data["website"]:
            _store_if_new(form)
        request.session[_SUBMITTED_SESSION_KEY] = True
        return redirect("website:teacher-application")

    return _render_form(request, form)
