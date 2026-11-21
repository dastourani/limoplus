"""
Numbered boxes («مثال ۳-۵»), counted over a whole chapter like LaTeX, and references to them.

Any named box can be linked; a box of a label marked «شماره‌دار» in the panel (models.Label.numbered; «مثال» and «نمودار» to start) is numbered in the
notes («درسنامه») of a chapter in order: the chapter's intro first, then its sections. The number is never written in
the text, so moving or deleting a box renumbers the rest. A box may carry a name, «:::مثال {#sin-hamarz}», and the text
anywhere in the book (notes, test explanations) can point to it with «[[#sin-hamarz]]», shown as «مثال ۳-۵» and a tap
to go there. The app renders the boxes (app/src/lib/renderMarkdown.ts); this module tells it where each section's
count starts and what every name stands for.
"""

from __future__ import annotations

import re

from .labels import all_labels, find

BOX = re.compile(r"^:::[ \t]*([^\s{](?:[^{\n]*[^\s{])?)[ \t]*(?:\{#([^}\s]+)\})?[ \t]*$", re.MULTILINE)
REF = re.compile(r"\[\[#([^\]\s]+)\]\]")
# A named display formula «$$…$$ {#name}»: numbered over the chapter («(۳-۲)») and linked as «رابطه‌ی (۳-۲)».
EQUATION = re.compile(r"\$\$[\s\S]+?\$\$[ \t]*(?:\{#([^}\s]+)\})?")
EQ = "رابطه"  # its key in the counts (the app reads start["رابطه"])

_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n) -> str:
    return str(n).translate(_DIGITS)


def boxes(text: str) -> list[tuple[dict, str]]:
    """(label, name or "") of every box in the text, in order."""
    out = []
    for m in BOX.finditer(text or ""):
        label = find(m.group(1))
        if label:
            out.append((label, (m.group(2) or "").strip()))
    return out


def numbered_names() -> set[str]:
    return {l["name"] for l in all_labels() if l.get("numbered")}


def count(position, parts) -> tuple[dict, dict[str, dict]]:
    """parts: (key, notes text) of a chapter in order, its intro first. Returns where each part's count starts
    ({key: {label: n already used}}) and the names in it ({name: {"text": "مثال ۳-۵", "node": key}})."""
    wanted = numbered_names()
    counts: dict[str, int] = {}
    starts: dict = {}
    refs: dict[str, dict] = {}
    for key, text in parts:
        starts[key] = dict(counts)
        for m in EQUATION.finditer(text or ""):
            if m.group(1):
                counts[EQ] = counts.get(EQ, 0) + 1
                number = f"{fa(position)}-{fa(counts[EQ])}" if position else fa(counts[EQ])
                refs.setdefault(m.group(1), {"text": f"رابطه‌ی ({number})", "node": key})
        for label, name in boxes(text):
            if label["name"] not in wanted:
                # Not numbered: a link to it shows the label's name («قضیه»).
                if name:
                    refs.setdefault(name, {"text": label["name"], "node": key})
                continue
            counts[label["name"]] = counts.get(label["name"], 0) + 1
            if name:
                n = counts[label["name"]]
                number = f"{fa(position)}-{fa(n)}" if position else fa(n)
                refs.setdefault(name, {"text": f"{label['name']} {number}", "node": key})
    return starts, refs


def chapter_numbering(chapter, sections) -> tuple[dict[int, dict[str, int]], dict[str, dict]]:
    return count(chapter.position, [(n.id, n.full_body) for n in [chapter, *sections]])


def panel_refs(book) -> dict[str, dict]:
    """The names of the whole book for the panel's previews, drafts included (archived parts left out)."""
    from .models import ContentNode

    refs: dict[str, dict] = {}
    for chapter in book.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False):
        sections = chapter.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False)
        for k, v in chapter_numbering(chapter, sections)[1].items():
            refs.setdefault(k, v)
    return refs


def book_refs(access) -> dict[str, dict]:
    """Every name in the book the learner can see, for links from any section or test."""
    refs: dict[str, dict] = {}
    for chapter in access.children(access.book):
        sections = access.children(chapter)
        refs.update({k: v for k, v in chapter_numbering(chapter, sections)[1].items() if k not in refs})
    return refs


def numbering_for(access, node) -> dict | None:
    """What the app needs to number one section's boxes and resolve its links."""
    if node.kind == node.Kind.CHAPTER:
        chapter = node
    elif node.kind == node.Kind.SECTION:
        chapter = node.get_parent()
    else:
        return None
    starts, _ = chapter_numbering(chapter, access.children(chapter))
    return {"chapter": chapter.position, "start": starts.get(node.id, {}), "refs": book_refs(access)}


def resolve(request, node, text: str) -> str:
    """«[[#name]]» in a test's explanation → «[[#name|مثال ۳-۵|section id]]», so the app can show and open it without
    knowing the book's names. Names the learner cannot see stay as they are (shown as missing)."""
    if not text or "[[#" not in text or node is None:
        return text
    from .access import AccessMap
    from .models import ContentNode

    if not isinstance(node, ContentNode):
        node = ContentNode.objects.filter(pk=node).first()
        if node is None:
            return text
    book = node.book()
    cache = getattr(request, "_limo_refs", None)
    if cache is None:
        cache = request._limo_refs = {}
    if book.pk not in cache:
        cache[book.pk] = book_refs(AccessMap(request.user, book))
    refs = cache[book.pk]

    def link(m):
        r = refs.get(m.group(1))
        return f"[[#{m.group(1)}|{r['text']}|{r['node']}]]" if r else m.group(0)

    return REF.sub(link, text)


def section_boxes(text: str) -> list[dict]:
    """The boxes of a section's notes: label, name and body, in order."""
    out, lines, i = [], (text or "").split("\n"), 0
    while i < len(lines):
        m = BOX.match(lines[i])
        label = find(m.group(1)) if m else None
        if label:
            end = next((j for j in range(i + 1, len(lines)) if lines[j].strip() == ":::"), None)
            if end is not None:
                out.append({"label": label, "name": (m.group(2) or "").strip(), "body": "\n".join(lines[i + 1 : end])})
                i = end + 1
                continue
        i += 1
    return out
