"""
Write a chapter from the database back out as a chapter.md text (the same format the importer reads).

The database is the source of truth; this text is what «دریافت فایل فصل» downloads, what the panel's whole-file
editor shows, and what each saved version (ChapterRevision) keeps. Importing the exported text changes nothing.

Images stay as `media:content/…` references, which the importer accepts when the file is on this server. For a
portable copy, `chapter_bundle` makes a ZIP with an images/ folder instead.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile

from django.core.files.storage import default_storage

from apps.learning.models import Flashcard, Question

from .importer import MEDIA_PREFIX, ParsedChapter, ParsedFlashcard, ParsedQuestion, ParsedSection
from .models import ContentNode

DIFFICULTY_FA = {"easy": "آسان", "medium": "متوسط", "hard": "سخت"}
DOMAIN_FA = {"general": "عمومی", "specialized": "تخصصی"}
KIND_FA = {"recall": "حفظی", "concept": "مفهومی", "calc": "محاسباتی", "analysis": "تحلیلی"}
_MEDIA_IMAGE = re.compile(r"!\[([^\]]*)\]\(" + re.escape(MEDIA_PREFIX) + r"([^)\s]+)\)")


# --- Items as parsed objects (the panel edits these) ----------------------------------------------------------


def question_to_parsed(q: Question) -> ParsedQuestion:
    sources = [(qs.source.name, qs.source.year, qs.number) for qs in q.questionsource_set.select_related("source").order_by("id")]
    return ParsedQuestion(
        slug=q.slug,
        line=0,
        stem=q.stem,
        explanation=q.explanation,
        quick_solution=q.quick_solution,
        alternative_view=q.alternative_view,
        difficulty=q.difficulty,
        domain=q.domain,
        kind=q.kind,
        seconds=q.estimated_seconds,
        is_free=q.is_free,
        fixed_order=q.fixed_order,
        is_original=q.is_original or not sources,
        sources=sources,
        flashcard_slugs=list(q.flashcards.order_by("order", "id").values_list("slug", flat=True)),
        choices=[(c.text, c.is_correct) for c in q.choices.all()],
    )


def flashcard_to_parsed(f: Flashcard) -> ParsedFlashcard:
    return ParsedFlashcard(slug=f.slug, line=0, title=f.title, point=f.point, formula=f.formula, is_free=f.is_free)


# --- Blocks as text --------------------------------------------------------------------------------------------


def question_block(q: ParsedQuestion) -> list[str]:
    lines = [f":::تست {{#{q.slug}}}"]
    if q.is_original:
        lines.append("منبع: تألیفی")
    for name, year, number in q.sources:
        lines.append(f"منبع: {name} {year}" + (f"، سؤال {number}" if number else ""))
    lines.append(f"سطح: {DIFFICULTY_FA.get(q.difficulty, q.difficulty)}")
    if q.domain:
        lines.append(f"حوزه: {DOMAIN_FA.get(q.domain, q.domain)}")
    if q.kind:
        lines.append(f"نوع: {KIND_FA.get(q.kind, q.kind)}")
    if q.seconds:
        lines.append(f"زمان: {q.seconds}")
    if q.is_free:
        lines.append("رایگان: بله")
    if q.fixed_order:
        lines.append("ترتیب گزینه‌ها: ثابت")
    lines.append("صورت:")
    lines.extend(q.stem.split("\n"))
    for text, ok in q.choices:
        lines.append(f"- [{'x' if ok else ' '}] {' '.join(text.split())}")
    lines.append(f"توضیح: {q.explanation}")
    if q.quick_solution:
        lines.append(f"راه‌حل سریع: {q.quick_solution}")
    if q.alternative_view:
        lines.append(f"زاویه‌ی دیگر: {q.alternative_view}")
    if q.flashcard_slugs:
        lines.append(f"فلش‌کارت: {', '.join(q.flashcard_slugs)}")
    lines.append(":::")
    return "\n".join(lines).split("\n")


def flashcard_block(f: ParsedFlashcard) -> list[str]:
    lines = [f":::فلش‌کارت {{#{f.slug}}}", f"عنوان: {f.title}", f"نکته: {f.point}"]
    if f.formula:
        lines.append(f"فرمول: {f.formula}")
    if f.is_free:
        lines.append("رایگان: بله")
    lines.append(":::")
    return "\n".join(lines).split("\n")


def _body(full: str, summary: str, questions, flashcards) -> list[str]:
    out = []
    if full.strip():
        out += [full.strip(), ""]
    if summary.strip():
        out += [":::خلاصه", summary.strip(), ":::", ""]
    for q in questions:
        out += question_block(q) + [""]
    for f in flashcards:
        out += flashcard_block(f) + [""]
    return out


def write_chapter(parsed: ParsedChapter) -> str:
    """A parsed chapter (from a file, from the database, or edited in the panel) as chapter.md text."""
    meta = parsed.meta
    out = ["---", f"شناسه-کتاب: {meta['book_slug']}", f"کتاب: {meta['book_title']}"]
    if meta.get("majors"):
        out.append(f"رشته‌ها: {', '.join(meta['majors'])}")
    out.append(f"شناسه-فصل: {meta['chapter_slug']}")
    if meta.get("chapter_number") is not None:
        out.append(f"فصل: {meta['chapter_number']}")
    out += [f"عنوان: {meta['chapter_title']}", f"رایگان: {'بله' if meta.get('chapter_free') else 'خیر'}", "---", ""]
    if parsed.intro:
        out += _body(parsed.intro.full_body, parsed.intro.summary_body, parsed.intro.questions, parsed.intro.flashcards)
    group = ""
    for section in parsed.sections:
        if section.group and section.group != group:
            out += [f"# {section.group}", ""]
            group = section.group
        out += [f"## {section.title} {{#{section.slug}}}", ""]
        out += _body(section.full_body, section.summary_body, section.questions, section.flashcards)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


def _items(queryset, node, to_parsed, archived=False):
    return [to_parsed(x) for x in queryset.filter(node=node, is_archived=archived).order_by("order", "id")]


def section_from_db(node: ContentNode, archived_items: bool = False) -> ParsedSection:
    """One section (or, for a chapter node, the chapter's introduction) as a parsed section."""
    is_chapter = node.kind == ContentNode.Kind.CHAPTER
    section = ParsedSection(slug="" if is_chapter else node.slug, title="" if is_chapter else node.title, line=0,
                            group="" if is_chapter else node.group)
    section.full_lines = node.full_body.strip().split("\n") if node.full_body.strip() else []
    section.summary_lines = node.summary_body.strip().split("\n") if node.summary_body.strip() else []
    section.questions = _items(Question.objects.prefetch_related("choices"), node, question_to_parsed, archived_items)
    section.flashcards = _items(Flashcard.objects.all(), node, flashcard_to_parsed, archived_items)
    return section


def chapter_from_db(chapter: ContentNode) -> ParsedChapter:
    chapter = ContentNode.objects.get(pk=chapter.pk)
    book = chapter.book()
    parsed = ParsedChapter()
    parsed.meta = {
        "book_slug": book.slug,
        "book_title": book.title,
        "majors": list(book.majors.order_by("order", "name").values_list("slug", flat=True)),
        "chapter_slug": chapter.slug,
        "chapter_number": chapter.position,
        "chapter_title": chapter.title,
        "chapter_free": chapter.is_free,
    }
    intro = section_from_db(chapter)
    parsed.intro = intro if (intro.full_body or intro.summary_body or intro.questions or intro.flashcards) else None
    parsed.sections = [section_from_db(s) for s in chapter.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False)]
    return parsed


def export_chapter(chapter: ContentNode) -> str:
    """The chapter's current, non-archived content as chapter.md text."""
    return write_chapter(chapter_from_db(chapter))


def media_paths(text: str) -> list[str]:
    return sorted({m.group(2) for m in _MEDIA_IMAGE.finditer(text)})


def chapter_bundle(chapter: ContentNode) -> tuple[str, bytes, str]:
    """(file name, data, content type): chapter.md, or a ZIP with an images/ folder when the chapter has images."""
    text = export_chapter(chapter)
    paths = media_paths(text)
    if not paths:
        return f"{chapter.slug}.md", text.encode("utf-8"), "text/markdown; charset=utf-8"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if default_storage.exists(path):
                with default_storage.open(path, "rb") as fh:
                    archive.writestr(f"images/{posixpath.basename(path)}", fh.read())
        text = _MEDIA_IMAGE.sub(lambda m: f"![{m.group(1)}](images/{posixpath.basename(m.group(2))})", text)
        archive.writestr("chapter.md", text)
    return f"{chapter.slug}.zip", buffer.getvalue(), "application/zip"


def book_bundle(book: ContentNode) -> bytes:
    """Every non-archived chapter of the book, each in its own folder, in one ZIP."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        chapters = book.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False)
        for i, chapter in enumerate(chapters, start=1):
            folder = f"{i:02d}-{chapter.slug}"
            name, data, _ = chapter_bundle(chapter)
            if name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    for entry in inner.namelist():
                        archive.writestr(f"{folder}/{entry}", inner.read(entry))
            else:
                archive.writestr(f"{folder}/chapter.md", data)
        if book.about.strip():
            archive.writestr("about.md", book.about)
    return buffer.getvalue()
