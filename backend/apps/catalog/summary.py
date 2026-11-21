"""
The summary («چکیده») written in labelled parts (labels: apps/catalog/labels.py, the panel's «برچسب‌های متن»):

    در یک نگاه: one or two sentences
    تعریف:
    - … [[phrase in the notes]]
    واژه:
    - تضعیف | Attenuation | کم شدن شدت پرتو در عبور از بدن

Summaries without labels are shown as plain Markdown, as before. Same rules as app/src/lib/reviewCard.ts.
"""

from .labels import line_label


def parse_summary(text: str) -> dict | None:
    """{"lead": text before the first label, "glance": str, "parts": [(label, [items])]} or None without labels."""
    parts: list[tuple[dict, list[str]]] = []
    by_name: dict[str, list[str]] = {}
    lead: list[str] = []
    glance: list[str] = []
    current = None  # a list of items, or "glance"
    for raw in (text or "").splitlines():
        m = line_label(raw)
        if m:
            label, rest = m
            if label["role"] == "glance":
                current = "glance"
                if rest.strip():
                    glance.append(rest.strip())
                continue
            if label["name"] not in by_name:
                by_name[label["name"]] = []
                parts.append((label, by_name[label["name"]]))
            current = by_name[label["name"]]
            if rest.strip():
                current.append(rest.strip())
            continue
        if current is None:
            lead.append(raw)
            continue
        line = raw.strip()
        if not line:
            continue
        if current == "glance":
            glance.append(line[2:].strip() if line.startswith(("- ", "* ")) else line)
        elif line.startswith(("- ", "* ")):
            current.append(line[2:].strip())
        elif current:
            current[-1] += " " + line
        else:
            current.append(line)
    if not parts and not glance:
        return None
    return {"lead": "\n".join(lead).strip(), "glance": " ".join(glance), "parts": parts}


def parse_parts(text: str) -> dict[str, list[str]]:
    """Label name → items (empty without labels). Kept for callers that only ask «is this a review card»."""
    parsed = parse_summary(text)
    if not parsed:
        return {}
    out = {label["name"]: items for label, items in parsed["parts"]}
    if parsed["glance"]:
        out["در یک نگاه"] = [parsed["glance"]]
    return out


def parse_terms(text: str) -> list[dict]:
    """Glossary items «فارسی | English | معنی» from the summary's «واژه» part."""
    parsed = parse_summary(text) or {"parts": []}
    out = []
    for label, items in parsed["parts"]:
        if label["role"] != "terms":
            continue
        for item in items:
            cells = [c.strip() for c in item.split("|")]
            if cells and cells[0]:
                out.append({"fa": cells[0], "en": cells[1] if len(cells) > 1 else "", "meaning": cells[2] if len(cells) > 2 else ""})
    return out
