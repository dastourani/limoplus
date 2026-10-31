"""
The review card: a section's summary written in labelled parts.

    در یک نگاه: one or two sentences
    مهم:
    - a pointer to an important idea [[phrase in the notes]]
    واژه:
    - تضعیف | Attenuation | کم شدن شدت پرتو در عبور از بدن
    قاعده: / حفظی: / تله:
    - ...

Summaries without these labels are shown as plain Markdown, as before.
"""

import re

PART_NAMES = {
    "در یک نگاه": "glance",
    "مهم": "important",
    "مهم‌ترین‌ها": "important",
    "واژه": "terms",
    "واژه‌ها": "terms",
    "واژه‌نامه": "terms",
    "قاعده": "rules",
    "قاعده و فرمول": "rules",
    "حفظی": "memorize",
    "تله": "traps",
    "تله‌ها": "traps",
}
_PART = re.compile(r"^\s*(" + "|".join(sorted(map(re.escape, PART_NAMES), key=len, reverse=True)) + r")\s*:\s*(.*)$")


def parse_parts(text: str) -> dict[str, list[str]]:
    """Map part key → list of lines (list items without the dash; the glance part as one line)."""
    parts: dict[str, list[str]] = {}
    current = None
    for raw in (text or "").splitlines():
        m = _PART.match(raw)
        if m:
            current = PART_NAMES[m.group(1)]
            parts.setdefault(current, [])
            if m.group(2).strip():
                parts[current].append(m.group(2).strip())
            continue
        if current is None:
            continue
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            parts[current].append(line[2:].strip())
        elif parts[current]:
            parts[current][-1] += " " + line
        else:
            parts[current].append(line)
    return parts


def parse_terms(text: str) -> list[dict]:
    """Glossary items «فارسی | English | معنی» from a summary's «واژه» part."""
    out = []
    for item in parse_parts(text).get("terms", []):
        cells = [c.strip() for c in item.split("|")]
        if cells and cells[0]:
            out.append({"fa": cells[0], "en": cells[1] if len(cells) > 1 else "", "meaning": cells[2] if len(cells) > 2 else ""})
    return out
