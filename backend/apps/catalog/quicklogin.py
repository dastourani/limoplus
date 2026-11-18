"""A one-click way into the demo preview.

Only ever active when settings.DEBUG is on AND the phone belongs to an existing superuser: in production DEBUG is
false, so the view refuses and nothing changes. It exists because a preview link that lands on a login form wastes a
round trip every time someone wants to look at a change.
"""
from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect


def quick_login(request, phone):
    if not settings.DEBUG:
        raise Http404
    from apps.accounts.models import User

    # Staff, not only superusers: the preview needs to be seen as a professor too, which is the whole point of
    # the publishing gate. Still DEBUG-only, so in production none of this exists.
    user = User.objects.filter(phone=phone, is_active=True, is_staff=True).first()
    if user is None:
        raise PermissionDenied("چنین کاربری در این نسخه‌ی آزمایشی نیست.")
    user.backend = "django.contrib.auth.backends.ModelBackend"
    login(request, user)
    return redirect(request.GET.get("next") or "/admin/")
