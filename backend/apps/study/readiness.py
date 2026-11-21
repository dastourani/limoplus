"""
How ready a learner is for a past konkur of a book, and an exam's results by chapter.

- A chapter counts as studied when it is finished (all sections read and 70% of its tests answered, the rule of
  reviews.is_finished) or its review cycle has started (the learner pressed «این فصل را تمام کردم»).
- «آمادگی» of a past exam: the share of its tests (in this book) that come from studied chapters.
- Before a konkur exam the app offers «فقط فصل‌های خوانده‌شده» when some of its tests are from chapters not studied yet.
"""

from __future__ import annotations

from apps.catalog.models import ContentNode


def chapter_of(access, node_id):
    """The chapter (depth 2) a node belongs to, from the access map's nodes."""
    node = access.nodes.get(node_id)
    if not node:
        return None
    if node.depth <= 2:
        return node if node.depth == 2 else None
    prefix = node.path[: ContentNode.steplen * 2]
    return next((n for n in access.nodes.values() if n.depth == 2 and n.path == prefix), None)


def studied_chapters(user, access) -> set[int]:
    if not user.is_authenticated:
        return set()
    from .models import ChapterReview
    from .reviews import is_finished

    started = set(ChapterReview.objects.filter(user=user, book=access.book, is_archived=False).values_list("chapter_id", flat=True))
    out = set(started)
    for chapter in access.children(access.book):
        if chapter.id not in out and access.readable(chapter.id) and is_finished(user, access, chapter):
            out.add(chapter.id)
    return out


def by_chapter(access, questions, studied=None) -> dict[int | None, list]:
    """{chapter id: [questions]} (None: a question whose place is not visible)."""
    out: dict[int | None, list] = {}
    for q in questions:
        c = chapter_of(access, q.node_id)
        out.setdefault(c.id if c else None, []).append(q)
    return out


def chapter_label(c) -> str:
    return f"فصل {fa(c.position)}، {c.title}" if c.position else c.title


def fa(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
