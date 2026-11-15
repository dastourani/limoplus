from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import DeviceSession


class DeviceSessionAuthentication(authentication.BaseAuthentication):
    """`Authorization: Bearer <token>`; the token belongs to one device session."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1").split()
        if not header or header[0] != self.keyword:
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("توکن نامعتبر است.")
        session = DeviceSession.find_by_token(header[1])
        if session is None or not session.is_active or not session.user.is_active:
            raise exceptions.AuthenticationFailed("نشست منقضی شده است. دوباره وارد شوید.")
        now = timezone.now()
        if now - session.last_seen_at > timedelta(minutes=5):
            session.last_seen_at = now
            session.save(update_fields=["last_seen_at"])
        request.device_session = session
        user = session.user
        # Staff can look at the app as a learner sees it (locks, prices, free labels); nothing else changes.
        user.view_as_learner = user.is_staff and request.META.get("HTTP_X_VIEW_AS") == "learner"
        return user, session

    def authenticate_header(self, request):
        return self.keyword
