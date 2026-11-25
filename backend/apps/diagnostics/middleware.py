from __future__ import annotations

import logging
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .service import record_server_exception

log = logging.getLogger("django.request")


class RequestDiagnosticsMiddleware:
    """
    Attaches a stable `X-Request-Id` to every request/response and records unhandled server exceptions
    without altering normal error responses or container console logging.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        req_id = (request.headers.get("X-Request-Id") or "").strip()[:64] or uuid.uuid4().hex[:16]
        request.diagnostics_request_id = req_id
        response = self.get_response(request)
        response["X-Request-Id"] = req_id
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, (Http404, PermissionDenied)):
            return None
        # Always write to standard logger first (survives even if PostgreSQL/SQLite is unreachable).
        log.exception("Unhandled exception on %s %s [req=%s]", request.method, request.path, getattr(request, "diagnostics_request_id", ""))
        # Never swallow or replace the exception; in tests with DEBUG/TESTING, avoid touching rolled-back atomic blocks unless safe.
        from django.db import connection

        if connection.in_atomic_block and connection.needs_rollback:
            # Defer or skip writing into an already-broken atomic block (in production ATOMIC_REQUESTS rolls back view atomic before process_exception returns,
            # or we can clear/leave it untouched; safest is not corrupting an active rollback block).
            return None
        if not getattr(settings, "DIAGNOSTICS_CAPTURE_EXCEPTIONS", True):
            return None
        record_server_exception(request, exception)
        return None
