"""
«زمان مطالعه»: the app sends what it counted (seconds per section, activity and day); the server adds it up exactly.
The learner sees rounded totals (book, chapter, week); the owner sees each learner's exact time in the panel.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.catalog.access import AccessMap
from apps.catalog.models import ContentNode

from .models import StudyTime, StudyTimeReport

MAX_CHUNK = 15 * 60  # one report never adds more than this to one entry (the app sends about once a minute)
MAX_DAY = 24 * 3600
OLDEST_DAYS = 30  # time counted offline may arrive late, but not older than this


@api_view(["POST"])
def add_time(request):
    entries = request.data.get("entries") or []
    if not isinstance(entries, list) or len(entries) > 200:
        return Response({"code": "invalid", "message": "داده نامعتبر است."}, status=status.HTTP_400_BAD_REQUEST)
    today = timezone.localdate()
    maps: dict[int, AccessMap] = {}
    nodes = {n.id: n for n in ContentNode.objects.filter(pk__in=[e.get("node_id") for e in entries if isinstance(e, dict)])}
    key = request.data.get("id")
    if key is not None and (not isinstance(key, str) or not 8 <= len(key) <= 40):
        return Response({"code": "invalid", "message": "داده نامعتبر است."}, status=status.HTTP_400_BAD_REQUEST)
    added = 0
    with transaction.atomic():
        # A report the app sends again (the answer was lost on the way) is added only once.
        if key and not StudyTimeReport.objects.get_or_create(user=request.user, key=key)[1]:
            return Response({"added": 0, "repeated": True})
        for e in entries:
            if not isinstance(e, dict):
                continue
            node = nodes.get(e.get("node_id"))
            kind = e.get("kind")
            try:
                seconds = int(e.get("seconds") or 0)
                day = date.fromisoformat(str(e.get("day"))) if e.get("day") else today
            except (TypeError, ValueError):
                continue
            if node is None or kind not in StudyTime.Kind.values or seconds <= 0 or day > today + timedelta(days=1) or day < today - timedelta(days=OLDEST_DAYS):
                continue
            if day > today:
                day = today
            book_path = node.path[: ContentNode.steplen]
            if book_path not in maps:
                maps[book_path] = AccessMap(request.user, node, light=True)
            access = maps[book_path]
            if not access.visible(node.id):
                continue
            seconds = min(seconds, MAX_CHUNK)
            row, _ = StudyTime.objects.select_for_update().get_or_create(user=request.user, node=node, day=day, kind=kind, defaults={"book": access.book})
            room = MAX_DAY - row.seconds
            if room > 0:
                StudyTime.objects.filter(pk=row.pk).update(seconds=F("seconds") + min(seconds, room))
                added += min(seconds, room)
    return Response({"added": added})


def totals(user, book=None) -> dict:
    """Exact seconds: all, per chapter (of a book), per kind, and the last 14 days."""
    rows = StudyTime.objects.filter(user=user)
    if book is not None:
        rows = rows.filter(book=book)
    total = rows.aggregate(s=Sum("seconds"))["s"] or 0
    by_kind = dict(rows.values_list("kind").annotate(s=Sum("seconds")).values_list("kind", "s"))
    since = timezone.localdate() - timedelta(days=13)
    by_day = dict(rows.filter(day__gte=since).values_list("day").annotate(s=Sum("seconds")).values_list("day", "s"))
    out = {
        "seconds": total,
        "by_kind": by_kind,
        "last_14_days": [{"date": since + timedelta(days=i), "seconds": by_day.get(since + timedelta(days=i), 0)} for i in range(14)],
        "week_seconds": sum(by_day.get(timezone.localdate() - timedelta(days=i), 0) for i in range(7)),
    }
    if book is not None:
        chapters = {}
        paths = {c.path: c.id for c in ContentNode.objects.filter(path__startswith=book.path, kind=ContentNode.Kind.CHAPTER)}
        for path, s in rows.values_list("node__path").annotate(s=Sum("seconds")).values_list("node__path", "s"):
            for cpath, cid in paths.items():
                if path.startswith(cpath):
                    chapters[str(cid)] = chapters.get(str(cid), 0) + s
                    break
        out["chapters"] = chapters
    return out
