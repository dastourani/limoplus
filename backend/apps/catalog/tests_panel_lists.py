"""Panel lists after section «ب»: the numbers they show, no query per row, the user's page, the stats dashboard and
«خبر دادن به منتظران» (one SMS per request, never two)."""

from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import DeviceSession, User
from apps.commerce.models import Entitlement, Order
from apps.learning.models import ExamSource, Flashcard, Question, QuestionSource, Report
from apps.study.models import SectionProgress, StudyDay, StudyTime

from .models import BookWaitlist, ContentNode, ShareSettings
from .panel_display import short_text


class Base(TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser("09120000701", password="x-Strong-pass-1")
        self.client.force_login(self.boss)
        self.book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب الف", slug="alef", price=249000, is_published=True)
        self.ch1 = self.book.add_child(kind=ContentNode.Kind.CHAPTER, title="حد", slug="ch1", position=1, is_published=True)
        self.ch2 = self.book.add_child(kind=ContentNode.Kind.CHAPTER, title="مشتق", slug="ch2", position=2, is_published=True)
        self.sec = self.ch1.add_child(kind=ContentNode.Kind.SECTION, title="مفهوم حد", slug="s1", is_published=True, group="پایه")
        self.sec2 = self.ch2.add_child(kind=ContentNode.Kind.SECTION, title="قواعد", slug="s2", is_published=True)
        self.learner = User.objects.create(phone="09120000702", first_name="سارا", last_name="رضایی")

    def question(self, i, node=None):
        return Question.objects.create(node=node or self.sec, slug=f"q{i}", stem=f"اگر $x^{i}$ باشد کدام درست است؟",
                                       explanation="-", difficulty="easy")

    def queries(self, url):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return len(ctx.captured_queries), response.content.decode()


class ShortTextTests(TestCase):
    def test_never_cuts_inside_a_formula(self):
        text = "متن " * 30 + "$\\frac{a}{b}$ پایان"
        out = short_text(text, 125)
        self.assertEqual(out.count("$") % 2, 0)
        self.assertTrue(out.endswith("…"))

    def test_drops_images_and_marks(self):
        self.assertEqual(short_text("**مهم** ![](a.png) ==قرمز:x== [[#eq1|رابطه]]"), "مهم قرمز:x eq1")


class ListQueryTests(Base):
    """Each list costs the same number of queries for 2 rows as for 12: nothing is fetched row by row."""

    def grow(self, make, n):
        for i in range(n):
            make(i)

    def assertFlat(self, url, make):
        make(0), make(1)
        # A first visit may fill one-off caches (one query more at random on PostgreSQL); count from the second.
        self.queries(url)
        few, _ = self.queries(url)
        for i in range(2, 12):
            make(i)
        many, page = self.queries(url)
        self.assertEqual(few, many, f"{url}: {few} queries for 2 rows, {many} for 12")
        return page

    def test_questions(self):
        src = ExamSource.objects.create(name="کنکور دکتری", year=1402)

        def make(i):
            q = self.question(i, self.sec if i % 2 else self.sec2)
            QuestionSource.objects.create(question=q, source=src)
        page = self.assertFlat("/admin/learning/question/", make)
        self.assertIn("کنکور دکتری ۱۴۰۲", page)  # name and year as one badge
        self.assertIn("فصل ۱", page)
        self.assertIn('class="lp-tex"', page)  # formulas drawn by lists.js
        self.assertIn('id="limo-macros"', page)

    def test_flashcards(self):
        page = self.assertFlat("/admin/learning/flashcard/", lambda i: Flashcard.objects.create(
            node=self.sec, slug=f"f{i}", title=f"کارت {i}", point="نکته", formula="E=mc^2"))
        self.assertIn("$E=mc^2$", page)

    def test_sections_books_users_orders_access_reports_sessions(self):
        for i in range(12):
            u = User.objects.create(phone=f"0912100{i:04d}")
            DeviceSession.start(u, "Samsung A51", "android")
            o = Order.objects.create(user=u, book=self.book, title="خرید", amount=1000 * (i + 1), status=Order.Status.PAID, track_id=f"t{i}")
            Entitlement.objects.create(user=u, book=self.book, order=o)
            Report.objects.create(user=u, question=self.question(100 + i), reason=Report.Reason.choices[0][0], note="غلط")
        for url in ("/admin/catalog/section/", "/admin/catalog/book/", "/admin/accounts/user/", "/admin/commerce/order/",
                    "/admin/commerce/entitlement/", "/admin/learning/report/", "/admin/accounts/devicesession/",
                    "/admin/catalog/bookwaitlist/", "/admin/catalog/banner/", "/admin/catalog/label/", "/admin/learning/examsource/"):
            n, _ = self.queries(url)
            self.assertLess(n, 25, url)


class ListContentTests(Base):
    def test_book_counts_chapters_and_waiting(self):
        for i in range(3):
            BookWaitlist.objects.create(user=User.objects.create(phone=f"0912200000{i}"), book=self.book)
        BookWaitlist.objects.create(user=User.objects.create(phone="09122000009"), book=self.book, is_active=False)
        _, page = self.queries("/admin/catalog/book/")
        self.assertIn("۳ نفر", page)
        self.assertIn(f"?book_id={self.book.pk}", page)

    def test_section_shows_chapter_number_and_group_without_a_group_column(self):
        _, page = self.queries("/admin/catalog/section/")
        self.assertIn("فصل ۱", page)
        self.assertIn("پایه", page)
        self.assertNotIn("column-group", page)

    def test_user_list_numbers(self):
        u = self.learner
        Order.objects.create(user=u, book=self.book, title="a", amount=100000, status=Order.Status.PAID, track_id="a")
        Order.objects.create(user=u, book=self.book, title="b", amount=50000, status=Order.Status.PAID, track_id="b")
        Order.objects.create(user=u, book=self.book, title="c", amount=70000, status=Order.Status.FAILED, track_id="c")
        other = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب ب", slug="be")
        Entitlement.objects.create(user=u, book=self.book)
        Entitlement.objects.create(user=u, book=other)
        Entitlement.objects.create(user=u, book=other, is_archived=True)
        Entitlement.objects.create(user=u, all_majors=True, ends_at=timezone.now() + timedelta(days=10))
        StudyTime.objects.create(user=u, node=self.sec, book=self.book, day=timezone.localdate(), kind="read", seconds=1800)
        StudyTime.objects.create(user=u, node=self.sec, book=self.book, day=timezone.localdate() - timedelta(days=1), kind="quiz", seconds=1800)
        StudyTime.objects.create(user=u, node=self.sec, book=self.book, day=timezone.localdate() - timedelta(days=40), kind="read", seconds=9000)
        _, page = self.queries("/admin/accounts/user/?q=09120000702")
        self.assertIn("۱۵۰٬۰۰۰ تومان", page)  # paid only
        self.assertIn("۲ کتاب", page)  # the archived one not counted
        self.assertIn("اشتراک تا", page)
        self.assertIn("۱ ساعت", page)  # 30 days only
        self.assertIn("سارا رضایی", page)

    def test_user_page_overview_and_no_delete(self):
        Entitlement.objects.create(user=self.learner, book=self.book)
        SectionProgress.objects.create(user=self.learner, node=self.sec, book=self.book, is_done=True, percent=100)
        StudyDay.objects.create(user=self.learner, date=timezone.localdate())
        _, page = self.queries(f"/admin/accounts/user/{self.learner.pk}/change/")
        for text in ("دسترسی‌ها", "سفارش‌ها", "مطالعه", "کتاب‌هایی که می‌خواند", "هدیه دادن کتاب یا اشتراک", "همیشگی"):
            self.assertIn(text, page)
        self.assertEqual(self.client.get(f"/admin/accounts/user/{self.learner.pk}/delete/").status_code, 403)

    def test_entitlement_days_left(self):
        Entitlement.objects.create(user=self.learner, all_majors=True, ends_at=timezone.now() + timedelta(days=5, hours=2))
        Entitlement.objects.create(user=self.learner, all_majors=True, starts_at=timezone.now() - timedelta(days=40),
                                   ends_at=timezone.now() - timedelta(days=10))
        _, page = self.queries("/admin/commerce/entitlement/")
        self.assertIn("۶ روز", page)
        self.assertIn("lp-badge lp-b-yellow", page)  # a week or less
        self.assertIn("تمام شده", page)
        _, page = self.queries("/admin/commerce/entitlement/?state=soon")
        self.assertNotIn("lp-badge lp-b-red", page)
        self.assertIn("۶ روز", page)

    def test_order_status_colours(self):
        Order.objects.create(user=self.learner, book=self.book, title="x", amount=249000, status=Order.Status.FAILED, track_id="x")
        _, page = self.queries("/admin/commerce/order/")
        self.assertIn("lp-badge lp-b-red", page)
        self.assertIn("۲۴۹٬۰۰۰ تومان", page)

    def test_report_count_in_the_menu_and_snippet(self):
        Report.objects.create(user=self.learner, question=self.question(1), reason=Report.Reason.choices[0][0], note="جواب غلط است")
        _, page = self.queries("/admin/learning/report/")
        self.assertIn("lp-nav-count", page)
        self.assertIn("جواب غلط است", page)
        self.assertIn(f"/admin/catalog/book/chapter/{self.ch1.pk}/#q=q1", page)

    def test_report_on_an_archived_section(self):
        live = Report.objects.create(user=self.learner, question=self.question(1), reason=Report.Reason.choices[0][0], note="زنده")
        gone = Report.objects.create(user=self.learner, node=self.sec2, reason=Report.Reason.choices[0][0], quote="متن قدیمی")
        self.sec2.is_archived = True
        self.sec2.save(update_fields=["is_archived"])
        _, page = self.queries("/admin/learning/report/")
        self.assertEqual(page.count("بخش بایگانی‌شده</span>"), 1)
        self.assertIn(f"/admin/catalog/book/chapter/{self.ch2.pk}/#s=s2&amp;gone=1&amp;r=", page)
        # The filter picks only reports of archived sections, to close them all at once.
        _, page = self.queries("/admin/learning/report/?gone=yes")
        self.assertIn("متن قدیمی", page)
        self.assertNotIn("زنده", page)
        response = self.client.post("/admin/learning/report/?gone=yes", {"action": "mark_rejected", "_selected_action": [gone.pk]})
        self.assertEqual(response.status_code, 302)
        gone.refresh_from_db()
        live.refresh_from_db()
        self.assertEqual(gone.status, Report.Status.REJECTED)
        self.assertEqual(live.status, Report.Status.OPEN)

    def test_share_settings_opens_the_form(self):
        response = self.client.get("/admin/catalog/sharesettings/")
        row = ShareSettings.objects.get()
        self.assertRedirects(response, f"/admin/catalog/sharesettings/{row.pk}/change/")

    def test_exam_sources(self):
        mine = ExamSource.objects.create(name="کنکور ارشد", year=1399)
        other = ExamSource.objects.create(name="کنکور ارشد", year=1399, group="ب")
        q1, q2 = self.question(1), self.question(2)
        QuestionSource.objects.create(question=q1, source=mine)
        QuestionSource.objects.create(question=q2, source=other)
        _, page = self.queries("/admin/learning/examsource/")
        self.assertIn("۱۳۹۹", page)
        self.assertIn("—", page)
        self.assertIn(f"?source={mine.pk}", page)
        _, page = self.queries(f"/admin/learning/question/?source={mine.pk}")
        self.assertIn("x^1", page)
        self.assertNotIn("x^2", page)

    def test_device_names(self):
        from apps.accounts.admin import device_label

        def s(name, platform):
            return DeviceSession(device_name=name, platform=platform)
        self.assertEqual(device_label(s("Samsung SM-A515F", "android")), "Samsung SM-A515F (اندروید)")
        self.assertEqual(device_label(s("مرورگر وب", "web")), "مرورگر وب")
        self.assertEqual(device_label(s("web", "")), "مرورگر وب")
        self.assertEqual(device_label(s("", "android")), "گوشی اندروید")
        self.assertEqual(device_label(s("", "")), "دستگاه ناشناس")


class DashboardTests(Base):
    def test_week_against_week_before_and_only_active_days(self):
        today = timezone.localdate()
        for days_ago in (1, 2, 9):
            StudyDay.objects.create(user=self.learner, date=today - timedelta(days=days_ago), answers=5)
        StudyTime.objects.create(user=self.learner, node=self.sec, book=self.book, day=today - timedelta(days=1), kind="read", seconds=600)
        from apps.study.dashboard import build, change

        data = build()
        # Days without activity are left out: the three study days and today (two sign-ups in setUp).
        self.assertEqual(len(data["table"]), 4)
        answers = next(c for c in data["weekly"] if "پاسخ" in c["label"])
        self.assertEqual(answers["value"], "۱۰")
        self.assertIn("۱۰۰٪", answers["text"])  # 10 against 5
        self.assertEqual(change(5, 10)["color"], "red")
        self.assertEqual(len(data["chart"]["dots"]), 30)
        n, page = self.queries("/admin/study/dashboard/")
        self.assertIn("dash-chart", page)
        self.assertNotIn("2026-", page)  # Jalali dates only
        self.assertLess(n, 30)


@override_settings(WAITLIST_SMS_ENABLED=True, SMS_BACKEND="console")
class WaitlistSMSTests(Base):
    def setUp(self):
        super().setUp()
        self.people = [User.objects.create(phone=f"0912300000{i}") for i in range(3)]
        for u in self.people:
            BookWaitlist.objects.create(user=u, book=self.book)
        self.cancelled = BookWaitlist.objects.create(user=User.objects.create(phone="09123000009"), book=self.book, is_active=False)
        self.url = f"/admin/catalog/book/{self.book.pk}/notify-waitlist/"

    def send(self):
        from .waitlist_sms import send_queued

        with mock.patch("apps.accounts.sms.send_sms") as sms:
            send_queued(self.book.pk, pause=0)
        return sms

    def test_confirmation_then_one_sms_each_never_twice(self):
        page = self.client.get(self.url).content.decode()
        self.assertIn("۳", page)
        self.assertIn("/book/alef", page)
        with self.captureOnCommitCallbacks(execute=False):
            response = self.client.post(self.url, {"text": "کتاب الف منتشر شد"})
        self.assertEqual(response.status_code, 302)
        sms = self.send()
        self.assertEqual(sorted(c.args[0] for c in sms.call_args_list), [u.phone for u in self.people])
        self.assertEqual(sms.call_args_list[0].args[1], "کتاب الف منتشر شد")
        self.assertEqual(BookWaitlist.objects.filter(notified_at__isnull=False).count(), 3)
        # Pressed again: nobody left to tell.
        with self.captureOnCommitCallbacks(execute=False):
            self.client.post(self.url, {"text": "دوباره"})
        self.assertEqual(self.send().call_count, 0)
        self.cancelled.refresh_from_db()
        self.assertIsNone(self.cancelled.notified_at)

    def test_a_failed_sms_is_kept_and_sent_again_later(self):
        from apps.accounts.sms import SMSNotSent

        from .waitlist_sms import queue, send_queued

        queue(self.book, "متن", start=False)
        with mock.patch("apps.accounts.sms.send_sms", side_effect=[None, SMSNotSent("no credit"), None]):
            done = send_queued(self.book.pk, pause=0)
        self.assertEqual(done, {"sent": 2, "failed": 1})
        failed = BookWaitlist.objects.get(notified_at__isnull=True, is_active=True)
        self.assertEqual(failed.notify_error, "no credit")
        self.assertIsNone(failed.notify_queued_at)
        self.assertIn("ناموفق", self.client.get("/admin/catalog/bookwaitlist/").content.decode())
        queue(self.book, "متن", start=False)
        with mock.patch("apps.accounts.sms.send_sms") as sms:
            send_queued(self.book.pk, pause=0)
        self.assertEqual([c.args[0] for c in sms.call_args_list], [failed.user.phone])

    def test_an_unclear_answer_is_never_sent_again(self):
        from apps.accounts.sms import SMSError

        from .waitlist_sms import queue, send_queued

        queue(self.book, "متن", start=False)
        with mock.patch("apps.accounts.sms.send_sms", side_effect=SMSError("timed out")):
            send_queued(self.book.pk, pause=0)
        self.assertEqual(BookWaitlist.objects.filter(notified_at__isnull=False).count(), 3)  # maybe sent: not again
        self.assertIn("نامعلوم", self.client.get("/admin/catalog/bookwaitlist/").content.decode())
        self.assertEqual(queue(self.book, "متن", start=False), 0)

    def test_the_hourly_retry_sends_the_confirmed_text(self):
        from .waitlist_sms import queue, retry_stuck

        queue(self.book, "متن تأییدشده", start=False)  # the process that queued them stopped
        BookWaitlist.objects.update(notify_queued_at=timezone.now() - timedelta(hours=1))
        with mock.patch("apps.accounts.sms.send_sms") as sms, mock.patch("apps.catalog.waitlist_sms.PAUSE_SECONDS", 0):
            retry_stuck()
        self.assertEqual({c.args[1] for c in sms.call_args_list}, {"متن تأییدشده"})

    def test_raygan_failures_are_told_apart(self):
        import requests

        from apps.accounts.sms import SMSError, SMSNotSent, _send_raygan

        with override_settings(RAYGAN_USERNAME="u", RAYGAN_PASSWORD="p", RAYGAN_SENDER_NUMBER="1"):
            with mock.patch("apps.accounts.sms.requests.post", side_effect=requests.ConnectionError("down")):
                self.assertRaises(SMSNotSent, _send_raygan, "09120000000", "x")
            with mock.patch("apps.accounts.sms.requests.post", side_effect=requests.ReadTimeout("slow")):
                with self.assertRaises(SMSError) as caught:
                    _send_raygan("09120000000", "x")
                self.assertNotIsInstance(caught.exception, SMSNotSent)
            with mock.patch("apps.accounts.sms.requests.post", return_value=mock.Mock(status_code=200, text="-3")):
                self.assertRaises(SMSNotSent, _send_raygan, "09120000000", "x")
            with mock.patch("apps.accounts.sms.requests.post", return_value=mock.Mock(status_code=200, text="12345")):
                _send_raygan("09120000000", "x")

    def test_off_or_coming_soon_sends_nothing(self):
        from .waitlist_sms import queue

        with override_settings(WAITLIST_SMS_ENABLED=False):
            self.assertIn("خاموش", self.client.get(self.url).content.decode())
            self.client.post(self.url, {"text": "x"})
            self.assertEqual(queue(self.book, "x", start=False), 0)
        ContentNode.objects.filter(pk=self.book.pk).update(is_coming_soon=True)
        self.book.refresh_from_db()
        self.assertEqual(queue(self.book, "x", start=False), 0)
        self.assertEqual(self.send().call_count, 0)
        self.assertFalse(BookWaitlist.objects.filter(notify_queued_at__isnull=False).exists())

    def test_hourly_retry_finishes_only_stopped_runs(self):
        from .waitlist_sms import retry_stuck

        BookWaitlist.objects.filter(user=self.people[0]).update(notify_queued_at=timezone.now() - timedelta(hours=1))
        BookWaitlist.objects.filter(user=self.people[1]).update(notify_queued_at=timezone.now())  # still being sent
        with mock.patch("apps.accounts.sms.send_sms") as sms, mock.patch("apps.catalog.waitlist_sms.PAUSE_SECONDS", 0):
            self.assertEqual(retry_stuck(), 1)
        self.assertEqual([c.args[0] for c in sms.call_args_list], [self.people[0].phone])

    def test_only_staff_with_book_rights(self):
        self.client.force_login(User.objects.create(phone="09123000099", is_staff=True))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class BookTeacherAdminScopeTests(Base):
    """Every content list is scoped to the teacher's assigned books; direct routes cannot hop to another book."""

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Group

        from apps.catalog.access import BOOK_EDITOR_GROUP
        from apps.catalog.models import BookEditor, ChapterRevision

        self.other_book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب محرمانه", slug="secret-book")
        self.other_chapter = self.other_book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل پنهان", slug="secret-ch", is_published=False)
        self.other_section = self.other_chapter.add_child(kind=ContentNode.Kind.SECTION, title="بخش پنهان", slug="secret-sec")
        self.own_question = self.question(301, self.sec)
        self.other_question = self.question(302, self.other_section)
        self.own_card = Flashcard.objects.create(node=self.sec, slug="own-card", title="کارت من", point="نکته")
        self.other_card = Flashcard.objects.create(node=self.other_section, slug="secret-card", title="کارت محرمانه", point="نکته")
        self.own_revision = ChapterRevision.objects.create(chapter=self.ch1, text="نسخه‌ی خودم", source="panel")
        self.other_revision = ChapterRevision.objects.create(chapter=self.other_chapter, text="نسخه‌ی محرمانه", source="panel")
        self.own_report = Report.objects.create(user=self.learner, question=self.own_question, reason=Report.Reason.TYPO, note="گزارش خودم")
        self.other_report = Report.objects.create(user=self.learner, question=self.other_question, reason=Report.Reason.TYPO, note="گزارش محرمانه")
        self.own_source = ExamSource.objects.create(name="منبع کتاب من", year=1401)
        self.other_source = ExamSource.objects.create(name="منبع محرمانه", year=1402)
        QuestionSource.objects.create(question=self.own_question, source=self.own_source)
        QuestionSource.objects.create(question=self.other_question, source=self.other_source)

        self.teacher = User.objects.create_user("09123000111", is_staff=True)
        self.teacher.groups.add(Group.objects.get(name=BOOK_EDITOR_GROUP))
        BookEditor.objects.create(book=self.book, user=self.teacher)
        self.client.force_login(self.teacher)

    def admin_request(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/admin/")
        request.user = self.teacher
        return request

    def test_each_content_admin_queryset_stays_inside_the_assigned_book(self):
        from django.contrib import admin

        from apps.catalog.models import Book, ChapterRevision, Section

        request = self.admin_request()
        cases = (
            (Book, {self.book.pk}),
            (Section, {self.sec.pk, self.sec2.pk}),
            (ChapterRevision, {self.own_revision.pk}),
            (Question, {self.own_question.pk}),
            (Flashcard, {self.own_card.pk}),
            (Report, {self.own_report.pk}),
            (ExamSource, {self.own_source.pk}),
        )
        for model, expected in cases:
            with self.subTest(model=model.__name__):
                rows = admin.site._registry[model].get_queryset(request)
                self.assertEqual(set(rows.values_list("pk", flat=True)), expected)

    def test_report_list_hides_other_books_and_reporter_identity(self):
        from django.contrib import admin

        response = self.client.get("/admin/learning/report/")
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        self.assertIn("گزارش خودم", page)
        self.assertNotIn("گزارش محرمانه", page)
        self.assertNotIn(self.learner.phone, page)
        actions = admin.site._registry[Report].get_actions(self.admin_request())
        self.assertNotIn("block_reporter", actions)
        self.assertNotIn("unblock_reporter", actions)

    def test_other_book_routes_are_not_reachable_even_with_forged_ids(self):
        from django.urls import reverse

        response = self.client.get(reverse("admin:catalog_book_change", args=[self.other_book.pk]))
        self.assertIn(response.status_code, (302, 403, 404))
        if response.status_code == 302:
            self.assertIn(response["Location"], ("/admin/", "/admin/catalog/book/"))
            page = self.client.get(response["Location"]).content.decode()
            self.assertNotIn("کتاب محرمانه", page)
        response = self.client.get(reverse("admin:catalog_chapter_manager", args=[self.other_chapter.pk]))
        self.assertEqual(response.status_code, 403)
        response = self.client.get(reverse("admin:catalog_chapter_api", args=[self.other_chapter.pk]))
        self.assertEqual(response.status_code, 403)
        from apps.catalog.filters import _book_choices

        self.assertEqual({int(pk) for pk, _title in _book_choices(user=self.teacher)}, {self.book.pk})
