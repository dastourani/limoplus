import datetime

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import User

from .filters import BookFilter, ChapterFilter
from .models import ContentNode
from .panel_display import badges, fa_number


class PanelDisplayTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser("09120000601", password="x-Strong-pass-1")
        self.client.force_login(self.boss)
        self.book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب الف", slug="alef", price=249000)
        self.inbox = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="صندوق تست", slug="inbox", is_inbox=True)
        self.chapter = self.book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل یک", slug="ch1", position=1)

    def test_numbers(self):
        self.assertEqual(fa_number(249000), "۲۴۹٬۰۰۰")
        self.assertEqual(fa_number(1401), "۱۴۰۱")  # a year: no separator
        self.assertEqual(fa_number(12345.5), "۱۲٬۳۴۵٫۵")

    def test_lists_show_jalali_dates_and_persian_prices(self):
        page = self.client.get("/admin/catalog/book/").content.decode()
        self.assertIn("۲۴۹٬۰۰۰", page)
        self.assertIn('class="lp-badge', page)  # one status column
        User.objects.filter(pk=self.boss.pk).update(date_joined=timezone.make_aware(datetime.datetime(2026, 11, 15, 12, 35)))
        page = self.client.get("/admin/accounts/user/").content.decode()
        self.assertIn("۱۴۰۵/۸/۲۴", page)
        self.assertNotIn("نوامبر", page)

    def test_book_filter_hides_the_inbox_and_chapters_wait_for_a_book(self):
        request = RequestFactory().get("/")
        books = BookFilter(request, {}, ContentNode, admin.site._registry[ContentNode] if ContentNode in admin.site._registry else None).lookups(request, None)
        self.assertEqual([t for _, t in books], ["کتاب الف"])
        self.assertEqual(ChapterFilter(request, {}, ContentNode, None).lookups(request, None), [])
        with_book = RequestFactory().get("/", {"book": str(self.book.pk)})
        self.assertEqual(len(ChapterFilter(with_book, {}, ContentNode, None).lookups(with_book, None)), 1)

    def test_long_filters_become_a_drop_down(self):
        for i in range(10):
            ContentNode.add_root(kind=ContentNode.Kind.BOOK, title=f"کتاب {i}", slug=f"b{i}")
        page = self.client.get("/admin/catalog/section/").content.decode()
        self.assertIn('class="lp-filter-select"', page)

    def test_badges(self):
        self.assertEqual(badges(False, None), "—")
        html = str(badges(("منتشر", "green"), False, ("رایگان", "blue")))
        self.assertIn("lp-b-green", html)
        self.assertIn("رایگان", html)
