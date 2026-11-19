"""Jalali date entry for every Django admin form.

Django's default date shortcuts are Gregorian even in the Persian-language panel. Keep dates as ordinary Gregorian
``date``/``datetime`` values in Python and the database; only the admin input/output boundary is Jalali.
"""

import datetime
import re

from django import forms
from django.contrib.admin.options import BaseModelAdmin
from django.contrib.admin.widgets import AdminSplitDateTime, AdminTimeWidget
from django.db import models
from django.utils import timezone

from .jalali import from_jalali, jalali_date, to_jalali

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_DATE_RE = re.compile(r"^\s*(\d{1,4})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*$")


def _normal_digits(value):
    return value.translate(_DIGITS) if isinstance(value, str) else value


def _parse_admin_date(value):
    """Parse a Jalali ``year/month/day`` value, with ISO/Gregorian input kept as a compatibility fallback."""
    if isinstance(value, datetime.datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str):
        return None
    match = _DATE_RE.fullmatch(_normal_digits(value))
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if year >= 1700:
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    if not (1 <= year <= 3177 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        result = from_jalali(year, month, day)
    except (OverflowError, ValueError):
        return None
    # ``from_jalali`` normalizes some impossible days; reject those rather than silently changing the date.
    return result if to_jalali(result.year, result.month, result.day) == (year, month, day) else None


def _date_attrs(attrs=None):
    attrs = dict(attrs or {})
    classes = [name for name in attrs.get("class", "").split() if name != "vDateField"]
    if "lp-jalali-date" not in classes:
        classes.append("lp-jalali-date")
    attrs["class"] = " ".join(classes)
    attrs.setdefault("size", "12")
    attrs.setdefault("placeholder", "۱۴۰۵/۰۸/۲۸")
    attrs.setdefault("autocomplete", "off")
    attrs.setdefault("inputmode", "numeric")
    attrs.setdefault("dir", "ltr")
    return attrs


class JalaliAdminDateInput(forms.DateInput):
    input_type = "text"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=_date_attrs(attrs), format=format)

    def format_value(self, value):
        if value is None or value == "":
            return ""
        parsed = _parse_admin_date(value)
        return jalali_date(parsed) if parsed else super().format_value(value)


class JalaliAdminSplitDateTime(AdminSplitDateTime):
    """Django's split date/time control with a Jalali date input and the normal local-time input."""

    def __init__(self, attrs=None, date_attrs=None, time_attrs=None):
        widgets = [
            JalaliAdminDateInput(attrs=date_attrs),
            AdminTimeWidget(attrs=time_attrs),
        ]
        # Use MultiWidget directly so Django's default vDateField/Gregorian calendar is never attached.
        forms.MultiWidget.__init__(self, widgets, attrs)


class JalaliDateField(forms.DateField):
    default_error_messages = {
        **forms.DateField.default_error_messages,
        "invalid": "تاریخ شمسی معتبر وارد کنید؛ نمونه: ۱۴۰۵/۰۸/۲۸.",
    }

    def to_python(self, value):
        if value in self.empty_values:
            return None
        parsed = _parse_admin_date(value)
        if parsed is not None:
            return parsed
        return super().to_python(_normal_digits(value))


class PersianTimeField(forms.TimeField):
    """Accept Persian/Arabic digits in the time box as well as Latin digits."""

    def to_python(self, value):
        return super().to_python(_normal_digits(value))


class JalaliSplitDateTimeField(forms.SplitDateTimeField):
    """Keep the admin's timezone-aware DateTimeField validation, with a Jalali date subfield."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        date_field, time_field = self.fields
        # Match Django's SplitDateTimeField: the parent reports required/incomplete values.
        self.fields = [
            JalaliDateField(
                required=date_field.required,
                input_formats=date_field.input_formats,
                error_messages=date_field.error_messages,
                localize=date_field.localize,
                disabled=date_field.disabled,
            ),
            PersianTimeField(
                required=time_field.required,
                input_formats=time_field.input_formats,
                error_messages=time_field.error_messages,
                localize=time_field.localize,
                disabled=time_field.disabled,
            ),
        ]


def _copy_formfield(field, *, widget, input_formats=None):
    """Build a replacement form field without dropping model/admin validation or labels."""
    kwargs = {
        "required": field.required,
        "label": field.label,
        "initial": field.initial,
        "help_text": field.help_text,
        "error_messages": field.error_messages,
        "validators": field.validators,
        "localize": field.localize,
        "disabled": field.disabled,
        "widget": widget,
    }
    if input_formats is not None:
        kwargs["input_formats"] = input_formats
    return kwargs


def _jalali_formfield(formfield, db_field):
    if formfield is None or formfield.widget.is_hidden:
        return formfield

    if isinstance(db_field, models.DateTimeField) and isinstance(formfield, forms.SplitDateTimeField):
        original_widget = formfield.widget
        original_widgets = getattr(original_widget, "widgets", ())
        date_attrs = original_widgets[0].attrs if len(original_widgets) > 0 else None
        time_attrs = original_widgets[1].attrs if len(original_widgets) > 1 else None
        widget = JalaliAdminSplitDateTime(
            attrs=getattr(original_widget, "attrs", None),
            date_attrs=date_attrs,
            time_attrs=time_attrs,
        )
        return JalaliSplitDateTimeField(
            **_copy_formfield(formfield, widget=widget),
            input_date_formats=formfield.fields[0].input_formats,
            input_time_formats=formfield.fields[1].input_formats,
        )

    if isinstance(db_field, models.DateField) and isinstance(formfield, forms.DateField):
        widget = JalaliAdminDateInput(attrs=formfield.widget.attrs)
        return JalaliDateField(
            **_copy_formfield(formfield, widget=widget, input_formats=formfield.input_formats)
        )
    return formfield


_installed = False


def install():
    """Install once on Django's shared admin formfield hook, covering every registered ModelAdmin."""
    global _installed
    if _installed:
        return
    original = BaseModelAdmin.formfield_for_dbfield
    if getattr(original, "_limo_jalali_admin", False):
        _installed = True
        return

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        formfield = original(self, db_field, request, **kwargs)
        return _jalali_formfield(formfield, db_field)

    formfield_for_dbfield._limo_jalali_admin = True
    BaseModelAdmin.formfield_for_dbfield = formfield_for_dbfield
    _installed = True
