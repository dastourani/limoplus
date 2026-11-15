"""How the panel shows values in every list and read-only field: Jalali dates and Persian digits (with a thousands
separator from 10,000 up, so prices read «۲۴۹٬۰۰۰» while years stay «۱۴۰۱»). Installed once from CatalogConfig.ready()
by replacing Django admin's display_for_field / display_for_value where the admin uses them."""

import datetime
import decimal

from django.db import models

from .jalali import fa_digits, jalali_date, jalali_datetime

_installed = False


def fa_number(value) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float | decimal.Decimal):
        text = f"{value:,.2f}".rstrip("0").rstrip(".") if abs(value) >= 10000 else f"{value:.2f}".rstrip("0").rstrip(".")
    else:
        text = f"{value:,}" if abs(value) >= 10000 else str(value)
    return fa_digits(text.replace(",", "٬").replace(".", "٫"))


def _plain(value):
    """A date, time or number made Persian; anything else None (left to Django)."""
    if isinstance(value, datetime.datetime):
        return jalali_datetime(value)
    if isinstance(value, datetime.date):
        return jalali_date(value)
    if isinstance(value, int | float | decimal.Decimal) and not isinstance(value, bool):
        return fa_number(value)
    return None


def install():
    global _installed
    if _installed:
        return
    from django.contrib.admin import helpers, utils
    from django.contrib.admin.templatetags import admin_list

    original_field = utils.display_for_field
    original_value = utils.display_for_value

    def display_for_field(value, field, empty_value_display, *args, **kwargs):
        if value is not None and not getattr(field, "flatchoices", None) and not isinstance(field, models.AutoField):
            if isinstance(field, models.DateTimeField | models.DateField):
                return _plain(value) or empty_value_display
            if isinstance(field, models.IntegerField | models.DecimalField | models.FloatField):
                return fa_number(value)
        return original_field(value, field, empty_value_display, *args, **kwargs)

    def display_for_value(value, empty_value_display, boolean=False, *args, **kwargs):
        if not boolean and value is not None:
            shown = _plain(value)
            if shown is not None:
                return shown
        return original_value(value, empty_value_display, boolean, *args, **kwargs)

    for module in (utils, helpers, admin_list):
        if hasattr(module, "display_for_field"):
            module.display_for_field = display_for_field
        if hasattr(module, "display_for_value"):
            module.display_for_value = display_for_value
    _installed = True


BADGE_COLORS = {"green": "lp-b-green", "yellow": "lp-b-yellow", "grey": "lp-b-grey", "blue": "lp-b-blue", "red": "lp-b-red"}


def badges(*items):
    """One «وضعیت» cell instead of a row of ✓/✗ columns: (text, colour) pairs, the falsy ones left out."""
    from django.utils.html import format_html, format_html_join

    shown = [(BADGE_COLORS[color], text) for text, color in (i for i in items if i)]
    if not shown:
        return "—"
    return format_html('<span class="lp-badges">{}</span>', format_html_join("", '<span class="lp-badge {}">{}</span>', shown))


def short_text(text: str, limit: int = 140) -> str:
    """Lesson text on one line for a list: images and markup marks dropped, at most `limit` characters, never cut
    inside a $…$ formula (the cut moves to just before it), «…» when shortened."""
    import re

    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")  # images
    text = re.sub(r"\[\[#?([^|\]]*)(?:\|[^\]]*)?\]\]", r"\1", text)  # [[#name|text]] links: their name
    text = re.sub(r"^\s*(:::[^\n]*|#+\s*)", " ", text, flags=re.M)  # box lines and headings
    text = text.replace("**", "").replace("==", "")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = limit
    # Where does each formula start and end? A cut inside one goes back to its start.
    for m in re.finditer(r"\$\$.+?\$\$|\$[^$]+\$", text):
        if m.start() < cut < m.end():
            cut = m.start() if m.start() > limit // 3 else min(m.end(), len(text))
            break
    return text[:cut].rstrip() + "…"


def tex(text: str, limit: int = 140):
    """A list cell with formulas: plain text that the panel's lists.js draws with the app's own renderer."""
    from django.utils.html import format_html

    short = short_text(text, limit)
    if "$" not in short:
        return short
    return format_html('<span class="lp-tex">{}</span>', short)


def fa_duration(seconds) -> str:
    """«۳ ساعت ۵ دقیقه», «۱۲ دقیقه», «کمتر از یک دقیقه»; «—» for nothing."""
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "—"
    hours, minutes = seconds // 3600, (seconds % 3600) // 60
    if not hours and not minutes:
        return "کمتر از یک دقیقه"
    parts = ([f"{fa_number(hours)} ساعت"] if hours else []) + ([f"{fa_number(minutes)} دقیقه"] if minutes else [])
    return " و ".join(parts)
