"""The public, no-cache landing page for a one-time teacher invitation fragment."""

from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .views import _base


@require_GET
def teacher_invitation(request):
    # The bearer token is deliberately in the URL fragment, not the path or query. Browsers never send fragments
    # in HTTP requests, access logs, or Referer headers; JavaScript submits it only with a valid phone OTP.
    context = _base(request, invitation_landing=True, invitation_login_url=reverse("teacher-login"))
    context["canonical"] = request.build_absolute_uri(reverse("website:home"))
    response = render(request, "website/teacher_invitation.html", context)
    response["Cache-Control"] = "no-store, max-age=0"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
