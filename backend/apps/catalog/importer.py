"""
Import one chapter from a Markdown file (or a ZIP with the Markdown file and an `images/` folder).

The format is documented in docs/content-format.md. In short:

    ---
    شناسه-کتاب: math-1
    کتاب: ریاضی عمومی ۱
    رشته‌ها: economics, biomedical-engineering
    شناسه-فصل: limits
    عنوان: حد و پیوستگی
    رایگان: بله
    ---

    ## مفهوم حد {#limit-idea}
    متن جزوه …

    :::خلاصه
    متن خلاصه …
    :::

    :::تست {#q-sin}
    …
    :::

Everything is matched by stable ids (slugs), so re-importing a corrected file updates content in place and
learners keep their progress. Items that disappear from the file are archived, never deleted.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
import zlib
import hashlib
from collections import Counter
from dataclasses import dataclass, field

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from apps.learning.models import Choice, ExamSource, Flashcard, Question, QuestionSource

from .models import ContentNode, Major
from .labels import find as find_label

MEDIA_PREFIX = "media:"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_MARKDOWN_BYTES = 2 * 1024 * 1024
MAX_ZIP_ENTRIES = 300
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024
_SVG_DANGER = re.compile(rb"<script|javascript:|<foreignobject|\son[a-z]+\s*=|<iframe|<embed|<object", re.IGNORECASE)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ARABIC_LETTERS = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})
_SLUG = re.compile(r"^[\w\-]+$", re.UNICODE)
_HEADING = re.compile(r"^##\s+(.+?)\s*(?:\{#([^}]+)\})?\s*$")
_GROUP = re.compile(r"^#\s+(.+?)\s*$")
_BLOCK_OPEN = re.compile(r"^:::\s*([^\s{](?:[^{]*[^\s{])?)\s*(?:\{#([^}]+)\})?\s*$")
_CHOICE = re.compile(r"^\s*-\s*\[( |x|X|✓)\]\s*(.*)$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_SOURCE = re.compile(r"^(.*?)\s*(1[34]\d\d)\s*(?:[،,]\s*(?:سؤال|سوال|شماره)\s*(\d+))?\s*$")

# Boxes in the notes («:::تعریف»): any label of the panel's «برچسب‌های متن» (apps/catalog/labels.py); kept in the text.


def _key(text: str) -> str:
    return text.translate(_ARABIC_LETTERS).replace("‌", "").replace(" ", "").replace("-", "").replace("_", "").lower()


META_KEYS = {
    _key(k): v
    for k, v in {
        "شناسه-کتاب": "book_slug", "book_id": "book_slug",
        "کتاب": "book_title", "book": "book_title",
        "قیمت-کتاب": "book_price", "book_price": "book_price",
        "رشته‌ها": "majors", "رشته": "majors", "majors": "majors",
        "شناسه-فصل": "chapter_slug", "chapter_id": "chapter_slug",
        "عنوان": "chapter_title", "title": "chapter_title",
        "فصل": "chapter_number", "chapter": "chapter_number",
        "رایگان": "chapter_free", "free": "chapter_free",
    }.items()
}

QUESTION_KEYS = {
    _key(k): v
    for k, v in {
        "صورت": "stem", "سؤال": "stem", "سوال": "stem",
        "توضیح": "explanation", "پاسخ تشریحی": "explanation",
        "راه‌حل سریع": "quick_solution", "راه حل سریع": "quick_solution",
        "زاویه‌ی دیگر": "alternative_view", "زاویه دیگر": "alternative_view",
        "منبع": "source", "سطح": "difficulty", "حوزه": "domain", "نوع": "kind",
        "زمان": "seconds", "فلش‌کارت": "flashcards", "رایگان": "free",
        "ترتیب گزینه‌ها": "fixed_order", "ترتیب گزینه ها": "fixed_order", "ترتیب": "fixed_order",
        "نقش": "role",
    }.items()
}

FLASHCARD_KEYS = {_key(k): v for k, v in {"عنوان": "title", "نکته": "point", "فرمول": "formula", "رایگان": "free"}.items()}

DIFFICULTY = {"آسان": "easy", "ساده": "easy", "متوسط": "medium", "سخت": "hard"}
DOMAIN = {"عمومی": "general", "عمومی رشته": "general", "تخصصی": "specialized"}
KIND = {"حفظی": "recall", "مفهومی": "concept", "محاسباتی": "calc", "تحلیلی": "analysis"}
YES = {"بله", "آره", "true", "yes", "1"}


@dataclass
class Issue:
    level: str  # "error" or "warning"
    message: str
    line: int | None = None

    def __str__(self):
        where = f"خط {self.line}: " if self.line else ""
        return f"{where}{self.message}"


@dataclass
class ParsedFlashcard:
    slug: str
    line: int
    title: str = ""
    point: str = ""
    formula: str = ""
    is_free: bool = False


@dataclass
class ParsedQuestion:
    slug: str
    line: int
    stem: str = ""
    explanation: str = ""
    quick_solution: str = ""
    alternative_view: str = ""
    difficulty: str = ""
    domain: str = ""
    kind: str = ""
    seconds: int | None = None
    is_free: bool = False
    is_original: bool = False
    fixed_order: bool = False
    is_extra: bool = False
    sources: list[tuple[str, int, int | None]] = field(default_factory=list)
    flashcard_slugs: list[str] = field(default_factory=list)
    choices: list[tuple[str, bool]] = field(default_factory=list)


@dataclass
class ParsedSection:
    slug: str
    title: str
    line: int
    group: str = ""
    full_lines: list[str] = field(default_factory=list)
    summary_lines: list[str] = field(default_factory=list)
    questions: list[ParsedQuestion] = field(default_factory=list)
    flashcards: list[ParsedFlashcard] = field(default_factory=list)

    @property
    def full_body(self):
        return "\n".join(self.full_lines).strip()

    @property
    def summary_body(self):
        return "\n".join(self.summary_lines).strip()


@dataclass
class ParsedChapter:
    meta: dict = field(default_factory=dict)
    intro: ParsedSection | None = None  # text and items before the first "##" heading
    sections: list[ParsedSection] = field(default_factory=list)
    images: dict[str, bytes] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    # Links from tests to flashcards that are not in this file: (test, flashcard, line); checked against the book.
    outside_cards: list = field(default_factory=list)

    def error(self, message, line=None):
        self.issues.append(Issue("error", message, line))

    def warn(self, message, line=None):
        self.issues.append(Issue("warning", message, line))

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]

    def all_sections(self):
        return ([self.intro] if self.intro else []) + self.sections


# --- Reading the upload --------------------------------------------------------------------------------------


def read_upload(filename: str, data: bytes, book: ContentNode | None = None) -> ParsedChapter:
    """Accept a .md file or a .zip containing one .md file and optional images/ folder.
    With `book`, the file may leave out the book lines; if it names another book, that is an error."""
    if filename.lower().endswith(".zip"):
        return _read_zip(data, book)
    if filename.lower().endswith(".md"):
        if len(data) > MAX_MARKDOWN_BYTES:
            chapter = ParsedChapter()
            chapter.error("فایل متن بیشتر از ۲ مگابایت است؛ فصل را کوچک‌تر کنید.")
            return chapter
        chapter = parse_chapter(data.decode("utf-8-sig", errors="replace"), book=book)
        _check_images(chapter)
        return chapter
    chapter = ParsedChapter()
    chapter.error("فقط فایل .md یا .zip پذیرفته می‌شود.")
    return chapter


def _read_zip(data: bytes, book: ContentNode | None = None) -> ParsedChapter:
    failed = ParsedChapter()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        infos = [i for i in archive.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
        if len(infos) > MAX_ZIP_ENTRIES:
            failed.error(f"تعداد فایل‌های داخل ZIP زیاد است (بیشتر از {MAX_ZIP_ENTRIES}).")
            return failed
        if sum(i.file_size for i in infos) > MAX_ZIP_TOTAL_BYTES:
            failed.error("حجم بازشده‌ی ZIP بیشتر از ۱۰۰ مگابایت است.")
            return failed
        markdown = [i for i in infos if i.filename.lower().endswith(".md")]
        if len(markdown) != 1:
            failed.error(f"داخل ZIP باید دقیقاً یک فایل .md باشد؛ {len(markdown)} فایل پیدا شد.")
            return failed
        if markdown[0].file_size > MAX_MARKDOWN_BYTES:
            failed.error("فایل متن بیشتر از ۲ مگابایت است؛ فصل را کوچک‌تر کنید.")
            return failed
        base = posixpath.dirname(markdown[0].filename)
        chapter = parse_chapter(archive.read(markdown[0]).decode("utf-8-sig", errors="replace"), book=book)
        for info in infos:
            name = info.filename
            if posixpath.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
                continue
            relative = posixpath.normpath(posixpath.relpath(name, base) if base else name)
            if info.file_size > MAX_IMAGE_BYTES:
                chapter.error(f"عکس «{relative}» بیشتر از ۵ مگابایت است.")
                continue
            content = archive.read(info)
            if relative.lower().endswith(".svg") and _SVG_DANGER.search(content):
                chapter.error(f"عکس «{relative}» کد اجرایی (اسکریپت) دارد و پذیرفته نمی‌شود.")
                continue
            chapter.images[relative] = content
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, OSError, ValueError):
        failed.error("فایل ZIP خراب است یا باز نمی‌شود.")
        return failed
    _check_images(chapter)
    return chapter


def _check_images(chapter: ParsedChapter):
    for section in chapter.all_sections():
        for line_no, text in _texts_with_lines(section):
            for match in _IMAGE.finditer(text):
                target = match.group(2)
                if target.startswith(MEDIA_PREFIX):
                    # An image already on this server (files exported from the panel, or images added in the panel).
                    stored = target[len(MEDIA_PREFIX) :]
                    if posixpath.normpath(stored) != stored or not stored.startswith("content/"):
                        chapter.error(f"آدرس عکس «{target}» معتبر نیست.", line_no)
                    elif not default_storage.exists(stored):
                        # Not a reason to block other edits: the picture just does not show until it is back
                        # (usually the media folder was not kept when the server was updated).
                        chapter.warn(f"فایل عکس «{target}» روی سرور نیست و نشان داده نمی‌شود؛ پوشه‌ی media را بررسی کنید.", line_no)
                    elif not match.group(1).strip():
                        chapter.warn(f"عکس «{target}» زیرنویس ندارد.", line_no)
                    continue
                if target.startswith(("http://", "https://")):
                    chapter.warn(f"عکس از اینترنت لود می‌شود ({target}); بهتر است داخل ZIP باشد.", line_no)
                    continue
                if posixpath.normpath(target) not in chapter.images:
                    chapter.error(f"عکس «{target}» داخل فایل ZIP پیدا نشد.", line_no)
                if not match.group(1).strip():
                    chapter.warn(f"عکس «{target}» زیرنویس ندارد.", line_no)


def _texts_with_lines(section: ParsedSection):
    yield section.line, section.full_body
    yield section.line, section.summary_body
    for q in section.questions:
        yield q.line, "\n".join([q.stem, q.explanation, q.quick_solution, q.alternative_view] + [c for c, _ in q.choices])
    for f in section.flashcards:
        yield f.line, f.point


# --- Parsing ------------------------------------------------------------------------------------------------


def parse_chapter(text: str, book: ContentNode | None = None) -> ParsedChapter:
    chapter = ParsedChapter()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").translate(_ARABIC_LETTERS).split("\n")

    start = _parse_front_matter(lines, chapter, book)
    if chapter.errors:
        return chapter

    current = ParsedSection(slug="", title="", line=start + 1)
    chapter.intro = current
    group = ""
    i = start
    while i < len(lines):
        line_no = i + 1
        line = lines[i]
        grp = _GROUP.match(line)
        if grp:
            # "# Title" starts a group: a heading shown above the following sections in the book's list.
            group = grp.group(1).strip()
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            title, slug = heading.group(1).strip(), (heading.group(2) or "").strip()
            auto = f"{chapter.meta.get('chapter_slug', 'ch')}-s{len(chapter.sections) + 1}"
            current = ParsedSection(slug=slug or auto, title=title, line=line_no, group=group)
            chapter.sections.append(current)
            i += 1
            continue
        block = _BLOCK_OPEN.match(line)
        if block:
            kind, slug = block.group(1), (block.group(2) or "").strip()
            end = _find_block_end(lines, i + 1)
            if end is None:
                chapter.error(f"بلوک «{kind}» بسته نشده است (::: پایانی ندارد).", line_no)
                return chapter
            body = lines[i + 1 : end]
            inner = next((i + 1 + k for k, b in enumerate(body) if _BLOCK_OPEN.match(b)), None)
            if inner is not None:
                chapter.error(
                    f"بلوک «{kind}» بسته نشده است؛ قبل از شروع بلوک بعدی در خط {inner + 1} یک خط ::: بگذارید "
                    "(بلوک‌ها نمی‌توانند داخل هم باشند).",
                    line_no,
                )
                return chapter
            if kind in ("خلاصه", "چکیده"):
                current.summary_lines.extend(body)
            elif kind == "تست":
                number = sum(len(s.questions) for s in chapter.all_sections()) + 1
                current.questions.append(_parse_question(body, slug or f"{chapter.meta.get('chapter_slug', 'ch')}-q{number}", line_no, chapter))
                if not slug:
                    chapter.warn("تست شناسه ندارد ({#...})؛ اگر ترتیب تست‌ها عوض شود، آمار آن جابه‌جا می‌شود.", line_no)
            elif kind == "فلش‌کارت":
                number = sum(len(s.flashcards) for s in chapter.all_sections()) + 1
                current.flashcards.append(_parse_flashcard(body, slug or f"{chapter.meta.get('chapter_slug', 'ch')}-f{number}", line_no, chapter))
            elif find_label(kind):
                current.full_lines.extend(lines[i : end + 1])
            else:
                chapter.error(f"برچسب «{kind}» شناخته نشد. برچسب تازه را اول در پنل › «برچسب‌های متن» بسازید.", line_no)
            i = end + 1
            continue
        current.full_lines.append(line)
        i += 1

    if chapter.intro and not (chapter.intro.full_body or chapter.intro.summary_body or chapter.intro.questions or chapter.intro.flashcards):
        chapter.intro = None
    elif chapter.intro and chapter.intro.full_body:
        chapter.warn("متن قبل از اولین تیتر «##» به‌عنوان مقدمه‌ی فصل ذخیره می‌شود.", chapter.intro.line)

    _validate(chapter)
    return chapter


def _find_block_end(lines, start):
    for j in range(start, len(lines)):
        if lines[j].strip() == ":::":
            return j
    return None


def _parse_front_matter(lines, chapter, book: ContentNode | None = None) -> int:
    if not lines or lines[0].strip() != "---":
        chapter.error("فایل باید با بخش مشخصات بین دو خط --- شروع شود.", 1)
        return 0
    for i in range(1, len(lines)):
        line = lines[i].strip()
        if line == "---":
            break
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            chapter.error(f"خط مشخصات نامعتبر است: «{line}»", i + 1)
            continue
        raw_key, value = line.split(":", 1)
        key = META_KEYS.get(_key(raw_key))
        if key is None:
            chapter.warn(f"کلید «{raw_key.strip()}» شناخته نشد و نادیده گرفته شد.", i + 1)
            continue
        chapter.meta[key] = value.strip()
    else:
        chapter.error("بخش مشخصات با --- بسته نشده است.", 1)
        return len(lines)

    meta = chapter.meta
    if book is not None:
        if meta.get("book_slug") and meta["book_slug"] != book.slug:
            chapter.error(f"این فایل مال کتاب «{meta['book_slug']}» است، نه «{book.slug}».", 1)
        meta.setdefault("book_slug", book.slug)
        meta.setdefault("book_title", book.title)
    for key, label in [("book_slug", "شناسه-کتاب"), ("book_title", "کتاب"), ("chapter_slug", "شناسه-فصل"), ("chapter_title", "عنوان")]:
        if not meta.get(key):
            chapter.error(f"«{label}» در مشخصات فایل نیامده است.", 1)
    for key in ("book_slug", "chapter_slug"):
        if meta.get(key) and not _SLUG.match(meta[key]):
            chapter.error(f"شناسه «{meta[key]}» فقط می‌تواند حرف، عدد، - و _ داشته باشد.", 1)
    meta["majors"] = [m.strip() for m in re.split(r"[,،]", meta.get("majors", "")) if m.strip()]
    if meta.get("book_price"):
        price = meta["book_price"].translate(_DIGITS).replace(",", "").replace("٬", "")
        if price.isdigit():
            meta["book_price"] = int(price)
        else:
            chapter.error("قیمت کتاب باید عدد (تومان) باشد.", 1)
    meta["chapter_free"] = meta.get("chapter_free", "").strip().lower() in YES
    number = str(meta.get("chapter_number", "")).translate(_DIGITS).strip()
    meta["chapter_number"] = int(number) if number.isdigit() else None
    return i + 1


SINGLE_LINE_FIELDS = {"source", "difficulty", "domain", "kind", "seconds", "free", "flashcards", "title", "formula", "fixed_order", "role"}
FIXED = YES | {"ثابت"}


def _split_fields(body, keys):
    """Turn 'key: value' lines into a dict of lists. Text fields may continue on the following lines;
    single-line fields (level, source, …) never swallow the lines after them."""
    fields, current = {}, None
    loose = []
    for offset, line in enumerate(body):
        if ":" in line and not _CHOICE.match(line):
            raw_key, value = line.split(":", 1)
            mapped = keys.get(_key(raw_key))
            if mapped:
                fields.setdefault(mapped, []).append([value.strip()])
                current = None if mapped in SINGLE_LINE_FIELDS else mapped
                continue
        if current is None:
            loose.append((offset, line))
        else:
            fields[current][-1].append(line)
    return fields, loose


def _join(parts):
    return "\n".join(parts).strip()


def _parse_question(body, slug, line_no, chapter) -> ParsedQuestion:
    q = ParsedQuestion(slug=slug, line=line_no)
    stem_lines, choice_seen, rest = [], False, []
    for offset, line in enumerate(body):
        m = _CHOICE.match(line)
        if m:
            choice_seen = True
            q.choices.append((m.group(2).strip(), m.group(1) != " "))
        elif not choice_seen:
            stem_lines.append(line)
        else:
            rest.append(line)

    head_fields, loose = _split_fields(stem_lines, QUESTION_KEYS)
    tail_fields, tail_loose = _split_fields(rest, QUESTION_KEYS)
    fields = {k: head_fields.get(k, []) + tail_fields.get(k, []) for k in set(head_fields) | set(tail_fields)}

    q.stem = _join([l for _, l in loose]) if "stem" not in fields else _join(fields["stem"][0])
    if "stem" in fields and loose:
        extra = _join([l for _, l in loose])
        if extra:
            q.stem = _join([extra, q.stem])
    if [l for _, l in tail_loose if l.strip()]:
        chapter.warn("متنی بعد از گزینه‌ها بدون کلید آمده و نادیده گرفته شد.", line_no)

    for name in ("explanation", "quick_solution", "alternative_view"):
        if name in fields:
            setattr(q, name, _join(fields[name][-1]))

    difficulty = _join(fields.get("difficulty", [[""]])[-1])
    q.difficulty = DIFFICULTY.get(difficulty, "")
    if not difficulty:
        chapter.error(f"تست {slug}: «سطح» لازم است (آسان، متوسط یا سخت).", line_no)
    elif not q.difficulty:
        chapter.error(f"تست {slug}: سطح «{difficulty}» معتبر نیست.", line_no)

    domain = _join(fields.get("domain", [[""]])[-1])
    if domain:
        q.domain = DOMAIN.get(domain, "")
        if not q.domain:
            chapter.error(f"تست {slug}: حوزه «{domain}» معتبر نیست (عمومی یا تخصصی).", line_no)
    kind = _join(fields.get("kind", [[""]])[-1])
    if kind:
        q.kind = KIND.get(kind, "")
        if not q.kind:
            chapter.error(f"تست {slug}: نوع «{kind}» معتبر نیست (حفظی، مفهومی، محاسباتی، تحلیلی).", line_no)
    seconds = _join(fields.get("seconds", [[""]])[-1]).translate(_DIGITS)
    if seconds:
        digits = re.sub(r"\D", "", seconds)
        q.seconds = int(digits) if digits else None
    q.is_free = _join(fields.get("free", [[""]])[-1]).lower() in YES
    role = _join(fields.get("role", [[""]])[-1]).strip()
    q.is_extra = role in {"تکمیلی", "مازاد", "بانک", "extra"}
    if role and not q.is_extra and role not in {"پایه", "اصلی", "core"}:
        chapter.error(f"تست {slug}: «نقش» فقط «پایه» یا «تکمیلی» است.", line_no)
    order = _join(fields.get("fixed_order", [[""]])[-1]).lower()
    q.fixed_order = order in FIXED
    if order and not q.fixed_order and order not in {"تصادفی", "خیر", "نه", "no", "false", "0"}:
        chapter.error(f"تست {slug}: «ترتیب گزینه‌ها» فقط «ثابت» یا «تصادفی» است.", line_no)

    for parts in fields.get("source", []):
        value = _join(parts).translate(_DIGITS)
        if value in {"تألیفی", "تالیفی"}:
            q.is_original = True
            continue
        m = _SOURCE.match(value)
        if not m and value.startswith("کتاب"):
            # A textbook («کتاب ایساک مارون»): no year; stored as 0 and never shown.
            book_source = re.match(r"^(.*?)\s*(?:[،,]\s*(?:سؤال|سوال|شماره|تمرین)\s*(\d+))?\s*$", value)
            q.sources.append((book_source.group(1).strip(" ،,"), 0, int(book_source.group(2)) if book_source.group(2) else None))
            continue
        if not m or not m.group(1).strip():
            chapter.error(f"تست {slug}: منبع «{value}» قابل خواندن نیست. مثال: «کنکور ارشد ریاضی ۱۴۰۱، سؤال ۲۳»، «کتاب ایساک مارون» یا «تألیفی».", line_no)
            continue
        q.sources.append((m.group(1).strip(" ،,"), int(m.group(2)), int(m.group(3)) if m.group(3) else None))
    if not q.sources and not q.is_original:
        chapter.error(f"تست {slug}: «منبع» لازم است (نام کنکور و سال، یا «تألیفی»).", line_no)

    for parts in fields.get("flashcards", []):
        q.flashcard_slugs.extend(s.strip() for s in re.split(r"[,،]", _join(parts)) if s.strip())

    if not q.stem:
        chapter.error(f"تست {slug}: صورت سؤال خالی است.", line_no)
    if not 2 <= len(q.choices) <= 6:
        chapter.error(f"تست {slug}: باید ۲ تا ۶ گزینه داشته باشد ({len(q.choices)} گزینه).", line_no)
    correct = sum(1 for _, ok in q.choices if ok)
    if correct != 1:
        chapter.error(f"تست {slug}: باید دقیقاً یک گزینه‌ی درست [x] داشته باشد ({correct} گزینه).", line_no)
    if not q.explanation:
        chapter.error(f"تست {slug}: «توضیح» (پاسخ تشریحی) لازم است.", line_no)
    from apps.learning.order import names_choice_number, refers_to_choices

    if not q.fixed_order and not refers_to_choices(t for t, _ in q.choices):
        for text in (q.explanation, q.quick_solution, q.alternative_view):
            named = names_choice_number(text)
            if named:
                chapter.warn(
                    f"تست {slug}: توضیح از «{named}» نام برده، ولی جای گزینه‌ها در اپ جابه‌جا می‌شود. "
                    "متن گزینه‌ی درست را بنویسید، یا «ترتیب گزینه‌ها: ثابت» بگذارید.",
                    line_no,
                )
                break
    return q


def _parse_flashcard(body, slug, line_no, chapter) -> ParsedFlashcard:
    f = ParsedFlashcard(slug=slug, line=line_no)
    fields, loose = _split_fields(body, FLASHCARD_KEYS)
    f.title = _join(fields.get("title", [[""]])[-1])
    f.point = _join(fields.get("point", [[""]])[-1]) or _join([l for _, l in loose])
    f.formula = _join(fields.get("formula", [[""]])[-1])
    f.is_free = _join(fields.get("free", [[""]])[-1]).lower() in YES
    if not f.title:
        chapter.error(f"فلش‌کارت {slug}: «عنوان» لازم است.", line_no)
    if not f.point:
        chapter.error(f"فلش‌کارت {slug}: «نکته» لازم است.", line_no)
    return f


def _validate(chapter: ParsedChapter):
    # Names of boxes («:::مثال {#sin-hamarz}») are unique in the chapter; links «[[#name]]» are checked in the panel.
    from .numbering import BOX, EQUATION

    names: dict[str, str] = {}
    for s in chapter.all_sections():
        found = [(m.group(2) or "").strip() for m in BOX.finditer(s.full_body or "")]
        found += [(m.group(1) or "").strip() for m in EQUATION.finditer(s.full_body or "")]  # «$$…$$ {#name}»
        for name in found:
            if not name:
                continue
            if not _SLUG.match(name):
                chapter.error(f"نام کادر یا فرمول «{name}» فقط می‌تواند حرف، عدد، - و _ داشته باشد.", s.line)
            elif name in names:
                chapter.error(f"نام «{name}» دو بار آمده (در «{names[name]}» و «{s.title or 'مقدمه'}»).", s.line)
            names[name] = s.title or "مقدمه"
    seen = {}
    for kind, items in (
        ("بخش", [(s.slug, s.line) for s in chapter.sections]),
        ("تست", [(q.slug, q.line) for s in chapter.all_sections() for q in s.questions]),
        ("فلش‌کارت", [(f.slug, f.line) for s in chapter.all_sections() for f in s.flashcards]),
    ):
        seen.clear()
        for slug, line in items:
            if not _SLUG.match(slug):
                chapter.error(f"شناسه‌ی {kind} «{slug}» فقط می‌تواند حرف، عدد، - و _ داشته باشد.", line)
            if slug in seen:
                chapter.error(f"شناسه‌ی {kind} «{slug}» تکراری است (اولین بار خط {seen[slug]}).", line)
            seen.setdefault(slug, line)

    if not chapter.sections:
        chapter.error("فصل هیچ بخشی (تیتر «## ...») ندارد.")

    flashcards = {f.slug for s in chapter.all_sections() for f in s.flashcards}
    questions = [q for s in chapter.all_sections() for q in s.questions]
    for q in questions:
        for ref in q.flashcard_slugs:
            if ref not in flashcards:
                # Another chapter of the same book may hold it (check_against_db).
                chapter.outside_cards.append((q.slug, ref, q.line))

    stems = Counter(re.sub(r"\s+", " ", q.stem) for q in questions)
    for stem, n in stems.items():
        if n > 1:
            chapter.warn(f"صورت سؤال تکراری ({n} بار): «{stem[:50]}…»")
    if len(questions) >= 8:
        positions = Counter(next(i for i, (_, ok) in enumerate(q.choices) if ok) for q in questions if sum(ok for _, ok in q.choices) == 1)
        if positions and positions.most_common(1)[0][1] > len(questions) / 2:
            chapter.warn("بیش از نیمی از جواب‌های درست روی یک گزینه است؛ ترتیب گزینه‌ها را متنوع کنید.")
    for section in chapter.sections:
        if not section.full_body and not section.summary_body:
            chapter.warn(f"بخش «{section.title}» متنی ندارد.", section.line)
    for section in chapter.all_sections():
        for phrase in missing_jump_phrases(section.full_body, section.summary_body):
            chapter.warn(f"بخش «{section.title or 'مقدمه'}»: عبارت «{phrase}» در خلاصه هست ولی در جزوه پیدا نشد؛ پرش به جزوه کار نمی‌کند.", section.line)


_JUMP = re.compile(r"\[\[(?!#)(.+?)\]\]")  # «[[#name]]» is a link to a numbered box, not a phrase


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", text or ""))


def missing_jump_phrases(full_body: str, summary_body: str) -> list[str]:
    """[[phrases]] of the review card that the app cannot find in the notes."""
    plain = _plain(full_body)
    return [p for p in _JUMP.findall(summary_body or "") if _plain(p).strip() not in plain]


# --- Checks that need the database ---------------------------------------------------------------------------


def check_against_db(chapter: ParsedChapter):
    if chapter.errors:
        return
    majors = chapter.meta.get("majors", [])
    known = set(Major.objects.filter(slug__in=majors).values_list("slug", flat=True))
    for slug in majors:
        if slug not in known:
            chapter.error(f"رشته‌ای با شناسه «{slug}» وجود ندارد. اول آن را در پنل بسازید.", 1)
    book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, slug=chapter.meta["book_slug"], depth=1).first()
    if book is None and not majors:
        chapter.warn("کتاب جدید است ولی هیچ رشته‌ای برایش تعیین نشده؛ در اپ نمایش داده نمی‌شود.", 1)
    if chapter.outside_cards:
        found = set(outside_flashcards(book, chapter, {ref for _, ref, _ in chapter.outside_cards}))
        for test, ref, line in chapter.outside_cards:
            if ref not in found:
                chapter.error(f"تست {test}: فلش‌کارت «{ref}» نه در این فایل هست نه در فصل‌های دیگر این کتاب.", line)


def outside_flashcards(book, chapter: ParsedChapter, slugs) -> dict:
    """Flashcards of the book's other chapters (not archived) with these ids: a test may link to any card of its book."""
    if book is None or not slugs:
        return {}
    own = ContentNode.objects.filter(path__startswith=book.path, depth=2, slug=chapter.meta.get("chapter_slug")).first()
    cards = Flashcard.objects.filter(node__path__startswith=book.path, is_archived=False, slug__in=list(slugs))
    if own is not None:
        cards = cards.exclude(node__path__startswith=own.path)
    return {f.slug: f for f in cards}


# --- Applying -----------------------------------------------------------------------------------------------


@dataclass
class ImportResult:
    book: ContentNode
    chapter: ContentNode
    created: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    archived: Counter = field(default_factory=Counter)

    def summary(self) -> str:
        parts = []
        for label, key in (("بخش", "section"), ("تست", "question"), ("فلش‌کارت", "flashcard"), ("عکس", "image")):
            bits = []
            if self.created[key]:
                bits.append(f"{self.created[key]} جدید")
            if self.updated[key]:
                bits.append(f"{self.updated[key]} به‌روز")
            if self.archived[key]:
                bits.append(f"{self.archived[key]} بایگانی")
            if bits:
                parts.append(f"{label}: " + "، ".join(bits))
        return " · ".join(parts) or "تغییری نبود"


@transaction.atomic
def apply_chapter(chapter: ParsedChapter, publish: bool = False) -> ImportResult:
    """Write a validated chapter. Sections, questions and flashcards are matched by id across the whole book,
    so moving them between sections or chapters keeps the same rows (and learners' answers)."""
    if chapter.errors:
        raise ValueError("Chapter has errors; fix them before importing.")
    meta = chapter.meta
    image_paths = _store_images(chapter, meta["book_slug"], meta["chapter_slug"])

    book = ContentNode.objects.select_for_update().filter(kind=ContentNode.Kind.BOOK, slug=meta["book_slug"], depth=1).first()
    if book is None:
        book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug=meta["book_slug"], title=meta["book_title"])
    book.title = meta["book_title"]
    if isinstance(meta.get("book_price"), int):
        book.price = meta["book_price"]
    book.is_archived = False
    if publish:
        book.is_published = True
    book.save()
    if meta["majors"]:
        book.majors.add(*Major.objects.filter(slug__in=meta["majors"]))

    chapter_node = _place(book, ContentNode.Kind.CHAPTER, meta["chapter_slug"], meta["chapter_title"])
    chapter_node.is_free = meta["chapter_free"]
    chapter_node.position = meta["chapter_number"]
    chapter_node.is_archived = False
    chapter_node.full_body = _rewrite_images(chapter.intro.full_body, image_paths) if chapter.intro else ""
    chapter_node.summary_body = _rewrite_images(chapter.intro.summary_body, image_paths) if chapter.intro else ""
    if publish:
        chapter_node.is_published = True
    chapter_node.save()
    _order_chapters(book)
    chapter_node.refresh_from_db()

    result = ImportResult(book=book, chapter=chapter_node)
    result.created["image"] = len(image_paths)

    keep_sections, section_ids = set(), []
    for parsed in chapter.sections:
        existed = ContentNode.objects.filter(path__startswith=book.path, kind=ContentNode.Kind.SECTION, slug=parsed.slug).exists()
        node = _place(chapter_node, ContentNode.Kind.SECTION, parsed.slug, parsed.title, search_root=book)
        node.full_body = _rewrite_images(parsed.full_body, image_paths)
        node.summary_body = _rewrite_images(parsed.summary_body, image_paths)
        node.group = parsed.group
        node.is_archived = False
        if publish:
            node.is_published = True
        node.save()
        (result.updated if existed else result.created)["section"] += 1
        keep_sections.add(node.pk)
        section_ids.append(node.pk)
    # Sections follow the order in the file (archived ones stay, at the end).
    for pk in section_ids:
        ContentNode.objects.get(pk=pk).move(ContentNode.objects.get(pk=chapter_node.pk), "last-child")
    chapter_node.refresh_from_db()
    for stale in chapter_node.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False).exclude(pk__in=keep_sections):
        stale.is_archived = True
        stale.save(update_fields=["is_archived"])
        result.archived["section"] += 1

    targets = ([(chapter_node, chapter.intro)] if chapter.intro else []) + [
        (ContentNode.objects.get(pk=pk), parsed) for pk, parsed in zip(section_ids, chapter.sections)
    ]
    scope_nodes = [chapter_node.pk, *chapter_node.get_descendants().values_list("pk", flat=True)]
    in_book = {"node__path__startswith": book.path}

    flashcard_by_slug, kept_flashcards = {}, set()
    for node, parsed in targets:
        for order, f in enumerate(parsed.flashcards, start=1):
            obj = Flashcard.objects.filter(slug=f.slug, **in_book).first()
            created = obj is None
            obj = obj or Flashcard(slug=f.slug)
            obj.node = node
            obj.title, obj.point, obj.formula = f.title, _rewrite_images(f.point, image_paths), f.formula
            obj.is_free, obj.is_archived, obj.order = f.is_free, False, order
            obj.save()
            (result.created if created else result.updated)["flashcard"] += 1
            flashcard_by_slug[f.slug] = obj
            kept_flashcards.add(obj.pk)
    result.archived["flashcard"] += (
        Flashcard.objects.filter(node_id__in=scope_nodes, is_archived=False).exclude(pk__in=kept_flashcards).update(is_archived=True)
    )

    kept_questions = set()
    for node, parsed in targets:
        for order, q in enumerate(parsed.questions, start=1):
            obj = Question.objects.filter(slug=q.slug, **in_book).first()
            created = obj is None
            obj = obj or Question(slug=q.slug)
            obj.node = node
            obj.stem = _rewrite_images(q.stem, image_paths)
            obj.explanation = _rewrite_images(q.explanation, image_paths)
            obj.quick_solution = _rewrite_images(q.quick_solution, image_paths)
            obj.alternative_view = _rewrite_images(q.alternative_view, image_paths)
            obj.difficulty, obj.domain, obj.kind = q.difficulty, q.domain, q.kind
            obj.estimated_seconds, obj.is_original, obj.is_free, obj.is_archived = q.seconds, q.is_original, q.is_free, False
            obj.fixed_order = q.fixed_order
            obj.is_extra = q.is_extra
            obj.order = order
            obj.save()
            (result.created if created else result.updated)["question"] += 1
            kept_questions.add(obj.pk)
            # A choice keeps its id while its text stays the same (moved or not), so a practice page already open still
            # means the same choice; a choice whose text changed is a new choice. Running exams keep their own copy
            # anyway (ExamAttempt.snapshot).
            old = list(obj.choices.order_by("order", "id"))
            old_key = [(c.text, c.is_correct) for c in old]  # before the loop below changes these rows
            unused = {c.id: c for c in old}
            for i, (text, ok) in enumerate(q.choices):
                text = _rewrite_images(text, image_paths)
                same = next((c for c in old if c.id in unused and c.text == text), None)
                if same:
                    del unused[same.id]
                    if (same.is_correct, same.order) != (ok, i):
                        same.is_correct, same.order = ok, i
                        same.save(update_fields=["is_correct", "order"])
                else:
                    Choice.objects.create(question=obj, text=text, is_correct=ok, order=i)
            Choice.objects.filter(pk__in=list(unused)).delete()
            if not created:
                _note_key_change(obj, old_key, [(_rewrite_images(t, image_paths), ok) for t, ok in q.choices])
            QuestionSource.objects.filter(question=obj).delete()
            for name, year, number in q.sources:
                source, _ = ExamSource.objects.get_or_create(name=name, year=year, group="", booklet="")
                QuestionSource.objects.create(question=obj, source=source, number=number)
            missing = [s for s in q.flashcard_slugs if s not in flashcard_by_slug]
            if missing:
                flashcard_by_slug.update(outside_flashcards(book, chapter, missing))
            obj.flashcards.set([flashcard_by_slug[s] for s in q.flashcard_slugs if s in flashcard_by_slug])
    result.archived["question"] += (
        Question.objects.filter(node_id__in=scope_nodes, is_archived=False).exclude(pk__in=kept_questions).update(is_archived=True)
    )
    return result


def _short(text: str, limit=60) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _note_key_change(question, old_choices, new_choices):
    """«اصلاح‌شده»: the right answer moved to another choice (a choice that stayed, now right or now wrong).
    A reworded right choice is a wording fix, not a change of answer."""
    old = dict(old_choices)
    new = dict(new_choices)
    moved = any(text in new and new[text] != ok for text, ok in old.items() if ok) or any(
        text in old and not old[text] for text, ok in new.items() if ok
    )
    if not moved:
        return
    before = next((t for t, ok in old_choices if ok), "")
    after = next((t for t, ok in new_choices if ok), "")
    question.key_changed_at = timezone.now()
    question.key_change_note = f"پاسخ درست از «{_short(before)}» به «{_short(after)}» تغییر کرد."[:400]
    question.save(update_fields=["key_changed_at", "key_change_note"])


def _place(parent: ContentNode, kind, slug, title, search_root: ContentNode | None = None) -> ContentNode:
    """Find the node with this id (under search_root, default parent) and make sure it sits under parent."""
    root = search_root or parent
    node = ContentNode.objects.filter(path__startswith=root.path, depth__gt=root.depth, kind=kind, slug=slug).first()
    parent = ContentNode.objects.get(pk=parent.pk)
    if node is None:
        node = parent.add_child(kind=kind, slug=slug, title=title)
    elif not node.path.startswith(parent.path) or node.depth != parent.depth + 1:
        node.move(parent, "last-child")
        node = ContentNode.objects.get(pk=node.pk)
    node.title = title
    return node


def _order_chapters(book: ContentNode):
    chapters = list(ContentNode.objects.get(pk=book.pk).get_children())
    wanted = sorted(chapters, key=lambda c: (c.position is None, c.position or 0, c.path))
    if [c.pk for c in wanted] == [c.pk for c in chapters]:
        return
    for chapter in wanted:
        ContentNode.objects.get(pk=chapter.pk).move(ContentNode.objects.get(pk=book.pk), "last-child")


def _store_images(chapter: ParsedChapter, book_slug, chapter_slug) -> dict[str, str]:
    """Content-addressed names: unguessable, no collisions, and safe to write before the database commits."""
    paths = {}
    for name, data in chapter.images.items():
        digest = hashlib.sha256(data).hexdigest()[:24]
        path = f"content/{book_slug}/{chapter_slug}/{digest}{posixpath.splitext(name)[1].lower()}"
        if not default_storage.exists(path):
            path = default_storage.save(path, ContentFile(data))
        paths[posixpath.normpath(name)] = path
    return paths


def _rewrite_images(text: str, image_paths: dict[str, str]) -> str:
    def replace(match):
        target = posixpath.normpath(match.group(2))
        if target in image_paths:
            return f"![{match.group(1)}]({MEDIA_PREFIX}{image_paths[target]})"
        return match.group(0)

    return _IMAGE.sub(replace, text) if text else text


def import_file(filename: str, data: bytes, publish: bool = False, dry_run: bool = False, book: ContentNode | None = None):
    """Parse, validate and (unless dry_run or invalid) apply. Returns (parsed chapter, result or None)."""
    chapter = read_upload(filename, data, book)
    check_against_db(chapter)
    if chapter.errors or dry_run:
        return chapter, None
    return chapter, apply_chapter(chapter, publish=publish)
