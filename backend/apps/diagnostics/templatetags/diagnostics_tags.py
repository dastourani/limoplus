from __future__ import annotations

from django import template

from ..sanitize import diag_session_tag

register = template.Library()


@register.simple_tag(takes_context=True)
def diagnostics_session_tag(context) -> str:
    """Returns a non-PII HMAC tag tying browser-queued events to the capture-time authenticated session."""
    request = context.get("request")
    if not request:
        return ""
    user = getattr(request, "user", None)
    session = getattr(request, "session", None)
    if not getattr(user, "is_authenticated", False) or not session or not session.session_key:
        return ""
    return diag_session_tag(user.pk, session.session_key)
