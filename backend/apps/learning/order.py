"""
Whether a question's choices may be shuffled, and checks on explanations that name a choice by its number.

Shuffling changes the meaning of a choice like «گزینه‌های ۱ و ۳»، «همه‌ی موارد» or «هیچ‌کدام», so those questions
keep the order written in the file, as do questions marked «ترتیب گزینه‌ها: ثابت».
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_S = r"[\s‌]*"
_REFERS = re.compile(
    "|".join(
        [
            r"گزینه",
            rf"همه{_S}(?:ی|ٔ)?{_S}(?:موارد|گزینه|موارد{_S}فوق|ی{_S}موارد)",
            rf"هیچ{_S}کدام",
            rf"هر{_S}(?:دو|سه|چهار)",
            r"موارد\s+(?:فوق|بالا)",
            r"(?:^|\s)(?:الف|ب|ج|د)\s*(?:و|،|,)\s*(?:الف|ب|ج|د)(?:\s|$)",
            r"(?:^|\s)[۱-۶1-6]\s*(?:و|،|,)\s*[۱-۶1-6](?:\s|$)",
            r"none of|all of the above|both",
        ]
    ),
    re.IGNORECASE,
)
_NAMES_NUMBER = re.compile(rf"گزینه{_S}(?:ی|ٔ)?{_S}(?:[۱-۶1-6]|اول|دوم|سوم|چهارم|پنجم|ششم)(?![۰-۹0-9])")


def refers_to_choices(texts: Iterable[str]) -> bool:
    return any(_REFERS.search(t or "") for t in texts)


def names_choice_number(text: str) -> str | None:
    """The first «گزینه‌ی ۲»-like words in an explanation, or None."""
    m = _NAMES_NUMBER.search(text or "")
    return m.group(0) if m else None
