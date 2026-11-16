"""
Editing a chapter from the panel.

Every change goes the same way as a file upload, so the panel follows exactly the same rules:

    database → parsed chapter → (the change) → chapter.md text → parse again (all file checks) → apply_chapter

Items keep their ids (slugs), so learners' answers, notes and progress stay attached. Removing an item archives it.
After each change a copy of the whole chapter is kept as a version (ChapterRevision).
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.learning.models import Flashcard, Question

from .exporter import (
    chapter_from_db,
    export_chapter,
    flashcard_to_parsed,
    question_to_parsed,
    section_from_db,
    write_chapter,
)
from .importer import (
    DIFFICULTY,
    DOMAIN,
    FLASHCARD_KEYS,
    KIND,
    ParsedChapter,
    ParsedFlashcard,
    ParsedQuestion,
    ParsedSection,
    _SLUG,
    _check_images,
    _parse_flashcard,
    _parse_question,
    apply_chapter,
    check_against_db,
    parse_chapter,
)
from .models import ChapterRevision, ContentNode

COALESCE_WINDOW = timedelta(minutes=10)
_BAD_BODY_LINE = re.compile(r"^(#{1,2}\s|:::\s*(خلاصه|چکیده|تست|فلش‌کارت)\b)")


class EditError(Exception):
    def __init__(self, messages):
        super().__init__("; ".join(messages) if isinstance(messages, list) else messages)
        self.messages = messages if isinstance(messages, list) else [messages]


class Conflict(EditError):
    pass


def version_of(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# --- Loading and saving -------------------------------------------------------------------------------------


def load(chapter: ContentNode) -> ParsedChapter:
    return chapter_from_db(chapter)


def record_revision(chapter: ContentNode, user=None, source=ChapterRevision.Source.PANEL, note: str = "") -> ChapterRevision:
    """Keep a copy of the chapter as it is now. Quick panel edits by one person within a few minutes share one copy."""
    text = export_chapter(chapter)
    last = chapter.revisions.order_by("-updated_at", "-id").first()
    if last and last.text == text:
        return last
    user_id = getattr(user, "pk", None)
    if (
        last
        and source == ChapterRevision.Source.PANEL
        and last.source == source
        and last.user_id == user_id
        and timezone.now() - last.updated_at < COALESCE_WINDOW
        and chapter.revisions.count() > 1
        # A version that a learner's copy points to keeps its text for good (apps.guard).
        and not last.copies.exists()
    ):
        notes = [n for n in last.note.split("، ") if n]
        if note and note not in notes:
            notes.append(note)
        last.text, last.note = text, "، ".join(notes)[:300]
        last.save(update_fields=["text", "note", "updated_at"])
        return last
    return ChapterRevision.objects.create(chapter=chapter, text=text, source=source, note=note[:300], user=user if user_id else None)


def ensure_baseline(chapter: ContentNode, user=None):
    """Before the first change, keep the chapter as it was (chapters imported before versions existed)."""
    if not chapter.revisions.exists():
        ChapterRevision.objects.create(
            chapter=chapter, text=export_chapter(chapter), source=ChapterRevision.Source.FILE, note="نسخه‌ی پیش از اولین ویرایش در پنل"
        )


def check_text(text: str, book: ContentNode, chapter: ContentNode | None = None) -> ParsedChapter:
    """All file checks, plus: a chapter edited in place must keep its book and chapter id."""
    parsed = parse_chapter(text, book=book)
    _check_images(parsed)
    if not parsed.errors and chapter is not None and parsed.meta.get("chapter_slug") != chapter.slug:
        parsed.error(f"شناسه‌ی فصل باید «{chapter.slug}» بماند؛ برای فصل تازه از «افزودن فصل از فایل» استفاده کنید.", 1)
    check_against_db(parsed)
    if not parsed.errors:
        _check_ids_in_other_chapters(parsed, book, chapter)
    return parsed


def _check_ids_in_other_chapters(parsed: ParsedChapter, book: ContentNode, chapter: ContentNode | None):
    """An id that belongs to another chapter would move that item here. That is allowed from a file (shown in the
    preview), but never by accident from the panel; save() turns these warnings into errors."""
    own = chapter.path if chapter else None
    for model, label, items in (
        (Question, "تست", [q.slug for s in parsed.all_sections() for q in s.questions]),
        (Flashcard, "فلش‌کارت", [f.slug for s in parsed.all_sections() for f in s.flashcards]),
    ):
        for obj in model.objects.filter(node__path__startswith=book.path, slug__in=items).select_related("node"):
            if own is None or not obj.node.path.startswith(own):
                parsed.warn(f"{label} «{obj.slug}» الان در فصل دیگری است و به این فصل منتقل می‌شود.")
    sections = [s.slug for s in parsed.sections]
    for node in ContentNode.objects.filter(path__startswith=book.path, kind=ContentNode.Kind.SECTION, slug__in=sections):
        if own is None or not node.path.startswith(own):
            parsed.warn(f"بخش «{node.slug}» الان در فصل دیگری است و به این فصل منتقل می‌شود.")


@transaction.atomic
def save(chapter: ContentNode, parsed: ParsedChapter, *, user=None, note: str = "", expected_version: str | None = None,
         source=ChapterRevision.Source.PANEL, allow_moves: bool = False):
    """Validate the edited chapter like a file and write it. Returns (import result, new version)."""
    chapter = ContentNode.objects.select_for_update().get(pk=chapter.pk)
    book = chapter.book()
    if expected_version and version_of(export_chapter(chapter)) != expected_version:
        raise Conflict("این فصل در این فاصله جای دیگری تغییر کرده است؛ صفحه را تازه کنید و دوباره انجام دهید.")
    text = write_chapter(parsed)
    checked = check_text(text, book, chapter)
    if not allow_moves:
        moves = [str(w) for w in checked.warnings if "منتقل می‌شود" in str(w)]
        if moves:
            raise EditError([m.replace("و به این فصل منتقل می‌شود", "؛ شناسه‌ی دیگری انتخاب کنید") for m in moves])
    errors = [str(e) for e in checked.errors]
    errors += _structure_errors(parsed, checked)
    if errors:
        raise EditError(errors)
    ensure_baseline(chapter, user)
    before = {s.slug for s in chapter.get_children().filter(kind=ContentNode.Kind.SECTION)}
    result = apply_chapter(checked)
    # Sections made in the panel follow the chapter: visible if the chapter is published.
    new = chapter.get_children().filter(kind=ContentNode.Kind.SECTION).exclude(slug__in=before)
    new.update(is_published=ContentNode.objects.get(pk=chapter.pk).is_published)
    record_revision(chapter, user=user, source=source, note=note)
    return result, version_of(export_chapter(chapter)), [str(w) for w in checked.warnings]


def _structure_errors(intended: ParsedChapter, checked: ParsedChapter) -> list[str]:
    """Text typed into a field must not change the chapter's structure (e.g. a '## ' line starts a new section)."""
    if [s.slug for s in intended.sections] == [s.slug for s in checked.sections] and all(
        len(a.questions) == len(b.questions) and len(a.flashcards) == len(b.flashcards)
        for a, b in zip(intended.sections, checked.sections)
    ):
        return []
    return ["متن یکی از بخش‌ها خطی دارد که ساختار فصل را به هم می‌زند (تیتر «#» یا «##» یا بلوک «:::»). برای تیتر داخل متن از «###» استفاده کنید."]


def check_body(text: str, label: str) -> list[str]:
    errors = []
    for n, line in enumerate((text or "").split("\n"), start=1):
        if _BAD_BODY_LINE.match(line):
            errors.append(f"{label}، خط {n}: «{line.strip()[:30]}» در متن مجاز نیست؛ تیتر «#» و «##» مخصوص گروه و بخش است (از «###» استفاده کنید) و تست و فلش‌کارت و خلاصه جای خودشان را دارند.")
    return errors


# --- Finding things in a parsed chapter --------------------------------------------------------------------


def section(parsed: ParsedChapter, slug: str) -> ParsedSection:
    """'' means the chapter's introduction (created if missing)."""
    if not slug:
        if parsed.intro is None:
            parsed.intro = ParsedSection(slug="", title="", line=0)
        return parsed.intro
    for s in parsed.sections:
        if s.slug == slug:
            return s
    raise EditError(f"بخش «{slug}» پیدا نشد.")


def find_item(parsed: ParsedChapter, kind: str, slug: str):
    for s in parsed.all_sections():
        items = s.questions if kind == "question" else s.flashcards
        for i, item in enumerate(items):
            if item.slug == slug:
                return s, items, i
    raise EditError(f"«{slug}» پیدا نشد.")


def used_slugs(book: ContentNode, parsed: ParsedChapter, kind: str) -> set[str]:
    if kind == "section":
        db = ContentNode.objects.filter(path__startswith=book.path, kind=ContentNode.Kind.SECTION).values_list("slug", flat=True)
        return set(db) | {s.slug for s in parsed.sections}
    model = Question if kind == "question" else Flashcard
    db = model.objects.filter(node__path__startswith=book.path).values_list("slug", flat=True)
    here = {i.slug for s in parsed.all_sections() for i in (s.questions if kind == "question" else s.flashcards)}
    return set(db) | here


def suggest_slug(book: ContentNode, parsed: ParsedChapter, kind: str) -> str:
    """Next id in the chapter's own pattern (bb2-q73 → bb2-q74), or chapter-q1, chapter-f1, chapter-s1."""
    taken = used_slugs(book, parsed, kind)
    if kind == "section":
        mine = [s.slug for s in parsed.sections]
    else:
        mine = [i.slug for s in parsed.all_sections() for i in (s.questions if kind == "question" else s.flashcards)]
    numbered = [m for m in (re.match(r"^(.*?)(\d+)$", x) for x in mine) if m]
    if numbered:
        prefix = max(set(m.group(1) for m in numbered), key=lambda p: sum(1 for m in numbered if m.group(1) == p))
        width = max(len(m.group(2)) for m in numbered if m.group(1) == prefix)
        n = max(int(m.group(2)) for m in numbered if m.group(1) == prefix) + 1
    else:
        prefix, width, n = f"{parsed.meta['chapter_slug']}-{kind[0]}", 1, 1
    while f"{prefix}{n:0{width}d}" in taken:
        n += 1
    return f"{prefix}{n:0{width}d}"


def require_new_slug(book: ContentNode, parsed: ParsedChapter, kind: str, slug: str):
    label = {"section": "بخش", "question": "تست", "flashcard": "فلش‌کارت"}[kind]
    if not slug or not _SLUG.match(slug):
        raise EditError(f"شناسه‌ی {label} فقط می‌تواند حرف، عدد، - و _ داشته باشد.")
    if slug in used_slugs(book, parsed, kind):
        raise EditError(f"شناسه‌ی {label} «{slug}» قبلاً در این کتاب استفاده شده (شاید بایگانی شده باشد).")


# --- Items from the panel's forms ---------------------------------------------------------------------------


def _scratch() -> ParsedChapter:
    return ParsedChapter(meta={"chapter_slug": "x"})


def _is_raw(data: dict) -> bool:
    """The «متن خام» mode sends only {"raw": text}; the form sends its fields (its copy of raw is ignored)."""
    return data.get("raw") is not None and not ({"stem", "choices", "title", "point"} & set(data))


def question_from_form(data: dict, slug: str) -> ParsedQuestion:
    """The question form (or its raw text) → a checked ParsedQuestion, using the file parser's own rules."""
    from .exporter import question_block

    if _is_raw(data):
        lines = data["raw"].replace("\r\n", "\n").split("\n")
        if lines and lines[0].startswith(":::"):
            lines = lines[1:]
        if lines and lines[-1].strip() == ":::":
            lines = lines[:-1]
    else:
        sources = []
        for src in data.get("sources") or []:
            name, year = (src.get("name") or "").strip(), str(src.get("year") or "").strip()
            if name.startswith("کتاب") and not year:
                year = "0"  # a textbook: no year
            if name or year:
                if not year.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).isdigit():
                    raise EditError("سال منبع کنکور باید عدد باشد (مثلاً ۱۴۰۲).")
                number = str(src.get("number") or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).strip()
                sources.append((name, int(year.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))), int(number) if number.isdigit() else None))
        seconds = str(data.get("seconds") or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")).strip()
        draft = ParsedQuestion(
            slug=slug,
            line=0,
            stem=(data.get("stem") or "").strip(),
            explanation=(data.get("explanation") or "").strip(),
            # «راه‌حل‌ها»: rows of a title and a text; an empty row is left out, a text without a title is refused.
            solutions=[(" ".join((x.get("title") or "").split()), (x.get("body") or "").strip())
                       for x in data.get("solutions") or [] if (x.get("title") or "").strip() or (x.get("body") or "").strip()],
            difficulty=data.get("difficulty") or "",
            domain=data.get("domain") or "",
            kind=data.get("kind") or "",
            seconds=int(seconds) if seconds.isdigit() else None,
            is_free=bool(data.get("is_free")),
            fixed_order=bool(data.get("fixed_order")),
            is_extra=bool(data.get("is_extra")),
            is_original=bool(data.get("is_original")) or not sources,
            sources=sources,
            flashcard_slugs=[s for s in data.get("flashcards") or [] if s],
            similar_slugs=[s.strip() for s in re.split(r"[,،\s]+", data.get("similar") or "") if s.strip()] if isinstance(data.get("similar"), str)
            else [s for s in data.get("similar") or [] if s],
            choices=[((c.get("text") or "").strip(), bool(c.get("correct"))) for c in data.get("choices") or [] if (c.get("text") or "").strip()],
        )
        for title, _ in draft.solutions:
            if not title:
                raise EditError("هر راه‌حل یک عنوان لازم دارد (مثلاً «راه‌حل تستی»).")
            if "(" in title or ")" in title:
                raise EditError("عنوان راه‌حل پرانتز نداشته باشد.")
        for name, value in (("صورت سؤال", draft.stem), ("توضیح", draft.explanation), *[(f"راه‌حل «{t}»", b) for t, b in draft.solutions]):
            errs = check_body(value, name)
            if errs:
                raise EditError(errs)
        if not draft.difficulty:
            raise EditError("«سطح» تست را انتخاب کنید.")
        lines = question_block(draft)[1:-1]
    scratch = _scratch()
    q = _parse_question(lines, slug, 0, scratch)
    if scratch.errors:
        raise EditError([str(e).replace("خط 0: ", "") for e in scratch.errors])
    return q


def flashcard_from_form(data: dict, slug: str) -> ParsedFlashcard:
    from .exporter import flashcard_block

    if _is_raw(data):
        lines = data["raw"].replace("\r\n", "\n").split("\n")
        if lines and lines[0].startswith(":::"):
            lines = lines[1:]
        if lines and lines[-1].strip() == ":::":
            lines = lines[:-1]
    else:
        draft = ParsedFlashcard(
            slug=slug, line=0, title=" ".join((data.get("title") or "").split()), point=(data.get("point") or "").strip(),
            formula=" ".join((data.get("formula") or "").split()), is_free=bool(data.get("is_free")),
        )
        errs = check_body(draft.point, "نکته")
        if errs:
            raise EditError(errs)
        lines = flashcard_block(draft)[1:-1]
    scratch = _scratch()
    f = _parse_flashcard(lines, slug, 0, scratch)
    if scratch.errors:
        raise EditError([str(e).replace("خط 0: ", "") for e in scratch.errors])
    return f


# --- Restoring archived things -----------------------------------------------------------------------------


def archived_section(chapter: ContentNode, slug: str) -> ParsedSection:
    node = chapter.get_children().filter(kind=ContentNode.Kind.SECTION, slug=slug, is_archived=True).first()
    if node is None:
        raise EditError(f"بخش بایگانی‌شده‌ی «{slug}» پیدا نشد.")
    restored = section_from_db(node)
    archived = section_from_db(node, archived_items=True)
    restored.questions += archived.questions
    restored.flashcards += archived.flashcards
    return restored


def archived_item(chapter: ContentNode, kind: str, slug: str):
    model, to_parsed = (Question, question_to_parsed) if kind == "question" else (Flashcard, flashcard_to_parsed)
    ids = [chapter.pk, *chapter.get_descendants().values_list("pk", flat=True)]
    obj = model.objects.filter(node_id__in=ids, slug=slug, is_archived=True).select_related("node").first()
    if obj is None:
        raise EditError(f"«{slug}» در بایگانی این فصل پیدا نشد.")
    return obj, to_parsed(obj)


# --- What a new text would change (preview before applying a file or a version) ----------------------------


def _item_fields(item):
    data = dataclasses.asdict(item)
    data.pop("line", None)
    return data


QUESTION_LABELS = {
    "stem": "صورت", "choices": "گزینه‌ها", "explanation": "توضیح", "solutions": "راه‌حل‌ها",
    "difficulty": "سطح", "domain": "حوزه", "kind": "نوع", "seconds": "زمان", "is_free": "رایگان", "is_original": "منبع",
    "fixed_order": "ترتیب گزینه‌ها", "is_extra": "نقش", "sources": "منبع", "flashcard_slugs": "فلش‌کارت‌های مرتبط", "similar_slugs": "تست‌های مشابه",
}
FLASHCARD_LABELS = {"title": "عنوان", "point": "نکته", "formula": "فرمول", "is_free": "رایگان"}


def plan_changes(current: ParsedChapter | None, new: ParsedChapter) -> dict:
    """A readable list of what applying `new` would do to the chapter as it is now."""
    plan = {"chapter": [], "sections": [], "questions": [], "flashcards": [], "notes": []}
    cur_meta = current.meta if current else {}
    for key, label in (("chapter_title", "عنوان فصل"), ("chapter_number", "شماره‌ی فصل"), ("chapter_free", "رایگان بودن فصل")):
        if current and cur_meta.get(key) != new.meta.get(key):
            plan["chapter"].append(f"{label}: «{cur_meta.get(key)}» ← «{new.meta.get(key)}»")
    cur_intro = current.intro if current else None
    if (cur_intro.full_body if cur_intro else "") != (new.intro.full_body if new.intro else ""):
        plan["chapter"].append("متن مقدمه‌ی فصل تغییر می‌کند")
    if (cur_intro.summary_body if cur_intro else "") != (new.intro.summary_body if new.intro else ""):
        plan["chapter"].append("خلاصه‌ی مقدمه‌ی فصل تغییر می‌کند")

    cur_sections = {s.slug: s for s in (current.sections if current else [])}
    new_sections = {s.slug: s for s in new.sections}
    for s in new.sections:
        old = cur_sections.get(s.slug)
        if old is None:
            plan["sections"].append(("new", s.title, "بخش تازه"))
            continue
        what = [label for attr, label in (("title", "عنوان"), ("group", "گروه"), ("full_body", "جزوه"), ("summary_body", "خلاصه"))
                if getattr(old, attr) != getattr(s, attr)]
        if what:
            plan["sections"].append(("changed", s.title, "، ".join(what)))
    for slug, s in cur_sections.items():
        if slug not in new_sections:
            plan["sections"].append(("archived", s.title, "بایگانی می‌شود (پاک نمی‌شود)"))
    if current and [s for s in (x.slug for x in current.sections) if s in new_sections] != [s for s in (x.slug for x in new.sections) if s in cur_sections]:
        plan["notes"].append("ترتیب بخش‌ها عوض می‌شود.")

    for kind, attr, labels, title in (
        ("questions", "questions", QUESTION_LABELS, lambda q: q.stem),
        ("flashcards", "flashcards", FLASHCARD_LABELS, lambda f: f.title),
    ):
        cur_items = {i.slug: (s, i) for s in (current.all_sections() if current else []) for i in getattr(s, attr)}
        new_items = {i.slug: (s, i) for s in new.all_sections() for i in getattr(s, attr)}
        for slug, (s, item) in new_items.items():
            label = f"{slug}: {title(item)[:70]}"
            if slug not in cur_items:
                plan[kind].append(("new", label, f"در «{s.title or 'مقدمه'}»"))
                continue
            old_s, old = cur_items[slug]
            changed = sorted({labels[k] for k, v in _item_fields(item).items() if k in labels and _item_fields(old).get(k) != v})
            if old_s.slug != s.slug:
                changed.insert(0, f"از «{old_s.title or 'مقدمه'}» به «{s.title or 'مقدمه'}»")
            if changed:
                plan[kind].append(("changed", label, "، ".join(changed)))
        for slug, (s, item) in cur_items.items():
            if slug not in new_items:
                plan[kind].append(("archived", f"{slug}: {title(item)[:70]}", "بایگانی می‌شود (پاک نمی‌شود؛ آمار کاربران می‌ماند)"))
        gone = [cur_items[k][1] for k in cur_items if k not in new_items]
        came = [new_items[k][1] for k in new_items if k not in cur_items]
        for old in gone:
            for item in came:
                if title(old).strip() and title(old).strip() == title(item).strip():
                    plan["notes"].append(
                        f"«{old.slug}» بایگانی و «{item.slug}» با همان متن ساخته می‌شود؛ اگر فقط شناسه را عوض کرده‌اید، آمار و یادداشت‌های کاربران به مورد تازه منتقل نمی‌شود."
                    )
    plan["count"] = sum(len(v) for k, v in plan.items() if isinstance(v, list) and k != "notes")
    return plan


def text_diff(old: str, new: str) -> list[tuple[str, str]]:
    """Line diff as (kind, line) with kind in ' ', '+', '-', '@' (a gap)."""
    out = []
    for line in difflib.unified_diff(old.split("\n"), new.split("\n"), lineterm="", n=2):
        if line.startswith(("---", "+++")):
            continue
        out.append(("@", "…") if line.startswith("@@") else (line[0], line[1:]))
    return out
