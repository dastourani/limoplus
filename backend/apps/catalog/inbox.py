"""
«صندوق تست»: a hidden book with one chapter and one section where new tests wait. Tests are pasted there in bulk
(«ویرایش کل فایل») and then moved, one by one or many at once, to any section of any book (panel op
«question.relocate», below). The inbox is never visible in the app (AccessMap hides is_inbox) and cannot be published.

Moving keeps the question's id, so learners' answers, exam history, reports and stats go with it.
"""

from __future__ import annotations

from django.db import transaction

from apps.learning.models import Question

from . import editing
from .models import ContentNode

BOOK_SLUG = "test-inbox"


def inbox_chapter() -> ContentNode:
    """The inbox's chapter, made on first use."""
    book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_inbox=True).first()
    if book is None:
        slug = BOOK_SLUG
        while ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, slug=slug).exists():
            slug += "-x"
        book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug=slug, title="صندوق تست", is_published=False, is_inbox=True)
    chapter = book.get_children().filter(kind=ContentNode.Kind.CHAPTER).first()
    if chapter is None:
        chapter = book.add_child(kind=ContentNode.Kind.CHAPTER, slug=f"{book.slug}-ch", title="تست‌های تازه", is_published=False, is_inbox=True)
    if not chapter.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False).exists():
        chapter.add_child(kind=ContentNode.Kind.SECTION, slug=f"{book.slug}-s1", title="منتظر انتقال", is_published=False, is_inbox=True)
    return chapter


def is_inbox(node: ContentNode) -> bool:
    book = node.book()
    return bool(book and book.is_inbox)


def destinations() -> list[dict]:
    """Every place a test can go: books (the inbox first), their chapters (the chapter's intro) and sections."""
    out = []
    books = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_archived=False).order_by("-is_inbox", "title")
    for book in books:
        chapters = []
        for c in book.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False):
            sections = [{"id": s.pk, "title": s.title} for s in c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False)]
            chapters.append({"id": c.pk, "title": c.title, "number": c.position, "sections": sections})
        out.append({"id": book.pk, "title": book.title, "inbox": book.is_inbox, "chapters": chapters})
    return out


def relocate(source: ContentNode, slugs: list[str], target_id, user) -> dict:
    """Move tests of the chapter `source` to the section (or chapter intro) `target_id`, in any book.
    The ids stay the same. A test whose id («شناسه») is already used in the target book gets a new one there;
    links to flashcards that are not in the target chapter are dropped (the file allows links only inside a chapter)."""
    target = ContentNode.objects.filter(pk=target_id, is_archived=False, kind__in=[ContentNode.Kind.CHAPTER, ContentNode.Kind.SECTION]).first()
    if target is None:
        raise editing.EditError("مقصد پیدا نشد؛ صفحه را تازه کنید.")
    target_chapter = target if target.kind == ContentNode.Kind.CHAPTER else target.get_parent()
    target_book = target_chapter.book()
    slugs = [s for s in dict.fromkeys(slugs or []) if s]
    if not slugs:
        raise editing.EditError("هیچ تستی انتخاب نشده.")
    with transaction.atomic():
        questions = list(Question.objects.select_for_update().filter(node__path__startswith=source.path, slug__in=slugs, is_archived=False))
        if len(questions) != len(slugs):
            found = {q.slug for q in questions}
            raise editing.EditError(f"تست «{'، '.join(s for s in slugs if s not in found)}» در این فصل نیست؛ صفحه را تازه کنید.")
        order = {s: i for i, s in enumerate(slugs)}
        questions.sort(key=lambda q: order[q.slug])
        nxt = (Question.objects.filter(node=target).order_by("-order").values_list("order", flat=True).first() or 0) + 1
        renamed, unlinked, moved = [], 0, 0
        for q in questions:
            if q.node_id == target.pk:
                continue
            if not q.node.path.startswith(target_book.path):
                taken = set(Question.objects.filter(node__path__startswith=target_book.path).values_list("slug", flat=True))
                if q.slug in taken:
                    old, n = q.slug, 2
                    while f"{old}-{n}" in taken:
                        n += 1
                    q.slug = f"{old}-{n}"
                    renamed.append(f"{old} ← {q.slug}")
            outside = [f for f in q.flashcards.all() if not f.node.path.startswith(target_chapter.path)]
            if outside:
                q.flashcards.remove(*outside)
                unlinked += len(outside)
            q.node = target
            q.order = nxt
            nxt += 1
            q.save(update_fields=["node", "order", "slug"])
            moved += 1
        where = f"«{target.title}»" + (f" در «{target_book.title}»" if target_book.pk != source.book().pk else "")
        note = f"انتقال {moved} تست به {where}"
        # Both chapters go through the editor (all file rules) and keep a version.
        editing.save(target_chapter, editing.load(target_chapter), user=user, note=note)
        if source.pk != target_chapter.pk:
            editing.save(source, editing.load(source), user=user, note=note)
    warnings = []
    if renamed:
        warnings.append("شناسه‌ی این تست‌ها در کتاب مقصد تکراری بود و عوض شد: " + "، ".join(renamed))
    if unlinked:
        warnings.append(f"{unlinked} پیوند به فلش‌کارت‌هایی که در فصل مقصد نیستند برداشته شد.")
    return {"ok": True, "note": f"{moved} تست به {where} منتقل شد.", "warnings": warnings}
