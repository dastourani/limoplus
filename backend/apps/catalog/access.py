"""
Who may see and read what. Everything goes through AccessMap so the rules live in one place:

- visible:  the node and every ancestor are published and not archived
- readable: visible, and (staff, or the node or an ancestor is free, or the user owns the book, or has an active
            subscription to one of the book's majors or to all majors)

AccessMap loads a whole book in one query, so lists of questions or sections cost a constant number of queries.
"""

from .models import ContentNode


def acts_as_staff(user) -> bool:
    """Staff, unless they asked to see the app as a learner does."""
    return bool(user and user.is_authenticated and user.is_staff and not getattr(user, "view_as_learner", False))


def owns_book(user, book: ContentNode) -> bool:
    """Bought the book, or has an active subscription covering it."""
    if not (user and user.is_authenticated):
        return False
    from django.db.models import Q

    from apps.commerce.models import Entitlement

    majors = list(book.majors.values_list("id", flat=True))
    return Entitlement.active_for(user).filter(Q(book=book) | Q(all_majors=True) | Q(major_id__in=majors, book__isnull=True)).exists()


def active_rows(user) -> list[tuple]:
    """The learner's active entitlements as (book_id, major_id, all_majors, bought): read once, used for many books."""
    if not (user and user.is_authenticated):
        return []
    from apps.commerce.models import Entitlement

    return [
        (b, m, a, o is not None or g is None)
        for b, m, a, o, g in Entitlement.active_for(user).values_list("book_id", "major_id", "all_majors", "order_id", "granted_by_id")
    ]


def access_kind_from(rows, user, book_id, major_ids) -> str | None:
    """access_kind from rows already read (see active_rows)."""
    if not (user and user.is_authenticated):
        return None
    if acts_as_staff(user):
        return "staff"
    own = [r for r in rows if r[0] == book_id]
    if any(r[3] for r in own):
        return "purchase"
    if own:
        return "gift"
    if any(r[2] or (r[0] is None and r[1] in major_ids) for r in rows):
        return "subscription"
    return None


def access_kind(user, book: ContentNode) -> str | None:
    """Why the user can read the whole book: "staff", "purchase", "gift", "subscription", or None."""
    if not (user and user.is_authenticated):
        return None
    if acts_as_staff(user):
        return "staff"
    return access_kind_from(active_rows(user), user, book.id, set(book.majors.values_list("id", flat=True)))


def access_until(user, book: ContentNode):
    """When the user's paid access to the book ends: None if it never does (bought, staff) or there is none."""
    if not (user and user.is_authenticated) or acts_as_staff(user):
        return None
    from django.db.models import Max, Q

    from apps.commerce.models import Entitlement

    covering = Entitlement.active_for(user).filter(Q(book=book) | Q(all_majors=True) | Q(major__in=book.majors.all(), book__isnull=True))
    if covering.filter(ends_at__isnull=True).exists():
        return None
    if not covering.exists():
        return None
    # Renewals already bought extend the access; so does a timed gift of this book.
    return Entitlement.objects.filter(user=user, is_archived=False).filter(
        Q(book=book) | Q(all_majors=True) | Q(major__in=book.majors.all(), book__isnull=True)
    ).aggregate(end=Max("ends_at"))["end"]


def book_of(node: ContentNode) -> ContentNode:
    if node.depth == 1:
        return node
    return ContentNode.objects.get(path=node.path[: ContentNode.steplen])


def can_edit_book(user, book: ContentNode) -> bool:
    """May this user WRITE this book's content?

    Superusers, always. Otherwise a staff member must hold the catalog change permission AND a «استاد کتاب»
    row for this very book. Reading other books is allowed; writing them is not. (See BookEditor.)
    """
    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    if not (user.is_staff and user.has_perm("catalog.change_contentnode")):
        return False
    from .models import BookEditor

    return BookEditor.objects.filter(book=book, user=user).exists()


def can_publish_book(user, book: ContentNode) -> bool:
    """Superusers, or an editor trusted with publishing. Drafting is open to every editor of the book."""
    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    from .models import BookEditor

    return BookEditor.objects.filter(book=book, user=user, can_publish=True).exists()


_UNSET = object()


class AccessMap:
    def __init__(self, user, node: ContentNode, light=False, kind=_UNSET):
        """light: without the lesson texts (a shelf needs only the tree). kind: the access already worked out."""
        self.book = book_of(node)
        nodes = ContentNode.objects.filter(path__startswith=self.book.path)
        if light:
            nodes = nodes.defer("full_body", "summary_body", "about", "cover_drawing")
        self.nodes = {n.id: n for n in nodes}
        hidden = [n.path for n in self.nodes.values() if not n.is_published or n.is_archived or n.is_inbox]
        free = [n.path for n in self.nodes.values() if n.is_free]
        self.access = access_kind(user, self.book) if kind is _UNSET else kind
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

    def visible_ids_under(self, node: ContentNode) -> list[int]:
        return [n.id for n in self.nodes.values() if n.path.startswith(node.path) and self._visible[n.id]]

    def children(self, node: ContentNode) -> list[ContentNode]:
        return sorted(
            (n for n in self.nodes.values() if n.depth == node.depth + 1 and n.path.startswith(node.path) and self._visible[n.id]),
            key=lambda n: n.path,
        )


def can_read(user, node: ContentNode) -> bool:
    return AccessMap(user, node).readable(node.id)
