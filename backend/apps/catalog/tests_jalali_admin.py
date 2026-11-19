import datetime

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from apps.catalog.jalali import from_jalali, jalali_date, to_jalali
from apps.catalog.jalali_admin import (
    JalaliAdminDateInput,
    JalaliDateField,
    JalaliSplitDateTimeField,
)
from apps.commerce.models import SaleCampaign
from apps.website.models import BookAccessRequest


class JalaliAdminDateTests(SimpleTestCase):
    def test_conversion_and_admin_date_input_round_trip(self):
        gregorian = datetime.date(2026, 11, 19)
        self.assertEqual(to_jalali(gregorian.year, gregorian.month, gregorian.day), (1405, 8, 28))
        self.assertEqual(from_jalali(1405, 8, 28), gregorian)
        self.assertEqual(jalali_date(gregorian), "۱۴۰۵/۸/۲۸")
        self.assertEqual(JalaliDateField().clean("۱۴۰۵/۰۸/۲۸"), gregorian)
        self.assertEqual(JalaliDateField().clean("2026-11-19"), gregorian)  # ISO compatibility for existing integrations
        with self.assertRaises(ValidationError):
            JalaliDateField().clean("۱۴۰۵/۱۲/۳۰")

    def test_split_datetime_keeps_the_same_local_date_and_standard_time_value(self):
        field = JalaliSplitDateTimeField(
            input_date_formats=["%Y-%m-%d"],
            input_time_formats=["%H:%M"],
        )
        value = field.clean(["۱۴۰۵/۰۸/۲۸", "۱۷:۰۴"])
        local = timezone.localtime(value)
        self.assertEqual(local.date(), datetime.date(2026, 11, 19))
        self.assertEqual(local.time(), datetime.time(17, 4))
        self.assertEqual(local.utcoffset(), datetime.timedelta(hours=3, minutes=30))

    def test_model_admin_date_and_datetime_fields_are_jalali(self):
        request = RequestFactory().get("/admin/")
        request.user = None
        access_admin = admin.site._registry[BookAccessRequest]
        date_field = access_admin.formfield_for_dbfield(BookAccessRequest._meta.get_field("ends_on"), request)
        self.assertIsInstance(date_field, JalaliDateField)
        self.assertIsInstance(date_field.widget, JalaliAdminDateInput)
        self.assertIn("۱۴۰۵/۸/۲۸", date_field.widget.render("ends_on", datetime.date(2026, 11, 19)))

        campaign_admin = admin.site._registry[SaleCampaign]
        datetime_field = campaign_admin.formfield_for_dbfield(SaleCampaign._meta.get_field("starts_at"), request)
        self.assertIsInstance(datetime_field, JalaliSplitDateTimeField)
        rendered = datetime_field.widget.render("starts_at", datetime.datetime(2026, 11, 19, 17, 4))
        self.assertIn("۱۴۰۵/۸/۲۸", rendered)
        self.assertIn('class="lp-jalali-date"', rendered)
