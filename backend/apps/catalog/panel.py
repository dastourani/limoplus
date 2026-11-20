"""
The panel's content pages: «کتاب‌ها» (book page with its chapters), «مدیریت فصل», whole-file editing, versions,
and importing a file with a preview. Wired into the admin by BookAdmin.get_urls (staff only, CSRF-protected).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.learning.models import ExamSource, Flashcard, Question, Report

from . import editing
from . import access
from .editing import EditError
from .exporter import book_bundle, chapter_bundle, export_chapter, flashcard_block, question_block, write_chapter
from .latex_export import chapter_tex_bundle
from .importer import outside_flashcards
from .importer import IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, _SVG_DANGER, apply_chapter, parse_chapter, read_upload, check_against_db
from .jalali import fa_digits, jalali_datetime
from .models import ChapterRevision, ContentNode
from .fresh import formula_macros
from .labels import all_labels
from .summary import parse_parts

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
# What «فصل از فایل» accepts, longest suffix first so «.pptx» is not matched as «.zip»-like by accident.
UPLOAD_EXTENSIONS = (".zip", ".pptx", ".tex", ".md")
PENDING_DIR = "imports/pending"


def _book(pk) -> ContentNode:
    return get_object_or_404(ContentNode, pk=pk, kind=ContentNode.Kind.BOOK, depth=1)


def _chapter(pk) -> ContentNode:
    chapter = get_object_or_404(ContentNode, pk=pk, kind=ContentNode.Kind.CHAPTER)
    if chapter.book() is None:
        raise Http404("این فصل داخل هیچ کتابی نیست.")
    return chapter


def orphans():
    """Content made by hand in the old panel outside any book (e.g. a chapter at the top level)."""
    return ContentNode.objects.filter(depth=1).exclude(kind=ContentNode.Kind.BOOK)


@require_POST
def archive_orphan(request, node_id):
    _can_edit(request)
    _require_superuser(request)
    node = get_object_or_404(orphans(), pk=node_id)
    ids = [node.pk, *node.get_descendants().values_list("pk", flat=True)]
    with transaction.atomic():
        ContentNode.objects.filter(pk__in=ids).update(is_archived=True, is_published=False)
        Question.objects.filter(node_id__in=ids).update(is_archived=True)
        Flashcard.objects.filter(node_id__in=ids).update(is_archived=True)
    messages.success(request, f"«{node.title}» بایگانی شد (پاک نشد).")
    return redirect(reverse("admin:catalog_book_changelist"))


def _can_edit(request, book=None):
    """Who may open the writing panel.

    A staff member with the catalog change permission, and — when a book is in play — only that book's own
    editors («استاد کتاب»), plus superusers. Reading another book is fine; writing it is refused.
    """
    if not (request.user.is_active and request.user.is_staff and request.user.has_perm("catalog.change_contentnode")):
        raise PermissionDenied
    if book is not None and not access.can_edit_book(request.user, book):
        raise PermissionDenied


def _can_edit_draft(request, chapter):
    """Only the manager may alter a published or archived chapter; teachers work on drafts for review."""
    _can_edit(request, chapter.book())
    if not access.can_edit_chapter(request.user, chapter):
        raise PermissionDenied("استاد فقط پیش‌نویس آماده می‌کند؛ محتوای منتشرشده را فقط مدیر کل تغییر می‌دهد.")


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied("این کار از این صفحه فقط برای مدیر کل است.")


def book_publish(admin_site, request, book_id):
    """Release a book to learners, or take it back — the only door to `Book.is_published`.

    Publishing a book without publishing its chapters shows an empty shelf, so this publishes the whole tree in the
    same breath. Taking it back hides the book and leaves the content alone: the reason to unpublish is almost never
    «delete what I wrote».
    """
    # Not @require_POST: this view takes `admin_site` first (BookAdmin.get_urls calls it through admin_view), so a
    # decorator that reads `request` from position 0 would be handed the site.
    if request.method != "POST":
        raise Http404
    book = _book(book_id)
    _can_edit(request, book)
    try:
        _may_publish(request.user, book)
    except EditError as e:
        # A sentence on the page, not a traceback: this is a normal thing to try, and 500 is not an answer.
        messages.error(request, "؛ ".join(e.messages))
        return redirect(reverse("admin:catalog_book_change", args=[book.pk]))
    value = request.POST.get("value") == "1"
    with transaction.atomic():
        ContentNode.objects.filter(path__startswith=book.path).update(is_published=value)
    messages.success(
        request,
        f"کتاب «{book.title}» {'منتشر شد و در اپ دیده می‌شود' if value else 'از انتشار خارج شد و در اپ دیده نمی‌شود'}."
    )
    return redirect(reverse("admin:catalog_book_change", args=[book.pk]))


def _book_by_slug(slug):
    """The book a file names, without creating it. Used only to ask «may this person publish it?»."""
    if not slug:
        return None
    return ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, slug=slug).first()


def _may_publish(user, book):
    """The publishing gate. Raises with a sentence the professor can act on, not a bare 403."""
    # A book that does not exist yet has no «استاد کتاب» rows, so it falls to superusers; importing a brand-new
    # book with «انتشار فوری» as a professor is exactly the case this must refuse.
    if not access.can_publish_book(user, book):
        raise EditError(
            "شما اجازه‌ی انتشار این کتاب را ندارید. نوشتن و آماده‌کردن آزاد است؛ انتشار را مدیر کل انجام می‌دهد."
        )


def _can_edit_destination(node_id, user):
    """«انتقال» moves content into another book, so the destination needs its own permission check."""
    node = ContentNode.objects.filter(pk=node_id).first()
    if node is None:
        return  # relocate() reports «مقصد پیدا نشد» with a readable message.
    target_chapter = node if node.kind == ContentNode.Kind.CHAPTER else node.get_parent()
    if target_chapter is None or not access.can_edit_chapter(user, target_chapter):
        raise PermissionDenied("مقصد باید پیش‌نویسی از کتاب‌های مجاز شما باشد.")


def _context(admin_site, request, title, **extra):
    return {**admin_site.each_context(request), "title": title, **extra}


# --- Chapter state for the manager page --------------------------------------------------------------------


def _question_json(q, obj, reports):
    return {
        "slug": q.slug,
        "id": obj.pk if obj else None,
        "stem": q.stem,
        "choices": [{"text": t, "correct": ok} for t, ok in q.choices],
        "explanation": q.explanation,
        "solutions": [{"title": t, "body": b} for t, b in q.solutions],
        "difficulty": q.difficulty,
        "domain": q.domain,
        "kind": q.kind,
        "seconds": q.seconds,
        "is_free": q.is_free,
        "fixed_order": q.fixed_order,
        "is_extra": q.is_extra,
        "is_original": q.is_original,
        "sources": [{"name": n, "year": y, "number": num} for n, y, num in q.sources],
        "flashcards": q.flashcard_slugs,
        "similar": q.similar_slugs,
        "raw": "\n".join(question_block(q)),
        "answers": obj.answer_count if obj else 0,
        "is_sample": bool(obj and obj.is_sample),
        "correct_rate": round(100 * obj.correct_count / obj.answer_count) if obj and obj.answer_count else None,
        "reports": reports.get(obj.pk, 0) if obj else 0,
    }


def _flashcard_json(f, obj):
    return {"slug": f.slug, "id": obj.pk if obj else None, "title": f.title, "point": f.point, "formula": f.formula,
            "is_free": f.is_free, "raw": "\n".join(flashcard_block(f))}


def chapter_state(chapter: ContentNode, user=None) -> dict:
    """Everything the chapter page draws. `user` decides the publishing gate, so callers must pass request.user."""
    chapter = ContentNode.objects.get(pk=chapter.pk)
    book = chapter.book()
    parsed = editing.load(chapter)
    version = editing.version_of(write_chapter(parsed))
    ids = [chapter.pk, *chapter.get_descendants().values_list("pk", flat=True)]
    questions = {q.slug: q for q in Question.objects.filter(node_id__in=ids)}
    flashcards = {f.slug: f for f in Flashcard.objects.filter(node_id__in=ids)}
    reports = {}
    for row in Report.objects.filter(question_id__in=[q.pk for q in questions.values()], status=Report.Status.OPEN).values_list("question_id", flat=True):
        reports[row] = reports.get(row, 0) + 1
    nodes = {n.slug: n for n in chapter.get_children().filter(kind=ContentNode.Kind.SECTION)}
    from .numbering import count, panel_refs

    # Where each section's «مثال ۳-۵» count starts, in the order of the file (intro first).
    starts, _ = count(chapter.position, [(x.slug, x.full_body) for x in [editing.section(parsed, ""), *parsed.sections]])

    def section_json(s, node):
        return {
            "slug": s.slug,
            "numbering_start": starts.get(s.slug, {}),
            "id": node.pk if node else chapter.pk,
            "title": s.title,
            "group": s.group,
            "full_body": s.full_body,
            "summary_body": s.summary_body,
            "is_review_card": bool(s.summary_body) and bool(parse_parts(s.summary_body)),
            "is_published": node.is_published if node else chapter.is_published,
            # The section's own «رایگان» flag: a free section of a paid book is open to every reader.
            "is_free": node.is_free if node else chapter.is_free,
            "missing_phrases": editing_missing(s),
            "questions": [_question_json(q, questions.get(q.slug), reports) for q in s.questions],
            "flashcards": [_flashcard_json(f, flashcards.get(f.slug)) for f in s.flashcards],
        }

    intro = editing.section(parsed, "")
    archived_q = Question.objects.filter(node_id__in=ids, is_archived=True).select_related("node").order_by("node__path", "order")
    archived_f = Flashcard.objects.filter(node_id__in=ids, is_archived=True).select_related("node").order_by("node__path", "order")
    may_publish = access.can_publish_book(user, book)
    return {
        "version": version,
        "can_edit": access.can_edit_chapter(user, chapter),
        "can_manage_access": bool(user and user.is_authenticated and user.is_superuser),
        # The panel draws the «منتشر» checkboxes from this. A checkbox that the server will refuse is worse than no
        # checkbox: the professor ticks it, the page reloads, nothing changed, and nobody says why.
        "can_publish": may_publish,
        "publish_why": "" if may_publish else access.publish_state(user, book)["why"],
        "book": {"id": book.pk, "slug": book.slug, "title": book.title, "is_published": book.is_published},
        "chapter": {"id": chapter.pk, "slug": chapter.slug, "title": chapter.title, "number": chapter.position,
                    "is_free": chapter.is_free, "is_published": chapter.is_published},
        # Chapter numbers are not unique, but the book is ordered by them. The manager checks this list before its
        # quick-edit «chapter.update» prompt; the whole-file editor gets the same warning from file.check.
        "sibling_chapters": list(ContentNode.objects.filter(path__startswith=book.path, depth=book.depth + 1,
                                                              kind=ContentNode.Kind.CHAPTER)
                                  .exclude(pk=chapter.pk).order_by("position", "path")
                                  .values("id", "title", "position")),
        "intro": section_json(intro, None),
        "sections": [section_json(s, nodes.get(s.slug)) for s in parsed.sections],
        "groups": sorted({s.group for s in parsed.sections if s.group}),
        "archived": {
            "sections": [{"slug": n.slug, "title": n.title} for n in nodes.values() if n.is_archived],
            "questions": [{"slug": q.slug, "text": q.stem[:90], "section": q.node.title} for q in archived_q],
            "flashcards": [{"slug": f.slug, "text": f.title, "section": f.node.title} for f in archived_f],
        },
        "suggest": {k: editing.suggest_slug(book, parsed, k) for k in ("section", "question", "flashcard")},
        "media_url": settings.MEDIA_URL if settings.MEDIA_URL.startswith("/") else "/" + settings.MEDIA_URL,
        "revisions": chapter.revisions.count(),
        "labels": all_labels(user=user),
        "macros": formula_macros(),
        "inbox": chapter.is_inbox,
        "refs": panel_refs(book),
        # Konkur names already in use, offered in the test form (the same name must be written the same way).
        "source_names": sorted(set(ExamSource.objects.values_list("name", flat=True)))[:1000],
        # Flashcards of the book's other chapters, for linking tests to them.
        "book_cards": _book_cards(book, chapter),
    }


def _book_cards(book, chapter) -> list[dict]:
    step = ContentNode.steplen
    chapters = dict(ContentNode.objects.filter(path__startswith=book.path, depth=2).values_list("path", "title"))
    cards = Flashcard.objects.filter(node__path__startswith=book.path, is_archived=False).exclude(node__path__startswith=chapter.path)
    return [{"slug": slug, "title": title, "chapter": chapters.get(path[: 2 * step], "")}
            for slug, title, path in cards.values_list("slug", "title", "node__path")[:2000]]


def editing_missing(s):
    from .importer import missing_jump_phrases

    return missing_jump_phrases(s.full_body, s.summary_body)


# --- Operations ----------------------------------------------------------------------------------------------


def _set_bodies(target, data, label):
    errors = []
    if "full_body" in data:
        errors += editing.check_body(data["full_body"], f"جزوه‌ی {label}")
    if "summary_body" in data:
        errors += editing.check_body(data["summary_body"], f"خلاصه‌ی {label}")
        errors += [f"خلاصه‌ی {label}: کادر «:::» داخل خلاصه مجاز نیست." for line in data["summary_body"].split("\n") if line.strip().startswith(":::")][:1]
    if errors:
        raise EditError(errors)
    if "full_body" in data:
        target.full_lines = data["full_body"].replace("\r\n", "\n").strip().split("\n") if data["full_body"].strip() else []
    if "summary_body" in data:
        target.summary_lines = data["summary_body"].replace("\r\n", "\n").strip().split("\n") if data["summary_body"].strip() else []


def _title(value, label):
    value = " ".join((value or "").split())
    if not value:
        raise EditError(f"{label} خالی است.")
    return value


def set_chapter_published(chapter: ContentNode, value: bool) -> int:
    """Publish or hide a chapter. Publishing also publishes its draft sections (a published chapter with draft
    sections shows in the app as a title with nothing inside). Hiding leaves the sections as they are: the hidden
    chapter hides them anyway, and publishing again brings them back. Returns how many drafts were published."""
    ContentNode.objects.filter(pk=chapter.pk).update(is_published=value)
    if not value:
        return 0
    return ContentNode.objects.filter(path__startswith=chapter.path, depth__gt=chapter.depth, is_published=False, is_archived=False).update(is_published=True)


def apply_op(chapter: ContentNode, data: dict, user) -> dict:
    """Run one panel operation. Returns {"ok": True, "note": …, "warnings": […]} or raises EditError."""
    if not access.can_edit_chapter(user, chapter):
        raise PermissionDenied("استاد فقط پیش‌نویس آماده می‌کند؛ محتوای منتشرشده را فقط مدیر کل تغییر می‌دهد.")
    op = data.get("op", "")
    book = chapter.book()
    note = ""

    if op in ("question.relocate", "flashcard.relocate"):
        from .inbox import relocate

        _can_edit_destination(data.get("to"), user)
        return relocate(chapter, data.get("slugs") or [], data.get("to"), user, kind=op.split(".")[0])
    if op == "section.relocate":
        from .inbox import relocate_section

        _can_edit_destination(data.get("to"), user)
        return relocate_section(chapter, data.get("slug", ""), data.get("to"), user, dry=bool(data.get("dry")))
    if op == "destinations":
        from .inbox import destinations

        return {"ok": True, "destinations": destinations(user)}

    # Visibility lives only in the panel (not in the file). The «صندوق تست» is never published.
    if op in ("chapter.publish", "section.publish") and data.get("value") and chapter.is_inbox:
        raise EditError("صندوق تست منتشر نمی‌شود؛ تست‌ها را به بخش‌هایشان منتقل کنید.")
    if op in ("chapter.publish", "section.publish"):
        _may_publish(user, book)   # both publishing and withdrawal change what learners can access
    if op == "chapter.publish":
        drafts = set_chapter_published(chapter, bool(data.get("value")))
        return {"ok": True, "note": f"{drafts} بخش پیش‌نویس هم منتشر شد." if drafts else ""}
    if op == "section.publish":
        n = chapter.get_children().filter(slug=data.get("slug"), kind=ContentNode.Kind.SECTION).update(is_published=bool(data.get("value")))
        if not n:
            raise EditError("بخش پیدا نشد.")
        return {"ok": True}
    if op == "section.free":
        # A free section opens that part of a paid book to every reader. The manager decides; a teacher may set it
        # in a chapter draft they are preparing (a published chapter stays the manager's alone — `can_edit_chapter`
        # above already refuses a teacher there). The flag lives in the panel, not in the file: the chapter file has
        # no marker for it, and re-reading the file never clears it.
        node = ContentNode.objects.get_children(chapter).filter(slug=data.get("slug") or "", kind=ContentNode.Kind.SECTION).first()
        if node is None:
            raise EditError("بخش پیدا نشد.")
        value = bool(data.get("value"))
        node.is_free = value
        node.save(update_fields=["is_free"])
        return {"ok": True, "note": f"بخش «{node.title}» {'رایگان' if value else 'پولی'} شد."}

    if op == "question.sample":
        # Sharing a sample with learners is a distribution decision, not part of a teacher's draft access.
        if not user.is_superuser:
            raise PermissionDenied("دسترسی دانشجویان و نمونه‌گذاری را فقط مدیر کل انجام می‌دهد.")
        from apps.learning.models import Question

        n = Question.objects.filter(node__path__startswith=book.path, slug=data.get("slug"), is_archived=False).update(is_sample=bool(data.get("value")))
        if not n:
            raise EditError("تست پیدا نشد.")
        return {"ok": True}

    if op in ("question.convert", "flashcard.convert"):
        # Form ⇄ raw text, without saving (the panel's «متن خام» switch).
        kind = op.split(".")[0]
        slug = (data.get("slug") or "").strip() or "new"
        if kind == "question":
            item = editing.question_from_form(data.get("data") or {}, slug)
            return {"ok": True, "item": _question_json(item, None, {})}
        item = editing.flashcard_from_form(data.get("data") or {}, slug)
        return {"ok": True, "item": _flashcard_json(item, None)}

    parsed = editing.load(chapter)
    if op == "chapter.update":
        parsed.meta["chapter_title"] = _title(data.get("title"), "عنوان فصل")
        number = str(data.get("number") or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).strip()
        parsed.meta["chapter_number"] = (int(number) if number.isdigit() else None) if (user.is_superuser or not book.is_published) else chapter.position
        parsed.meta["chapter_free"] = bool(data.get("is_free")) if user.is_superuser else chapter.is_free
        note = "مشخصات فصل"
    elif op == "section.create":
        slug = (data.get("slug") or "").strip() or editing.suggest_slug(book, parsed, "section")
        editing.require_new_slug(book, parsed, "section", slug)
        new = editing.ParsedSection(slug=slug, title=_title(data.get("title"), "عنوان بخش"), line=0, group=" ".join((data.get("group") or "").split()))
        after = data.get("after")
        index = next((i + 1 for i, s in enumerate(parsed.sections) if s.slug == after), len(parsed.sections))
        parsed.sections.insert(index, new)
        note = f"بخش تازه «{new.title}»"
    elif op == "section.update":
        target = editing.section(parsed, data.get("slug", ""))
        label = f"«{target.title}»" if target.slug else "مقدمه"
        if target.slug:
            if "title" in data:
                target.title = _title(data["title"], "عنوان بخش")
            if "group" in data:
                target.group = " ".join((data["group"] or "").split())
        _set_bodies(target, data, label)
        note = f"{label}"
    elif op == "section.reorder":
        order = data.get("order") or []
        by_slug = {s.slug: s for s in parsed.sections}
        if sorted(order) != sorted(by_slug):
            raise EditError("فهرست بخش‌ها با فصل نمی‌خواند؛ صفحه را تازه کنید.")
        parsed.sections = [by_slug[s] for s in order]
        note = "ترتیب بخش‌ها"
    elif op == "section.archive":
        target = editing.section(parsed, data.get("slug", ""))
        if not target.slug:
            raise EditError("مقدمه بایگانی نمی‌شود؛ متنش را خالی کنید.")
        if len(parsed.sections) == 1:
            raise EditError("فصل باید دست‌کم یک بخش داشته باشد.")
        parsed.sections.remove(target)
        _drop_refs(parsed, {f.slug for f in target.flashcards})
        note = f"بایگانی بخش «{target.title}»"
    elif op == "section.restore":
        restored = editing.archived_section(chapter, data.get("slug", ""))
        parsed.sections.append(restored)
        note = f"بازگرداندن بخش «{restored.title}»"
    elif op in ("question.save", "flashcard.save"):
        kind = op.split(".")[0]
        slug = (data.get("slug") or "").strip()
        attr = "questions" if kind == "question" else "flashcards"
        if data.get("new"):
            slug = slug or editing.suggest_slug(book, parsed, kind)
            editing.require_new_slug(book, parsed, kind, slug)
            target = editing.section(parsed, data.get("section", ""))
            item = (editing.question_from_form if kind == "question" else editing.flashcard_from_form)(data.get("data") or {}, slug)
            if not user.is_superuser:
                item.is_free = False
            getattr(target, attr).append(item)
            note = f"{'تست' if kind == 'question' else 'فلش‌کارت'} تازه {slug}"
        else:
            sec, items, i = editing.find_item(parsed, kind, slug)
            existing_free = items[i].is_free
            item = (editing.question_from_form if kind == "question" else editing.flashcard_from_form)(data.get("data") or {}, slug)
            if not user.is_superuser:
                item.is_free = existing_free
            items[i] = item
            note = f"{'تست' if kind == 'question' else 'فلش‌کارت'} {slug}"
        if kind == "question":
            known = {f.slug for s in parsed.all_sections() for f in s.flashcards}
            missing = [s for s in item.flashcard_slugs if s not in known]
            missing = [s for s in missing if s not in outside_flashcards(book, parsed, missing)]
            if missing:
                raise EditError(f"فلش‌کارت «{'، '.join(missing)}» نه در این فصل هست نه در فصل‌های دیگر این کتاب.")
    elif op in ("question.reorder", "flashcard.reorder"):
        kind = op.split(".")[0]
        target = editing.section(parsed, data.get("section", ""))
        attr = "questions" if kind == "question" else "flashcards"
        items = {i.slug: i for i in getattr(target, attr)}
        order = data.get("order") or []
        if sorted(order) != sorted(items):
            raise EditError("فهرست با بخش نمی‌خواند؛ صفحه را تازه کنید.")
        setattr(target, attr, [items[s] for s in order])
        note = f"ترتیب {'تست‌ها' if kind == 'question' else 'فلش‌کارت‌ها'}ی «{target.title or 'مقدمه'}»"
    elif op in ("question.move", "flashcard.move"):
        kind = op.split(".")[0]
        sec, items, i = editing.find_item(parsed, kind, data.get("slug", ""))
        target = editing.section(parsed, data.get("to", ""))
        item = items.pop(i)
        getattr(target, "questions" if kind == "question" else "flashcards").append(item)
        note = f"انتقال {item.slug} به «{target.title or 'مقدمه'}»"
    elif op in ("question.archive", "flashcard.archive"):
        kind = op.split(".")[0]
        sec, items, i = editing.find_item(parsed, kind, data.get("slug", ""))
        item = items.pop(i)
        if kind == "flashcard":
            _drop_refs(parsed, {item.slug})
        note = f"بایگانی {item.slug}"
    elif op in ("question.restore", "flashcard.restore"):
        kind = op.split(".")[0]
        obj, item = editing.archived_item(chapter, kind, data.get("slug", ""))
        to = data.get("to")
        if to is None:
            to = "" if obj.node.kind == ContentNode.Kind.CHAPTER else obj.node.slug
            if to and to not in {s.slug for s in parsed.sections}:
                to = ""
        if kind == "question":
            known = {f.slug for s in parsed.all_sections() for f in s.flashcards}
            known |= set(outside_flashcards(book, parsed, item.flashcard_slugs))
            item.flashcard_slugs = [s for s in item.flashcard_slugs if s in known]
        getattr(editing.section(parsed, to), "questions" if kind == "question" else "flashcards").append(item)
        note = f"بازگرداندن {item.slug}"
    else:
        raise EditError("عملیات ناشناخته.")

    before = editing.load(chapter) if data.get("fresh") else None
    result, version, warnings = editing.save(chapter, parsed, user=user, note=note, expected_version=data.get("version"))
    out = {"ok": True, "warnings": warnings}
    if before is not None:
        out["note"] = _mark_fresh(chapter, before, editing.load(chapter), data.get("fresh_note") or "")
    return out


def _fresh_targets(before, after) -> tuple[list[str], list[str], list[str]]:
    """Slugs of what a save changed or added: sections (the intro is ""), tests and flashcards."""
    old_s = {s.slug: s for s in before.all_sections()}
    sections = [s.slug for s in after.all_sections()
                if s.slug not in old_s or (old_s[s.slug].full_body, old_s[s.slug].summary_body) != (s.full_body, s.summary_body)]
    out = [sections]
    for attr in ("questions", "flashcards"):
        old = {i.slug: editing._item_fields(i) for s in before.all_sections() for i in getattr(s, attr)}
        out.append([i.slug for s in after.all_sections() for i in getattr(s, attr) if old.get(i.slug) != editing._item_fields(i)])
    return out[0], out[1], out[2]


def _mark_fresh(chapter, before, after, text: str) -> str:
    """«مطلب تازه»: mark what this save changed as «به‌روز شده» for learners, and write it in «تغییرات کتاب»."""
    from .fresh import mark

    book = chapter.book()
    sections, questions, flashcards = _fresh_targets(before, after)
    by_slug = {n.slug: n.pk for n in chapter.get_children().filter(kind=ContentNode.Kind.SECTION)}
    node_ids = [chapter.pk if not slug else by_slug.get(slug) for slug in sections]
    ids = [chapter.pk, *chapter.get_descendants().values_list("pk", flat=True)]
    q_ids = list(Question.objects.filter(node_id__in=ids, slug__in=questions, is_archived=False).values_list("pk", flat=True))
    f_ids = list(Flashcard.objects.filter(node_id__in=ids, slug__in=flashcards, is_archived=False).values_list("pk", flat=True))
    # New tests and cards are «تازه» by themselves; the tick marks the edited ones.
    added_q = set(Question.objects.filter(pk__in=q_ids, added_at__gte=timezone.now() - timedelta(minutes=5)).values_list("pk", flat=True))
    added_f = set(Flashcard.objects.filter(pk__in=f_ids, added_at__gte=timezone.now() - timedelta(minutes=5)).values_list("pk", flat=True))
    where = ContentNode.objects.filter(pk=node_ids[0]).first() if len(node_ids) == 1 and node_ids[0] else chapter
    n = mark(book, nodes=node_ids, questions=[i for i in q_ids if i not in added_q], flashcards=[i for i in f_ids if i not in added_f],
             text=text, where=where)
    if not n and (added_q or added_f) and text.strip():
        from .models import BookChange

        BookChange.objects.create(book=book, node=chapter, text=text.strip()[:300])
    return "به‌عنوان «مطلب تازه» به کاربران نشان داده می‌شود." if n or added_q or added_f else "چیزی تغییر نکرده بود که «مطلب تازه» بخورد."


def _drop_refs(parsed, flashcard_slugs: set[str]):
    for s in parsed.all_sections():
        for q in s.questions:
            q.flashcard_slugs = [x for x in q.flashcard_slugs if x not in flashcard_slugs]


# --- Views -------------------------------------------------------------------------------------------------


def chapter_api(request, chapter_id):
    chapter = _chapter(chapter_id)
    _can_edit(request, chapter.book())
    if request.method == "POST":
        if request.content_type.startswith("multipart/"):
            _can_edit_draft(request, chapter)
            return _upload_image(request, chapter)
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"errors": ["درخواست نامعتبر."]}, status=400)
        if data.get("op") != "file.check":
            _can_edit_draft(request, chapter)
        if data.get("op") == "file.check":
            return JsonResponse(_file_check(chapter, data.get("text", ""), data.get("meta"), request.user))
        if data.get("op") == "file.apply":
            return _file_apply(request, chapter, data)
        if data.get("op") == "file.restore_text":
            return _restore_text(request, chapter, data)
        try:
            outcome = apply_op(chapter, data, request.user)
        except editing.Conflict as e:
            return JsonResponse({"errors": e.messages, "conflict": True}, status=409)
        except EditError as e:
            return JsonResponse({"errors": e.messages}, status=400)
        if "item" in outcome:
            return JsonResponse(outcome)
        return JsonResponse({**outcome, "state": chapter_state(chapter, request.user)})
    return JsonResponse({"state": chapter_state(chapter, request.user)})


def _upload_image(request, chapter):
    upload = request.FILES.get("image")
    if not upload:
        return JsonResponse({"errors": ["عکسی انتخاب نشده."]}, status=400)
    ext = posixpath.splitext(upload.name)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return JsonResponse({"errors": ["فقط png، jpg، webp، gif یا svg."]}, status=400)
    if upload.size > MAX_IMAGE_BYTES:
        return JsonResponse({"errors": ["عکس بیشتر از ۵ مگابایت است."]}, status=400)
    data = upload.read()
    if ext == ".svg" and _SVG_DANGER.search(data):
        return JsonResponse({"errors": ["این SVG کد اجرایی دارد و پذیرفته نمی‌شود."]}, status=400)
    book = chapter.book()
    path = f"content/{book.slug}/{chapter.slug}/{hashlib.sha256(data).hexdigest()[:24]}{ext}"
    if not default_storage.exists(path):
        path = default_storage.save(path, ContentFile(data))
    return JsonResponse({"ref": f"media:{path}", "url": default_storage.url(path)})


def _lock_teacher_distribution_fields(parsed, book, existing_chapter, user):
    """A teacher's import may prepare lesson content, never alter price or who can access it."""
    if not user or user.is_superuser or book is None:
        return parsed
    parsed.meta["book_slug"] = book.slug
    parsed.meta["book_title"] = book.title
    parsed.meta["majors"] = list(book.majors.values_list("slug", flat=True))
    parsed.meta.pop("book_price", None)
    parsed.meta["chapter_free"] = existing_chapter.is_free if existing_chapter else False
    if existing_chapter:
        parsed.meta["chapter_number"] = existing_chapter.position
    elif book.is_published:
        from django.db.models import Max

        last_number = (ContentNode.objects.filter(path__startswith=book.path, depth=book.depth + 1, kind=ContentNode.Kind.CHAPTER)
                       .aggregate(last=Max("position"))["last"] or 0)
        parsed.meta["chapter_number"] = last_number + 1

    question_free = dict(Question.objects.filter(node__path__startswith=book.path).values_list("slug", "is_free"))
    card_free = dict(Flashcard.objects.filter(node__path__startswith=book.path).values_list("slug", "is_free"))
    for section in parsed.all_sections():
        for question in section.questions:
            question.is_free = question_free.get(question.slug, False)
        for card in section.flashcards:
            card.is_free = card_free.get(card.slug, False)
    return parsed


def _file_check(chapter, text, meta=None, user=None):
    meta_error = _meta_error(meta)
    if meta_error:
        return {"errors": [meta_error], "warnings": [], "plan": None, "diff": [], "meta": {"error": True}}
    parsed = editing.check_text(text, chapter.book(), chapter)
    if not parsed.errors:
        _lock_teacher_distribution_fields(parsed, chapter.book(), chapter, user)
    current = export_chapter(chapter)
    return {
        "errors": [str(e) for e in parsed.errors],
        "warnings": [str(w) for w in parsed.warnings if "مقدمه‌ی فصل ذخیره می‌شود" not in str(w)],
        "plan": editing.plan_changes(editing.load(chapter), parsed) if not parsed.errors else None,
        "diff": editing.text_diff(current, text.replace("\r\n", "\n")),
        "meta": _meta_notes(chapter, parsed, meta),
    }


def _meta_notes(chapter, parsed, meta=None) -> dict:
    """What the page says about the details above the box (the card), not about the text.

    «clash» is the one that matters: the chapter's number is not unique and `_order_chapters` sorts the book by it, so
    a second chapter numbered ۲ moves every chapter after it — silently, until now. Said here, before the save.
    """
    number = parsed.meta.get("chapter_number")
    if meta and "chapter_number" in meta:
        number = meta["chapter_number"]
    if number is None:
        return {}
    book = chapter.book()
    twin = (ContentNode.objects.filter(path__startswith=book.path, depth=book.depth + 1, position=number, kind=ContentNode.Kind.CHAPTER)
            .exclude(pk=chapter.pk).first())
    if twin is None:
        return {}
    return {"clash": f"شماره‌ی {fa_digits(number)} الان به فصل «{twin.title}» داده شده؛ با ذخیره ترتیب فصل‌های کتاب عوض می‌شود.",
            "twin": twin.title}



def _file_apply(request, chapter, data):
    _can_edit_draft(request, chapter)
    text = data.get("text", "")
    meta_error = _meta_error(data.get("meta"))
    if meta_error:
        return JsonResponse({"errors": [meta_error], "meta": {"error": True}}, status=400)
    parsed = editing.check_text(text, chapter.book(), chapter)
    if parsed.errors:
        return JsonResponse({"errors": [str(e) for e in parsed.errors]}, status=400)
    _lock_teacher_distribution_fields(parsed, chapter.book(), chapter, request.user)
    try:
        with transaction.atomic():
            locked = ContentNode.objects.select_for_update().get(pk=chapter.pk)
            if data.get("version") and editing.version_of(export_chapter(locked)) != data["version"]:
                raise editing.Conflict("این فصل در این فاصله تغییر کرده است؛ صفحه را تازه کنید.")
            editing.ensure_baseline(locked, request.user)
            before = editing.load(locked) if data.get("fresh") else None
            apply_chapter(parsed)
            source = ChapterRevision.Source.RESTORE if data.get("restore") else ChapterRevision.Source.PANEL
            editing.record_revision(locked, user=request.user, source=source, note=data.get("note") or "ویرایش کل فایل")
            note = _mark_fresh(locked, before, editing.load(locked), data.get("fresh_note") or "") if before is not None else ""
    except editing.Conflict as e:
        return JsonResponse({"errors": e.messages, "conflict": True}, status=409)
    return JsonResponse({"ok": True, "note": note, "state": chapter_state(chapter, request.user)})


def _meta_error(meta) -> str:
    """The card sends its three details beside the text. They are also lines of the header, so the text is what is
    checked — but a value that cannot become a line (a number that is not a number, an empty title) is refused here,
    with its own sentence, rather than as a confusing «خط مشخصات نامعتبر است»."""
    if not isinstance(meta, dict):
        return ""
    number = meta.get("chapter_number")
    if number is not None and (isinstance(number, bool) or not isinstance(number, int) or number < 0 or number > 32767):
        return "شماره‌ی فصل باید عددی بین ۰ و ۳۲۷۶۷ باشد."
    if "chapter_title" in meta and not str(meta.get("chapter_title") or "").strip():
        return "عنوان فصل خالی است."
    return ""


def _restore_text(request, chapter, data):
    """«فقط متن بخش‌ها را برگردان»: the notes and summaries of an old version go back into the sections that exist now
    (and the intro). Nothing else changes: no section, test or flashcard is archived, moved or edited."""
    _can_edit_draft(request, chapter)
    old = parse_chapter(data.get("text", ""))
    texts = {s.slug: s for s in old.all_sections()}
    current = editing.load(chapter)
    changed = 0
    for s in current.all_sections():
        o = texts.get(s.slug)
        if o and (o.full_body, o.summary_body) != (s.full_body, s.summary_body):
            s.full_lines, s.summary_lines = list(o.full_lines), list(o.summary_lines)
            changed += 1
    if not changed:
        return JsonResponse({"errors": ["متن هیچ بخشی با این نسخه فرقی ندارد."]}, status=400)
    try:
        with transaction.atomic():
            editing.save(chapter, current, user=request.user, note=data.get("note") or "بازگرداندن متن بخش‌ها",
                         expected_version=data.get("version"), source=ChapterRevision.Source.RESTORE)
    except editing.Conflict as e:
        return JsonResponse({"errors": e.messages, "conflict": True}, status=409)
    except EditError as e:
        return JsonResponse({"errors": e.messages}, status=400)
    return JsonResponse({"ok": True, "changed": changed, "state": chapter_state(chapter, request.user)})


def open_inbox(request):
    """«صندوق تست»: made on first use, then opened in the chapter manager."""
    # The inbox belongs to no book, so no «استاد کتاب» row can guard it. It is a test bench for the whole site.
    _can_edit(request)
    _require_superuser(request)
    from .inbox import inbox_chapter

    return redirect(reverse("admin:catalog_chapter_manager", args=[inbox_chapter().pk]))


def chapter_manager(admin_site, request, chapter_id):
    chapter = _chapter(chapter_id)
    _can_edit_draft(request, chapter)
    book = chapter.book()
    return TemplateResponse(
        request,
        "admin/catalog/book/chapter_manager.html",
        _context(admin_site, request, f"مدیریت فصل: {chapter.title}", book=book, chapter=chapter,
                 api_url=reverse("admin:catalog_chapter_api", args=[chapter.pk])),
    )


def chapter_file(admin_site, request, chapter_id):
    chapter = _chapter(chapter_id)
    book = chapter.book()
    _can_edit_draft(request, chapter)
    current_text = export_chapter(chapter)
    text = current_text
    restore = None
    if request.GET.get("revision"):
        revision = get_object_or_404(ChapterRevision, pk=request.GET["revision"], chapter=chapter)
        text, restore = revision.text, revision
    # The box holds only the selected version's body; its header always comes from the *current* chapter. Restoring an
    # old text must never undo a later book rename, slug, major assignment, or chapter detail hidden from the box.
    body = whole_file_body(text)
    current_header = whole_file_header(current_text)
    majors = list(book.majors.order_by("order", "name"))
    # A full version restore includes the three editable chapter details from that version. The book, its majors and
    # both slugs remain current/read-only: a restore must not roll back book metadata or user-progress identities.
    restore_details = parse_chapter(text).meta if restore and whole_file_header(text) else {}
    meta = {
        "chapter_title": restore_details.get("chapter_title", chapter.title),
        "chapter_number": restore_details.get("chapter_number", chapter.position),
        "chapter_free": restore_details.get("chapter_free", chapter.is_free),
        "book_slug": book.slug, "book_title": book.title, "chapter_slug": chapter.slug,
        "majors": [{"slug": m.slug, "name": m.name} for m in majors], "header": current_header,
    }
    return TemplateResponse(
        request,
        "admin/catalog/book/chapter_file.html",
        _context(admin_site, request, f"ویرایش کل فایل: {chapter.title}", book=book, chapter=chapter, body=body, meta=meta,
                 book_url=reverse("admin:catalog_inbox") if book.is_inbox else reverse("admin:catalog_book_change", args=[book.pk]),
                 restore=restore, restore_when=jalali_datetime(restore.updated_at) if restore else "",
                 version=editing.version_of(export_chapter(chapter)), api_url=reverse("admin:catalog_chapter_api", args=[chapter.pk])),
    )


FRONT_MATTER = re.compile(r"\A\ufeff?[ \t]*---[ \t]*\n(.*?)\n[ \t]*---[ \t]*(?:\n|\Z)", re.S)
FRONT_KEY = re.compile(r"^(شناسه-کتاب|کتاب|قیمت-کتاب|رشته‌ها|شناسه-فصل|فصل|عنوان|عنوان-انگلیسی|رایگان)\s*:", re.M)


def whole_file_header(text: str) -> str:
    """The leading chapter header, exactly as written, or an empty string if the text has none."""
    match = FRONT_MATTER.match(text or "")
    if not match:
        return ""
    lines = [line for line in match.group(1).split("\n") if line.strip()]
    return (text or "")[:match.end()] if lines and all(FRONT_KEY.match(line.strip()) for line in lines) else ""


def whole_file_body(text: str) -> str:
    """The chapter's text without its header — what «ویرایش کل فایل» puts in the box.

    The same rule the page has always used to keep the header out of the preview: only a block at the very top that
    holds nothing but the chapter's keys. A «---» pair around prose is a horizontal rule and stays in the text.
    """
    header = whole_file_header(text)
    return (text or "")[len(header):] if header else (text or "")


def chapter_export(request, chapter_id):
    chapter = _chapter(chapter_id)
    _can_edit(request, chapter.book())
    name, data, content_type = chapter_bundle(chapter)
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def chapter_tex(request, chapter_id):
    """The chapter as a LaTeX project: a .tex alone, or a ZIP with the .tex and its images/ — for Overleaf."""
    chapter = _chapter(chapter_id)
    _can_edit(request, chapter.book())
    name, data, content_type = chapter_tex_bundle(chapter)
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def chapter_email_tex(request, chapter_id):
    """Email the chapter's TeX/LaTeX project bundle directly to the verified teacher."""
    from django.contrib import messages
    from django.core.mail import EmailMessage
    from django.shortcuts import redirect

    chapter = _chapter(chapter_id)
    _can_edit(request, chapter.book())
    user = request.user

    if not user.email:
        messages.error(request, "ابتدا ایمیل خود را در پنل ثبت کنید.")
        return redirect(reverse("admin:catalog_book_change", args=[chapter.book().pk]))
    if not user.is_email_verified:
        messages.warning(request, f"ایمیل شما ({user.email}) هنوز تأیید نشده است. لطفاً ابتدا روی لینک تأیید ارسال‌شده کلیک کنید.")
        return redirect(reverse("admin:catalog_book_change", args=[chapter.book().pk]))

    name, data, content_type = chapter_tex_bundle(chapter)
    msg = EmailMessage(
        subject=f"فایل خروجی LaTeX فصل {chapter.title} - لیموخوان",
        body=(
            f"استاد گرامی سلام،\n\n"
            f"فایل سورس LaTeX فصل «{chapter.title}» از کتاب «{chapter.book().title}» پیوست شد.\n\n"
            f"با احترام،\nتیم پشتیبانی لیموخوان"
        ),
        to=[user.email],
    )
    msg.attach(name, data, content_type)
    try:
        msg.send(fail_silently=False)
        messages.success(request, f"فایل LaTeX فصل با موفقیت به ایمیل {user.email} ارسال شد.")
    except Exception as exc:
        messages.error(request, f"خطا در ارسال ایمیل: {exc}")

    return redirect(reverse("admin:catalog_book_change", args=[chapter.book().pk]))


def book_export(request, book_id):
    book = _book(book_id)
    _can_edit(request, book)
    response = HttpResponse(book_bundle(book), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{book.slug}.zip"'
    return response


def book_email_export(request, book_id):
    """Email the complete book ZIP archive directly to the verified teacher."""
    from django.contrib import messages
    from django.core.mail import EmailMessage
    from django.shortcuts import redirect

    book = _book(book_id)
    _can_edit(request, book)
    user = request.user

    if not user.email:
        messages.error(request, "ابتدا ایمیل خود را در پنل ثبت کنید.")
        return redirect(reverse("admin:catalog_book_change", args=[book.pk]))
    if not user.is_email_verified:
        messages.warning(request, f"ایمیل شما ({user.email}) هنوز تأیید نشده است. لطفاً ابتدا روی لینک تأیید ارسال‌شده کلیک کنید.")
        return redirect(reverse("admin:catalog_book_change", args=[book.pk]))

    data = book_bundle(book)
    name = f"{book.slug}.zip"
    msg = EmailMessage(
        subject=f"فایل آرشیو کامل کتاب {book.title} - لیموخوان",
        body=(
            f"استاد گرامی سلام،\n\n"
            f"آرشیو کامل زیپ کتاب «{book.title}» پیوست شد.\n\n"
            f"با احترام،\nتیم پشتیبانی لیموخوان"
        ),
        to=[user.email],
    )
    msg.attach(name, data, "application/zip")
    try:
        msg.send(fail_silently=False)
        messages.success(request, f"آرشیو کامل کتاب با موفقیت به ایمیل {user.email} ارسال شد.")
    except Exception as exc:
        messages.error(request, f"خطا در ارسال ایمیل: {exc}")

    return redirect(reverse("admin:catalog_book_change", args=[book.pk]))


def chapter_history(admin_site, request, chapter_id):
    chapter = _chapter(chapter_id)
    _can_edit(request, chapter.book())
    revisions = list(chapter.revisions.select_related("user").order_by("-updated_at", "-id"))
    current = export_chapter(chapter)
    rows = [{"r": r, "when": jalali_datetime(r.updated_at), "is_current": r.text == current, "size": len(r.text.splitlines())} for r in revisions]
    compare, diff = None, None
    if request.GET.get("compare"):
        compare = get_object_or_404(ChapterRevision, pk=request.GET["compare"], chapter=chapter)
        diff = editing.text_diff(compare.text, current)
        compare = {"r": compare, "when": jalali_datetime(compare.updated_at)}
    return TemplateResponse(
        request,
        "admin/catalog/book/chapter_history.html",
        _context(admin_site, request, f"نسخه‌های فصل: {chapter.title}", book=chapter.book(), chapter=chapter, rows=rows, compare=compare, diff=diff),
    )


def revision_text(request, chapter_id, revision_id):
    _can_edit(request, _chapter(chapter_id).book())
    revision = get_object_or_404(ChapterRevision, pk=revision_id, chapter_id=chapter_id)
    response = HttpResponse(revision.text, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{revision.chapter.slug}-v{revision.pk}.md"'
    return response


# --- Importing a file with a preview -----------------------------------------------------------------------


def import_view(admin_site, request, book_id=None):
    """Upload → check and preview what will change → confirm. The upload waits on the server between the two steps."""
    book = _book(book_id) if book_id else None
    if book is None:
        # With no book in the URL the file itself names the book, so it could land in ANY book. Superusers only;
        # everyone else imports through their own book's page, which passes book_id.
        _can_edit(request)
        _require_superuser(request)
    else:
        _can_edit(request, book)
    report = None
    if request.method == "POST" and request.POST.get("token"):
        token = request.POST["token"]
        if not all(c in "0123456789abcdef-" for c in token):
            raise PermissionDenied
        found = [p for p in (f"{PENDING_DIR}/{token}{ext}" for ext in UPLOAD_EXTENSIONS) if default_storage.exists(p)]
        if not found:
            messages.error(request, "فایل بررسی‌شده پیدا نشد؛ دوباره انتخابش کنید.")
            return redirect(request.path)
        with default_storage.open(found[0], "rb") as fh:
            data = fh.read()
        default_storage.delete(found[0])
        parsed = read_upload(found[0], data, book)
        check_against_db(parsed)
        if parsed.errors:
            messages.error(request, "فایل خطا دارد؛ چیزی وارد نشد.")
            return redirect(request.path)
        publish_now = bool(request.POST.get("publish"))
        if publish_now:
            # The file names its own book, which may not be one the uploader may publish.
            try:
                _may_publish(request.user, book or _book_by_slug(parsed.meta.get("book_slug")))
            except EditError as exc:
                messages.error(request, "؛ ".join(exc.messages))
                return redirect(request.path)
        with transaction.atomic():
            existing = _existing_chapter(parsed)
            if existing and not access.can_edit_chapter(request.user, existing):
                raise PermissionDenied("استاد فقط می‌تواند پیش‌نویس بسازد و تغییر دهد؛ محتوای زنده را مدیر کل بازبینی می‌کند.")
            _lock_teacher_distribution_fields(parsed, book or (existing.book() if existing else None), existing, request.user)
            if existing:
                editing.ensure_baseline(existing, request.user)
            result = apply_chapter(parsed, publish=publish_now)
            editing.record_revision(result.chapter, user=request.user, source=ChapterRevision.Source.FILE, note=f"بارگذاری فایل: {request.POST.get('filename', '')}"[:300])
        messages.success(request, f"وارد شد. {result.summary()}")
        return redirect(reverse("admin:catalog_chapter_manager", args=[result.chapter.pk]))
    if request.method == "POST" and request.FILES.get("file"):
        _cleanup_pending()
        upload = request.FILES["file"]
        if upload.size > MAX_UPLOAD_BYTES:
            report = {"filename": upload.name, "errors": ["حجم فایل بیشتر از ۵۰ مگابایت است."], "warnings": []}
        else:
            data = upload.read()
            parsed = read_upload(upload.name, data, book)
            check_against_db(parsed)
            existing = _existing_chapter(parsed) if not parsed.errors else None
            if existing and not access.can_edit_chapter(request.user, existing):
                parsed.error("استاد فقط می‌تواند پیش‌نویس بسازد و تغییر دهد؛ محتوای زنده را مدیر کل بازبینی می‌کند.")
            if not parsed.errors:
                _lock_teacher_distribution_fields(parsed, book or (existing.book() if existing else None), existing, request.user)
                _check_moves(parsed, existing)
            report = {
                "filename": upload.name,
                "errors": [str(e) for e in parsed.errors],
                "warnings": [str(w) for w in parsed.warnings if "مقدمه‌ی فصل ذخیره می‌شود" not in str(w)],
            }
            if not parsed.errors:
                token = str(uuid.uuid4())
                ext = next(e for e in UPLOAD_EXTENSIONS if upload.name.lower().endswith(e))
                default_storage.save(f"{PENDING_DIR}/{token}{ext}", ContentFile(data))
                report.update(
                    token=token,
                    existing=existing,
                    target_book=parsed.meta["book_title"],
                    target_chapter=parsed.meta["chapter_title"],
                    counts={
                        "sections": len(parsed.sections),
                        "questions": sum(len(s.questions) for s in parsed.all_sections()),
                        "flashcards": sum(len(s.flashcards) for s in parsed.all_sections()),
                    },
                    plan=editing.plan_changes(editing.load(existing) if existing else None, parsed),
                    diff=editing.text_diff(export_chapter(existing), write_chapter(parsed)) if existing else None,
                    # What the chapter will LOOK like, before anything is saved. A professor could not see this until
                    # after «اعمال تغییرات», which is where a mis-read \note or a lost table was found — too late.
                    markdown=write_chapter(parsed),
                )
    return TemplateResponse(
        request,
        "admin/catalog/book/import.html",
        _context(admin_site, request, "افزودن یا به‌روزرسانی فصل از فایل", book=book, report=report),
    )


def _existing_chapter(parsed):
    book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, slug=parsed.meta["book_slug"], depth=1).first()
    if not book:
        return None
    return ContentNode.objects.filter(path__startswith=book.path, kind=ContentNode.Kind.CHAPTER, slug=parsed.meta["chapter_slug"]).first()


def _check_moves(parsed, existing):
    book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, slug=parsed.meta["book_slug"], depth=1).first()
    if book:
        editing._check_ids_in_other_chapters(parsed, book, existing)


def _cleanup_pending():
    """Forget checked uploads nobody confirmed within a day."""
    try:
        _, files = default_storage.listdir(PENDING_DIR)
    except (FileNotFoundError, NotImplementedError, OSError):
        return
    cutoff = timezone.now() - timezone.timedelta(days=1)
    for name in files:
        path = f"{PENDING_DIR}/{name}"
        try:
            if default_storage.get_modified_time(path) < cutoff:
                default_storage.delete(path)
        except (NotImplementedError, OSError):
            pass


# --- Book page actions ---------------------------------------------------------------------------------------


@require_POST
def book_chapter_action(request, book_id):
    book = _book(book_id)
    _can_edit(request, book)
    action = request.POST.get("action")
    if action in ("free", "publish", "archive"):
        _require_superuser(request)
    if action in ("up", "down") and book.is_published and not request.user.is_superuser:
        raise PermissionDenied("ترتیب فصل‌های کتاب منتشرشده را فقط مدیر کل تغییر می‌دهد.")
    back = reverse("admin:catalog_book_change", args=[book.pk]) + "#chapters"
    if action == "new":
        title = " ".join(request.POST.get("title", "").split())
        slug = request.POST.get("slug", "").strip()
        if not title or not slug or not editing._SLUG.match(slug):
            messages.error(request, "عنوان و شناسه‌ی فصل لازم است (شناسه فقط حرف لاتین، عدد، - و _).")
            return redirect(back)
        if ContentNode.objects.filter(path__startswith=book.path, slug=slug).exists():
            messages.error(request, f"شناسه‌ی «{slug}» در این کتاب استفاده شده است.")
            return redirect(back)
        chapters = list(book.get_children().filter(kind=ContentNode.Kind.CHAPTER))
        number = request.POST.get("number", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).strip()
        next_number = max([c.position or 0 for c in chapters], default=0) + 1
        chapter_number = next_number if (not request.user.is_superuser and book.is_published) else (int(number) if number.isdigit() else next_number)
        parsed = editing.ParsedChapter(meta={
            "book_slug": book.slug, "book_title": book.title,
            "majors": list(book.majors.values_list("slug", flat=True)),
            "chapter_slug": slug, "chapter_title": title,
            "chapter_number": chapter_number,
            "chapter_free": False,
        })
        parsed.sections = [editing.ParsedSection(slug=f"{slug}-s1", title="بخش ۱", line=0)]
        checked = parse_chapter(write_chapter(parsed), book=book)
        if checked.errors:
            messages.error(request, "؛ ".join(str(e) for e in checked.errors))
            return redirect(back)
        with transaction.atomic():
            result = apply_chapter(checked)
            editing.record_revision(result.chapter, user=request.user, source=ChapterRevision.Source.PANEL, note="فصل تازه")
        messages.success(request, f"فصل «{title}» ساخته شد.")
        return redirect(reverse("admin:catalog_chapter_manager", args=[result.chapter.pk]))

    chapter = get_object_or_404(ContentNode, pk=request.POST.get("chapter"), kind=ContentNode.Kind.CHAPTER, path__startswith=book.path)
    try:
        _chapter_action(request, book, chapter, action)
    except EditError as e:
        messages.error(request, "؛ ".join(e.messages))
    return redirect(back)


def _chapter_action(request, book, chapter, action):
    name = f"فصل {chapter.position or ''} «{chapter.title}»".replace("  ", " ")
    if action in ("free", "publish", "archive"):
        field = {"free": "is_free", "publish": "is_published", "archive": "is_archived"}[action]
        value = request.POST.get("value") == "1"
        if field == "is_free":
            # Part of the file too, so it goes through the editor (and gets a version).
            parsed = editing.load(chapter)
            parsed.meta["chapter_free"] = value
            editing.save(chapter, parsed, user=request.user, note="رایگان" if value else "پولی")
            messages.success(request, f"{name} {'رایگان' if value else 'پولی'} شد. بقیه‌ی فصل‌های کتاب تغییری نکردند.")
        elif field == "is_published":
            if value:
                _may_publish(request.user, book)
            drafts = set_chapter_published(chapter, value)
            done = f"{name} {'منتشر شد' if value else 'از انتشار خارج شد'}"
            messages.success(request, f"{done}؛ {drafts} بخش پیش‌نویس آن هم منتشر شد." if drafts else f"{done}.")
        else:
            ContentNode.objects.filter(pk=chapter.pk).update(**{field: value})
            messages.success(request, f"{name} {'بایگانی شد' if value else 'از بایگانی بیرون آمد'}.")
    elif action in ("up", "down"):
        chapters = list(book.get_children().filter(kind=ContentNode.Kind.CHAPTER))
        i = next(i for i, c in enumerate(chapters) if c.pk == chapter.pk)
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(chapters):
            chapters[i], chapters[j] = chapters[j], chapters[i]
            with transaction.atomic():
                for n, c in enumerate(chapters, start=1):
                    if c.position != n:
                        parsed = editing.load(c)
                        parsed.meta["chapter_number"] = n
                        editing.save(c, parsed, user=request.user, note=f"شماره‌ی فصل {n}")
            messages.success(request, "ترتیب فصل‌ها عوض شد (شماره‌ی فصل‌ها هم به‌روز شد).")
