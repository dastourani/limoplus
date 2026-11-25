from __future__ import annotations

from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts import ratelimit
from apps.accounts.views import _client_ip

from .models import ErrorGroup
from .sanitize import scrub_text
from .service import record_event

EVENTS_PER_IP_PER_HOUR = 90
EVENTS_PER_INSTALL_PER_HOUR = 45
MAX_BATCH_SIZE = 20

_CLIENT_SEVERITIES = {
    ErrorGroup.Severity.CRITICAL,
    ErrorGroup.Severity.ERROR,
    ErrorGroup.Severity.WARNING,
}
_CLIENT_KINDS = {
    ErrorGroup.Kind.CLIENT_ERROR,
    ErrorGroup.Kind.OFFLINE,
    ErrorGroup.Kind.NETWORK,
    ErrorGroup.Kind.INVARIANT,
}


@transaction.non_atomic_requests
@api_view(["POST"])
@permission_classes([AllowAny])
def ingest_events(request):
    """
    Receives sanitized client error / offline-health reports (single object or `{"events": [...]}`).
    Idempotent on `event_id` so network retries never double-count; strictly rate-limited and allowlisted.
    """
    ip = _client_ip(request)
    if ratelimit.count(f"diag-ip:{ip}") >= EVENTS_PER_IP_PER_HOUR:
        return Response({"code": "rate_limited", "message": "درخواست‌های گزارش زیاد است."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    payload = request.data if isinstance(request.data, dict) else {}
    raw_items = payload.get("events") if isinstance(payload.get("events"), list) else [payload]
    if not raw_items:
        return Response({"accepted": 0, "duplicates": 0})
    raw_items = raw_items[:MAX_BATCH_SIZE]

    header_platform = (request.headers.get("X-App-Platform") or "").strip().lower()
    header_channel = (request.headers.get("X-App-Channel") or "").strip().lower()
    header_build = (request.headers.get("X-App-Build") or "").strip()
    header_web_commit = (request.headers.get("X-App-Web-Commit") or "").strip()
    header_install = (request.headers.get("X-App-Install-Id") or "").strip()
    header_req_id = getattr(request, "diagnostics_request_id", "") or (request.headers.get("X-Request-Id") or "").strip()

    user_id = request.user.pk if getattr(request, "user", None) and request.user.is_authenticated else None

    accepted = 0
    duplicates = 0
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        code = scrub_text(item.get("code"), 80)
        title = scrub_text(item.get("title"), 240)
        if not code and not title:
            continue

        install_id = scrub_text(item.get("install_id") or header_install, 64)
        if install_id and ratelimit.count(f"diag-install:{install_id}") >= EVENTS_PER_INSTALL_PER_HOUR:
            return Response(
                {"code": "rate_limited", "message": "محدودیت ارسال گزارش برای این نصب پر شده است.", "accepted": accepted, "duplicates": duplicates},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        ratelimit.hit(f"diag-ip:{ip}")
        if install_id:
            ratelimit.hit(f"diag-install:{install_id}")

        kind = item.get("kind") if item.get("kind") in _CLIENT_KINDS else ErrorGroup.Kind.CLIENT_ERROR
        severity = item.get("severity") if item.get("severity") in _CLIENT_SEVERITIES else ErrorGroup.Severity.ERROR
        platform = scrub_text(item.get("platform") or header_platform, 20).lower()
        channel = scrub_text(item.get("channel") or header_channel, 20).lower()
        app_build = scrub_text(item.get("app_build") or header_build, 40)
        web_commit = scrub_text(item.get("web_commit") or header_web_commit, 40)

        _, created = record_event(
            source=ErrorGroup.Source.CLIENT,
            kind=kind,
            code=code or "client_error",
            title=title or code or "خطای کلاینت",
            event_id=item.get("event_id"),
            request_id=scrub_text(item.get("request_id") or header_req_id, 64),
            op_id=scrub_text(item.get("op_id"), 64),
            install_id=install_id,
            user_id=user_id,
            platform=platform,
            channel=channel,
            app_build=app_build,
            web_commit=web_commit,
            is_offline=bool(item.get("is_offline", False)),
            route=item.get("route") or "",
            operation=item.get("operation") or "",
            expected=item.get("expected") or "",
            observed=item.get("observed") or "",
            severity=severity,
            context=item.get("context") if isinstance(item.get("context"), dict) else {},
            breadcrumbs=item.get("breadcrumbs") if isinstance(item.get("breadcrumbs"), list) else [],
        )
        if created:
            accepted += 1
        else:
            duplicates += 1

    return Response({"accepted": accepted, "duplicates": duplicates})
