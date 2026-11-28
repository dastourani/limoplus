"""Normalise Iranian mobile numbers to the 09XXXXXXXXX form."""

import re

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MOBILE = re.compile(r"^09\d{9}$")


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """Accept Persian/Arabic digits, spaces, dashes, +98, 0098 or a bare 9XXXXXXXXX."""
    if not raw:
        raise InvalidPhone("شماره موبایل وارد نشده است.")
    phone = re.sub(r"[\s\-()]", "", str(raw).translate(_DIGITS))
    if phone.startswith("+98"):
        phone = "0" + phone[3:]
    elif phone.startswith("0098"):
        phone = "0" + phone[4:]
    elif phone.startswith("98") and len(phone) == 12:
        phone = "0" + phone[2:]
    elif phone.startswith("9") and len(phone) == 10:
        phone = "0" + phone
    if not _MOBILE.match(phone):
        raise InvalidPhone("شماره موبایل معتبر نیست.")
    return phone
