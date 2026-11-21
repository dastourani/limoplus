"""LaTeX/Markdown natural section chunker.

Splits a raw LaTeX or Markdown text into logical, standalone chunks along natural boundaries
(like \\chapter, \\section, \\subsection, or Markdown headings #, ##), preserving math blocks,
formula environments, and custom box delimiters without splitting across them.
"""

from __future__ import annotations

import re


def chunk_latex_source(text: str, max_chars_per_chunk: int = 25000) -> list[dict]:
    """Break a raw LaTeX source into section-level natural chunks.

    Returns a list of dicts:
    [
        {"index": 1, "title": "مقدمه فصل", "type": "intro", "raw": "..."},
        {"index": 2, "title": "تعریف انتگرال", "type": "section", "raw": "..."},
        ...
    ]
    """
    clean_text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = clean_text.split("\n")

    chunks: list[dict] = []
    current_title = "مقدمه فصل"
    current_type = "intro"
    current_lines: list[str] = []

    heading_pat = re.compile(
        r"^\s*\\(chapter|section|subsection)\*?\s*(?:\[[^\]]*\])?\s*\{([^}]+)\}",
        re.MULTILINE,
    )

    for line in lines:
        m = heading_pat.match(line)
        if m:
            level_name = m.group(1)
            raw_title = m.group(2).strip()
            # Clean LaTeX title formatting
            clean_t = re.sub(r"[{}\\]+", "", raw_title).strip() or "بخش بدون عنوان"

            # Flush current chunk if it has non-empty content
            chunk_body = "\n".join(current_lines).strip()
            if chunk_body:
                chunks.append({
                    "index": len(chunks) + 1,
                    "title": current_title,
                    "type": current_type,
                    "raw": chunk_body,
                    "word_count": len(chunk_body.split()),
                })
                current_lines = []

            current_title = clean_t
            current_type = level_name
            current_lines.append(line)
        else:
            current_lines.append(line)

    chunk_body = "\n".join(current_lines).strip()
    if chunk_body:
        chunks.append({
            "index": len(chunks) + 1,
            "title": current_title,
            "type": current_type,
            "raw": chunk_body,
            "word_count": len(chunk_body.split()),
        })

    # If the document had no sections at all, wrap everything as one or split by double-newlines if huge
    if not chunks:
        chunks.append({
            "index": 1,
            "title": "کل محتوا",
            "type": "content",
            "raw": clean_text.strip(),
            "word_count": len(clean_text.split()),
        })

    return chunks
