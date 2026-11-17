"""
PowerPoint → the chapter format of docs/content-format.md.

A professor often already has the lecture as slides. Each slide becomes one **section** of the chapter: the slide's
title is the section title, the rest of the slide is the section's notes, and pictures on the slide are carried over
as images.

    .pptx ──► read_pptx() ──► chapter Markdown text + images ──► importer.parse_chapter()

No dependency is added for this (python-pptx is not installed, and a .pptx is just a ZIP of XML — the LaTeX ZIP is
read the same way). Only the parts the format guarantees are used: ppt/presentation.xml lists the slides, each
ppt/slides/slideN.xml holds shapes whose a:t elements are the text runs.

Two rules decide what is kept:

1. **Reading order, not XML order.** Shapes carry a position; a slide's text is read top-to-bottom, then
   left-to-right, so a two-column slide does not come out shuffled.
2. **A slide with no title still becomes a section**, named after its number («اسلاید ۳»), because silently dropping
   a slide loses half the lecture without the author noticing.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# The paragraph levels that become Markdown list nesting. PowerPoint levels are 0-based.
MAX_LEVEL = 4

_WHITESPACE = re.compile(r"[ \t\u00a0]+")
# Zero-width characters PowerPoint leaves behind. The ZWNJ (U+200C) is NOT one of them: it is the Persian half-space
# («بی‌عنوان» is one word, «بیعنوان» is a typo), so it must survive the trip.
_INVISIBLE = re.compile(r"[\u200b\u200d\u200e\u200f\u202a-\u202e\ufeff]")


@dataclass
class Slide:
    """One slide, already reduced to what a section needs."""

    number: int
    title: str = ""
    lines: list[tuple[int, str]] = field(default_factory=list)  # (level, text)
    pictures: list[str] = field(default_factory=list)  # part names inside the ZIP


@dataclass
class PptxReading:
    """What came out of the file: the slides, and anything the author should know."""

    slides: list[Slide] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fatal: str = ""  # a message that stops the import (not a .pptx, no slides, …)


# --- Reading the package ---------------------------------------------------------------------------------------


def _xml(data: bytes):
    from xml.etree import ElementTree

    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None


def _slides_in_order(archive: zipfile.ZipFile) -> list[str]:
    """The slide part names, in the order the presentation shows them (not file-name order)."""
    names = set(archive.namelist())
    presentation = _xml(archive.read("ppt/presentation.xml")) if "ppt/presentation.xml" in names else None
    if presentation is not None:
        rels_name = "ppt/_rels/presentation.xml.rels"
        targets: dict[str, str] = {}
        if rels_name in names:
            rels = _xml(archive.read(rels_name))
            if rels is not None:
                for rel in rels:
                    if rel.get("Id") and rel.get("Target"):
                        targets[rel.get("Id")] = _resolve("ppt", rel.get("Target"))
        ordered = []
        for slide_id in presentation.iter(f"{{{NS['p']}}}sldId"):
            rid = slide_id.get(f"{{{NS['r']}}}id")
            name = targets.get(rid, "")
            if name in names:
                ordered.append(name)
        if ordered:
            return ordered
    # No usable relationship list: fall back to slide1, slide2, … and say nothing, the file is still readable.
    numbered = []
    for name in names:
        match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
        if match:
            numbered.append((int(match.group(1)), name))
    return [name for _, name in sorted(numbered)]


def _resolve(base: str, target: str) -> str:
    """A relationship Target is relative to the part that holds it («../media/image1.png»).

    PowerPoint writes some targets as absolute-from-package («/ppt/slides/slide1.xml»), so both forms are accepted.
    """
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join(base, target))


def _text_of(paragraph) -> str:
    """The text of one a:p, runs joined; a «tab» run becomes a space, a «br» a line break."""
    parts = []
    for child in paragraph:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "r":
            for run_child in child:
                if run_child.tag.rsplit("}", 1)[-1] == "t":
                    parts.append(run_child.text or "")
                elif run_child.tag.rsplit("}", 1)[-1] == "br":
                    parts.append("\n")
        elif tag == "br":
            parts.append("\n")
        elif tag == "fld":  # a slide number or date placeholder: not the author's words
            continue
    text = "".join(parts)
    return _WHITESPACE.sub(" ", _INVISIBLE.sub("", text)).strip()


def _level_of(paragraph) -> int:
    props = paragraph.find("a:pPr", NS)
    if props is None:
        return 0
    raw = props.get("lvl", "0")
    try:
        return max(0, min(MAX_LEVEL, int(raw)))
    except ValueError:
        return 0


def _shape_position(shape) -> tuple[int, int]:
    """Top, left — in EMU. A shape without a position sorts last (it is usually a background)."""
    off = shape.find("p:spPr/a:xfrm/a:off", NS)
    if off is None:
        off = shape.find("p:grpSpPr/a:xfrm/a:off", NS)
    if off is None:
        return (10**9, 10**9)
    try:
        return (int(off.get("y", 0)), int(off.get("x", 0)))
    except ValueError:
        return (10**9, 10**9)


def _picture_targets(shape) -> list[str]:
    """The image parts a picture shape points at (its blipFill relationship)."""
    out = []
    for blip in shape.iter(f"{{{NS['a']}}}blip"):
        rid = blip.get(f"{{{NS['r']}}}embed")
        if rid:
            out.append(rid)
    return out


def _slide_parts(archive: zipfile.ZipFile, name: str) -> dict[str, str]:
    """The slide's relationships: rId → part name (pictures and the like)."""
    base = posixpath.dirname(name)
    rels_name = posixpath.join(base, "_rels", posixpath.basename(name) + ".rels")
    if rels_name not in archive.namelist():
        return {}
    rels = _xml(archive.read(rels_name))
    if rels is None:
        return {}
    out = {}
    for rel in rels:
        if rel.get("Id") and rel.get("Target"):
            out[rel.get("Id")] = _resolve(base, rel.get("Target"))
    return out


def _read_slide(archive: zipfile.ZipFile, name: str, number: int) -> Slide:
    slide = Slide(number=number)
    root = _xml(archive.read(name))
    if root is None:
        return slide
    tree = root.find("p:cSld/p:spTree", NS)
    if tree is None:
        return slide
    parts = _slide_parts(archive, name)

    title_placeholder = None
    body: list[tuple[tuple[int, int], list[tuple[int, str]]]] = []
    for shape in tree:
        tag = shape.tag.rsplit("}", 1)[-1]
        if tag == "pic":
            for rid in _picture_targets(shape):
                picture = parts.get(rid, "")
                if picture:
                    slide.pictures.append(picture)
            continue
        if tag not in ("sp", "graphicFrame"):
            continue
        for rid in _picture_targets(shape):
            picture = parts.get(rid, "")
            if picture:
                slide.pictures.append(picture)
        paragraphs = []
        for paragraph in shape.iter(f"{{{NS['a']}}}p"):
            text = _text_of(paragraph)
            if text:
                paragraphs.append((_level_of(paragraph), text))
        if not paragraphs:
            continue
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS)
        kind = placeholder.get("type", "body") if placeholder is not None else ""
        if kind in ("title", "ctrTitle") and title_placeholder is None:
            title_placeholder = " ".join(text for _, text in paragraphs)
            continue
        body.append((_shape_position(shape), paragraphs))

    # Reading order: top-to-bottom, left-to-right. Python's sort is stable, so ties keep the XML order.
    body.sort(key=lambda pair: pair[0])
    slide.title = title_placeholder or ""
    for _, paragraphs in body:
        slide.lines.extend(paragraphs)
    return slide


def read_pptx(data: bytes) -> PptxReading:
    """Read a .pptx and return its slides. Never raises on a bad file: the reason comes back in `fatal`."""
    reading = PptxReading()
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        reading.fatal = "فایل پاورپوینت باز نشد؛ مطمئن شوید فایل سالم و با پسوند .pptx است."
        return reading
    with archive:
        names = archive.namelist()
        if "ppt/presentation.xml" not in names:
            reading.fatal = "این فایل پاورپوینت نیست (ساختار ppt/presentation.xml را ندارد)."
            return reading
        ordered = _slides_in_order(archive)
        if not ordered:
            reading.fatal = "در این فایل هیچ اسلایدی پیدا نشد."
            return reading
        for number, name in enumerate(ordered, start=1):
            reading.slides.append(_read_slide(archive, name, number))
        if not any(s.title or s.lines for s in reading.slides):
            reading.fatal = "هیچ متنی در اسلایدها پیدا نشد؛ شاید متن‌ها عکس‌اند. اول متن را به اسلاید اضافه کنید."
            return reading
        reading.slides = [s for s in reading.slides if s.title or s.lines or s.pictures]
    return reading


# --- Turning slides into a chapter -----------------------------------------------------------------------------


def _slug(text: str, number: int, taken: set[str]) -> str:
    """A section slug: Latin letters, digits, - and _ only, as the chapter format requires.

    A Persian title gives no usable slug, so the slide number keeps it stable («slide-3»); the title itself is the
    heading, so nothing is lost.
    """
    stem = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:40]
    # A Persian title gives no Latin letters, and «اسلاید 1» would leave a bare «1»: both need the slide number.
    base = stem if re.search(r"[a-z]", stem) else f"slide-{number}"
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    taken.add(slug)
    return slug


def _paragraph(line: str, level: int) -> str:
    """One slide line as Markdown: a top-level line is a sentence, a deeper one is a list item."""
    if level <= 0:
        return line
    return f"{'  ' * (level - 1)}- {line}"


def to_chapter(reading: PptxReading, *, book_slug: str, book_title: str, chapter_slug: str, chapter_title: str,
               chapter_number: int = 1, majors: list[str] | None = None) -> str:
    """The slides as a chapter file the importer already understands, in the same shape `latex.py` produces."""
    taken: set[str] = set()
    out = [
        "---",
        f"شناسه-کتاب: {book_slug}",
        f"کتاب: {book_title}",
        f"رشته‌ها: {', '.join(majors or [])}",
        f"شناسه-فصل: {chapter_slug}",
        f"فصل: {chapter_number}",
        f"عنوان: {chapter_title}",
        "---",
        "",
    ]
    for slide in reading.slides:
        title = slide.title.strip() or f"اسلاید {slide.number}"
        out.append(f"## {title} {{#{_slug(title, slide.number, taken)}}}")
        out.append("")
        for level, text in slide.lines:
            out.append(_paragraph(text, level))
        if slide.lines:
            out.append("")
    return "\n".join(out).rstrip() + "\n"


_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def images_of(data: bytes, reading: PptxReading) -> dict[str, bytes]:
    """The pictures the slides point at, keyed by their base name («image1.png»)."""
    out: dict[str, bytes] = {}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return out
    with archive:
        names = set(archive.namelist())
        for slide in reading.slides:
            for part in slide.pictures:
                if part in names and part.lower().endswith(_IMAGE_EXTENSIONS):
                    base = posixpath.basename(part)
                    if base not in out:
                        out[base] = archive.read(part)
    return out


def report(reading: PptxReading) -> list[str]:
    """What the author should know, in the panel's voice."""
    notes = []
    if reading.fatal:
        return [reading.fatal]
    empty = [s.number for s in reading.slides if not (s.title and s.lines)]
    if empty:
        notes.append(
            "این اسلایدها متن کامل نداشتند (فقط عنوان یا فقط عکس): "
            + "، ".join(str(n) for n in empty[:12])
            + ("…" if len(empty) > 12 else "")
        )
    untitled = [s.number for s in reading.slides if not s.title]
    if untitled:
        notes.append("این اسلایدها عنوان نداشتند و «اسلاید N» نام گرفتند: " + "، ".join(str(n) for n in untitled[:12]))
    repeated = [s.number for s in reading.slides if s.title and sum(1 for o in reading.slides if o.title == s.title) > 1]
    if repeated:
        notes.append("عنوان این اسلایدها تکراری است: " + "، ".join(str(n) for n in sorted(set(repeated))[:12]))
    return notes
