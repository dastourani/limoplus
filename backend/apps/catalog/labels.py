"""
Labels of the lesson text («برچسب‌ها»), managed in the panel (models.Label). The same list as app/src/lib/labels.ts:

    درسنامه (notes):  :::تعریف … :::        a box
    چکیده (summary):  تعریف:  then «- » items  a part of the review card

DEFAULT_LABELS is the starting list (created by migration 0014) and the fallback before the table exists.
"""

from __future__ import annotations

import re
import time

DEFAULT_LABELS = [
    # name, group, style, role, aliases, columns, hidden
    ("در یک نگاه", "عمومی", "note", "glance", "", "", False),
    ("مهم", "عمومی", "note", "important", "مهم‌ترین‌ها", "", False),
    ("تعریف", "ریاضی و علوم", "formal", "", "", "", False),
    ("قضیه", "ریاضی و علوم", "formal", "", "", "", False),
    ("نتیجه", "ریاضی و علوم", "formal", "", "", "", False),
    ("گزاره", "ریاضی و علوم", "formal", "", "", "", False),
    ("فرمول", "ریاضی و علوم", "formal", "", "", "", False),
    ("قاعده", "ریاضی و علوم", "formal", "", "قاعده و فرمول", "", False),
    ("شرط کاربرد", "ریاضی و علوم", "note", "", "", "", False),
    ("نمودار", "ریاضی و علوم", "formal", "", "", "", False),
    ("مثال", "عمومی", "formal", "", "", "", False),
    ("مثال نقض", "ریاضی و علوم", "warn", "", "", "", False),
    ("نکته", "عمومی", "note", "", "", "", False),
    ("یادآوری", "عمومی", "note", "", "", "", False),
    ("حفظی", "عمومی", "note", "memorize", "", "", False),
    ("تله", "عمومی", "warn", "", "تله‌ها، تله‌ی تستی", "", False),
    ("هشدار", "عمومی", "warn", "", "", "", True),
    ("واژه", "زبان", "table", "terms", "واژه‌ها، واژه‌نامه", "فارسی | English | معنی", False),
    ("مترادف", "زبان", "table", "", "", "واژه | مترادف", False),
    ("متضاد", "زبان", "table", "", "", "واژه | متضاد", False),
]

_ARABIC = str.maketrans({"ي": "ی", "ك": "ک", "ى": "ی"})


def normalize(name: str) -> str:
    """«مثال‌نقض», «مثال  نقض» and «مثال نقض» are the same name."""
    return re.sub(r"[‌\s]+", " ", (name or "").translate(_ARABIC)).strip()


def _split(text, sep):
    return [x.strip() for x in re.split(sep, text or "") if x.strip()]


def _defaults() -> list[dict]:
    return [
        {"name": n, "group": g, "style": s, "role": r, "aliases": _split(a, r"[،,]"), "columns": _split(c, r"\|"), "hidden": h}
        for n, g, s, r, a, c, h in DEFAULT_LABELS
    ]


_cache: tuple[float, list[dict]] | None = None
TTL = 20  # seconds: other server processes see a panel change this soon


def all_labels() -> list[dict]:
    global _cache
    if _cache and time.monotonic() - _cache[0] < TTL:
        return _cache[1]
    from django.db import DatabaseError

    from .models import Label

    try:
        rows = [label.as_json() for label in Label.objects.all()]
    except DatabaseError:
        rows = []
    result = rows or _defaults()
    _cache = (time.monotonic(), result)
    return result


def forget():
    """After a change in the panel."""
    global _cache
    _cache = None


def find(name: str) -> dict | None:
    wanted = normalize(name)
    for label in all_labels():
        if wanted in {normalize(n) for n in [label["name"], *label["aliases"]]}:
            return label
    return None


def line_label(line: str) -> tuple[dict, str] | None:
    """A summary line that starts a part: «تعریف: …» → (label, the rest of the line)."""
    m = re.match(r"^\s*([^:：]{1,40}?)\s*[:：]\s*(.*)$", (line or "").translate(_ARABIC))
    if not m:
        return None
    label = find(m.group(1))
    return (label, re.sub(r"^[-*]\s+", "", m.group(2))) if label else None
