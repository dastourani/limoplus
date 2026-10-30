"""
Who may see and read what. Everything goes through AccessMap so the rules live in one place:

- visible:  the node and every ancestor are published and not archived
- readable: visible, and (staff, or the node or an ancestor is free, or — later — the book is owned)

AccessMap loads a whole book in one query, so lists of questions or sections cost a constant number of queries.
"""

from .models import ContentNode


def book_of(node: ContentNode) -> ContentNode:
    if node.depth == 1:
        return node
    return ContentNode.objects.get(path=node.path[: ContentNode.steplen])


class AccessMap:
    def __init__(self, user, node: ContentNode):
        self.book = book_of(node)
        self.nodes = {n.id: n for n in ContentNode.objects.filter(path__startswith=self.book.path)}
        hidden = [n.path for n in self.nodes.values() if not n.is_published or n.is_archived]
        free = [n.path for n in self.nodes.values() if n.is_free]
        is_staff = bool(user and user.is_authenticated and user.is_staff)
        # TODO(payments): owned books / active subscriptions make the whole book readable.
        self._visible, self._readable = {}, {}
        for n in self.nodes.values():
            visible = not any(n.path.startswith(h) for h in hidden)
            self._visible[n.id] = visible
            self._readable[n.id] = visible and (is_staff or any(n.path.startswith(f) for f in free))

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
