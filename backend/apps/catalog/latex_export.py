"""
The chapter format of docs/content-format.md → a LaTeX document (the reverse of apps/catalog/latex.py).

A chapter taken out of the book builds a .tex file that compiles on its own with XeLaTeX and xepersian, on Overleaf
as it is: the preamble is complete, each box is a real environment, each cross-reference a real \\ref, and formulas
go out as they came in (KaTeX's TeX is TeX).

    the database ──► chapter_to_tex() ──► .tex (+ images/) ──► Overleaf ──► .tex ──► back into the book

The order below is the whole trick, and the reason this file was rewritten twice:

    1. formulas are pulled out first   ($…$ must never be escaped or read as Markdown)
    2. Markdown is turned into LaTeX    (**x** → \\textbf{x}, ==قرمز:y== → \\hlc{y}, [[#a]] → \\ref{a})
    3. only what is left is escaped     (%, &, _, ^, {, } … are text, not markup)

Escaping first and converting after turns \\textbf into \\textbackslash{}\\{textbf\\} — which compiles, prints the
command as words, and looks like a working export until someone opens the PDF.
"""

from __future__ import annotations

import posixpath
import re

# --- Labels and environments ------------------------------------------------------------------------------------

# The labels of the book that are numbered (apps/catalog/labels.py NUMBERED).
NUMBERED = {"مثال", "نمودار", "تمرین"}
LATIN_LABEL = "لاتین"

# The LaTeX environment of each label. The preamble defines every one of them.
ENVIRONMENT_NAMES = {
    "تعریف": "definition",
    "قضیه": "theorem",
    "گزاره": "proposition",
    "نتیجه": "corollary",
    "مثال": "example",
    "تمرین": "exercise",
    "پرسش و پاسخ": "qa",
    "نکته": "note",
    "یادآوری": "recall",
    "هشدار": "warning",
    "مثال نقض": "counterexample",
    "تله": "trap",
    "مهم": "important",
    "در یک نگاه": "ataglance",
    "فرمول": "formula",
    "قاعده": "rule",
    "شرط کاربرد": "condition",
    "حفظی": "memorize",
    "نمودار": "plot",
    LATIN_LABEL: "latin",
    "واژه": "terms",
    "مترادف": "synonyms",
    "متضاد": "antonyms",
}
# The colour of each box: the frame and its fill, as the app draws it.
BOX_COLOURS = {
    "definition": ("A7C4E0", "F0F6FB"), "theorem": ("E8C07D", "FCF6EA"), "proposition": ("E8C07D", "FCF6EA"),
    "corollary": ("E8C07D", "FCF6EA"), "example": ("8FBF7F", "F1F8EE"), "exercise": ("8FBF7F", "F1F8EE"),
    "qa": ("8FBF7F", "F1F8EE"), "plot": ("7FA8C9", "EEF4F9"), "note": ("D9C27E", "FBF7EA"),
    "recall": ("D9C27E", "FBF7EA"), "warning": ("D98A7A", "FBF0EE"), "counterexample": ("D98A7A", "FBF0EE"),
    "trap": ("D98A7A", "FBF0EE"), "important": ("B39DD1", "F5F1FA"), "ataglance": ("B39DD1", "F5F1FA"),
    "formula": ("A7C4E0", "F0F6FB"), "rule": ("A7C4E0", "F0F6FB"), "condition": ("D9C27E", "FBF7EA"),
    "memorize": ("B39DD1", "F5F1FA"), "terms": ("8FBF7F", "F1F8EE"), "synonyms": ("8FBF7F", "F1F8EE"),
    "antonyms": ("8FBF7F", "F1F8EE"),
}
# Boxes that are a plain listing without a frame («:::لاتین» is a left-to-right block).
NO_FRAME = {"latin"}

_BOX_OPEN = re.compile(r"^:::\s*([^\s{][^{]*?)\s*(?:\{#([^}]+)\})?\s*$")
_BOX_CLOSE = re.compile(r"^:::\s*$")
_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*(?:\{#([^}]+)\})?\s*$")
_GROUP = re.compile(r"^#\s+(.+?)\s*$")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_NAMED_FORMULA = re.compile(r"^\$\$\s*([\s\S]*?)\s*\$\$\s*\{#([^}]+)\}\s*$")
_FORMULA = re.compile(r"^\$\$\s*([\s\S]*?)\s*\$\$\s*$")
_REF = re.compile(r"\[\[#([^\]]+)\]\]")
_WORD_REF = re.compile(r"\[\[([^\]#]+)\]\]")
_COLOUR = re.compile(r"==(قرمز|آبی|سبز|red|blue|green):([^\n]+?)==")
_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n\s][^*\n]*?)\*(?![\w*])")
_ORDERED = re.compile(r"^\d+[.)]\s+")
_BULLET = re.compile(r"^[-*]\s+")

# Placeholders, kept apart from the words while the text is escaped.
_MATH_MARK = "\x01m%d\x01"
_LATEX_MARK = "\x01l%d\x01"


def _label_name(name: str) -> str:
    """A book name ({#sin-hamarz}) as a LaTeX label: no spaces, no braces."""
    return re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE).strip("-") or "ref"


def environment_of(label: str) -> str:
    """The LaTeX environment of a book label; a label added in the panel gets a name of its own."""
    known = ENVIRONMENT_NAMES.get(label.strip())
    if known:
        return known
    cleaned = re.sub(r"[^a-z0-9]+", "", label.lower())
    return "box" + cleaned if cleaned else "bookbox"


def _escape(text: str) -> str:
    """Plain words → LaTeX. Formulas are already taken out when this runs."""
    out = []
    # \\\\ first: a backslash that is already LaTeX must not be escaped twice (\begin of a kept environment).
    for char in text:
        out.append({
            "\\": r"\textbackslash{}",
            "{": r"\{",
            "}": r"\}",
            "$": r"\$",
            "&": r"\&",
            "#": r"\#",
            "_": r"\_",
            "%": r"\%",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }.get(char, char))
    return "".join(out)


def _protect(text: str) -> tuple[str, list[str]]:
    """Take the formulas out of a line, so nothing below can escape or rewrite them."""
    pieces: list[str] = []

    def stash(match):
        pieces.append(match.group(0))
        return _MATH_MARK % (len(pieces) - 1)

    # $$…$$ before $…$: the display pair must not be read as two inline ones.
    text = re.sub(r"\$\$.+?\$\$", stash, text, flags=re.S)
    text = re.sub(r"\$[^$\n]+?\$", stash, text)
    return text, pieces


def _restore(text: str, pieces: list[str], mark: str) -> str:
    """Put the stashed pieces back. Formulas and LaTeX commands have their own marks: one list's index never
    collides with the other's."""
    for number, piece in enumerate(pieces):
        text = text.replace(mark % number, piece)
    return text


def inline(text: str) -> str:
    """One line of the book's Markdown → one line of LaTeX.

    The order is the whole trick: formulas out, Markdown → LaTeX (each piece stashed in a placeholder), escape what is
    left, then put the pieces back. Escaping before the conversion writes «\\textbf» as words on the page; escaping
    after it destroys the commands just built.
    """
    text, formulas = _protect(text)
    latex: list[str] = []

    def stash(piece: str) -> str:
        latex.append(piece)
        return _LATEX_MARK % (len(latex) - 1)

    text = _IMAGE.sub(lambda m: stash(_figure(m.group(1), m.group(2))), text)
    text = _REF.sub(lambda m: stash(r"\ref{" + _label_name(m.group(1)) + "}"), text)
    text = _WORD_REF.sub(lambda m: stash(r"\textbf{" + _escape(m.group(1)) + "}"), text)
    text = _BOLD.sub(lambda m: stash(r"\textbf{" + _escape(m.group(1)) + "}"), text)
    text = _ITALIC.sub(lambda m: stash(r"\emph{" + _escape(m.group(1)) + "}"), text)
    text = _COLOUR.sub(
        lambda m: stash(("\\hlc{" if m.group(1) in ("قرمز", "red") else "\\hl{") + _escape(m.group(2)) + "}"), text)

    text = _escape(text)
    text = _restore(text, latex, _LATEX_MARK)
    text = _restore(text, formulas, _MATH_MARK)
    return text


def _figure(caption: str, target: str) -> str:
    """![caption](media:content/…) → a figure; the exporter writes the file into images/ next to the .tex."""
    path = target[len("media:") :] if target.startswith("media:") else target
    name = posixpath.basename(path)
    lines = [r"\begin{figure}[H]", r"\centering", r"\includegraphics[width=0.8\textwidth]{images/" + name + "}"]
    if caption.strip():
        lines.append(r"\caption{" + _escape(caption.strip()) + "}")
    lines.append(r"\end{figure}")
    return "\n".join(lines)


# --- Blocks -----------------------------------------------------------------------------------------------------

def blocks(lines: list[str]) -> list[str]:
    """A section's body: paragraphs, boxes, lists, tables and formulas, as LaTeX lines."""
    out: list[str] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()

        if not stripped:
            out.append("")
            index += 1
            continue

        box = _BOX_OPEN.match(stripped)
        if box:
            label, name = box.group(1).strip(), (box.group(2) or "").strip()
            body, index = _take_box(lines, index)
            out.extend(_box(label, name, body))
            continue

        if _BOX_CLOSE.match(stripped):
            index += 1   # a stray «:::»; the format allows it
            continue

        heading = _HEADING.match(stripped)
        if heading:
            # The chapter is \section here, so its own sections are subsections and their sub-headings deeper.
            depth = len(heading.group(1)) - 1   # ## → 1
            command = {1: "subsection", 2: "subsubsection"}.get(depth, "paragraph")
            slug = (heading.group(3) or "").strip()
            line = "\\" + command + "{" + inline(heading.group(2).strip()) + "}"
            if slug:
                line += r"\label{" + _label_name(slug) + "}"
            out.append(line)
            index += 1
            continue

        group = _GROUP.match(stripped)
        if group:
            out.append(r"\subsection*{" + inline(group.group(1).strip()) + "}")
            index += 1
            continue

        named = _NAMED_FORMULA.match(stripped)
        if named:
            out += [r"\begin{equation}\label{" + _label_name(named.group(2)) + "}", named.group(1), r"\end{equation}"]
            index += 1
            continue

        formula = _FORMULA.match(stripped)
        if formula:
            out += [r"\[", formula.group(1), r"\]"]
            index += 1
            continue

        if stripped.startswith("|"):
            table, index = _take_table(lines, index)
            out.extend(_table(table))
            continue

        if _BULLET.match(stripped) or _ORDERED.match(stripped):
            ordered = bool(_ORDERED.match(stripped))
            items, index = _take_list(lines, index, ordered)
            out.extend(_list(items, ordered))
            continue

        out.append(inline(stripped))
        index += 1
    return out


def _take_box(lines: list[str], start: int) -> tuple[list[str], int]:
    body = []
    index = start + 1
    while index < len(lines) and not _BOX_CLOSE.match(lines[index].strip()):
        body.append(lines[index])
        index += 1
    return body, index + 1


def _take_table(lines: list[str], start: int) -> tuple[list[str], int]:
    rows = []
    index = start
    while index < len(lines) and lines[index].strip().startswith("|"):
        rows.append(lines[index])
        index += 1
    return rows, index


def _take_list(lines: list[str], start: int, ordered: bool) -> tuple[list[str], int]:
    pattern = _ORDERED if ordered else _BULLET
    items: list[str] = []
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if pattern.match(stripped):
            items.append(pattern.sub("", stripped))
            index += 1
        elif stripped and items and not stripped.startswith("|") and not _BOX_OPEN.match(stripped):
            items[-1] += " " + stripped   # a wrapped line of the same item
            index += 1
        else:
            break
    return items, index


def _list(items: list[str], ordered: bool) -> list[str]:
    environment = "enumerate" if ordered else "itemize"
    out = [r"\begin{" + environment + "}"]
    out += [r"\item " + inline(item) for item in items]
    out.append(r"\end{" + environment + "}")
    return out


def _table(rows: list[str]) -> list[str]:
    """A Markdown table → tabular with a rule above and below the header (booktabs)."""
    if len(rows) < 2:
        return [inline(row) for row in rows]
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    header = cells[0]
    body = cells[2:] if _is_rule_row(cells[1]) else cells[1:]
    width = max(len(row) for row in cells)
    out = [r"\begin{center}", r"\begin{tabular}{" + ("l" * width) + "}", r"\toprule"]
    out.append(" & ".join(inline(cell) for cell in header) + r" \\")
    out.append(r"\midrule")
    out += [" & ".join(inline(cell) for cell in row) + r" \\" for row in body]
    out += [r"\bottomrule", r"\end{tabular}", r"\end{center}"]
    return out


def _is_rule_row(cells: list[str]) -> bool:
    """«| --- | :---: |»: the row of a Markdown table that is only dashes and colons."""
    return bool(cells) and all(cell and set(cell) <= set("-: ") for cell in cells)


def _box(label: str, name: str, body: list[str]) -> list[str]:
    """«:::تعریف» → a definition environment; a named box keeps its name as \\label for \\ref."""
    environment = environment_of(label)
    inner = blocks(body)
    while inner and not inner[-1].strip():
        inner.pop()
    # The \label rides on the \begin line: that is where the reader looks for the box's name, and it is valid LaTeX.
    opening = r"\begin{" + environment + "}" + (r"\label{" + _label_name(name) + "}" if name else "")
    out = [opening]
    out.extend(inner)
    out.append(r"\end{" + environment + "}")
    return out


# --- The document -----------------------------------------------------------------------------------------------

def _preamble(labels: list[str]) -> list[str]:
    """A preamble that compiles alone with XeLaTeX: one environment and one counter per label the chapter uses.

    The boxes use `mdframed` (a frame that breaks across pages) and only standard TeX Live packages, so Overleaf needs
    nothing extra. The class is `article`, which has no chapters: a chapter of the book is a \\section here, so its
    own sections are \\subsection and their sub-headings \\subsubsection.
    """
    environments: list[str] = []
    for label in labels:
        name = environment_of(label)
        if name not in environments:
            environments.append(name)

    lines = [
        r"% ----------------------------------------------------------------",
        r"%  ساخته‌شده از «لیموخوان» — لیموخوان",
        r"%",
        r"%  کامپایل با XeLaTeX (در Overleaf: Menu ← Compiler ← XeLaTeX).",
        r"%  فقط بسته‌های استاندارد TeX Live؛ بسته‌ی اضافه‌ای لازم نیست.",
        r"% ----------------------------------------------------------------",
        r"\documentclass[12pt,a4paper]{article}",
        r"\usepackage{fontspec}",
        r"\usepackage{xepersian}",
        r"\settextfont{XB Niloofar}",
        r"\setlatintextfont{Times New Roman}",
        r"\usepackage{amsmath,amssymb,amsfonts}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{float}",
        r"\usepackage{xcolor}",
        r"\usepackage{mdframed}",
        r"\usepackage{enumitem}",
        r"\usepackage[colorlinks=true,linkcolor=blue]{hyperref}",
        "",
        r"% کادرها: هر برچسبِ متنِ کتاب یک محیط است، با شمارنده و رنگ خودش.",
        r"% شماره مثل اپ: «۲-۳» = کادر سوم از این نوع در بخش ۲.",
    ]
    for environment in environments:
        if environment in NO_FRAME:
            continue
        line, fill = BOX_COLOURS.get(environment, ("C9D8C0", "F7F7F2"))
        lines += [
            "",
            r"\definecolor{%sline}{HTML}{%s}" % (environment, line),
            r"\definecolor{%sfill}{HTML}{%s}" % (environment, fill),
            r"\newcounter{%sbox}[section]" % environment,
            # «۲-۳» با متن و رقم لاتین: در پاراگراف فارسی، خط‌تیره‌ی ریاضی و ارقام فارسی جای خود را عوض می‌کنند.
            r"\renewcommand{\the%sbox}{\text{\ifnum\value{section}>0 \thesection-\fi\arabic{%sbox}}}" % (
                environment, environment),
            r"\newenvironment{%s}" % environment,
            r"  {\par\medskip\refstepcounter{%sbox}%%" % environment,
            r"   \begin{mdframed}[backgroundcolor=%sfill,linecolor=%sline,linewidth=1pt,roundcorner=4pt]%%" % (
                environment, environment),
            r"   \noindent\textbf{\the%sbox}\quad\ignorespaces}" % environment,
            r"  {\end{mdframed}\par\medskip}",
        ]
    if "latin" in environments:
        lines += ["", r"% «:::لاتین»: چپ‌چین، بدون کادر.",
                  r"\newenvironment{latin}{\begin{LTR}\begin{quote}}{\end{quote}\end{LTR}}"]
    lines += [
        "",
        r"% «==آبی:…==» و «==قرمز:…==» (هایلایتِ متن)",
        r"\definecolor{hlblue}{HTML}{FFF3B0}",
        r"\definecolor{hlred}{HTML}{FFD9D9}",
        r"\newcommand{\hl}[1]{\colorbox{hlblue}{#1}}",
        r"\newcommand{\hlc}[1]{\colorbox{hlred}{#1}}",
        "",
    ]
    return lines


def _labels_in(lines: list[str]) -> list[str]:
    found: list[str] = []
    for line in lines:
        match = _BOX_OPEN.match(line.strip())
        if match:
            label = match.group(1).strip()
            if label not in found:
                found.append(label)
    return found


def chapter_to_tex(meta: dict, intro: list[str], sections: list[tuple[str, str, list[str]]]) -> str:
    """One chapter → a whole .tex document.

    `meta` holds the chapter's title, its number and the book's title; `intro` is the chapter's own text; each
    section is (title, id, body lines). The file compiles as it is, with XeLaTeX.
    """
    # `chapter_from_db` names the keys as the format does (chapter_title); a caller may also pass the short ones.
    title = meta.get("title") or meta.get("chapter_title") or "فصل"
    book_title = meta.get("book_title") or ""
    if not meta.get("number") and meta.get("chapter_number"):
        meta = dict(meta, number=meta["chapter_number"])
    number = meta.get("number")

    labels = _labels_in(intro)
    for _title, _slug, body in sections:
        labels += [label for label in _labels_in(body) if label not in labels]

    out = _preamble(labels)
    subtitle = " \\\\ \\large " + _escape(book_title) if book_title else ""
    out += ["", r"\title{" + _escape(title) + subtitle + "}"]
    out += [r"\author{}", r"\date{}", r"\begin{document}", r"\maketitle"]
    # No \setcounter{section}: `article` numbers sections from 1, and the chapter's own number is on the title
    # (a section counter set to the chapter's position turned chapter 99 into «بخش ۹۸»).
    out += [r"\tableofcontents", r"\newpage", ""]

    # The format of the book needs at least one «##» in a chapter file (parse_chapter refuses one without a section),
    # so a chapter that is all introduction is written as one section named after the chapter.
    if intro and not sections:
        sections = [(title, meta.get("chapter_slug") or "", intro)]
        intro = []

    if intro:
        out += blocks(intro)
        out.append("")

    for section_title, slug, body in sections:
        line = r"\section{" + inline(section_title) + "}"
        if slug:
            line += r"\label{" + _label_name(slug) + "}"
        out.append(line)
        out += blocks(body)
        out.append("")

    out += [r"\end{document}", ""]
    # A blank line between blocks, but never two: the format separates with one and the text has trailing spaces.
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text)


def chapter_node_to_tex(chapter) -> tuple[str, list[str]]:
    """A chapter in the database → (the .tex file, the media paths it refers to).

    The pieces come from `chapter_from_db`, so the .tex is built from the same chapter the .md export writes: what the
    editor shows and what Overleaf gets cannot drift apart.
    """
    from apps.catalog.exporter import chapter_from_db, export_chapter, media_paths

    parsed = chapter_from_db(chapter)
    intro = list(parsed.intro.full_lines) if parsed.intro else []
    sections = [(section.title, section.slug, list(section.full_lines)) for section in parsed.sections]
    tex = chapter_to_tex(parsed.meta, intro, sections)
    # The stored paths come from the .md export, which already knows them; the .tex only carries images/<basename>.
    return tex, media_paths(export_chapter(chapter))


def chapter_tex_bundle(chapter) -> tuple[str, bytes, str]:
    """(file name, data, content type): a .tex alone, or a ZIP with the .tex and its images/ folder.

    Same rule as `exporter.chapter_bundle` for the .md: a chapter without pictures is one readable file a professor can
    open in any editor; one with pictures needs the folder, or Overleaf shows an empty box where a diagram was.
    """
    import io
    import zipfile

    from django.core.files.storage import default_storage

    tex, paths = chapter_node_to_tex(chapter)
    if not paths:
        return f"{chapter.slug}.tex", tex.encode("utf-8"), "application/x-tex; charset=utf-8"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{chapter.slug}.tex", tex)
        archive.writestr("preamble.tex", "\n".join(_preamble(list(ENVIRONMENT_NAMES.keys()))) + "\n")
        for path in paths:
            if default_storage.exists(path):
                with default_storage.open(path, "rb") as handle:
                    archive.writestr(f"images/{posixpath.basename(path)}", handle.read())
    return f"{chapter.slug}.zip", buffer.getvalue(), "application/zip"


def book_tex_bundle(book) -> tuple[str, bytes, str]:
    """Generate a complete multi-chapter LaTeX project for the entire book.

    Archive structure:
      - main.tex (uses \\documentclass{book}, includes table of contents, and \\include for each chapter)
      - preamble.tex (global preamble, package definitions, and box environments)
      - chapters/
          - 01-slug.tex
          - 02-slug.tex
      - images/
    """
    import io
    import zipfile
    from django.core.files.storage import default_storage
    from apps.catalog.exporter import chapter_from_db, export_chapter, media_paths
    from apps.catalog.models import ContentNode

    chapters = list(book.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False))
    all_labels: list[str] = []
    chapter_files: list[tuple[str, str, str]] = []  # (folder_rel_path, tex_body, chapter_title)
    all_media_paths: set[str] = set()

    for i, chapter in enumerate(chapters, start=1):
        parsed = chapter_from_db(chapter)
        intro = list(parsed.intro.full_lines) if parsed.intro else []
        sections = [(section.title, section.slug, list(section.full_lines)) for section in parsed.sections]

        for label in _labels_in(intro):
            if label not in all_labels:
                all_labels.append(label)
        for _title, _slug, body in sections:
            for label in _labels_in(body):
                if label not in all_labels:
                    all_labels.append(label)

        for path in media_paths(export_chapter(chapter)):
            all_media_paths.add(path)

        # Build chapter content for book class
        ch_out = [
            r"\chapter{" + inline(chapter.title) + "}" + (r"\label{" + _label_name(chapter.slug) + "}" if chapter.slug else ""),
            "",
        ]
        if intro:
            ch_out += blocks(intro)
            ch_out.append("")
        for sec_title, sec_slug, sec_body in sections:
            line = r"\section{" + inline(sec_title) + "}"
            if sec_slug:
                line += r"\label{" + _label_name(sec_slug) + "}"
            ch_out.append(line)
            ch_out += blocks(sec_body)
            ch_out.append("")

        ch_tex = re.sub(r"\n{3,}", "\n\n", "\n".join(ch_out))
        ch_filename = f"chapters/{i:02d}-{chapter.slug}.tex"
        chapter_files.append((ch_filename, ch_tex, chapter.title))

    # Preamble adapted for book class
    preamble_lines = _preamble(all_labels or list(ENVIRONMENT_NAMES.keys()))
    # Replace documentclass article with book
    preamble_content = "\n".join(preamble_lines)
    preamble_content = preamble_content.replace(r"\documentclass[12pt,a4paper]{article}", r"\documentclass[12pt,a4paper]{book}")

    # Build main.tex
    main_lines = [
        r"% ----------------------------------------------------------------",
        r"%  پروژه کتاب کامل لاتک — ایجادشده از سامانه لیمو",
        r"%  کامپایل با XeLaTeX (فایل اصلی: main.tex)",
        r"% ----------------------------------------------------------------",
        r"\input{preamble.tex}",
        "",
        r"\title{" + _escape(book.title) + "}",
        r"\author{" + _escape(book.author or "") + "}",
        r"\date{\today}",
        "",
        r"\begin{document}",
        r"\maketitle",
        r"\tableofcontents",
        r"\newpage",
        "",
    ]
    for ch_path, _, _ in chapter_files:
        include_path = ch_path[:-4] if ch_path.endswith(".tex") else ch_path
        main_lines.append(r"\include{" + include_path + "}")

    main_lines += ["", r"\end{document}", ""]
    main_tex = "\n".join(main_lines)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main.tex", main_tex)
        archive.writestr("preamble.tex", preamble_content)
        for ch_path, ch_tex, _ in chapter_files:
            archive.writestr(ch_path, ch_tex)
        for path in all_media_paths:
            if default_storage.exists(path):
                with default_storage.open(path, "rb") as handle:
                    archive.writestr(f"images/{posixpath.basename(path)}", handle.read())

    return f"{book.slug}-latex.zip", buffer.getvalue(), "application/zip"

