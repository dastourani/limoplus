"""Where a section sits, for the line above «سؤال ۱ از ۴»: «فصل ۱، نام بخش»."""

from __future__ import annotations

from .models import ContentNode


def chapter_number(request, node) -> int | None:
    """The number of the node's chapter in its book: its «شماره‌ی فصل» (as in the breadcrumb and the chapter end), or its
    place among the published chapters. Kept for the request, so a list of questions costs one query per book."""
    if node is None or node.depth < 2:
        return None
    step = ContentNode.steplen
    book_path, chapter_path = node.path[:step], node.path[: 2 * step]
    cache = getattr(request, "_limo_chapter_numbers", None) if request is not None else None
    if cache is None:
        cache = {}
        if request is not None:
            request._limo_chapter_numbers = cache
    if book_path not in cache:
        paths = ContentNode.objects.filter(
            path__startswith=book_path, depth=2, kind=ContentNode.Kind.CHAPTER, is_published=True, is_archived=False
        ).order_by("path").values_list("path", "position")
        cache[book_path] = {p: position or i for i, (p, position) in enumerate(paths, start=1)}
    return cache[book_path].get(chapter_path)
