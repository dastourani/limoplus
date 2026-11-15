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
