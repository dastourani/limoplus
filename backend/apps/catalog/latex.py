"""
LaTeX → the chapter format of docs/content-format.md.

A professor writes their notes in LaTeX (usually on Overleaf, with xepersian) and uploads the .tex file or the whole
project as a ZIP. This module turns it into the same Markdown text the importer already understands, so the database,
the panel and the app stay exactly as they are: no second format, no second renderer.

    .tex / .zip ──► read_latex() ──► chapter Markdown text + images ──► importer.parse_chapter()

XeLaTeX only: nothing is built here (no TeX Live on the server, and no room for it), so \\ifxetex and friends are not
run — the text is read as written.

One rule decides what is kept: **a file LaTeX builds is dropped, a file the author wrote is kept.** Build output
(.aux .log .toc .out …) never reaches the importer; a missing image is a clear error the author can fix, not a blank.

Two rules decide how the text is read:

1. **Math is never touched.** Everything between $…$, $$…$$ and in math environments is copied as it is, before any
   command handling runs. (A converter that strips unknown commands first turns $\\frac{a}{b}$ into a pair of dollar
   signs. The tests keep that case.)
2. **An unknown command never stops the import.** Its braces are removed and the words inside kept; the author is
   told once per command which ones were dropped.
"""

from __future__ import annotations

import posixpath
import re

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# --- What a ZIP may contain ------------------------------------------------------------------------------------

# Made by LaTeX on every run: never part of the book.
BUILD_JUNK = {
    ".aux", ".log", ".out", ".toc", ".lof", ".lot", ".fls", ".fdb_latexmk", ".synctex", ".synctex.gz",
    ".bbl", ".blg", ".idx", ".ilg", ".ind", ".bcf", ".run.xml", ".nav", ".snm", ".vrb", ".thm", ".glo",
    ".ist", ".acn", ".acr", ".alg", ".loa", ".lol", ".xdv", ".dvi", ".ps", ".spl", ".brf", ".glsdefs",
}
# Not ours, but they may carry the author's own shortcuts (\newcommand), so they are read for those and forgotten.
STYLE_FILES = {".cls", ".sty"}
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif")
JUNK_FOLDERS = {"__MACOSX", ".git", ".svn"}
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def _suffix(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".synctex.gz"):
        return ".synctex.gz"
    return posixpath.splitext(lowered)[1]


def is_junk(name: str) -> bool:
    """A file of the ZIP that must not become part of the chapter."""
    parts = [p for p in name.replace("\\", "/").split("/") if p]
    if any(p in JUNK_FOLDERS for p in parts):
        return True
    base = parts[-1] if parts else ""
    if base.lower() in JUNK_NAMES or base.startswith(".#"):
        return True
    suffix = _suffix(base)
    # The compiled PDF is a picture of the source, not the source.
    if suffix == ".pdf":
        return True
    # A class or style file is not the chapter's text, but it is the author's own file: read_latex keeps it for the
    # \newcommand definitions inside (which the panel's «دستورهای فرمول» needs). So it is not junk here.
    return suffix in BUILD_JUNK


def is_text_file(name: str) -> bool:
    """A file whose text is the chapter: .tex only (a .cls/.sty is read for macros, never as text)."""
    return _suffix(name) == ".tex"


def is_style_file(name: str) -> bool:
    """A class or style file: read for the author's \\newcommand shortcuts, then dropped."""
    return _suffix(name) in STYLE_FILES


# --- Commands that do nothing in a book -----------------------------------------------------------------------

# Dropped with their arguments, silently: they only say where the page breaks.
SILENT_WITH_ARGS = {
    "vspace", "hspace", "vskip", "hskip", "vfill", "hfill", "newpage", "clearpage", "cleardoublepage",
    "pagebreak", "nopagebreak", "linebreak", "nolinebreak", "noindent", "indent", "centering", "raggedleft",
    "raggedright", "smallskip", "medskip", "bigskip", "quad", "qquad", "phantom", "hphantom", "vphantom",
    "documentclass", "usepackage", "RequirePackage", "setlength", "addtolength", "pagestyle", "thispagestyle",
    "bibliographystyle", "pagenumbering", "setcounter", "addtocounter", "setboolean", "geometry", "hypersetup",
    "graphicspath", "definecolor", "lstset", "tikzset", "usetikzlibrary", "pgfplotsset", "sisetup", "captionsetup",
    "newenvironment", "renewenvironment", "newtheorem", "DeclareMathOperator", "DeclareGraphicsExtensions",
    "newcommand", "renewcommand", "providecommand", "def", "let", "DeclareRobustCommand", "newcounter",
    # The set-up of a box the author built (our own export writes these too); never part of the text.
    "newsavebox", "savebox", "sbox", "newlength", "setlength", "settowidth", "fcolorbox", "colorbox", "lrbox",
    "pageref", "index", "glossary", "bibliography", "printbibliography", "nocite",
}
# Commands that stand alone (no arguments) and are simply removed.
SILENT_ALONE = {
    "maketitle", "tableofcontents", "listoffigures", "listoftables", "appendix", "frontmatter", "mainmatter",
    "backmatter", "hrule", "vrule", "item", "par", "newline", "linebreak", "bfseries", "itshape", "rmfamily",
    "sffamily", "ttfamily", "normalfont", "tiny", "scriptsize", "footnotesize", "small", "normalsize", "large",
    "Large", "LARGE", "huge", "Huge", "protect", "selectlanguage", "clearpage", "noindent", "centering",
    "ignorespaces", "medskip", "smallskip", "bigskip",
    "raggedright", "raggedleft", "tableofcontents", "listoffigures",
}
# Commands dropped together with their environment.
SILENT_ENVIRONMENTS = {"comment", "filecontents", "filecontents*"}

# Inline emphasis: only these become Markdown marks.
EMPHASIS = (("textbf", "**"), ("textit", "*"), ("emph", "*"))        # \hl becomes «==رنگ:…==» (see _highlight)
# Commands whose braces are markup, and the words inside are the text.
TEXT_WRAPPERS = {
    "textnormal", "textrm", "textsf", "texttt", "textsl", "textsc", "textup", "textmd", "mbox", "hbox",
    "mathrm", "mathbf", "mathit", "mathsf", "mathtt", "bm", "boldsymbol", "ensuremath", "textsuperscript",
    "textsubscript", "substack", "title", "author", "date", "thanks", "footnotetext", "fbox", "makebox",
    "framebox", "parbox", "raisebox", "resizebox", "scalebox", "rotatebox", "caption", "captionof",
    "texorpdfstring", "url", "href", "foreignlanguage", "lrbox", "smash", "overline", "underbrace", "overbrace",
}
# For these, only the last brace group is text (the earlier ones are settings: colour, width, language).
LAST_ARG_IS_TEXT = {
    "textcolor", "colorbox", "fcolorbox", "color", "parbox", "makebox", "framebox", "raisebox", "resizebox",
    "scalebox", "rotatebox", "href", "foreignlanguage", "texorpdfstring", "multicolumn", "multirow", "rule",
}

SECTIONING = {"part": 1, "chapter": 2, "section": 3, "subsection": 4, "subsubsection": 5, "paragraph": 6,
              "subparagraph": 6}

# LaTeX environments that are a labelled box in the book, with the same Persian label as the panel.
# The names of latex_export.ENVIRONMENT_NAMES are here too: the export writes «:::تله» as \\begin{trap}, and reading
# that file back must find the same box. One table, two directions — otherwise a chapter written and re-read by
# Lemo has boxes that look the same but lose their label.
BOX_ENVIRONMENTS = {
    "definition": "تعریف", "theorem": "قضیه", "lemma": "گزاره", "proposition": "گزاره", "corollary": "نتیجه",
    "example": "مثال", "exercise": "تمرین", "problem": "تمرین", "remark": "نکته", "note": "نکته",
    "hint": "نکته", "fact": "در یک نگاه", "question": "پرسش و پاسخ", "warning": "هشدار",
    # The rest of the panel's labels: the exported .tex writes these names, so the import must read them.
    "qa": "پرسش و پاسخ", "recall": "یادآوری", "counterexample": "مثال نقض", "trap": "تله",
    "important": "مهم", "ataglance": "در یک نگاه", "formula": "فرمول", "rule": "قاعده",
    "condition": "شرط کاربرد", "memorize": "حفظی", "plot": "نمودار", "terms": "واژه",
    "synonyms": "مترادف", "antonyms": "متضاد",
}
# Boxes that are numbered in the book (labels.NUMBERED): a \label inside becomes the box's name.
NUMBERED_BOXES = {"قضیه", "گزاره", "نتیجه", "مثال", "تمرین", "نمودار"}
# Copied as they are (the words are the text; the \commands inside are KaTeX's).
MATH_ENVIRONMENTS = {
    "equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*", "eqnarray",
    "eqnarray*", "displaymath", "math", "split", "aligned", "array", "matrix", "pmatrix", "bmatrix", "vmatrix",
    "Vmatrix", "cases", "flalign", "flalign*", "alignat", "alignat*", "dmath", "dmath*",
}
LIST_ENVIRONMENTS = {"itemize", "enumerate", "description", "compactitem", "compactenum", "asparaitem"}
TABLE_ENVIRONMENTS = {"tabular", "tabular*", "tabularx", "longtable", "array", "longtabu", "tabu"}
FIGURE_ENVIRONMENTS = {"figure", "figure*", "wrapfigure", "SCfigure", "subfigure", "subfigure*", "center"}
TABLE_FLOAT_ENVIRONMENTS = {"table", "table*", "longtable*"}

# Font and language set-up of xepersian/polyglossia: it only chooses a face, never text.
SETUP_COMMANDS = re.compile(
    r"\\(settextfont|setlatintextfont|setdigitfont|setmainfont|setsansfont|setmonofont|newfontfamily|"
    r"newfontface|defaultfontfeatures|setmathrm|setmathsf|setmathtt)\s*(\[[^\]]*\])?\s*\{[^}]*\}"
)


# --- Small helpers --------------------------------------------------------------------------------------------

def _read_group(text: str, start: int, opener: str = "{", closer: str = "}") -> tuple[str, int]:
    """The contents of the group starting at `start` and the index just after it closes."""
    if start >= len(text) or text[start] != opener:
        return "", start
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
        index += 1
    return text[start + 1 :], len(text)


def _skip_whitespace(text: str, start: int) -> int:
    while start < len(text) and text[start] in " \t\n":
        start += 1
    return start


def _strip_comments(text: str) -> str:
    """A comment runs from an unescaped % to the end of its line."""
    out = []
    for line in text.split("\n"):
        cut = len(line)
        index = 0
        while index < len(line):
            if line[index] == "\\":
                index += 2
                continue
            if line[index] == "%":
                cut = index
                break
            index += 1
        out.append(line[:cut])
    return "\n".join(out)


def extract_tex_sources(filename: str, data: bytes) -> list[str]:
    """Extract .tex, .cls and .sty file contents from a .tex upload or a ZIP project."""
    import io
    import zipfile
    lowered = filename.lower()
    if lowered.endswith(".tex"):
        return [data.decode("utf-8-sig", errors="replace")]
    if lowered.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                out = []
                for info in archive.infolist():
                    if not info.is_dir() and info.filename.lower().endswith((".tex", ".cls", ".sty")):
                        out.append(archive.read(info.filename).decode("utf-8-sig", errors="replace"))
                return out
        except Exception:
            return []
    return []


def discover_custom_environments(*sources: str) -> dict[str, str]:
    """Find custom environment definitions like \newtheorem{mythm}{قضیه اساسی} in LaTeX sources."""
    discovered: dict[str, str] = {}
    for source in sources:
        cleaned = _strip_comments(source)
        for m in re.finditer(r"\\newtheorem\*?\s*\{([^}]+)\}(?:\[[^\]]*\])?\s*\{([^}]+)\}", cleaned):
            discovered[m.group(1).strip()] = m.group(2).strip()
        for m in re.finditer(r"\\declaretheorem\s*\[([^\]]*?)\]\s*\{([^}]+)\}", cleaned):
            opts, env = m.group(1), m.group(2).strip()
            nm = re.search(r"name\s*=\s*([^,\]]+)", opts)
            if nm:
                discovered[env] = nm.group(1).strip()
        for m in re.finditer(r"\\declaretheorem\s*\{([^}]+)\}\s*\[([^\]]*?)\]", cleaned):
            env, opts = m.group(1).strip(), m.group(2)
            nm = re.search(r"name\s*=\s*([^,\]]+)", opts)
            if nm:
                discovered[env] = nm.group(1).strip()
        for m in re.finditer(r"\\newenvironment\*?\s*\{([^}]+)\}", cleaned):
            env = m.group(1).strip()
            if env not in discovered and env not in BOX_ENVIRONMENTS:
                discovered[env] = env
    return discovered


STANDARD_IGNORED_ENVIRONMENTS = (
    {"document"}
    | MATH_ENVIRONMENTS
    | LIST_ENVIRONMENTS
    | TABLE_ENVIRONMENTS
    | FIGURE_ENVIRONMENTS
    | TABLE_FLOAT_ENVIRONMENTS
    | set(BOX_ENVIRONMENTS.keys())
)


def extract_environment_snippets(*sources: str, max_snippets_per_env: int = 3) -> dict[str, list[str]]:
    """Scan LaTeX sources for occurrences of environments and extract clean text snippets."""
    snippets_by_env: dict[str, list[str]] = {}
    pattern = re.compile(r"\\begin\{([a-zA-Z0-9_\*]+)\}")

    for source in sources:
        cleaned = _strip_comments(source)
        pos = 0
        while pos < len(cleaned):
            m = pattern.search(cleaned, pos)
            if not m:
                break
            env = m.group(1).strip()
            start = m.end()
            depth = 1
            curr = start
            end_pat = re.compile(r"\\(begin|end)\{" + re.escape(env) + r"\}")
            end_pos = None
            while depth > 0:
                em = end_pat.search(cleaned, curr)
                if not em:
                    break
                if em.group(1) == "begin":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        end_pos = em.start()
                        break
                curr = em.end()
            if end_pos is not None:
                body = cleaned[start:end_pos].strip()
                # Clean snippet for human preview
                snippet = re.sub(r"\\label\{[^}]*\}", "", body)
                snippet = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^}]*)\}", r"\1", snippet)
                snippet = re.sub(r"\\[a-zA-Z]+", " ", snippet)
                snippet = re.sub(r"\s+", " ", snippet).strip()
                if snippet:
                    if len(snippet) > 160:
                        snippet = snippet[:157] + "..."
                    cur_list = snippets_by_env.setdefault(env, [])
                    if len(cur_list) < max_snippets_per_env and snippet not in cur_list:
                        cur_list.append(snippet)
            pos = start
    return snippets_by_env


def discover_all_environments(*sources: str) -> dict[str, dict]:
    """Find custom environments defined via \newtheorem, plus any unknown \begin{...} blocks with counts and snippets."""
    explicit_titles = discover_custom_environments(*sources)
    snippets = extract_environment_snippets(*sources)

    # Count occurrences
    counts: dict[str, int] = {}
    pattern = re.compile(r"\\begin\{([a-zA-Z0-9_\*]+)\}")
    for source in sources:
        cleaned = _strip_comments(source)
        for m in pattern.finditer(cleaned):
            e = m.group(1).strip()
            counts[e] = counts.get(e, 0) + 1

    all_envs: dict[str, dict] = {}
    candidate_keys = (set(explicit_titles.keys()) | set(counts.keys())) - STANDARD_IGNORED_ENVIRONMENTS

    for env in candidate_keys:
        title = explicit_titles.get(env, env)
        cnt = counts.get(env, 0)
        snips = snippets.get(env, [])
        all_envs[env] = {
            "title": title,
            "count": cnt,
            "snippets": snips,
            "has_explicit_def": env in explicit_titles,
        }

    # Sort primarily by frequency (descending)
    return dict(sorted(all_envs.items(), key=lambda item: item[1]["count"], reverse=True))


def infer_label_for_title(title: str, available_labels: list[str]) -> str | None:
    """Match a Persian theorem/box title to an official Limo label."""
    t = title.strip()
    if t in available_labels:
        return t
    keywords = [
        ("قضیه", "قضیه"), ("تعریف", "تعریف"), ("مثال نقض", "مثال نقض"),
        ("مثال", "مثال"), ("تمرین", "تمرین"), ("نکته", "نکته"),
        ("گزاره", "گزاره"), ("لم", "گزاره"), ("نتیجه", "نتیجه"),
        ("فرمول", "فرمول"), ("قاعده", "قاعده"), ("یادآوری", "یادآوری"),
        ("هشدار", "هشدار"), ("تله", "تله"), ("مهم", "مهم"),
    ]
    for kw, target in keywords:
        if kw in t and target in available_labels:
            return target
    return None


def _slug_name(label: str) -> str:
    """\\label{fig:sin} → a name the book accepts ([[#sin]]): Latin letters, digits and dashes.

    «مثال ۳-۵» is made by the app from the number, so the name only has to be unique and stable inside the chapter.
    """
    name = re.sub(r"^(fig|tab|eq|sec|ch|thm|def|ex|lst|alg|plot|app)[:\-]", "", label.strip(), flags=re.IGNORECASE)
    name = re.sub(r"[^\w\-]+", "-", name, flags=re.UNICODE).strip("-")
    return name[:60] or "ref"


# --- Macros ---------------------------------------------------------------------------------------------------

_MACRO_DEFINITION = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareMathOperator\*?)\s*"
    r"(?:\{\s*\\[A-Za-z@]+\s*\}|\\[A-Za-z@]+)"
    r"(?:\s*\[\d\])?(?:\s*\[[^\]]*\])?\s*\{",
)


# A box the author built: \newenvironment{note}{begin code}{end code}. Both bodies are settings, never text.
_NEW_ENVIRONMENT = re.compile(r"\\(?:newenvironment|renewenvironment)\*?\s*\{[^}]*\}")


def _drop_macro_definitions(text: str) -> str:
    """Remove \\newcommand{\\R}{\\mathbb{R}} and the like, with the body that follows them.

    A \\newenvironment goes too, with both of its bodies: its «begin code» often holds a \\begin{mdframed}[…] whose
    options would otherwise end up on the page as words («[backgroundcolor=notefill]»). The definitions were already
    collected by `collect_macros`.
    """
    while True:
        found = _MACRO_DEFINITION.search(text)
        new_environment = _NEW_ENVIRONMENT.search(text)
        if new_environment and (not found or new_environment.start() < found.start()):
            end = new_environment.end()
            for _ in range(2):   # the begin code and the end code
                spaces = re.match(r"\s*", text[end:])
                end += spaces.end()
                if end < len(text) and text[end] == "{":
                    _, end = _read_group(text, end)
            text = text[: new_environment.start()] + text[end:]
            continue
        if not found:
            return text
        _, end = _read_group(text, found.end() - 1)
        text = text[: found.start()] + text[end:]


def collect_macros(*sources: str) -> dict[str, str]:
    """The author's own shortcuts: \\newcommand{\\R}{\\mathbb{R}} → {"\\\\R": "\\\\mathbb{R}"}.

    Read from the chapter and from the .cls/.sty of the ZIP (a professor's macros often live there). The same names
    go to the panel's «دستورهای فرمول» so KaTeX knows them, wherever they are used (math included).
    """
    macros: dict[str, str] = {}
    for source in sources:
        for name, body, arguments in _iter_macros(_strip_comments(source)):
            macros[name] = (body, arguments)  # type: ignore[assignment]
    return macros  # type: ignore[return-value]


def _iter_macros(text: str):
    pattern = re.compile(
        r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator)(\*?)\s*"
        r"(?:\{\s*\\([A-Za-z@]+)\s*\}|\\\\([A-Za-z@]+))"
        r"(?:\s*\[(\d)\])?"
        r"(?:\s*\[([^\]]*)\])?"
        r"\s*\{"
    )
    for match in pattern.finditer(text):
        command = match.group(1)
        name = "\\" + (match.group(3) or match.group(4))
        arguments = int(match.group(5) or 0)
        body, _ = _read_group(text, match.end() - 1)
        if not body.strip() and command != "DeclareMathOperator":
            continue
        if command == "DeclareMathOperator":
            yield name, f"\\operatorname{{{body.strip()}}}", 0
        else:
            # A default in […] (\newcommand{\limx}[1][x]{…}): a use without the argument writes it.
            default = match.group(6)
            if default is not None and arguments:
                body = body.replace("#1", default)
                arguments = 0
            yield name, body.strip(), arguments


_MATH_COMMAND = re.compile(
    r"\\(?:mathbb|mathcal|mathrm|mathbf|mathit|mathsf|mathtt|operatorname|boldsymbol|bm|lVert|rVert|"
    r"lvert|rvert|frac|dfrac|tfrac|sqrt|sum|prod|int|lim|infty|alpha|beta|gamma|delta|theta|lambda|mu|nu|"
    r"sigma|phi|psi|omega|pi|partial|nabla|times|cdot|pm|mp|leq|geq|neq|approx|equiv|in|notin|subset|"
    r"subseteq|cup|cap|forall|exists|to|rightarrow|Rightarrow|leftrightarrow|ldots|dots|quad|qquad|"
    r"begin|end|text|overline|underline|vec|hat|bar|tilde|dot|ddot|ell|hbar|Re|Im)\b")


def _looks_like_math(body: str) -> bool:
    """A macro body of math commands (\\mathbb{R}, \\operatorname{sgn}, \\lVert #1 \\rVert) is a formula."""
    return bool(_MATH_COMMAND.search(body)) or bool(re.search(r"[_^]", body))


def expand_macros(text: str, macros: dict) -> str:
    """Write out the author's shortcuts — outside math only.

    Inside math they stay: KaTeX gets the same definitions in the panel's «دستورهای فرمول», and expanding there would
    both break a formula's LaTeX and lose the point of a formula macro.
    """
    if not macros:
        return text
    pieces = _split_math(text)
    for position, (is_math, chunk) in enumerate(pieces):
        if is_math:
            continue
        pieces[position] = (False, _expand_plain(chunk, macros))
    return "".join(chunk for _, chunk in pieces)


def _expand_plain(text: str, macros: dict) -> str:
    for _ in range(3):  # a macro built on other macros
        before = text
        for name in sorted(macros, key=len, reverse=True):
            body, arguments = macros[name] if isinstance(macros[name], tuple) else (macros[name], 0)
            pattern = re.compile(re.escape(name) + r"(?![A-Za-z@])")
            if not pattern.search(text):
                continue
            text = _replace_macro(text, pattern, body, arguments)
        if text == before:
            break
    return text


def _replace_macro(text: str, pattern: re.Pattern, body: str, arguments: int) -> str:
    out = []
    index = 0
    for match in pattern.finditer(text):
        out.append(text[index : match.start()])
        cursor = match.end()
        args = []
        for _ in range(arguments):
            cursor = _skip_whitespace(text, cursor)
            if cursor < len(text) and text[cursor] == "{":
                arg, cursor = _read_group(text, cursor)
            elif cursor < len(text) and text[cursor] == "[":
                arg, cursor = _read_group(text, cursor, "[", "]")
            else:
                arg, cursor = text[cursor : cursor + 1], cursor + 1
            args.append(arg.strip())
        filled = body
        for number, arg in enumerate(args, start=1):
            filled = filled.replace(f"#{number}", arg)
        # A shortcut for math (e.g. R for the real numbers) used in the prose: it is still a formula, so it
        # is put in dollars and KaTeX draws it. Written out bare, the words would read as nothing at all.
        # and KaTeX draws it — written out bare, the words would read as «» (the panel's «دستورهای فرمول» has it too).
        if _looks_like_math(filled):
            filled = f"${filled}$"
        out.append(filled)
        index = cursor
    out.append(text[index:])
    return "".join(out)


# --- Math protection ------------------------------------------------------------------------------------------

_MATH_MARK = "\x00math{}\x00"


def _split_math(text: str) -> list[tuple[bool, str]]:
    """Break the text into (is_math, chunk) pieces: $…$, $$…$$, \\[…\\] and \\(…\\) are math.

    This is the safety net of the whole converter: no command handling ever runs inside these pieces.
    """
    pieces: list[tuple[bool, str]] = []
    pattern = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$|\\\[.+?\\\]|\\\(.+?\\\)", re.S)
    index = 0
    for match in pattern.finditer(text):
        if match.start() > index:
            pieces.append((False, text[index : match.start()]))
        pieces.append((True, match.group(0)))
        index = match.end()
    if index < len(text):
        pieces.append((False, text[index:]))
    return pieces


def _protect_math(text: str) -> tuple[str, list[str]]:
    """Replace every math piece with a placeholder; the pieces come back untouched at the end."""
    pieces: list[str] = []
    out = []
    for is_math, chunk in _split_math(text):
        if is_math:
            out.append(_MATH_MARK.format(len(pieces)))
            pieces.append(chunk)
        else:
            out.append(chunk)
    return "".join(out), pieces


def _restore_math(text: str, pieces: list[str]) -> str:
    for number, chunk in enumerate(pieces):
        text = text.replace(_MATH_MARK.format(number), chunk)
    return text


# --- The converter --------------------------------------------------------------------------------------------

def _without_math(text: str, apply=None) -> str:
    """Run a rewrite on the words of a line, with the formulas ($…$ and $$…$$) held aside.

    KaTeX's TeX is TeX: a brace inside $…$ is an argument, not grouping, and no rewrite meant for the prose may touch
    it. Without this, the brace-stripper of a table cell turned \\frac{x^2}{2} into \\fracx^22.
    """
    pieces: list[str] = []

    def hold(match):
        pieces.append(match.group(0))
        return "\x00%d\x00" % (len(pieces) - 1)

    kept = re.sub(r"\$\$.+?\$\$|\$[^$\n]+?\$", hold, text, flags=re.S)
    kept = apply(kept) if apply else kept
    for number, formula in enumerate(pieces):
        kept = kept.replace("\x00%d\x00" % number, formula)
    return kept


def _strip_preamble(text: str) -> str:
    """Everything before \\begin{document}: the class, the packages, the author's own \\newenvironment.

    The preamble of a real chapter is full of definitions — a box built with `mdframed`, a colour, a counter — and the
    reader has no business turning those settings into prose. The body is what the book keeps; the macro definitions
    were already collected by `collect_macros`, and a custom environment the author uses in the text is still read by
    `_environment` (with one warning and the text kept).
    """
    match = re.search(r"\\(?:begin|end)\s*\{document\}", text)
    if not match:
        return text   # a fragment without a document environment: all of it is text
    return text[match.end():]


class Converter:
    """One .tex document → the chapter Markdown of docs/content-format.md."""

    def __init__(self, text: str, macros: dict | None = None, sources: dict[str, str] | None = None, custom_boxes: dict[str, str] | None = None):
        self.raw = text
        # The author's own shortcuts, read from the text itself when the caller did not pass the ZIP's classes too.
        self.macros = collect_macros(text) if macros is None else macros
        self.custom_boxes = dict(custom_boxes or {})
        # The other .tex files of the ZIP, by name without extension, for \input / \include.
        self.sources = sources or {}
        self.warnings: list[str] = []
        self.unknown: set[str] = set()
        self.images: dict[str, bytes] = {}
        self.needed_images: set[str] = set()
        self.references: dict[str, str] = {}   # label → box kind («مثال»), for the report
        self._labels_seen: set[str] = set()
        self._converted = False
        # Set by the caller (the file name, the book page): the chapter's «شناسه-فصل» and «عنوان».
        self.slug = ""
        self.title = ""
        # \title{…} names the chapter in a document that has no \chapter (an `article`, or the .tex of an export).
        title = re.search(r"\\title\s*\{", _strip_comments(self.raw))
        if title:
            with_title, _ = _read_group(_strip_comments(self.raw), title.end() - 1)
            # «حد \\ \large ریاضی عمومی ۱»: the book's title is the second line, not part of the chapter's. Take the
            # first line only — the rest is a subtitle whose size command would be read as words.
            with_title = re.split(r"\\\\|\n", with_title)[0]
            self.title = self._inline(with_title).strip()
        self.book = None
        # The headings met, in order: (level, title, name). The first is the chapter's title when none was given.
        self.headings: list[tuple[int, str, str | None]] = []

    # -- public --

    def to_chapter(self) -> str:
        """The chapter file the importer reads: the front matter of docs/content-format.md, then the text.

        «شناسه-کتاب» و «کتاب» are left out on purpose: when a chapter is uploaded into a book the importer fills them
        from the book itself, and a .tex file has no way to know them. «شناسه-فصل» comes from the file name (the
        caller sets it), «عنوان» from the first heading of the document.
        """
        body = self.to_markdown()
        title = self.title or (self.headings[0][1] if self.headings else "")
        slug = self.slug or "ch1"
        header = ["---"]
        # The book lines come from the book the chapter is uploaded into: a .tex file cannot know them.
        if self.book is not None:
            header.append(f"شناسه-کتاب: {self.book.slug}")
            header.append(f"کتاب: {self.book.title}")
        header.append(f"شناسه-فصل: {slug}")
        if title:
            header.append(f"عنوان: {title}")
        header.append("---")
        return "\n".join(header) + "\n\n" + body

    def to_markdown(self) -> str:
        text = self._prepare(self.raw)
        text = self._inline_inputs(text)
        text = expand_macros(text, self.macros)
        # A heading or an environment often follows other text on the same line (after \input, after a dropped
        # \documentclass); the block reader works line by line, so they get a line of their own first.
        text = re.sub(r"[ \t]*(?=\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph|begin|end)\b)",
                      "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return self._blocks(text).strip() + "\n"

    def _prepare(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _strip_comments(text)
        # The title block of a document: \\title, \\author, \\date — read into the front matter (see __init__), and
        # no part of the text. \\maketitle prints them; it prints nothing in the book.
        text = re.sub(r"\\(title|author|date|thanks)\s*\{[^{}]*\}", "", text)
        text = re.sub(r"\\maketitle\b", "", text)
        # The author's definitions are collected for the panel's «دستورهای فرمول»; in the text they are no longer
        # needed (KaTeX knows the name), and rewriting them here would put \mathbb into the prose.
        text = _drop_macro_definitions(text)
        text = SETUP_COMMANDS.sub("", text)
        text = re.sub(r"\\(begin|end)\s*\{document\}", "", text)
        text = _strip_preamble(text)
        # \ifxetex … \else … \fi and the other conditionals: keep the branches as written, drop the switches.
        text = re.sub(r"\\(ifxetex|ifluatex|ifpdf|ifPDFTeX|ifXeTeX|ifLuaTeX|ifdefined|ifcsname)\b", "", text)
        text = re.sub(r"\\(else|fi)\b", "", text)
        return text

    def _inline_inputs(self, text: str, depth: int = 0) -> str:
        """\\input{ch1/part} and \\include{part} become their file's text; a missing file is one clear warning."""
        if depth > 6:  # a file that includes itself
            return text

        def replace(match):
            name = match.group(1).strip()
            body = self.sources.get(name) or self.sources.get(name + ".tex")
            if body is None:
                self._warn_once(f"فایل «{name}» که با \\input صدا زده شده داخل ZIP نیست؛ جایش خالی ماند.")
                return ""
            # A file included mid-line must still start its own block, or a \section inside it would read as prose.
            return "\n" + self._inline_inputs(self._prepare(body), depth + 1) + "\n"

        return re.sub(r"\\(?:input|include|subfile)\s*\{([^}]+)\}", replace, text)

    def _warn_once(self, message: str):
        if message not in self.warnings:
            self.warnings.append(message)

    # -- block level --

    def _blocks(self, text: str) -> str:
        """Walk the document once, deciding block by block: headings, boxes, lists, tables, math, prose."""
        out: list[str] = []
        lines = text.split("\n")
        index = 0
        buffer: list[str] = []

        def flush():
            if buffer:
                out.append(self._prose("\n".join(buffer)))
                buffer.clear()

        while index < len(lines):
            line = lines[index]
            stripped = line.strip()

            heading = re.match(
                r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*(?:\[[^\]]*\])?\s*", stripped)
            if heading:
                title, rest = self._heading_of(stripped, heading)
                flush()
                out.append(self._heading(SECTIONING[heading.group(1)], title, self._label_in(rest)))
                # «\section{حد} متنِ بعدش» on one line: the text after the title is the section's first paragraph.
                rest = re.sub(r"\\label\s*\{[^}]*\}", "", rest).strip()
                if rest:
                    index += 1
                    buffer.append(rest)
                    continue
                index += 1
                continue

            begin = re.match(r"\\begin\s*\{([^}]+)\}", stripped)
            if begin:
                flush()   # the text before a box is its own paragraph, not the one after it
                env = begin.group(1).strip()
                end_index = self._find_end(lines, index, env)
                # The environment's text is what sits after \begin{env} on its line, the lines between, and what
                # comes before \end{env} on the last line. All three matter: \label and \caption often ride along
                # on the \begin or \end line, and dropping them lost the names and captions.
                if end_index == index:
                    # All on one line: \\begin{env} … \\end{env} — the text is what lies between them.
                    line = lines[index]
                    start_at = begin.end()
                    stop_at = line.rfind("\\end")
                    body = line[start_at:stop_at] if stop_at > start_at else line[start_at:]
                else:
                    pieces = [lines[index][begin.end():]] + lines[index + 1 : end_index]
                    last = lines[end_index]
                    pieces.append(last[: last.rfind("\\end")] if "\\end" in last else last)
                    body = "\n".join(pieces)
                out.append(self._environment(env, body, stripped))
                index = end_index + 1
                continue

            if stripped == r"\[":
                flush()
                end = index + 1
                chunk = []
                while end < len(lines) and lines[end].strip() != r"\]":
                    chunk.append(lines[end])
                    end += 1
                out.append("$$" + "\n".join(chunk).strip() + "$$")
                index = end + 1
                continue

            if re.match(r"\\(maketitle|tableofcontents|listoffigures|listoftables|newpage|clearpage|"
                        r"cleardoublepage|appendix|frontmatter|mainmatter|backmatter|printbibliography)\b", stripped):
                flush()
                index += 1
                continue

            buffer.append(line)
            index += 1
        flush()
        return "\n\n".join(part for part in out if part.strip())

    def _heading_of(self, stripped: str, match: re.Match) -> tuple[str, str]:
        cursor = match.end()
        title, cursor = _read_group(stripped, cursor)
        return self._inline(title).strip(), stripped[cursor:]

    def _heading(self, level: int, title: str, name: str | None) -> str:
        """The chapter's own title is the file's, so \\chapter names the chapter instead of starting a section.

        In the book, a «section» is «##» and a «subsection» is «###» (docs/content-format.md keeps only two depths);
        deeper levels stay deeper, which the renderer shows smaller.
        """
        self.headings.append((level, title, name))
        if level <= 2 and not self.title:
            # \chapter{…} (or \part{…}): the chapter's title, which the caller puts in the front matter.
            self.title = title
            return ""
        depth = 3 if level == 4 else 2 if level == 3 else min(level - 2, 4)
        marks = "#" * depth
        return f"{marks} {title}" + (f" {{#{name}}}" if name else "")

    def _label_in(self, rest: str) -> str | None:
        found = re.search(r"\\label\s*\{([^}]+)\}", rest)
        if not found:
            return None
        name = _slug_name(found.group(1))
        if name in self._labels_seen:
            suffix = 2
            while f"{name}-{suffix}" in self._labels_seen:
                suffix += 1
            name = f"{name}-{suffix}"
        self._labels_seen.add(name)
        return name

    def _find_end(self, lines: list[str], start: int, env: str) -> int:
        """The line of the \\end{env} that closes the one on line `start` (nested ones counted)."""
        depth = 0
        pattern = re.compile(r"\\(begin|end)\s*\{" + re.escape(env) + r"\}")
        for index in range(start, len(lines)):
            for found in pattern.finditer(lines[index]):
                depth += 1 if found.group(1) == "begin" else -1
                if depth == 0:
                    return index
        self._warn_once(f"محیط «{env}» بسته نشده بود؛ تا آخر فایل خوانده شد.")
        return len(lines) - 1

    # -- environments --

    def _environment(self, env: str, body: str, opening: str) -> str:
        # The environment's own arguments are settings, not text: the {cc} of a tabular, the [width] of a figure.
        if env in TABLE_ENVIRONMENTS and env != "array":
            body = re.sub(r"^\s*\{[^}]*\}\s*", "", body, count=1)
        elif env in FIGURE_ENVIRONMENTS:
            body = re.sub(r"^\s*(\[[^\]]*\]\s*)?(\{[^}]*\}\s*)?", "", body, count=1)
        elif env in TABLE_FLOAT_ENVIRONMENTS:
            # «\begin{table}[H]»: the placement option ([H] [htbp] [t]) is a setting, not the author's words — it used
            # to survive as a bare «[H]» line above the table.
            body = re.sub(r"^\s*\[[^\]]*\]\s*", "", body, count=1)
        elif env in ("mdframed", "tcolorbox", "mdframed*", "shaded", "framed", "adjustbox", "minipage"):
            # Framing settings, not text: \begin{mdframed}[backgroundcolor=…,linewidth=1pt]
            body = re.sub(r"^\s*(\[[^\]]*\]\s*)?(\{[^}]*\}\s*)?", "", body, count=1)
        if env in SILENT_ENVIRONMENTS:
            return ""
        if env in MATH_ENVIRONMENTS:
            return self._math_environment(env, body)
        if env in LIST_ENVIRONMENTS:
            return self._list(env, body)
        if env in TABLE_ENVIRONMENTS:
            return self._table(body)
        if env in TABLE_FLOAT_ENVIRONMENTS:
            return self._table_float(body)
        if env in ("figure", "figure*", "wrapfigure", "SCfigure"):
            return self._figure(body)
        if env in ("subfigure", "subfigure*"):
            return self._blocks(body)
        if env in ("center", "flushleft", "flushright", "minipage", "small", "footnotesize", "large", "quotation",
                   "quote", "abstract", "titlepage", "adjustbox", "landscape", "mdframed"):
            return self._blocks(body)
        if env in ("lstlisting", "verbatim", "verbatim*", "minted", "alltt"):
            return self._code(env, body, opening)
        if env in ("tikzpicture", "pgfpicture", "tikzfigure", "axis"):
            return self._tikz(body)
        if env in ("algorithm", "algorithm*", "algorithm2e", "algorithmic", "algorithmicx", "algpseudocode"):
            return self._algorithm(body, env)
        box_label = self.custom_boxes.get(env) or BOX_ENVIRONMENTS.get(env)
        if box_label:
            return self._box(box_label, body, opening)
        # An unknown environment is not a reason to lose the text inside it.
        self._warn_once(f"محیط «{env}» شناخته نشد؛ متن داخلش بدون کادر آورده شد.")
        return self._blocks(body)

    def _math_environment(self, env: str, body: str) -> str:
        name = self._label_in(body)
        body = re.sub(r"\\label\s*\{[^}]*\}", "", body).strip()
        body = re.sub(r"\\(nonumber|notag)\b", "", body)
        # KaTeX reads \\ as a line break inside an aligned environment; a bare math environment is left as it is.
        if env in ("equation", "equation*", "displaymath", "math", "dmath", "dmath*"):
            return "$$" + body + "$$" + (f" {{#{name}}}" if name else "")
        return "$$\\begin{" + env.replace("*", "") + "}" + body + "\\end{" + env.replace("*", "") + "}$$" + (
            f" {{#{name}}}" if name else "")

    def _box(self, label: str, body: str, opening: str) -> str:
        # A name on the \\begin line is the box's own name, whatever the label; inside the body only a numbered box
        # takes one, because there the \\label usually belongs to a formula or a figure the box holds.
        name = self._label_in(opening)
        if name is None and label in NUMBERED_BOXES:
            name = self._label_in(body)
        body = re.sub(r"\\(label|index|glossary)\s*\{[^}]*\}", "", body)
        inner = self._blocks(body).strip()
        head = f":::{label}" + (f" {{#{name}}}" if name else "")
        return f"{head}\n{inner}\n:::"

    def _list(self, env: str, body: str) -> str:
        items = self._items(body)
        out = []
        for position, item in enumerate(items, start=1):
            text = self._blocks(item).strip()
            # A list item is one line of Markdown: its paragraphs become line breaks.
            text = re.sub(r"\n\s*\n", "\n", text).replace("\n", "  \n")
            if env in ("enumerate", "compactenum"):
                out.append(f"{position}. {text}")
            elif env in ("description",):
                term, _, meaning = text.partition("\n")
                out.append(f"- **{term.strip()}**" + (f": {meaning.strip()}" if meaning.strip() else ""))
            else:
                out.append(f"- {text}")
        return "\n".join(out)

    def _items(self, body: str) -> list[str]:
        parts = re.split(r"\\item\b", body)
        items = []
        for part in parts[1:]:
            # «\item[الف]»: a custom marker; the book's lists are plain, so it goes.
            part = re.sub(r"^\s*\[[^\]]*\]\s*", "", part)
            items.append(part.strip())
        return items

    # -- tables --

    def _table(self, body: str) -> str:
        rows = self._rows(body)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        header, rest = rows[0], rows[1:]
        out = ["| " + " | ".join(self._cell(c) for c in header) + " |",
               "| " + " | ".join("---" for _ in header) + " |"]
        for row in rest:
            out.append("| " + " | ".join(self._cell(c) for c in row) + " |")
        return "\n".join(out)

    def _table_float(self, body: str) -> str:
        """A table float: the tabular inside becomes the table, its \\caption the line above it."""
        caption, body = self._take_caption(body)
        name = self._label_in(body)
        body = re.sub(r"\\label\s*\{[^}]*\}", "", body)
        inner = self._blocks(body).strip()
        parts = []
        if caption:
            parts.append(f"**{caption}**")
        if name:
            parts.append(f"{{#{name}}}")
        parts.append(inner)
        return "\n\n".join(p for p in parts if p)

    def _take_caption(self, body: str) -> tuple[str, str]:
        found = re.search(r"\\caption\s*(?:\[[^\]]*\])?\s*\{", body)
        if not found:
            return "", body
        text, after = _read_group(body, found.end() - 1)
        caption = self._inline(text).strip()
        return caption, body[: found.start()] + body[after:]

    def _rows(self, body: str) -> list[list[str]]:
        body = re.sub(r"\\toprule|\\midrule|\\bottomrule|\\hline|\\endhead|\\endfirsthead|\\endfoot|\\endlastfoot", "", body)
        body = re.sub(r"\\(cline|cmidrule|addlinespace|specialrule)\s*(\([^)]*\))?\s*(\{[^}]*\})?", "", body)
        rows = []
        for chunk in re.split(r"\\\\(?!\[)", body):
            chunk = chunk.strip()
            if not chunk:
                continue
            rows.append([cell.strip() for cell in re.split(r"(?<!\\)&", chunk)])
        return rows

    def _cell(self, cell: str) -> str:
        cell = cell.strip()
        # \multicolumn{2}{c}{text} → its text: a Markdown table has no merged cells.
        while True:
            found = re.search(r"\\multicolumn\s*\{\s*\d+\s*\}\s*\{[^}]*\}\s*\{", cell)
            if not found:
                break
            inner, after = _read_group(cell, found.end() - 1)
            cell = cell[: found.start()] + inner + cell[after:]
        cell = re.sub(r"\\multirow\s*\{\s*\d+\s*\}\s*\{[^}]*\}\s*\{([^}]*)\}", r"\1", cell)
        cell = self._inline(cell)
        # A cell's braces group nothing for the book: {a} → a. But a formula's braces are its own — \frac{x^2}{2}
        # lost both its arguments here, and the cell came out as «\fracx^22».
        cell = _without_math(cell, lambda text: re.sub(r"(?<!\\)[{}]", "", text))
        return cell.replace("|", "\\|").strip()

    # -- figures --

    def _figure(self, body: str) -> str:
        """\\begin{figure} … \\includegraphics … \\caption … \\end{figure} → the picture with its caption under it.

        The book has no «شکل» label, so a figure is not a box: an image with a caption already is one. When the
        author gave the figure a name, a «:::نکته» line under it carries the name so [[#name]] finds it.
        """
        caption, body = self._take_caption(body)
        name = self._label_in(body)
        body = re.sub(r"\\label\s*\{[^}]*\}", "", body)
        body = re.sub(r"\\centering\b", "", body)
        inner = self._blocks(body).strip()
        if not inner:
            return ""
        if caption:
            # The image's own caption line: ![](file) → ![caption](file)
            inner = re.sub(r"!\[\]\(([^)]+)\)", lambda m: f"![{caption}]({m.group(1)})", inner, count=1)
            if "![" not in inner:
                inner = f"{inner}\n\n*{caption}*"
        if name:
            inner = f"{inner}\n\n{{#{name}}}"
        return inner

    # -- code and algorithms --

    def _code(self, env: str, body: str, opening: str) -> str:
        language = ""
        if env == "minted":
            found = re.match(r"\\begin\s*\{minted\}\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}", opening)
            language = found.group(1).strip() if found else ""
        else:
            found = re.match(r"\\begin\s*\{" + re.escape(env) + r"\}\s*(?:\[[^\]]*\])?", opening)
            options = found.group(0) if found else ""
            lang = re.search(r"language\s*=\s*([A-Za-z]+)", options)
            language = lang.group(1).lower() if lang else ""
        fence = "````" if "```" in body else "```"
        return f"{fence}{language}\n{body.strip(chr(10))}\n{fence}"

    def _algorithm(self, body: str, env: str) -> str:
        caption, body = self._take_caption(body)
        name = self._label_in(body)
        body = re.sub(r"\\label\s*\{[^}]*\}", "", body)
        if env.startswith("algorithmic") or env in ("algorithmicx", "algpseudocode"):
            inner = self._pseudocode(body)
        else:
            inner = self._blocks(body).strip()
        head = ":::الگوریتم" + (f" {{#{name}}}" if name else "")
        parts = [f"**{caption}**"] if caption else []
        parts.append(inner)
        return f"{head}\n" + "\n\n".join(p for p in parts if p) + "\n:::"

    def _pseudocode(self, body: str) -> str:
        """algorithmic is a numbered pseudocode list: every \\State/\\If/\\For becomes a line of it."""
        lines = []
        body = re.sub(r"\\(begin|end)\s*\{algorithmic\}", "", body)
        body = re.sub(r"\\(end|begin)\s*\{[^}]*\}", "", body)
        for raw in re.split(r"\\(?:State|STATE)\b", body):
            text = raw.strip()
            if not text:
                continue
            text = re.sub(r"\b(If|ElsIf|Else|EndIf|For|EndFor|While|EndWhile|Repeat|Until|Procedure|EndProcedure|"
                          r"Function|EndFunction|Return|Require|Ensure|KwIn|KwOut|KwRet|Loop|EndLoop)\b",
                          lambda m: m.group(1), text)
            text = re.sub(r"\\(textbf|textit|emph)\s*\{([^}]*)\}", r"**\2**", text)
            text = re.sub(r"\\(Then|Do|To)\b", r" \1", text)
            text = re.sub(r"\\[A-Za-z@]+\*?", "", text)
            text = text.replace("{", "").replace("}", "").strip()
            text = self._inline(text).strip()
            if text:
                lines.append(f"- {text}")
        return "\n".join(lines)

    # -- TikZ --

    def _tikz(self, body: str) -> str:
        """A TikZ picture: a pgfplots plot becomes «:::نمودار»; a drawing cannot be redrawn from its code, so the
        author is told to put an SVG in the ZIP instead — no TeX Live runs on the server."""
        plot = self._pgfplots(body)
        if plot:
            return plot
        self._warn_once(
            "نمودار TikZ پیدا شد و قابل تبدیل نبود؛ آن را به‌صورت SVG بسازید و با \\includegraphics{image.svg} "
            "در متن بگذارید.")
        return "> نمودار TikZ — باید به‌صورت SVG در فایل ZIP باشد."

    def _pgfplots(self, body: str) -> str:
        """\\addplot {sin(x)} or \\addplot coordinates {…} → the «:::نمودار» text of app/src/lib/plot.ts."""
        plots = []
        for found in re.finditer(r"\\addplot\s*(\[[^\]]*\])?\s*(?:coordinates\s*)?\{", body):
            inner, _ = _read_group(body, found.end() - 1)
            options = found.group(1) or ""
            if re.search(r"\\addplot\s*3", options):
                continue
            plots.append((inner.strip(), options))
        if not plots:
            return ""
        x_min, x_max = self._axis_range(body)
        lines = []
        plotted = 0
        for expression, _options in plots:
            if not expression:
                continue
            if "\\" in expression and ("(" in expression or "\\frac" in expression):
                expression = self._formula_text(expression)
            if not expression:
                continue
            plotted += 1
            lines.append(f"تابع: {expression}")
        if not plotted:
            return ""
        lines.append(f"بازه: {x_min} تا {x_max}")
        return ":::نمودار\n" + "\n".join(lines) + "\n:::"

    def _axis_range(self, body: str) -> tuple[str, str]:
        low = re.search(r"xmin\s*=\s*([-\d.]+)", body)
        high = re.search(r"xmax\s*=\s*([-\d.]+)", body)
        return (low.group(1) if low else "-5", high.group(1) if high else "5")

    def _formula_text(self, expression: str) -> str:
        """\\frac{x}{2} → ((x)/(2)), \\sin x → sin(x): the plot parser reads a plain expression, not TeX."""
        out = expression
        for _ in range(6):
            found = re.search(r"\\frac\s*\{", out)
            if not found:
                break
            numerator, after = _read_group(out, found.end() - 1)
            after = _skip_whitespace(out, after)
            if after < len(out) and out[after] == "{":
                denominator, after = _read_group(out, after)
            else:
                denominator = out[after : after + 1]
                after += 1
            out = out[: found.start()] + f"(({numerator})/({denominator}))" + out[after:]
        # sin x → sin(x): the plot parser needs brackets.
        out = re.sub(r"\\(sin|cos|tan|cot|sec|csc|exp|ln|log|sqrt|abs|sinh|cosh|tanh|arcsin|arccos|arctan)\b",
                     lambda m: m.group(1) + "((", out)
        out = re.sub(r"\\(left|right|,|;|!|quad|qquad)\b|[\\{}]", "", out)
        out = out.replace("\\cdot", "*").replace("\\times", "*")
        out = re.sub(r"([a-z]+)\(\(([^()]*)\)", r"\1((\2))", out)
        out = out.replace("((", "(").replace("))", ")")
        out = out.replace("pi", "pi").replace("^", "^")
        return out.strip()

    # -- prose and inline -----------------------------------------------------------------------------------------

    def _prose(self, text: str) -> str:
        if not text.strip():
            return ""
        return "\n\n".join(self._inline(part.strip()) for part in re.split(r"\n\s*\n", text) if part.strip())

    def _inline(self, text: str) -> str:
        """One paragraph: math is set aside first, then emphasis, links, images, footnotes, references."""
        protected, math_pieces = _protect_math(text)
        protected = self._images(protected)
        protected = self._emphasis(protected)
        protected = self._references(protected)
        protected = self._footnotes(protected)
        protected = self._commands(protected)
        protected = self._spacing(protected)
        return _restore_math(protected, math_pieces)

    def _images(self, text: str) -> str:
        def replace(match):
            name = match.group(2).strip()
            self.needed_images.add(name)
            return f"![]({self._image_file(name)})"

        return re.sub(r"\\includegraphics\s*(\[[^\]]*\])?\s*(?:\{[^}]*\}\s*)*\{([^}]*)\}", replace, text)

    def _image_file(self, name: str) -> str:
        """\\includegraphics{plot} or {plot.pdf}: LaTeX is given a name without its extension and finds whatever the
        build made. The ZIP of a professor usually has plot.pdf (compiled) or the original plot.png, so the name gets
        the extension of the file that is actually in the project, defaulting to .png."""
        path = posixpath.normpath(name.replace("\\", "/")).lstrip("./").strip("/")
        if path.lower().endswith(IMAGE_EXTENSIONS):
            return path
        stem = path[: -len(".pdf")] if path.lower().endswith(".pdf") else path
        for suffix in IMAGE_EXTENSIONS:
            if stem.lower().endswith(suffix):
                return stem
        return stem + ".png"

    def _emphasis(self, text: str) -> str:
        for command, mark in EMPHASIS:
            while True:
                found = re.search(r"\\" + command + r"\s*\{", text)
                if not found:
                    break
                inner, after = _read_group(text, found.end() - 1)
                body = self._inline(inner).strip()
                text = text[: found.start()] + (f"{mark}{body}{mark}" if body else "") + text[after:]
        return text

    def _references(self, text: str) -> str:
        def replace(match):
            return f"[[#{_slug_name(match.group(2))}]]"

        text = re.sub(r"\\(ref|eqref|autoref|cref|Cref|nameref)\s*\{([^}]*)\}", replace, text)
        return re.sub(r"\\label\s*\{[^}]*\}", "", text)

    def _footnotes(self, text: str) -> str:
        """\\footnote{…} → a parenthetical after the sentence: the book has no footnote, and a note in brackets
        keeps the words where the author put them."""

        def replace(match):
            inner, _ = _read_group(match.group(0), match.group(0).index("{"))
            return f" ({self._inline(inner).strip()})"

        return re.sub(r"\\footnote\s*\{", lambda m: m.group(0), text) and re.sub(
            r"\\footnote\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", replace, text)

    def _commands(self, text: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(text):
            if text[index] != "\\":
                # Braces of LaTeX are grouping, not words: {x} reads as x (and a stray one reads as nothing).
                if text[index] in "{}":
                    index += 1
                    continue
                out.append(text[index])
                index += 1
                continue
            found = re.match(r"\\([A-Za-z@]+\*?)", text[index:])
            if not found:
                if index + 1 < len(text):
                    escaped = text[index + 1]
                    out.append({"&": "&", "%": "%", "$": "$", "#": "#", "_": "_", "{": "{", "}": "}",
                                " ": " ", "\\": "\n"}.get(escaped, escaped))
                    index += 2
                else:
                    index += 1
                continue
            name = found.group(1).rstrip("*")
            index += found.end()

            if name in SILENT_ALONE:
                continue
            if name in SILENT_WITH_ARGS:
                # Decorative and set-up commands: dropped without a word (they are not the author's mistake).
                index = self._drop_args(text, index)
                continue
            if name in ("hl", "hlc"):
                inner, index = self._take_group(text, index)
                colour = "قرمز" if name == "hlc" else "آبی"
                out.append(f"=={colour}:{self._inline(inner).strip()}==")
                continue
            if name == "caption":
                inner, index = self._take_group(text, index)
                out.append(f"**{self._inline(inner).strip()}**")
                continue
            if name in TEXT_WRAPPERS:
                if name in LAST_ARG_IS_TEXT:
                    index = self._keep_last_group(text, out, index)
                else:
                    inner, index = self._take_group(text, index)
                    out.append(self._inline(inner))
                continue
            # Unknown: keep the words inside, drop the command, and tell the author once.
            self._note_unknown(name)
            index = self._drop_args(text, index, keep_text=out)
        return "".join(out)

    def _note_unknown(self, name: str):
        if name not in self.unknown:
            self.unknown.add(name)

    def _drop_args(self, text: str, index: int, keep_text: list | None = None) -> int:
        """Skip the command's arguments. With `keep_text`, a brace argument's words go there instead of being lost."""
        while True:
            index = _skip_whitespace(text, index)
            if index < len(text) and text[index] in "{[":
                opener = text[index]
                inner, index = _read_group(text, index, opener, "}" if opener == "{" else "]")
                if keep_text is not None and opener == "{":
                    keep_text.append(self._inline(inner))
                continue
            return index

    def _take_group(self, text: str, index: int) -> tuple[str, int]:
        index = _skip_whitespace(text, index)
        if index < len(text) and text[index] == "[":
            _, index = _read_group(text, index, "[", "]")
            index = _skip_whitespace(text, index)
        if index < len(text) and text[index] == "{":
            return _read_group(text, index)
        return "", index

    def _keep_last_group(self, text: str, out: list, index: int) -> int:
        """\\textcolor{red}{word} → word: the earlier braces are settings, the last one is the text."""
        index = _skip_whitespace(text, index)
        groups = []
        while index < len(text) and text[index] == "{":
            inner, index = _read_group(text, index)
            groups.append(inner)
            index = _skip_whitespace(text, index)
        if groups:
            out.append(self._inline(groups[-1]))
        return index

    def _spacing(self, text: str) -> str:
        text = text.replace("~", " ")
        text = re.sub(r"\\[,;:!]", "", text)
        text = text.replace("---", "—").replace("--", "–")
        text = text.replace("``", "«").replace("''", "»")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    # -- report --

    def report(self) -> list[str]:
        """What the author should know, in Persian, for the preview screen (converting first, if not done yet)."""
        if not self._converted:
            self.to_markdown()
        warnings = list(self.warnings)
        if self.unknown:
            # A professor does not know \DeclareFloatingEnvironment by name, and reading 23 of them in one line tells
            # them nothing. The warning says what happened, how many, and names only the few that usually mean the
            # author expected something else («\note» is often a box in their head, not a command).
            total = len(self.unknown)
            known_but_missing = {
                "note": "«کادر». در لیموخوان کادر با «:::نکته» ساخته می‌شود.",
                "begin": "محیطی که بسته نشده بود.",
                "textbf": "در متن درس، پررنگ با **متن** ساخته می‌شود.",
                "includegraphics": "عکس؛ اگر عکس را در پوشه‌ی images نگذاشته‌اید، همان‌جاست که جا افتاده.",
                "footnote": "پانویس؛ لیموخوان پانویس ندارد.",
                "cite": "ارجاع به منبع؛ لیموخوان فهرست منابع ندارد.",
                "ref": "ارجاع به شماره‌ی شکل/جدول؛ نام‌گذاری «{#نام}» را ببینید.",
            }
            hints = [f"\\{n} → {known_but_missing[n]}" for n in sorted(self.unknown) if n in known_but_missing]
            names = "، ".join("\\" + n for n in sorted(self.unknown)[:5])
            more = "" if total <= 5 else f" و {str(total - 5).translate(_PERSIAN_DIGITS)} دستور دیگر"
            message = (
                f"{str(total).translate(_PERSIAN_DIGITS)} دستور LaTeX در فایل بود که لیموخوان نمی‌شناسد؛ حذف شدند ولی متن داخلشان "
                f"نگه داشته شد. مهم‌ترین‌ها: {names}{more}."
            )
            if hints:
                message += "  " + " ".join(hints)
            if total > 5:
                message += " فهرست کامل در پایین صفحه."
            warnings.append(message)
        return warnings


# --- Reading an upload ----------------------------------------------------------------------------------------

def read_latex(filename: str, data: bytes, book=None, slug: str = "", custom_boxes: dict[str, str] | None = None) -> tuple[str, dict[str, bytes], list[str]]:
    """A .tex file or a .zip of the project → (chapter Markdown text, images by path, warnings).

    The caller (importer.read_upload) parses the text exactly as it parses an uploaded .md, so all of the format's
    checks — labels, slugs, tests, flashcards — apply to a LaTeX chapter unchanged.
    """
    import io
    import zipfile
    import zlib

    warnings: list[str] = []
    if filename.lower().endswith(".tex"):
        text = data.decode("utf-8-sig", errors="replace")
        converter = Converter(text, custom_boxes=custom_boxes)
        return converter.to_markdown(), {}, converter.report()

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError):
        return "", {}, ["فایل ZIP خراب است یا باز نمی‌شود."]

    names = [info.filename for info in archive.infolist() if not info.is_dir()]
    sources: dict[str, str] = {}
    style: list[str] = []
    images: dict[str, bytes] = {}
    main_file = ""
    for name in names:
        if is_junk(name):
            continue
        suffix = _suffix(name)
        if suffix in (".tex",):
            body = archive.read(name).decode("utf-8-sig", errors="replace")
            sources[name] = body
            sources[posixpath.splitext(name)[0]] = body
            sources[posixpath.basename(posixpath.splitext(name)[0])] = body
            if r"\documentclass" in body and not main_file:
                main_file = name
        elif is_style_file(name):
            style.append(archive.read(name).decode("utf-8-sig", errors="replace"))
        elif suffix in IMAGE_EXTENSIONS:
            images[name] = archive.read(name)

    if not sources:
        return "", {}, ["داخل ZIP هیچ فایل .tex نیست."]
    if not main_file:
        # No \documentclass anywhere: the largest file is the one the author wrote.
        main_file = max(sources, key=lambda n: len(sources[n]) if n.endswith(".tex") else -1)
    text = sources[main_file]

    macros = collect_macros(text, *style)
    converter = Converter(text, macros=macros, sources=sources, custom_boxes=custom_boxes)
    converter.book = book
    converter.slug = slug or posixpath.splitext(posixpath.basename(main_file))[0] or "ch1"
    markdown = converter.to_chapter()

    # Only the images the text actually points at are kept: a project's folder of old screenshots is not the book.
    kept = {path: body for path, body in images.items()
            if any(self_name in path for self_name in _referenced(converter.needed_images))}
    return markdown, kept, converter.report() + warnings


def _referenced(needed: set[str]) -> set[str]:
    """The image names the text points at, as paths a ZIP entry may end with (icons/plot.png matches plot.png)."""
    out = set()
    for name in needed:
        clean = posixpath.normpath(name.replace("\\", "/")).lstrip("./")
        out.add(clean)
        for suffix in IMAGE_EXTENSIONS:
            if clean.lower().endswith(suffix):
                out.add(clean[: -len(suffix)])
                break
    return out
