"""Recording what happened, without ever breaking the thing that happened.

Every call here is best-effort: a professor saving a chapter must not lose that save because the history row could
not be written. That is a deliberate trade — the text matters more than the log of it, and `ChapterRevision` keeps
the text itself. Failures are swallowed and (in debug) printed, nothing more.

See `models.Activity` for why the list is this short.
"""

from __future__ import annotations

import logging

from django.utils import timezone

log = logging.getLogger(__name__)


def record(kind, actor=None, book=None, node=None, title="", note=""):
    """Write one `Activity`. Returns the row, or None if it could not be written."""
    from .models import Activity

    try:
        return Activity.objects.create(
            at=timezone.now(),
            actor=actor if (actor and getattr(actor, "pk", None)) else None,
            kind=kind,
            book=book,
            node=node,
            title=(title or (node.title if node is not None else "") or (book.title if book is not None else ""))[:200],
            note=(note or "")[:300],
        )
    except Exception:  # noqa: BLE001 — see the module docstring: never let the log take the page down
        log.warning("could not record activity %s", kind, exc_info=True)
        return None


def visible(user, book=None, limit=None):
    """The history one person may see.

    A professor sees their own books; a superuser sees everything. Anyone else sees nothing — this is not a window
    into other people's books.
    """
    from .models import Activity, BookEditor

    rows = Activity.objects.select_related("actor", "book", "node")
    if not (user and user.is_authenticated and user.is_active):
        return rows.none()
    if not user.is_superuser:
        mine = list(BookEditor.objects.filter(user=user).values_list("book_id", flat=True))
        if not mine:
            return rows.none()
        rows = rows.filter(book_id__in=mine)
    if book is not None:
        rows = rows.filter(book=book)
    return rows[:limit] if limit else rows


def can_see(user, activity) -> bool:
    """One row. Same rule as `visible`, asked of a single object."""
    from .access import can_edit_book

    if activity.book_id is None:
        return bool(user and user.is_superuser)
    return bool(activity.book and can_edit_book(user, activity.book))
