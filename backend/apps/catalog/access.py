"""
Who may see and read what. Everything goes through AccessMap so the rules live in one place:

- visible:  the node and every ancestor are published and not archived
- readable: visible, and (staff, or the node or an ancestor is free, or the user owns the book, or has an active
            subscription to one of the book's majors or to all majors)

AccessMap loads a whole book in one query, so lists of questions or sections cost a constant number of queries.
"""

from .models import ContentNode


BOOK_EDITOR_GROUP = "استاد کتاب"


def is_book_teacher(user) -> bool:
    """A manager-approved, invited panel user; a staff flag or an editor row alone is never an approval."""
    return bool(
        user and user.is_authenticated and user.is_active and user.is_staff and not user.is_superuser
        and user.groups.filter(name=BOOK_EDITOR_GROUP).exists()
    )


def book_editor_ids(user, capability="can_edit_content"):
    """Book IDs assigned to this editor; by default, only books they may edit."""
    if capability and capability not in {
        "can_edit_content", "can_request_publication", "can_request_group_access",
        "can_view_reports", "can_view_aggregate_study", "can_view_aggregate_sales",
    }:
        return ContentNode.objects.none().values("pk")
    if user and user.is_authenticated and user.is_active and user.is_superuser:
        return ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1).values("pk")
    if not is_book_teacher(user) or not user.has_perm("catalog.change_contentnode"):
        return ContentNode.objects.none().values("pk")
    from .models import BookEditor

    rows = BookEditor.objects.filter(
        user_id=user.pk,
        book__kind=ContentNode.Kind.BOOK,
        book__depth=1,
        book__is_inbox=False,
    )
    if capability:
        rows = rows.filter(**{capability: True})
    return rows.values("book_id")


def books_for_editor(user, capability="can_edit_content"):
    """The books visible to a panel user, as a queryset (so filters never need every title in Python)."""
    return ContentNode.objects.filter(pk__in=book_editor_ids(user, capability=capability), kind=ContentNode.Kind.BOOK, depth=1)


def scope_to_editor_books(queryset, user, path_field="path", capability="can_edit_content"):
    """Restrict a related-object queryset to rows beneath this editor's assigned book roots.

    `path_field` can be `path`, `node__path`, `chapter__path`, or a previously annotated `item_path`.
    The root lookup stays in SQL and works for any number of assigned books.
    """
    if user and user.is_authenticated and user.is_active and user.is_superuser:
        return queryset
    if not is_book_teacher(user) or not user.has_perm("catalog.change_contentnode"):
        return queryset.none()
    from django.db.models import OuterRef, Subquery
    from django.db.models.functions import Substr

    roots = ContentNode.objects.filter(
        path=Substr(OuterRef(path_field), 1, ContentNode.steplen),
        kind=ContentNode.Kind.BOOK,
        depth=1,
        pk__in=book_editor_ids(user, capability=capability),
    ).order_by()
    return queryset.annotate(_lp_editor_book_id=Subquery(roots.values("pk")[:1])).filter(_lp_editor_book_id__isnull=False)


def acts_as_staff(user) -> bool:
    """Global staff access, except the deliberately book-scoped teacher role and learner-view sessions."""
    return bool(
        user and user.is_authenticated and user.is_active and user.is_staff
        and not is_book_teacher(user) and not getattr(user, "view_as_learner", False)
    )


def book_coverage_q(book: ContentNode):
    """Query filter matching any Entitlement that covers `book` (direct, major-scoped, or all-majors)."""
    from django.db.models import Q

    majors = list(book.majors.values_list("id", flat=True))
    q = Q(book=book) | Q(all_majors=True)
    if majors:
        q |= Q(major_id__in=majors, book__isnull=True)
    return q


def owns_book(user, book: ContentNode) -> bool:
    """Bought the book, or has an active subscription covering it."""
    if not (user and user.is_authenticated):
        return False
    from apps.commerce.models import Entitlement

    return Entitlement.active_for(user).filter(book_coverage_q(book)).exists()


def active_rows(user) -> list[tuple]:
    """The learner's active entitlements as (book_id, major_id, all_majors, bought): read once, used for many books."""
    if not (user and user.is_authenticated):
        return []
    from apps.commerce.models import Entitlement

    return [
        (b, m, a, o is not None or g is None)
        for b, m, a, o, g in Entitlement.active_for(user).values_list("book_id", "major_id", "all_majors", "order_id", "granted_by_id")
    ]


def _teacher_can_read_book(user, book_id) -> bool:
    """A book-teacher role is never global staff access; only an explicitly editable book is readable in the app."""
    if not is_book_teacher(user) or getattr(user, "view_as_learner", False):
        return False
    from .models import BookEditor

    return BookEditor.objects.filter(user_id=user.pk, book_id=book_id, can_edit_content=True).exists()


def access_kind_from(rows, user, book_id, major_ids) -> str | None:
    """access_kind from rows already read (see active_rows)."""
    if not (user and user.is_authenticated):
        return None
    if acts_as_staff(user):
        return "staff"
    if _teacher_can_read_book(user, book_id):
        return "editor"
    own = [r for r in rows if r[0] == book_id]
    if any(r[3] for r in own):
        return "purchase"
    if own:
        return "gift"
    if any(r[2] or (r[0] is None and r[1] in major_ids) for r in rows):
        return "subscription"
    return None


def access_kind(user, book: ContentNode) -> str | None:
    """Why the user can read the whole book: staff, an assigned editor, purchase, gift, subscription, or None."""
    if not (user and user.is_authenticated):
        return None
    if acts_as_staff(user):
        return "staff"
    return access_kind_from(active_rows(user), user, book.id, set(book.majors.values_list("id", flat=True)))


def access_until(user, book: ContentNode):
    """When the user's paid access to the book ends: None if it never does (bought, staff, editor) or there is none."""
    if not (user and user.is_authenticated) or acts_as_staff(user) or _teacher_can_read_book(user, book.id):
        return None
    from django.db.models import Max

    from apps.commerce.models import Entitlement

    coverage_q = book_coverage_q(book)
    covering = Entitlement.active_for(user).filter(coverage_q)
    if covering.filter(ends_at__isnull=True).exists():
        return None
    if not covering.exists():
        return None
    # Renewals already bought extend the access; so does a timed gift of this book.
    return Entitlement.objects.filter(user=user, is_archived=False).filter(coverage_q).aggregate(end=Max("ends_at"))["end"]


def book_of(node: ContentNode) -> ContentNode:
    if node.depth == 1:
        return node
    return ContentNode.objects.get(path=node.path[: ContentNode.steplen])


def can_edit_book(user, book: ContentNode) -> bool:
    """May this user WRITE this book's content?

    Superusers always can. Everyone else must be an approved member of «استاد کتاب», have the narrow
    content-editor permission, and have a «استاد کتاب» row for this exact book. A staff flag or a stray
    per-user permission cannot approve somebody or give them a book. Archived books are manager-only.
    """
    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    if book.is_archived or book.is_inbox or not is_book_teacher(user) or not user.has_perm("catalog.change_contentnode"):
        return False
    from .models import BookEditor

    return BookEditor.objects.filter(
        book=book, user=user, can_edit_content=True, book__kind=ContentNode.Kind.BOOK, book__depth=1
    ).exists()


def can_edit_chapter(user, chapter: ContentNode) -> bool:
    """Editors may work only on drafts; published or archived content remains under the manager's control."""
    if not can_edit_book(user, chapter.book()):
        return False
    if user.is_superuser:
        return True
    return not chapter.is_published and not chapter.is_archived


def can_publish_book(user, book: ContentNode) -> bool:
    """Only the active superuser (the manager) may change publication state.

    `BookEditor.can_publish` is retained as a manually maintained legacy/review flag, but it does not grant
    publication rights. Teachers can prepare drafts; the manager alone publishes or withdraws them.
    """
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def publish_state(user, book: ContentNode) -> dict:
    """What the panel needs to draw publishing honestly: the gate, and why it is closed.

    Returned as a dict because the JS renders from it, and every page that shows a publish control needs the same
    three facts — otherwise one of them drifts and shows a button the server will refuse.
    """
    allowed = can_publish_book(user, book)
    if allowed:
        reason = ""
    elif not (user and user.is_authenticated and user.is_staff):
        reason = "برای انتشار باید عضو پنل باشید."
    else:
        reason = "انتشار و بازکردن دسترسی دانشجویان فقط با مدیر کل است؛ استاد محتوا را پیش‌نویس و آماده می‌کند."
    return {"can_publish": allowed, "why": reason}


_UNSET = object()


class AccessMap:
    def __init__(self, user, node: ContentNode, light=False, kind=_UNSET):
        """light: without the lesson texts (a shelf needs only the tree). kind: the access already worked out."""
        self.book = book_of(node)
        nodes = ContentNode.objects.filter(path__startswith=self.book.path)
        if light:
            nodes = nodes.defer("full_body", "summary_body", "about", "cover_drawing")
        self.nodes = {n.id: n for n in nodes}
        self.access = access_kind(user, self.book) if kind is _UNSET else kind
        # A manager-granted book entitlement is private, person-specific access, not a public release. If the
        # book itself is still unpublished, let only this entitled reader see its tree; archived/inbox nodes
        # remain hidden, and an unpublished chapter in an already-published book is still withheld.
        private_unpublished_book = self.access == "gift" and not self.book.is_published
        if self.access is not None and not self.book.is_published and not private_unpublished_book and user.is_authenticated:
            from apps.commerce.models import Entitlement

            # Purchase access outranks a simultaneous gift in the card label; the private-grant check is still
            # independent so a group member with both entitlement kinds can open an unpublished group book.
            private_unpublished_book = Entitlement.active_for(user).filter(
                book=self.book, order__isnull=True, granted_by__isnull=False
            ).exists()
        hidden = [
            n.path for n in self.nodes.values()
            if (not n.is_published and not private_unpublished_book) or n.is_archived or n.is_inbox
        ]
        free = [n.path for n in self.nodes.values() if n.is_free]
        self.owned = self.access is not None
        self._visible, self._readable = {}, {}
        for n in self.nodes.values():
            visible = not any(n.path.startswith(h) for h in hidden)
            self._visible[n.id] = visible
            self._readable[n.id] = visible and (self.owned or any(n.path.startswith(f) for f in free))

    def visible(self, node_id) -> bool:
        return self._visible.get(node_id, False)

    def readable(self, node_id) -> bool:
        return self._readable.get(node_id, False)

    def usable_node(self, node_id, is_free: bool = False) -> bool:
        return self.visible(node_id) and (is_free or self.readable(node_id))

    def usable(self, item) -> bool:
        """True if the item's node is visible and the item is free or its node is readable."""
        return self.usable_node(item.node_id, getattr(item, "is_free", False))

    def visible_ids_under(self, node: ContentNode) -> list[int]:
        return [n.id for n in self.nodes.values() if n.path.startswith(node.path) and self._visible[n.id]]

    def children(self, node: ContentNode) -> list[ContentNode]:
        return sorted(
            (n for n in self.nodes.values() if n.depth == node.depth + 1 and n.path.startswith(node.path) and self._visible[n.id]),
            key=lambda n: n.path,
        )


def can_read(user, node: ContentNode) -> bool:
    return AccessMap(user, node).readable(node.id)
