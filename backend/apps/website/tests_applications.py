from django.contrib.auth.models import Group
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import BookEditor

from .models import TeacherApplication


class TeacherApplicationPublicTests(TestCase):
    def _data(self, **overrides):
        return {
            "name": "نسترن پژوهشگر",
            "phone": "۰۹۱۲۱۲۳۴۵۶۷",
            "book_or_link": "کتاب زیست‌شناسی یا پیوند معرفی کتاب",
            "resume_url": "https://example.com/profile",
            "collaboration_scope": TeacherApplication.CollaborationScope.PUBLIC_AND_CLASS,
            "explanation": "برای تدوین محتوای آموزشی و بازبینی آن درخواست همکاری دارم.",
            "sample_work": "شرح نمونه‌کار آموزشی و پیوند آن: https://example.com/work",
            **overrides,
        }

    def test_public_submission_creates_only_a_pending_review_record(self):
        group_count = Group.objects.count()
        response = self.client.post(reverse("website:teacher-application"), self._data(), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "درخواست همکاری شما ثبت شد. در صورت تأیید، لینک دعوت به میز تألیف برایتان ارسال می‌شود.")
        application = TeacherApplication.objects.get()
        self.assertEqual(application.phone, "09121234567")
        self.assertEqual(application.status, TeacherApplication.Status.PENDING)
        self.assertEqual(application.name, "نسترن پژوهشگر")
        self.assertEqual(application.resume_url, "https://example.com/profile")
        self.assertEqual(application.collaboration_scope, TeacherApplication.CollaborationScope.PUBLIC_AND_CLASS)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Group.objects.count(), group_count)
        self.assertFalse(BookEditor.objects.filter(user__phone=application.phone).exists())

    def test_submission_with_only_basic_fields_succeeds(self):
        response = self.client.post(
            reverse("website:teacher-application"),
            {
                "name": "استاد کم‌فرم",
                "phone": "09121234568",
                "book_or_link": "ریاضی عمومی ۱",
                "resume_url": "",
                "collaboration_scope": "",
                "sample_work": "",
                "explanation": "",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "درخواست همکاری شما ثبت شد. در صورت تأیید، لینک دعوت به میز تألیف برایتان ارسال می‌شود.")
        self.assertContains(response, "استفادهٔ خصوصی برای دانشجویان خودتان رایگان است.")
        application = TeacherApplication.objects.get()
        self.assertEqual(application.phone, "09121234568")
        self.assertEqual(application.resume_url, "")
        self.assertEqual(application.collaboration_scope, "")
        self.assertEqual(application.sample_work, "")
        self.assertEqual(application.explanation, "")
        self.assertEqual(User.objects.count(), 0)
        self.assertFalse(BookEditor.objects.filter(user__phone=application.phone).exists())

    def test_top_copy_does_not_promise_guaranteed_invite(self):
        response = self.client.get(reverse("website:teacher-application"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "در صورت تأیید، لینک دعوت به میز تألیف برایتان ارسال می‌شود.")
        self.assertNotContains(response, "پس از بررسی، لینک ورود")

    def test_invalid_phone_does_not_create_a_record(self):
        response = self.client.post(reverse("website:teacher-application"), self._data(phone="02112345678"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "شماره موبایل معتبر نیست")
        self.assertFalse(TeacherApplication.objects.exists())

    def test_honeypot_is_silent_and_does_not_store_a_submission(self):
        response = self.client.post(reverse("website:teacher-application"), self._data(website="spam"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "درخواست همکاری شما ثبت شد. در صورت تأیید، لینک دعوت به میز تألیف برایتان ارسال می‌شود.")
        self.assertFalse(TeacherApplication.objects.exists())
        self.assertEqual(User.objects.count(), 0)

    @override_settings(TEACHER_APPLICATIONS_PER_PHONE_PER_HOUR=5)
    def test_duplicate_open_request_is_not_created_or_disclosed_across_ips(self):
        first = Client(REMOTE_ADDR="198.51.100.20")
        second = Client(REMOTE_ADDR="198.51.100.21")
        first_response = first.post(reverse("website:teacher-application"), self._data(), follow=True)
        second_response = second.post(
            reverse("website:teacher-application"),
            self._data(phone="+98 912 123 4567"),
            follow=True,
        )
        self.assertContains(first_response, "درخواست همکاری شما ثبت شد. در صورت تأیید، لینک دعوت به میز تألیف برایتان ارسال می‌شود.")
        self.assertContains(second_response, "درخواست همکاری شما ثبت شد. در صورت تأیید، لینک دعوت به میز تألیف برایتان ارسال می‌شود.")
        self.assertEqual(TeacherApplication.objects.filter(phone="09121234567").count(), 1)

    @override_settings(TEACHER_APPLICATIONS_PER_IP_PER_HOUR=1)
    def test_submission_rate_limit_is_per_ip(self):
        first = self.client.post(reverse("website:teacher-application"), self._data(), follow=True)
        self.assertEqual(first.status_code, 200)

        limited = self.client.post(
            reverse("website:teacher-application"),
            self._data(phone="09120000123"),
        )
        self.assertEqual(limited.status_code, 429)
        self.assertContains(limited, "تعداد ارسال درخواست از این نشانی زیاد است", status_code=429)
        self.assertEqual(TeacherApplication.objects.count(), 1)

    def test_public_form_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("website:teacher-application"))
        response = client.post(reverse("website:teacher-application"), self._data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(TeacherApplication.objects.exists())

    def test_contact_page_and_footer_link_to_the_application(self):
        response = self.client.get("/site/p/contact/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("website:teacher-application"))
        self.assertContains(response, "درخواست همکاری آموزشی")


class TeacherApplicationReviewTests(TestCase):
    def setUp(self):
        self.application = TeacherApplication.objects.create(
            name="مینا مدرس",
            phone="09120000101",
            book_or_link="زیست‌شناسی",
            explanation="درخواست همکاری برای تولید محتوای آموزشی.",
            sample_work="نمونه‌کار آموزشی.",
        )
        self.staff = User.objects.create_user("09120000102", is_staff=True)
        self.manager = User.objects.create_superuser("09120000103", password="Manager-Password-123")
        self.list_url = reverse("admin:website_teacherapplication_changelist")
        self.change_url = reverse("admin:website_teacherapplication_change", args=[self.application.pk])

    def test_only_superusers_can_open_the_review_queue(self):
        staff_client = Client()
        staff_client.force_login(self.staff)
        self.assertEqual(staff_client.get(self.list_url).status_code, 403)
        self.assertEqual(staff_client.get(self.change_url).status_code, 403)

        manager_client = Client()
        manager_client.force_login(self.manager)
        self.assertEqual(manager_client.get(self.list_url).status_code, 200)
        self.assertEqual(manager_client.get(self.change_url).status_code, 200)
        self.assertEqual(manager_client.get(reverse("admin:website_teacherapplication_add")).status_code, 403)

    def test_decision_records_reviewer_and_time_but_grants_no_account_or_access(self):
        client = Client()
        client.force_login(self.manager)
        response = client.post(self.change_url, {
            "status": TeacherApplication.Status.APPROVED,
            "review_note": "بررسی شد؛ دعوت در مرحله‌ی بعد انجام می‌شود.",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 302)

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, TeacherApplication.Status.APPROVED)
        self.assertEqual(self.application.reviewed_by, self.manager)
        self.assertIsNotNone(self.application.reviewed_at)
        self.assertEqual(self.application.review_note, "بررسی شد؛ دعوت در مرحله‌ی بعد انجام می‌شود.")
        self.assertFalse(User.objects.filter(phone=self.application.phone).exists())
        self.assertFalse(BookEditor.objects.filter(user__phone=self.application.phone).exists())
        self.assertFalse(self.manager.edited_books.filter(book__isnull=False).exists())

    def test_unspecified_collaboration_scope_displays_not_declared_in_admin(self):
        self.assertEqual(self.application.collaboration_scope, "")
        client = Client()
        client.force_login(self.manager)
        changelist = client.get(self.list_url)
        change = client.get(self.change_url)
        self.assertEqual(changelist.status_code, 200)
        self.assertEqual(change.status_code, 200)
        self.assertContains(changelist, "اعلام نشده")
        self.assertContains(change, "اعلام نشده")
