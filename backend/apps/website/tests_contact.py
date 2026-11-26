from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from .models import ContactMessage, SiteSettings


class ContactPageAndFormTests(TestCase):
    def setUp(self):
        self.url = reverse("website:page", args=["contact"])

    def _data(self, **overrides):
        return {
            "topic": ContactMessage.Topic.ORDER_PAYMENT,
            "name": "سارا محمدی",
            "phone": "۰۹۱۲۱۲۳۴۵۶۷",
            "email": "sara@example.com",
            "order_reference": "ZB-88421",
            "related_item": "ریاضی عمومی ۱",
            "message": "مبلغ از حسابم کسر شده اما دسترسی کتاب هنوز فعال نشده است.",
            **overrides,
        }

    def test_contact_page_renders_structured_support_form_and_official_channels(self):
        s = SiteSettings.get()
        s.email = "support@limookhan.ir"
        s.phone = "021-88112233"
        s.address = "تهران، خیابان آزادی"
        s.save()

        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "این متن نمونه است")
        self.assertContains(r, "ارسال پیام به پشتیبانی")
        self.assertContains(r, "پرداخت ناموفق")
        self.assertContains(r, "۷ روز کاری")
        self.assertContains(r, "support@limookhan.ir")
        self.assertContains(r, "021-88112233")
        self.assertContains(r, "تهران، خیابان آزادی")
        self.assertContains(r, reverse("website:teacher-application"))
        self.assertContains(r, reverse("teacher-login"))

    def test_query_param_preselects_valid_topic(self):
        r = self.client.get(self.url, {"topic": "refund"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["contact_active_topic"]["value"], ContactMessage.Topic.REFUND)

    @patch("apps.catalog.backups.notify_bale_after_commit")
    def test_valid_payment_submission_creates_high_priority_ticket_and_tracking_code(self, mock_bale):
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url, self._data(), follow=True)
        self.assertEqual(r.status_code, 200)
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.phone, "09121234567")
        self.assertEqual(msg.priority, ContactMessage.Priority.HIGH)
        self.assertEqual(msg.status, ContactMessage.Status.NEW)
        self.assertEqual(msg.order_reference, "ZB-88421")
        self.assertTrue(msg.tracking_code.startswith("LM-"))
        self.assertContains(r, msg.tracking_code)
        self.assertContains(r, "پیام شما با موفقیت ثبت شد")
        mock_bale.assert_called_once()
        self.assertIn(msg.tracking_code, mock_bale.call_args.args[0])

    def test_phone_required_for_sensitive_topics_even_if_email_is_given(self):
        for topic in (
            ContactMessage.Topic.ORDER_PAYMENT,
            ContactMessage.Topic.REFUND,
            ContactMessage.Topic.ACCOUNT_ACCESS,
            ContactMessage.Topic.PRIVACY,
        ):
            r = self.client.post(self.url, self._data(topic=topic, phone="", email="user@example.com"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "شماره موبایل ثبت‌شده یا شماره تماس معتبر الزامی است")
        self.assertFalse(ContactMessage.objects.exists())

    def test_general_topics_accept_email_only_and_reject_when_both_phone_and_email_missing(self):
        bad = self.client.post(
            self.url,
            self._data(topic=ContactMessage.Topic.OTHER, phone="", email=""),
        )
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "دست‌کم شماره موبایل یا نشانی ایمیل را وارد کنید")
        self.assertFalse(ContactMessage.objects.exists())

        good = self.client.post(
            self.url,
            self._data(topic=ContactMessage.Topic.CONTENT_COPYRIGHT, phone="", email="Reader@Example.com", order_reference=""),
            follow=True,
        )
        self.assertEqual(good.status_code, 200)
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.email, "reader@example.com")
        self.assertEqual(msg.priority, ContactMessage.Priority.NORMAL)
        self.assertContains(good, msg.tracking_code)

    def test_honeypot_is_silent_and_does_not_store_a_message(self):
        r = self.client.post(self.url, self._data(website="https://spam.invalid"), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "پیام شما با موفقیت ثبت شد")
        self.assertFalse(ContactMessage.objects.exists())

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.get(self.url)
        r = client.post(self.url, self._data())
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ContactMessage.objects.exists())

    @override_settings(CONTACT_MESSAGES_PER_IP_PER_HOUR=1)
    def test_ip_rate_limit(self):
        first = self.client.post(self.url, self._data(), follow=True)
        self.assertEqual(first.status_code, 200)
        second = self.client.post(self.url, self._data(phone="09120000111"))
        self.assertEqual(second.status_code, 429)
        self.assertContains(second, "تعداد پیام‌های ارسالی", status_code=429)
        self.assertEqual(ContactMessage.objects.count(), 1)

    @override_settings(CONTACT_MESSAGES_PER_IP_PER_HOUR=10, CONTACT_MESSAGES_PER_SENDER_PER_HOUR=1)
    def test_sender_rate_limit_across_ips(self):
        c1 = Client(REMOTE_ADDR="198.51.100.30")
        c2 = Client(REMOTE_ADDR="198.51.100.31")
        r1 = c1.post(self.url, self._data(), follow=True)
        self.assertEqual(r1.status_code, 200)
        r2 = c2.post(self.url, self._data(phone="+98 912 123 4567"))
        self.assertEqual(r2.status_code, 429)
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_authenticated_user_prefills_and_attaches_user(self):
        user = User.objects.create_user("09125554433", first_name="امیر", last_name="رضایی")
        self.client.force_login(user)
        get_r = self.client.get(self.url)
        self.assertContains(get_r, "امیر رضایی")
        self.assertContains(get_r, "09125554433")

        post_r = self.client.post(self.url, self._data(phone="09125554433"), follow=True)
        self.assertEqual(post_r.status_code, 200)
        msg = ContactMessage.objects.get()
        self.assertEqual(msg.user, user)


class ContactMessageAdminTests(TestCase):
    def setUp(self):
        self.msg = ContactMessage.objects.create(
            topic=ContactMessage.Topic.REFUND,
            priority=ContactMessage.Priority.NORMAL,
            name="نیلوفر کاربر",
            phone="09121112233",
            order_reference="ORD-99",
            message="درخواست بررسی انصراف در بازه ۷ روز کاری.",
        )
        self.staff = User.objects.create_user("09120000201", is_staff=True)
        self.manager = User.objects.create_superuser("09120000202", password="Manager-Password-123")
        self.list_url = reverse("admin:website_contactmessage_changelist")
        self.change_url = reverse("admin:website_contactmessage_change", args=[self.msg.pk])

    def test_only_superusers_can_view_and_update_contact_inbox(self):
        staff_client = Client()
        staff_client.force_login(self.staff)
        self.assertEqual(staff_client.get(self.list_url).status_code, 403)
        self.assertEqual(staff_client.get(self.change_url).status_code, 403)

        manager_client = Client()
        manager_client.force_login(self.manager)
        self.assertEqual(manager_client.get(self.list_url).status_code, 200)
        res = manager_client.post(
            self.change_url,
            {
                "priority": ContactMessage.Priority.HIGH,
                "status": ContactMessage.Status.RESOLVED,
                "admin_note": "مبلغ به حساب کاربر مسترد شد.",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.msg.refresh_from_db()
        self.assertEqual(self.msg.status, ContactMessage.Status.RESOLVED)
        self.assertEqual(self.msg.priority, ContactMessage.Priority.HIGH)
        self.assertEqual(self.msg.handled_by, self.manager)
        self.assertIsNotNone(self.msg.handled_at)
