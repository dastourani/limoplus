"""«نیاز به مرور»: sections worth a second look, at most three, shown on the home page.

Two reasons, in this order:
  - mistakes: the section has tests the learner got wrong and has not answered right since (the notebook's «open»);
  - old: the section was finished more than OLD_DAYS ago and not opened since, and its chapter is not in a chapter
    review cycle (those are already asked for in «کارهای امروز»).
Opening the section again (or answering its tests right) takes it off the list.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.utils import timezone

from apps.catalog.models import ContentNode
from apps.learning.models import Question

from .mistakes import OPEN, _map_for, notebook
from .models import ChapterReview, SectionProgress

OLD_DAYS = 30
LIMIT = 3


def needs_review(request, limit: int = LIMIT) -> dict:
    user = request.user
    items: list[dict] = []
    seen: set[int] = set()

    open_ids = [qid for qid, e in notebook(user).items() if e["state"] == OPEN]
    wrong = Counter(
        Question.objects.filter(id__in=open_ids, is_archived=False).values_list("node_id", flat=True)
    )
    nodes = ContentNode.objects.in_bulk(list(wrong))
    for node_id, count in wrong.most_common():
        node = nodes.get(node_id)
        if not node or not _map_for(request, node).readable(node_id):
            continue
        items.append(_item(request, node, "mistakes", mistakes=count))
        seen.add(node_id)

    cutoff = timezone.now() - timedelta(days=OLD_DAYS)
    in_cycle = set(ChapterReview.objects.filter(user=user, is_archived=False).values_list("chapter_id", flat=True))
    old = (
        SectionProgress.objects.filter(user=user, is_done=True, updated_at__lt=cutoff, node__kind=ContentNode.Kind.SECTION)
        .select_related("node")
        .order_by("updated_at")[:200]
    )
    today = timezone.now()
    for p in old:
        node = p.node
        if node.id in seen or not _map_for(request, node).readable(node.id):
            continue
        parent = node.get_parent()
        if parent and parent.id in in_cycle:
            continue
        items.append(_item(request, node, "old", days=(today - p.updated_at).days))
        seen.add(node.id)
    return {"items": items[:limit], "total": len(items)}


def _item(request, node, reason: str, mistakes: int = 0, days: int = 0) -> dict:
    book = _map_for(request, node).book
    return {
        "id": node.id,
        "title": node.title,
        "book_title": book.title,
        "book_slug": book.slug,
        "reason": reason,
        "mistakes": mistakes,
        "days": days,
    }
