from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.study.views import _err, _readable_node

from . import alerts, core


def _quota(used: int) -> dict:
    return {"used": used, "limit": core.DAILY_LIMIT, "left": max(0, core.DAILY_LIMIT - used)}


@api_view(["GET"])
def copy_quota(request):
    return Response(_quota(core.used_today(request.user)))


@api_view(["POST"])
def copy_text(request, node_id):
    """Copy a piece of a lesson: recorded, counted against today's copies, and given back with its fingerprint."""
    node, _, error = _readable_node(request, node_id)
    if error:
        return error
    quote = str(request.data.get("text", "")).strip()
    if not quote:
        return _err("متنی انتخاب نشده است.", "empty")
    if len(quote) > core.MAX_CHARS:
        return _err("کپی متن طولانی مجاز نیست.", "too_long")
    mode = "summary" if request.data.get("mode") == "summary" else "full"
    with transaction.atomic():
        # One copy at a time per learner, so two quick copies cannot both take the last place.
        type(request.user).objects.select_for_update().filter(pk=request.user.pk).first()
        used = core.used_today(request.user)
        if used >= core.DAILY_LIMIT:
            return Response({"code": "quota", "message": f"سهم کپی امروز تمام شد ({core.DAILY_LIMIT} از {core.DAILY_LIMIT}). می‌توانی متن را به یادداشت‌هایت ببری.",
                             **_quota(used)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        event, text = core.record(request.user, node, quote, mode, request.headers.get("X-App-Platform", "web"))
        used += 1
        alerts.after_copy(event, used)
    return Response({"text": text, **_quota(used)}, status=status.HTTP_201_CREATED)
