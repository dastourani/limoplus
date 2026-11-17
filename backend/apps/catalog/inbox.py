"""
«صندوق تست»: a hidden book with one chapter and one section where new tests wait. Tests are pasted there in bulk
(«ویرایش کل فایل») and then moved, one by one or many at once, to any section of any book (panel op
«question.relocate», below). The inbox is never visible in the app (AccessMap hides is_inbox) and cannot be published.

Moving keeps the question's id, so learners' answers, exam history, reports and stats go with it.
"""

from __future__ import annotations

from django.db import transaction

from apps.learning.models import Flashcard, Question

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


def destinations(user=None) -> list[dict]:
    """Every place a test can go: books (the inbox first), their chapters (the chapter's intro) and sections.

    With `user`, only books that user may write are listed: «انتقال» is a write into the destination book."""
    from . import access

    out = []
    books = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_archived=False).order_by("-is_inbox", "title")
    if user is not None:
        books = [b for b in books if access.can_edit_book(user, b)]
    for book in books:
        chapters = []
        for c in book.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False):
            sections = [{"id": s.pk, "title": s.title} for s in c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False)]
            chapters.append({"id": c.pk, "title": c.title, "number": c.position, "sections": sections})
        out.append({"id": book.pk, "title": book.title, "inbox": book.is_inbox, "chapters": chapters})
    return out


def _free_slug(slug: str, taken: set[str]) -> str:
    if slug not in taken:
        return slug
    n = 2
    while f"{slug}-{n}" in taken:
        n += 1
    return f"{slug}-{n}"


def relocate(source: ContentNode, slugs: list[str], target_id, user, kind: str = "question") -> dict:
    """Move tests or flashcards of the chapter `source` to the section (or chapter intro) `target_id`, in any book.
    The ids stay the same, so answers, stats and Leitner boxes go along. An item id («شناسه») already used in the
    target book gets «-2». Links between tests and flashcards stay inside a book: crossing to another book drops
    the links that would point outside it."""
    model = Question if kind == "question" else Flashcard
    word = "تست" if kind == "question" else "فلش‌کارت"
    target = ContentNode.objects.filter(pk=target_id, is_archived=False, kind__in=[ContentNode.Kind.CHAPTER, ContentNode.Kind.SECTION]).first()
    if target is None:
        raise editing.EditError("مقصد پیدا نشد؛ صفحه را تازه کنید.")
    target_chapter = target if target.kind == ContentNode.Kind.CHAPTER else target.get_parent()
    target_book = target_chapter.book()
    slugs = [s for s in dict.fromkeys(slugs or []) if s]
    if not slugs:
        raise editing.EditError(f"هیچ {word}ی انتخاب نشده.")
    with transaction.atomic():
        items = list(model.objects.select_for_update().filter(node__path__startswith=source.path, slug__in=slugs, is_archived=False))
        if len(items) != len(slugs):
            found = {q.slug for q in items}
            raise editing.EditError(f"{word} «{'، '.join(s for s in slugs if s not in found)}» در این فصل نیست؛ صفحه را تازه کنید.")
        order = {s: i for i, s in enumerate(slugs)}
        items.sort(key=lambda q: order[q.slug])
        nxt = (model.objects.filter(node=target).order_by("-order").values_list("order", flat=True).first() or 0) + 1
        renamed, unlinked, moved = [], 0, 0
        for item in items:
            if item.node_id == target.pk:
                continue
            if not item.node.path.startswith(target_book.path):
                taken = set(model.objects.filter(node__path__startswith=target_book.path).values_list("slug", flat=True))
                new = _free_slug(item.slug, taken)
                if new != item.slug:
                    renamed.append(f"{item.slug} ← {new}")
                    item.slug = new
                # Links may not cross books.
                if kind == "question":
                    outside = [f for f in item.flashcards.all() if not f.node.path.startswith(target_book.path)]
                    item.flashcards.remove(*outside)
                else:
                    outside = [q for q in item.questions.all() if not q.node.path.startswith(target_book.path)]
                    item.questions.remove(*outside)
                unlinked += len(outside)
            fields = ["node", "order", "slug"]
            if source.is_inbox or source.book().is_inbox:
                # Out of the hidden «صندوق»: learners see it from now («تازه»).
                from django.utils import timezone

                item.added_at = timezone.now()
                fields.append("added_at")
            item.node = target
            item.order = nxt
            nxt += 1
            item.save(update_fields=fields)
            moved += 1
        where = f"«{target.title}»" + (f" در «{target_book.title}»" if target_book.pk != source.book().pk else "")
        note = f"انتقال {moved} {word} به {where}"
        # Both chapters go through the editor (all file rules) and keep a version.
        editing.save(target_chapter, editing.load(target_chapter), user=user, note=note)
        if source.pk != target_chapter.pk:
            editing.save(source, editing.load(source), user=user, note=note)
    warnings = []
    if renamed:
        warnings.append(f"شناسه‌ی این {word}‌ها در کتاب مقصد تکراری بود و عوض شد: " + "، ".join(renamed))
    if unlinked:
        warnings.append(f"{unlinked} پیوند تست و فلش‌کارت برداشته شد، چون پیوند بین دو کتاب مجاز نیست.")
    return {"ok": True, "note": f"{moved} {word} به {where} منتقل شد.", "warnings": warnings}


def _texts(node: ContentNode) -> str:
    """Everything of a section that may hold a [[#name]] link: notes, summary and its tests' explanations."""
    parts = [node.full_body or "", node.summary_body or ""]
    for q in Question.objects.filter(node=node, is_archived=False).only("explanation", "solutions", "stem"):
        parts += [q.stem, q.explanation, *[x.get("body", "") for x in q.solutions or []]]
    return "\n".join(p for p in parts if p)


def relocate_section(source: ContentNode, slug: str, target_id, user, dry: bool = False) -> dict:
    """Move a whole section (notes, summary, tests, flashcards; learners' progress, notes and answers stay with it,
    as they attach to its id) to the end of another chapter, in any book. `dry`: only say what would break."""
    from .numbering import BOX, REF

    section = source.get_children().filter(kind=ContentNode.Kind.SECTION, slug=slug, is_archived=False).first()
    target = ContentNode.objects.filter(pk=target_id, kind=ContentNode.Kind.CHAPTER, is_archived=False).first()
    if section is None or target is None:
        raise editing.EditError("بخش یا فصل مقصد پیدا نشد؛ صفحه را تازه کنید.")
    if target.pk == source.pk:
        raise editing.EditError("این بخش همین حالا در همین فصل است.")
    if source.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False).count() == 1:
        raise editing.EditError("این تنها بخش فصل است؛ فصل باید دست‌کم یک بخش داشته باشد. اول بخش دیگری بسازید.")
    source_book, target_book = source.book(), target.book()
    cross = source_book.pk != target_book.pk

    # Box names are unique in a chapter.
    names = {m.group(2) for m in BOX.finditer(section.full_body or "") if m.group(2)}
    there = set()
    for node in [target, *target.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False)]:
        there |= {m.group(2) for m in BOX.finditer(node.full_body or "") if m.group(2)}
    clash = sorted(names & there)
    if clash:
        raise editing.EditError(f"نام کادر «{'، '.join(clash)}» در فصل مقصد هم هست؛ اول یکی را عوض کنید.")

    warnings = []
    if cross:
        # [[#name]] links that will point to another book.
        others = [n for n in ContentNode.objects.filter(path__startswith=source_book.path, kind__in=[ContentNode.Kind.CHAPTER, ContentNode.Kind.SECTION], is_archived=False).exclude(pk=section.pk)]
        broken_in = [n.title for n in others if names & set(REF.findall(_texts(n)))]
        here = set(REF.findall(_texts(section)))
        elsewhere = set()
        for n in others:
            elsewhere |= {m.group(2) for m in BOX.finditer(n.full_body or "") if m.group(2)}
        broken_out = sorted(here & elsewhere - names)
        if broken_in:
            warnings.append("ارجاع به کادرهای این بخش در این بخش‌ها می‌شکند: " + "، ".join(broken_in))
        if broken_out:
            warnings.append("ارجاع‌های این بخش به کادرهای کتاب فعلی می‌شکند: " + "، ".join(broken_out))
        q_ids = list(Question.objects.filter(node=section).values_list("pk", flat=True))
        f_ids = list(Flashcard.objects.filter(node=section).values_list("pk", flat=True))
        links_out = Question.flashcards.through.objects.filter(question_id__in=q_ids).exclude(flashcard_id__in=f_ids).count()
        links_in = Question.flashcards.through.objects.filter(flashcard_id__in=f_ids).exclude(question_id__in=q_ids).count()
        if links_out + links_in:
            warnings.append(f"{links_out + links_in} پیوند تست و فلش‌کارت با بقیه‌ی کتاب برداشته می‌شود.")
    if dry:
        return {"ok": True, "warnings": warnings, "cross": cross}

    with transaction.atomic():
        section = ContentNode.objects.select_for_update().get(pk=section.pk)
        renamed = []
        if cross:
            taken = set(ContentNode.objects.filter(path__startswith=target_book.path, kind=ContentNode.Kind.SECTION).values_list("slug", flat=True))
            new = _free_slug(section.slug, taken)
            if new != section.slug:
                renamed.append(f"{section.slug} ← {new}")
                ContentNode.objects.filter(pk=section.pk).update(slug=new)
            for model in (Question, Flashcard):
                taken = set(model.objects.filter(node__path__startswith=target_book.path).values_list("slug", flat=True))
                for item in model.objects.filter(node=section):
                    new = _free_slug(item.slug, taken)
                    if new != item.slug:
                        renamed.append(f"{item.slug} ← {new}")
                        item.slug = new
                        item.save(update_fields=["slug"])
                    taken.add(new)
            q_ids = list(Question.objects.filter(node=section).values_list("pk", flat=True))
            f_ids = list(Flashcard.objects.filter(node=section).values_list("pk", flat=True))
            through = Question.flashcards.through.objects
            through.filter(question_id__in=q_ids).exclude(flashcard_id__in=f_ids).delete()
            through.filter(flashcard_id__in=f_ids).exclude(question_id__in=q_ids).delete()
        ContentNode.objects.get(pk=section.pk).move(ContentNode.objects.get(pk=target.pk), "last-child")
        ContentNode.objects.filter(pk=section.pk).update(is_published=target.is_published)
        note = f"انتقال بخش «{section.title}» به «{target.title}»" + (f" در «{target_book.title}»" if cross else "")
        editing.save(ContentNode.objects.get(pk=target.pk), editing.load(ContentNode.objects.get(pk=target.pk)), user=user, note=note)
        editing.save(ContentNode.objects.get(pk=source.pk), editing.load(ContentNode.objects.get(pk=source.pk)), user=user, note=note)
    if renamed:
        warnings.append("این شناسه‌ها در کتاب مقصد تکراری بودند و عوض شدند: " + "، ".join(renamed))
    return {"ok": True, "note": note + " انجام شد.", "warnings": warnings}
