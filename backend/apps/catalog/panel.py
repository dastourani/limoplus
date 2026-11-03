"""
The panel's content pages: «کتاب‌ها» (book page with its chapters), «مدیریت فصل», whole-file editing, versions,
and importing a file with a preview. Wired into the admin by BookAdmin.get_urls (staff only, CSRF-protected).
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import uuid

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

from apps.learning.models import Flashcard, Question, Report

from . import editing
from .editing import EditError
from .exporter import book_bundle, chapter_bundle, export_chapter, flashcard_block, question_block, write_chapter
from .importer import IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, _SVG_DANGER, apply_chapter, parse_chapter, read_upload, check_against_db
from .jalali import jalali_datetime
from .models import ChapterRevision, ContentNode
from .labels import all_labels
from .summary import parse_parts

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
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
    node = get_object_or_404(orphans(), pk=node_id)
    ids = [node.pk, *node.get_descendants().values_list("pk", flat=True)]
    with transaction.atomic():
        ContentNode.objects.filter(pk__in=ids).update(is_archived=True, is_published=False)
        Question.objects.filter(node_id__in=ids).update(is_archived=True)
        Flashcard.objects.filter(node_id__in=ids).update(is_archived=True)
    messages.success(request, f"«{node.title}» بایگانی شد (پاک نشد).")
    return redirect(reverse("admin:catalog_book_changelist"))


def _can_edit(request):
    if not (request.user.is_active and request.user.is_staff and request.user.has_perm("catalog.change_contentnode")):
        raise PermissionDenied


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
        "quick_solution": q.quick_solution,
        "alternative_view": q.alternative_view,
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
        "raw": "\n".join(question_block(q)),
        "answers": obj.answer_count if obj else 0,
        "is_sample": bool(obj and obj.is_sample),
        "correct_rate": round(100 * obj.correct_count / obj.answer_count) if obj and obj.answer_count else None,
        "reports": reports.get(obj.pk, 0) if obj else 0,
    }


def _flashcard_json(f, obj):
    return {"slug": f.slug, "id": obj.pk if obj else None, "title": f.title, "point": f.point, "formula": f.formula,
            "is_free": f.is_free, "raw": "\n".join(flashcard_block(f))}


def chapter_state(chapter: ContentNode) -> dict:
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
            "missing_phrases": editing_missing(s),
            "questions": [_question_json(q, questions.get(q.slug), reports) for q in s.questions],
            "flashcards": [_flashcard_json(f, flashcards.get(f.slug)) for f in s.flashcards],
        }

    intro = editing.section(parsed, "")
    archived_q = Question.objects.filter(node_id__in=ids, is_archived=True).select_related("node").order_by("node__path", "order")
    archived_f = Flashcard.objects.filter(node_id__in=ids, is_archived=True).select_related("node").order_by("node__path", "order")
    return {
        "version": version,
        "book": {"id": book.pk, "slug": book.slug, "title": book.title},
        "chapter": {"id": chapter.pk, "slug": chapter.slug, "title": chapter.title, "number": chapter.position,
                    "is_free": chapter.is_free, "is_published": chapter.is_published},
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
        "labels": all_labels(),
        "inbox": chapter.is_inbox,
        "refs": panel_refs(book),
    }


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
    op = data.get("op", "")
    book = chapter.book()
    note = ""

    if op == "question.relocate":
        from .inbox import relocate

        return relocate(chapter, data.get("slugs") or [], data.get("to"), user)
    if op == "destinations":
        from .inbox import destinations

        return {"ok": True, "destinations": destinations()}

    # Visibility lives only in the panel (not in the file). The «صندوق تست» is never published.
    if op in ("chapter.publish", "section.publish") and data.get("value") and chapter.is_inbox:
        raise EditError("صندوق تست منتشر نمی‌شود؛ تست‌ها را به بخش‌هایشان منتقل کنید.")
    if op == "chapter.publish":
        drafts = set_chapter_published(chapter, bool(data.get("value")))
        return {"ok": True, "note": f"{drafts} بخش پیش‌نویس هم منتشر شد." if drafts else ""}
    if op == "section.publish":
        n = chapter.get_children().filter(slug=data.get("slug"), kind=ContentNode.Kind.SECTION).update(is_published=bool(data.get("value")))
        if not n:
            raise EditError("بخش پیدا نشد.")
        return {"ok": True}

    if op == "question.sample":
        # «قابل اشتراک»: set in the panel only (not part of the file).
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
        parsed.meta["chapter_number"] = int(number) if number.isdigit() else None
        parsed.meta["chapter_free"] = bool(data.get("is_free"))
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
            getattr(target, attr).append(item)
            note = f"{'تست' if kind == 'question' else 'فلش‌کارت'} تازه {slug}"
        else:
            sec, items, i = editing.find_item(parsed, kind, slug)
            item = (editing.question_from_form if kind == "question" else editing.flashcard_from_form)(data.get("data") or {}, slug)
            items[i] = item
            note = f"{'تست' if kind == 'question' else 'فلش‌کارت'} {slug}"
        if kind == "question":
            known = {f.slug for s in parsed.all_sections() for f in s.flashcards}
            missing = [s for s in item.flashcard_slugs if s not in known]
            if missing:
                raise EditError(f"فلش‌کارت «{'، '.join(missing)}» در این فصل نیست.")
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
            item.flashcard_slugs = [s for s in item.flashcard_slugs if s in known]
        getattr(editing.section(parsed, to), "questions" if kind == "question" else "flashcards").append(item)
        note = f"بازگرداندن {item.slug}"
    else:
        raise EditError("عملیات ناشناخته.")

    result, version, warnings = editing.save(chapter, parsed, user=user, note=note, expected_version=data.get("version"))
    return {"ok": True, "warnings": warnings}


def _drop_refs(parsed, flashcard_slugs: set[str]):
    for s in parsed.all_sections():
        for q in s.questions:
            q.flashcard_slugs = [x for x in q.flashcard_slugs if x not in flashcard_slugs]


# --- Views -------------------------------------------------------------------------------------------------


def chapter_api(request, chapter_id):
    _can_edit(request)
    chapter = _chapter(chapter_id)
    if request.method == "POST":
        if request.content_type.startswith("multipart/"):
            return _upload_image(request, chapter)
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            return JsonResponse({"errors": ["درخواست نامعتبر."]}, status=400)
        if data.get("op") == "file.check":
            return JsonResponse(_file_check(chapter, data.get("text", "")))
        if data.get("op") == "file.apply":
            return _file_apply(request, chapter, data)
        try:
            outcome = apply_op(chapter, data, request.user)
        except editing.Conflict as e:
            return JsonResponse({"errors": e.messages, "conflict": True}, status=409)
        except EditError as e:
            return JsonResponse({"errors": e.messages}, status=400)
        if "item" in outcome:
            return JsonResponse(outcome)
        return JsonResponse({**outcome, "state": chapter_state(chapter)})
    return JsonResponse({"state": chapter_state(chapter)})


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


def _file_check(chapter, text):
    parsed = editing.check_text(text, chapter.book(), chapter)
    current = export_chapter(chapter)
    return {
        "errors": [str(e) for e in parsed.errors],
        "warnings": [str(w) for w in parsed.warnings if "مقدمه‌ی فصل ذخیره می‌شود" not in str(w)],
        "plan": editing.plan_changes(editing.load(chapter), parsed) if not parsed.errors else None,
        "diff": editing.text_diff(current, text.replace("\r\n", "\n")),
    }


def _file_apply(request, chapter, data):
    text = data.get("text", "")
    parsed = editing.check_text(text, chapter.book(), chapter)
    if parsed.errors:
        return JsonResponse({"errors": [str(e) for e in parsed.errors]}, status=400)
    try:
        with transaction.atomic():
            locked = ContentNode.objects.select_for_update().get(pk=chapter.pk)
            if data.get("version") and editing.version_of(export_chapter(locked)) != data["version"]:
                raise editing.Conflict("این فصل در این فاصله تغییر کرده است؛ صفحه را تازه کنید.")
            editing.ensure_baseline(locked, request.user)
            apply_chapter(parsed)
            source = ChapterRevision.Source.RESTORE if data.get("restore") else ChapterRevision.Source.PANEL
            editing.record_revision(locked, user=request.user, source=source, note=data.get("note") or "ویرایش کل فایل")
    except editing.Conflict as e:
        return JsonResponse({"errors": e.messages, "conflict": True}, status=409)
    return JsonResponse({"ok": True, "state": chapter_state(chapter)})


def open_inbox(request):
    """«صندوق تست»: made on first use, then opened in the chapter manager."""
    _can_edit(request)
    from .inbox import inbox_chapter

    return redirect(reverse("admin:catalog_chapter_manager", args=[inbox_chapter().pk]))


def chapter_manager(admin_site, request, chapter_id):
    _can_edit(request)
    chapter = _chapter(chapter_id)
    book = chapter.book()
    return TemplateResponse(
        request,
        "admin/catalog/book/chapter_manager.html",
        _context(admin_site, request, f"مدیریت فصل: {chapter.title}", book=book, chapter=chapter,
                 api_url=reverse("admin:catalog_chapter_api", args=[chapter.pk])),
    )


def chapter_file(admin_site, request, chapter_id):
    _can_edit(request)
    chapter = _chapter(chapter_id)
    text = export_chapter(chapter)
    restore = None
    if request.GET.get("revision"):
        revision = get_object_or_404(ChapterRevision, pk=request.GET["revision"], chapter=chapter)
        text, restore = revision.text, revision
    return TemplateResponse(
        request,
        "admin/catalog/book/chapter_file.html",
        _context(admin_site, request, f"ویرایش کل فایل: {chapter.title}", book=chapter.book(), chapter=chapter, text=text,
                 restore=restore, restore_when=jalali_datetime(restore.updated_at) if restore else "",
                 version=editing.version_of(export_chapter(chapter)), api_url=reverse("admin:catalog_chapter_api", args=[chapter.pk])),
    )


def chapter_export(request, chapter_id):
    _can_edit(request)
    name, data, content_type = chapter_bundle(_chapter(chapter_id))
    response = HttpResponse(data, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    return response


def book_export(request, book_id):
    _can_edit(request)
    book = _book(book_id)
    response = HttpResponse(book_bundle(book), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{book.slug}.zip"'
    return response


def chapter_history(admin_site, request, chapter_id):
    _can_edit(request)
    chapter = _chapter(chapter_id)
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
    _can_edit(request)
    revision = get_object_or_404(ChapterRevision, pk=revision_id, chapter_id=chapter_id)
    response = HttpResponse(revision.text, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{revision.chapter.slug}-v{revision.pk}.md"'
    return response


# --- Importing a file with a preview -----------------------------------------------------------------------


def import_view(admin_site, request, book_id=None):
    """Upload → check and preview what will change → confirm. The upload waits on the server between the two steps."""
    _can_edit(request)
    book = _book(book_id) if book_id else None
    report = None
    if request.method == "POST" and request.POST.get("token"):
        token = request.POST["token"]
        if not all(c in "0123456789abcdef-" for c in token):
            raise PermissionDenied
        found = [p for p in (f"{PENDING_DIR}/{token}.md", f"{PENDING_DIR}/{token}.zip") if default_storage.exists(p)]
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
        with transaction.atomic():
            existing = _existing_chapter(parsed)
            if existing:
                editing.ensure_baseline(existing, request.user)
            result = apply_chapter(parsed, publish=bool(request.POST.get("publish")))
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
            if not parsed.errors:
                _check_moves(parsed, existing)
            report = {
                "filename": upload.name,
                "errors": [str(e) for e in parsed.errors],
                "warnings": [str(w) for w in parsed.warnings if "مقدمه‌ی فصل ذخیره می‌شود" not in str(w)],
            }
            if not parsed.errors:
                token = str(uuid.uuid4())
                ext = ".zip" if upload.name.lower().endswith(".zip") else ".md"
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
    _can_edit(request)
    book = _book(book_id)
    action = request.POST.get("action")
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
        parsed = editing.ParsedChapter(meta={
            "book_slug": book.slug, "book_title": book.title,
            "majors": list(book.majors.values_list("slug", flat=True)),
            "chapter_slug": slug, "chapter_title": title,
            "chapter_number": int(number) if number.isdigit() else (max([c.position or 0 for c in chapters], default=0) + 1),
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
