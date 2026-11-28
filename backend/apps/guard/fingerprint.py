"""
An invisible fingerprint in copied text: a code written with zero-width characters between two markers.

Never U+200C (ZWNJ): Persian uses it as نیم‌فاصله. Four invisible characters carry two bits each.
"""

import re
import secrets

START, STOP = "⁤", "⁣"
DIGITS = ["​", "⁠", "⁡", "⁢"]
_VALUE = {c: i for i, c in enumerate(DIGITS)}
_FOUND = re.compile(f"{START}([{''.join(DIGITS)}]+){STOP}")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
CODE_LEN = 10


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def encode(code: str) -> str:
    out = []
    for byte in code.encode():
        out.extend(DIGITS[(byte >> shift) & 3] for shift in (6, 4, 2, 0))
    return START + "".join(out) + STOP


def decode_all(text: str) -> list[str]:
    codes = []
    for run in _FOUND.findall(text or ""):
        if len(run) % 4:
            continue
        data = bytes(
            (_VALUE[run[i]] << 6) | (_VALUE[run[i + 1]] << 4) | (_VALUE[run[i + 2]] << 2) | _VALUE[run[i + 3]]
            for i in range(0, len(run), 4)
        )
        try:
            code = data.decode()
        except UnicodeDecodeError:
            continue
        if code not in codes:
            codes.append(code)
    return codes


def mark(text: str, code: str) -> str:
    """The fingerprint after the first word and again before the last one, so a part of the text keeps it too."""
    fp = encode(code)
    first = text.find(" ")
    last = text.rfind(" ")
    if first < 0:
        return text + fp
    if last <= first:
        return text[:first] + fp + text[first:]
    return text[:first] + fp + text[first:last] + fp + text[last:]


def strip(text: str) -> str:
    return _FOUND.sub("", text or "")
