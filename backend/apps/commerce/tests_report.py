from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.jalali import from_jalali, to_jalali
from apps.catalog.models import ContentNode

from . import report
from .models import Order, Plan


class SalesReportTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser("09120000801", password="x-Strong-pass-1")
        self.client.force_login(self.boss)
        self.book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب الف", slug="alef")
        self.plan = Plan.objects.create(title="ماهانه", months=1, price=150000)
        self.buyer = User.objects.create(phone="09120000802", first_name="=HYPERLINK(1)")
        now = timezone.now()
        self.order(249000, Order.Status.PAID, now, book=self.book)
        self.order(150000, Order.Status.PAID, now, plan=self.plan)
        self.order(150000, Order.Status.FAILED, None, plan=self.plan)
        self.order(100000, Order.Status.PAID, now - timedelta(days=400), book=self.book)  # outside every range but «year» sometimes

    def order(self, amount, status, paid_at, **what):
        n = Order.objects.count()
        return Order.objects.create(user=self.buyer, title="x", amount=amount, status=status, paid_at=paid_at, track_id=f"t{n}", **what)

    def test_jalali_dates(self):
        self.assertEqual(report.parse_jalali("۱۴۰۵/۸/۲۵"), from_jalali(1405, 8, 25))
        self.assertEqual(report.parse_jalali("1405-08-25"), from_jalali(1405, 8, 25))
        self.assertIsNone(report.parse_jalali("1405/7/31"))  # Mehr has 30 days
        self.assertIsNone(report.parse_jalali("1404/12/30"))  # 1404 is not a leap year
        self.assertIsNone(report.parse_jalali("hello"))
        start, end, _ = report.period("month")
        today = timezone.localdate()
        self.assertEqual(to_jalali(start.year, start.month, start.day)[2], 1)
        self.assertEqual(end, today)
        bad = report.period("custom", "1405/9/1", "1405/8/1")  # backwards: this month instead
        self.assertEqual(bad[0], start)

    def test_totals_by_book_and_plan(self):
        data = report.build("30")
        self.assertEqual(data["cards"][0]["value"], "۳۹۹٬۰۰۰")
        self.assertEqual(data["cards"][1]["value"], "۲")
        self.assertEqual(data["cards"][3]["value"], "۱")  # the failed payment
        self.assertEqual([r["name"] for r in data["by_book"]], ["کتاب الف"])
        self.assertEqual(data["by_book"][0]["share"], "۶۲٪")
        self.assertEqual(len(data["bars"]), 30)
        page = self.client.get("/admin/commerce/order/report/?range=30").content.decode()
        self.assertIn("گزارش فروش", page)
        self.assertIn("ماهانه", page)

    def test_csv_for_excel_never_runs_a_formula(self):
        response = self.client.get("/admin/commerce/order/report/csv/?range=30")
        body = response.content.decode("utf-8")
        self.assertTrue(body.startswith("﻿"))
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertIn("ناموفق", body)

    def test_list_shows_the_paid_total_and_filters_by_book(self):
        page = self.client.get(f"/admin/commerce/order/?book_id={self.book.pk}").content.decode()
        self.assertIn("۲ سفارش، ۳۴۹٬۰۰۰ تومان", page)
        self.assertIn("/admin/commerce/order/report/", page)

    def test_only_people_who_may_see_orders(self):
        self.client.force_login(User.objects.create(phone="09120000803", is_staff=True))
        self.assertEqual(self.client.get("/admin/commerce/order/report/").status_code, 403)
        self.assertEqual(self.client.get("/admin/commerce/order/report/csv/").status_code, 403)

    def test_panel_font_and_open_app_form(self):
        page = self.client.get("/admin/").content.decode()
        self.assertIn("catalog/fonts/Vazirmatn_400Regular.ttf", page)
        # A form with rel="noreferrer" sends «Origin: null» and Django's CSRF check refuses it (the 403 of the button).
        self.assertIn('rel="noopener"', page)
        self.assertNotIn("noreferrer", page)
