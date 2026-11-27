from datetime import timedelta
from io import StringIO
import threading
from unittest import mock

from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import CommandError, call_command
from django.db import close_old_connections, connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import OTPCode, TeacherNotification, User
from apps.accounts.notifications import retry_teacher_notifications
from apps.catalog.access import BOOK_EDITOR_GROUP
from apps.catalog.models import BookEditor, ContentNode
from apps.commerce.models import BookRoyaltyRule, PayoutRequest, TeacherBankAccount, TeacherWallet
from apps.commerce.wallet import finalize_payout_paid, reject_payout_request, request_teacher_payout
from apps.website.models import BookAccessRequest, PublicationRequest
from apps.website.publication import publication_content_digest


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_VERIFICATION_EXPIRY_HOURS=24,
    SITE_URL="https://limookhan.ir",
)
class TeacherEmailLifecycleTests(TestCase):
    def setUp(self):
        mail.outbox.clear()
        teacher_group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        self.teacher = User.objects.create_user(
            "09121000001",
            first_name="مریم",
            last_name="کاظمی",
            is_staff=True,
        )
        self.teacher.groups.add(teacher_group)
        self.other_teacher = User.objects.create_user(
            "09121000002",
            first_name="علی",
            last_name="رضایی",
            is_staff=True,
        )
        self.other_teacher.groups.add(teacher_group)
        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="ریاضی پیشرفته",
            slug="adv-math",
            is_published=False,
        )
        BookEditor.objects.create(
            book=self.book,
            user=self.teacher,
            can_edit_content=True,
            can_request_publication=True,
            can_request_group_access=True,
        )
        self.client = Client()
        self.client.force_login(self.teacher)

    def _extract_verify_path(self, email_message) -> str:
        for token in email_message.body.split():
            if "/verify-email/" in token:
                idx = token.index("/verify-email/")
                return token[idx:]
        self.fail(f"Verification URL not found in email body: {email_message.body}")

    def test_header_always_offers_edit_link_for_unverified_and_verified_email(self):
        res_empty = self.client.get(reverse("admin:index"))
        self.assertContains(res_empty, reverse("admin:accounts_user_change_email"))

        self.teacher.email = "typo@example.com"
        self.teacher.save(update_fields=["email"])
        res_unverified = self.client.get(reverse("admin:index"))
        self.assertContains(res_unverified, reverse("admin:accounts_user_change_email"))
        self.assertContains(res_unverified, reverse("admin:accounts_user_send_verification"))

        self.teacher.email_verified_at = timezone.now()
        self.teacher.save(update_fields=["email_verified_at"])
        res_verified = self.client.get(reverse("admin:index"))
        self.assertContains(res_verified, reverse("admin:accounts_user_change_email"))

    def test_email_change_a_to_b_to_a_stops_old_address_and_invalidates_prior_links(self):
        # Step 1: set email A and verify it
        res1 = self.client.post(reverse("admin:accounts_user_change_email"), {"email": "alpha@example.com"}, follow=True)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        link_a1 = self._extract_verify_path(mail.outbox[-1])
        self.assertEqual(self.client.get(link_a1).status_code, 302)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.is_email_verified)
        self.assertEqual(self.teacher.email, "alpha@example.com")

        # Step 2: change verified A -> wrong B; verification must drop immediately in DB
        self.client.post(reverse("admin:accounts_user_change_email"), {"email": "beta-typo@example.com"}, follow=True)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.email, "beta-typo@example.com")
        self.assertFalse(self.teacher.is_email_verified)
        self.assertIsNone(self.teacher.email_verified_at)
        link_b = self._extract_verify_path(mail.outbox[-1])

        # Book export email to previous address must be blocked immediately
        export_res = self.client.get(reverse("admin:catalog_book_email_export", args=[self.book.pk]))
        self.assertEqual(export_res.status_code, 302)
        self.assertEqual(len(mail.outbox), 2)

        # Step 3: change B -> back to A; link_a1 and link_b must NOT verify the new A request
        self.client.post(reverse("admin:accounts_user_change_email"), {"email": "alpha@example.com"}, follow=True)
        link_a2 = self._extract_verify_path(mail.outbox[-1])

        # Replay link_a1 (from first A) -> must be rejected with 400 and keep unverified
        replay_a1 = self.client.get(link_a1)
        self.assertEqual(replay_a1.status_code, 400)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_email_verified)

        # Replay link_b -> must be rejected
        replay_b = self.client.get(link_b)
        self.assertEqual(replay_b.status_code, 400)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_email_verified)

        # Open genuine link_a2 -> succeeds, and second open of link_a2 is rejected (single-use)
        verify_ok = self.client.get(link_a2)
        self.assertEqual(verify_ok.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher.is_email_verified)

        second_use = self.client.get(link_a2)
        self.assertEqual(second_use.status_code, 400)

    def test_verification_link_expires_after_configured_hours(self):
        self.client.post(reverse("admin:accounts_user_change_email"), {"email": "exp@example.com"})
        link = self._extract_verify_path(mail.outbox[-1])
        User.objects.filter(pk=self.teacher.pk).update(
            email_verification_sent_at=timezone.now() - timedelta(hours=25)
        )
        res = self.client.get(link)
        self.assertEqual(res.status_code, 400)
        self.assertContains(res, "مهلت", status_code=400)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_email_verified)

    def test_verification_link_rejected_when_different_user_logged_in(self):
        self.client.post(reverse("admin:accounts_user_change_email"), {"email": "mine@example.com"})
        link = self._extract_verify_path(mail.outbox[-1])
        other_client = Client()
        other_client.force_login(self.other_teacher)
        res = other_client.get(link)
        self.assertEqual(res.status_code, 403)
        self.teacher.refresh_from_db()
        self.assertFalse(self.teacher.is_email_verified)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_URL="https://limookhan.ir",
)
class TeacherWorkflowNotificationsTests(TestCase):
    def setUp(self):
        mail.outbox.clear()
        teacher_group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        self.manager = User.objects.create_superuser("09120000099", password="Manager-Password-123")
        self.teacher = User.objects.create_user(
            "09121111111",
            first_name="سهراب",
            last_name="سپهری",
            email="sohrab@example.com",
            email_verified_at=timezone.now(),
            is_staff=True,
        )
        self.teacher.groups.add(teacher_group)
        self.other_teacher = User.objects.create_user(
            "09122222222",
            first_name="فروغ",
            last_name="فرخزاد",
            email="forough@example.com",
            email_verified_at=timezone.now(),
            is_staff=True,
        )
        self.other_teacher.groups.add(teacher_group)
        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="فیزیک کوانتوم",
            slug="quantum-physics",
            price=180000,
            is_published=False,
        )
        BookEditor.objects.create(
            book=self.book,
            user=self.teacher,
            can_edit_content=True,
            can_request_publication=True,
            can_request_group_access=True,
        )
        self.pub_req = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            request_note="آماده بازبینی است.",
            content_digest=publication_content_digest(self.book),
            status=PublicationRequest.Status.PENDING,
        )
        self.mgr_client = Client()
        self.mgr_client.force_login(self.manager)

    def _extract_notice_path(self, email_message) -> str:
        for line in email_message.body.splitlines():
            if "/teacher/notice/" in line:
                idx = line.index("/teacher/notice/")
                return line[idx:].strip()
        self.fail(f"Notice link not found in email: {email_message.body}")

    def _offer_post_payload(self, *, fee=25, note="پیشنهاد رسمی نسخه اول", send=False, **extra):
        data = {
            "offer_platform_fee_percent": str(fee),
            "offer_prep_mode": PublicationRequest.OfferPrepMode.READY_FILES,
            "offer_distribution_scope": PublicationRequest.DistributionScope.STANDARD,
            "offer_campaign_discount_cap": "30",
            "offer_rate_validity_note": PublicationRequest.DEFAULT_RATE_VALIDITY_NOTE,
            "offer_technical_deliverable": PublicationRequest.DEFAULT_TECH_DELIVERABLE,
            "offer_note": note,
            "status": self.pub_req.status,
            "content_feedback": self.pub_req.content_feedback,
            "review_note": self.pub_req.review_note,
            **extra,
        }
        if send:
            data["_send_offer"] = "ارسال پیشنهاد به استاد"
        return data

    def test_draft_offer_and_internal_note_never_send_email_while_official_offer_and_reminder_do(self):
        url = reverse("admin:website_publicationrequest_change", args=[self.pub_req.pk])

        # 1. Saving draft offer + internal review_note must send NO email
        with self.captureOnCommitCallbacks(execute=True):
            res_draft = self.mgr_client.post(
                url,
                self._offer_post_payload(fee=22, note="پیش‌نویس محرمانه", review_note="یادداشت داخلی مدیر"),
            )
        self.assertEqual(res_draft.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(TeacherNotification.objects.exists())

        # 2. Sending official offer sends 1 minimal email without leaking fee/notes
        with self.captureOnCommitCallbacks(execute=True):
            res_send = self.mgr_client.post(
                url,
                self._offer_post_payload(fee=25, note="شرایط ویژه ۲۵ درصد", send=True),
            )
        self.assertEqual(res_send.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        sent_mail = mail.outbox[0]
        self.assertEqual(sent_mail.to, ["sohrab@example.com"])
        self.assertIn("فیزیک کوانتوم", sent_mail.subject)
        self.assertIn("پیشنهاد انتشار کتاب «فیزیک کوانتوم» در میز تألیف شما آمادهٔ بررسی است.", sent_mail.body)
        self.assertIn("مشاهده در میز تألیف", sent_mail.body)
        self.assertNotIn("25", sent_mail.body)
        self.assertNotIn("۲۵", sent_mail.body)
        self.assertNotIn("شرایط ویژه", sent_mail.body)
        self.assertNotIn("یادداشت داخلی", sent_mail.body)

        # 3. Re-saving unchanged form must NOT create a duplicate notification
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(url, self._offer_post_payload(fee=25, note="شرایط ویژه ۲۵ درصد", send=False))
        self.assertEqual(TeacherNotification.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

        # 4. Manager intentionally clicks "ارسال پیشنهاد به استاد" again with unchanged terms -> separate reminder row
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(url, self._offer_post_payload(fee=25, note="شرایط ویژه ۲۵ درصد", send=True))
        self.assertEqual(TeacherNotification.objects.count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        reminder = TeacherNotification.objects.order_by("-pk").first()
        self.assertTrue(reminder.is_reminder)
        self.assertEqual(reminder.event_type, TeacherNotification.EventType.PUB_OFFER_REMINDER)

    def test_fresh_browser_otp_login_via_email_link_lands_on_latest_offer_and_requires_explicit_accept(self):
        url = reverse("admin:website_publicationrequest_change", args=[self.pub_req.pk])
        # Send offer v1
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(url, self._offer_post_payload(fee=30, note="شرایط نسخه اول", send=True))
        v1_link = self._extract_notice_path(mail.outbox[0])

        # Manager immediately sends newer offer v2 before teacher clicks v1 link
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(url, self._offer_post_payload(fee=20, note="شرایط بهتر نسخه دوم", send=True))

        # Teacher opens v1 link in a completely fresh browser (no cookies)
        fresh = Client()
        r1 = fresh.get(v1_link)
        self.assertEqual(r1.status_code, 302)
        self.assertTrue(r1["Location"].startswith(reverse("teacher-login") + "?next="))

        # Teacher completes OTP sign-in
        login_url = r1["Location"]
        fresh.get(login_url)
        with mock.patch("apps.accounts.admin_login.send_login_code"):
            fresh.post(
                reverse("teacher-login"),
                {"action": "send_otp", "phone": self.teacher.phone, "next": v1_link},
            )
        otp = OTPCode.objects.filter(phone=self.teacher.phone).latest("created_at")
        # Extract code by issuing known OTP or matching via OTPCode.issue
        otp.delete()
        _, known_code = OTPCode.issue(self.teacher.phone)
        r_login = fresh.post(
            reverse("teacher-login"),
            {"action": "verify_otp", "phone": self.teacher.phone, "code": known_code, "next": v1_link},
            follow=True,
        )
        self.assertEqual(r_login.status_code, 200)
        # Lands on offer page showing latest version #2 (20%) — and has NOT auto-accepted!
        self.assertContains(r_login, "نسخهٔ #2")
        self.assertContains(r_login, "20٪")
        self.pub_req.refresh_from_db()
        self.assertEqual(self.pub_req.accepted_offer_version or 0, 0)

        # Already logged-in teacher clicking the email link goes straight to the offer box
        r_direct = fresh.get(v1_link, follow=True)
        self.assertEqual(r_direct.status_code, 200)
        self.assertContains(r_direct, "پذیرش نسخهٔ #2 پیشنهاد")

        # Teacher explicitly accepts version #2
        accept_res = fresh.post(
            reverse("admin:catalog_book_respond_offer", args=[self.book.pk]),
            {
                "request_id": self.pub_req.pk,
                "expected_offer_version": 2,
                "expected_offer_digest": self.pub_req.sent_offer_digest,
                "decision": PublicationRequest.TeacherResponse.ACCEPTED,
                "response_note": "تأیید شد",
                "return_to": "request_page",
            },
            follow=True,
        )
        self.assertEqual(accept_res.status_code, 200)
        self.pub_req.refresh_from_db()
        self.assertEqual(self.pub_req.accepted_offer_version, 2)

    def test_notice_link_denies_other_teacher_and_revoked_access_without_leaking_details(self):
        url = reverse("admin:website_publicationrequest_change", args=[self.pub_req.pk])
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(url, self._offer_post_payload(fee=25, note="شرایط محرمانه", send=True))
        link = self._extract_notice_path(mail.outbox[0])

        # Other teacher cannot open it
        other_client = Client()
        other_client.force_login(self.other_teacher)
        other_res = other_client.get(link)
        self.assertEqual(other_res.status_code, 403)
        self.assertNotContains(other_res, "فیزیک کوانتوم", status_code=403)
        self.assertNotContains(other_res, "شرایط محرمانه", status_code=403)

        # Revoke teacher's BookEditor permission -> original recipient is now denied (403)
        BookEditor.objects.filter(book=self.book, user=self.teacher).delete()
        t_client = Client()
        t_client.force_login(self.teacher)
        revoked_res = t_client.get(link)
        self.assertEqual(revoked_res.status_code, 403)
        self.assertNotContains(revoked_res, "فیزیک کوانتوم", status_code=403)

    def test_needs_info_approved_and_rejected_publication_events_and_email_failure_does_not_block(self):
        from apps.website.publication import publication_content_digest, review_publication_request

        self.pub_req.content_digest = publication_content_digest(self.book)
        self.pub_req.save(update_fields=["content_digest"])

        # 1. NEEDS_INFO email (without leaking content_feedback text in email)
        with self.captureOnCommitCallbacks(execute=True):
            review_publication_request(
                self.pub_req.pk,
                actor=self.manager,
                status=PublicationRequest.Status.NEEDS_INFO,
                content_feedback="فرمول صفحه ۳ اشتباه است.",
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("فرمول صفحه ۳", mail.outbox[0].body)
        self.assertIn("فیزیک کوانتوم", mail.outbox[0].subject)

        # 2. Send & accept offer, then APPROVE even when SMTP raises an error -> book STILL publishes, notification stays FAILED for retry
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(
                reverse("admin:website_publicationrequest_change", args=[self.pub_req.pk]),
                self._offer_post_payload(fee=25, note="نهایی", send=True),
            )
        self.pub_req.refresh_from_db()
        t_client = Client()
        t_client.force_login(self.teacher)
        t_client.post(
            reverse("admin:catalog_book_respond_offer", args=[self.book.pk]),
            {
                "request_id": self.pub_req.pk,
                "expected_offer_version": self.pub_req.sent_offer_version,
                "expected_offer_digest": self.pub_req.sent_offer_digest,
                "decision": PublicationRequest.TeacherResponse.ACCEPTED,
            },
        )

        mail.outbox.clear()
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP down")):
            with self.captureOnCommitCallbacks(execute=True):
                review_publication_request(
                    self.pub_req.pk,
                    actor=self.manager,
                    status=PublicationRequest.Status.APPROVED,
                    review_note="انتشار تأیید شد",
                )

        self.book.refresh_from_db()
        self.assertTrue(self.book.is_published)
        approved_notif = TeacherNotification.objects.filter(
            event_type=TeacherNotification.EventType.PUB_APPROVED
        ).get()
        self.assertEqual(approved_notif.status, TeacherNotification.Status.FAILED)
        self.assertIn("SMTP down", approved_notif.last_error)
        self.assertEqual(approved_notif.subject, "درخواست انتشار کتاب «فیزیک کوانتوم» تأیید شد")

        # Retrying sends without creating a duplicate row
        stats = retry_teacher_notifications()
        self.assertEqual(stats["sent"], 1)
        approved_notif.refresh_from_db()
        self.assertEqual(approved_notif.status, TeacherNotification.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            TeacherNotification.objects.filter(event_type=TeacherNotification.EventType.PUB_APPROVED).count(),
            1,
        )

        # 3. Separate request -> REJECTED email without leaking feedback text
        req2 = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            content_digest=publication_content_digest(self.book),
            status=PublicationRequest.Status.PENDING,
        )
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            review_publication_request(
                req2.pk,
                actor=self.manager,
                status=PublicationRequest.Status.REJECTED,
                content_feedback="دلیل محرمانه رد درخواست.",
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("دلیل محرمانه", mail.outbox[0].body)

    def test_group_access_and_payout_notifications_plus_teacher_without_verified_email(self):
        # Remove teacher's verified email -> decisions must stay visible in panel with guidance banner
        self.teacher.email = ""
        self.teacher.email_verified_at = None
        self.teacher.save(update_fields=["email", "email_verified_at"])

        # Group access request approved by manager
        access_req = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            request_note="دانشجویان ترم پاییز",
            status=BookAccessRequest.Status.PENDING,
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(
                reverse("admin:website_bookaccessrequest_change", args=[access_req.pk]),
                {
                    "status": BookAccessRequest.Status.APPROVED,
                    "review_note": "برای ۳۰ روز تأیید شد",
                    "expiry_policy": BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION,
                    "duration_days": "30",
                    "ends_on": "",
                },
            )
        self.assertEqual(len(mail.outbox), 0)
        acc_notif = TeacherNotification.objects.get(source_ref=f"access:{access_req.pk}")
        self.assertEqual(acc_notif.status, TeacherNotification.Status.SKIPPED_NO_EMAIL)

        # Teacher without verified email sees BookAccessRequest in menu, list, detail, and guidance banner
        t_client = Client()
        t_client.force_login(self.teacher)
        idx_res = t_client.get(reverse("admin:index"))
        self.assertContains(idx_res, reverse("admin:website_bookaccessrequest_changelist"))
        acc_list = t_client.get(reverse("admin:website_bookaccessrequest_changelist"))
        self.assertEqual(acc_list.status_code, 200)
        self.assertContains(acc_list, "برای دریافت اعلان‌ها، ایمیل کاری‌تان را تأیید کنید")
        acc_detail = t_client.get(reverse("admin:website_bookaccessrequest_change", args=[access_req.pk]))
        self.assertEqual(acc_detail.status_code, 200)
        self.assertContains(acc_detail, "برای ۳۰ روز تأیید شد")

        # Unverified teacher also sees guidance banner on PayoutRequest list and PublicationRequest box
        payout_list_unverified = t_client.get(reverse("admin:commerce_payoutrequest_changelist"))
        self.assertContains(payout_list_unverified, "برای دریافت اعلان‌ها، ایمیل کاری‌تان را تأیید کنید")
        pub_box_unverified = t_client.get(reverse("admin:catalog_book_request_publication", args=[self.book.pk]))
        self.assertContains(pub_box_unverified, "برای دریافت اعلان‌ها، ایمیل کاری‌تان را تأیید کنید")

        # Now teacher verifies email -> payout decision sends email without leaking tracking code
        self.teacher.email = "sohrab-new@example.com"
        self.teacher.email_verified_at = timezone.now()
        self.teacher.save(update_fields=["email", "email_verified_at"])

        TeacherBankAccount.objects.create(
            teacher=self.teacher,
            account_holder_name="سهراب سپهری",
            iban="IR120170000000123456789012",
            bank_name="ملی",
            is_verified=True,
        )
        wallet = TeacherWallet.objects.create(teacher=self.teacher, available_balance=600000)
        payout = request_teacher_payout(self.teacher, 250000)

        with mock.patch("apps.catalog.backups.notify_bale_after_commit"):
            with self.captureOnCommitCallbacks(execute=True):
                finalize_payout_paid(payout, tracking_code="PAYA-998877", manager_user=self.manager)

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["sohrab-new@example.com"])
        self.assertNotIn("PAYA-998877", mail.outbox[0].body)
        self.assertNotIn("250000", mail.outbox[0].body)
        notice_path = self._extract_notice_path(mail.outbox[0])
        res_payout = t_client.get(notice_path, follow=True)
        self.assertEqual(res_payout.status_code, 200)
        self.assertContains(res_payout, "PAYA-998877")

        # Also test reject payout even when SMTP fails -> payout stays REJECTED and notification stays FAILED for retry
        wallet.refresh_from_db()
        payout2 = request_teacher_payout(self.teacher, 200000)
        mail.outbox.clear()
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP rejected")):
            with self.captureOnCommitCallbacks(execute=True):
                reject_payout_request(payout2, reason="شماره شبا منقضی بود", manager_user=self.manager)
        payout2.refresh_from_db()
        self.assertEqual(payout2.status, PayoutRequest.Status.REJECTED)
        rej_notif = TeacherNotification.objects.get(source_ref=f"payout:{payout2.pk}")
        self.assertEqual(rej_notif.status, TeacherNotification.Status.FAILED)

        # Superuser retries from TeacherNotification detail page
        retry_page = self.mgr_client.get(reverse("admin:accounts_teachernotification_change", args=[rej_notif.pk]))
        self.assertEqual(retry_page.status_code, 200)
        retry_res = self.mgr_client.post(
            reverse("admin:accounts_teachernotification_retry", args=[rej_notif.pk]),
            follow=True,
        )
        self.assertEqual(retry_res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("شماره شبا منقضی بود", mail.outbox[0].body)
        rej_notif.refresh_from_db()
        self.assertEqual(rej_notif.status, TeacherNotification.Status.SENT)

    def test_management_commands_send_test_email_and_retry(self):
        # 1. Non-SMTP backend must warn explicitly and must NOT claim SMTP acceptance
        out = StringIO()
        call_command("send_test_email", "probe@example.com", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["probe@example.com"])
        self.assertIn("آزمایش محلی انجام شد", out.getvalue())
        self.assertNotIn("پذیرش توسط SMTP", out.getvalue())

        # 2. SMTP backend with sent=1 reports SMTP acceptance
        out_smtp = StringIO()
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"):
            with mock.patch("django.core.mail.EmailMultiAlternatives.send", return_value=1):
                call_command("send_test_email", "smtp-ok@example.com", stdout=out_smtp)
        self.assertIn("پذیرش توسط SMTP", out_smtp.getvalue())

        # 3. sent=0 must raise CommandError
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend"):
            with mock.patch("django.core.mail.EmailMultiAlternatives.send", return_value=0):
                with self.assertRaises(CommandError):
                    call_command("send_test_email", "zero@example.com", stdout=StringIO())

        # Retry command handles pending/failed cleanly
        notif = TeacherNotification.objects.create(
            recipient=self.teacher,
            event_type=TeacherNotification.EventType.PAYOUT_PAID,
            dedupe_key="cmd-retry-test-1",
            source_ref="payout:999999",
            object_id=999999,
            subject="تست",
            headline="تست",
            status=TeacherNotification.Status.FAILED,
        )
        out2 = StringIO()
        call_command("retry_teacher_notifications", stdout=out2)
        self.assertIn("Attempted=1", out2.getvalue())
        notif.refresh_from_db()
        self.assertEqual(notif.status, TeacherNotification.Status.FAILED)

    def test_send_returning_zero_records_notification_as_failed(self):
        from apps.accounts.notifications import dispatch_teacher_notification

        access_req = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            request_note="دانشجویان ترم بهار",
            status=BookAccessRequest.Status.PENDING,
        )
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", return_value=0):
            with self.captureOnCommitCallbacks(execute=True):
                self.mgr_client.post(
                    reverse("admin:website_bookaccessrequest_change", args=[access_req.pk]),
                    {
                        "status": BookAccessRequest.Status.NEEDS_INFO,
                        "review_note": "لطفاً شماره‌ها را اصلاح کنید",
                        "expiry_policy": "",
                        "duration_days": "",
                        "ends_on": "",
                    },
                )
        notif = TeacherNotification.objects.get(source_ref=f"access:{access_req.pk}")
        self.assertEqual(notif.status, TeacherNotification.Status.FAILED)
        self.assertIn("sent=0", notif.last_error)
        with mock.patch("django.core.mail.EmailMultiAlternatives.send", return_value=0):
            self.assertFalse(dispatch_teacher_notification(notif.pk))
        notif.refresh_from_db()
        self.assertEqual(notif.status, TeacherNotification.Status.FAILED)
        self.assertEqual(notif.attempt_count, 2)

    def test_book_access_note_edit_in_needs_info_is_silent_until_explicit_message_button(self):
        access_req = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            request_note="گروه اول",
            status=BookAccessRequest.Status.PENDING,
        )
        url = reverse("admin:website_bookaccessrequest_change", args=[access_req.pk])

        # 1. Status transition PENDING -> NEEDS_INFO sends email
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(
                url,
                {
                    "status": BookAccessRequest.Status.NEEDS_INFO,
                    "review_note": "شماره دوم ناقص است",
                    "expiry_policy": "",
                    "duration_days": "",
                    "ends_on": "",
                },
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(TeacherNotification.objects.filter(source_ref=f"access:{access_req.pk}").count(), 1)

        # 2. Normal edit of review_note while already NEEDS_INFO must NOT send email
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.mgr_client.post(
                url,
                {
                    "status": BookAccessRequest.Status.NEEDS_INFO,
                    "review_note": "یادداشت اصلاح‌شده داخلی/ویرایشی بدون ایمیل",
                    "expiry_policy": "",
                    "duration_days": "",
                    "ends_on": "",
                },
            )
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(TeacherNotification.objects.filter(source_ref=f"access:{access_req.pk}").count(), 1)

        # 3. Clicking explicit "_send_access_message" sends an ACCESS_MESSAGE email
        with self.captureOnCommitCallbacks(execute=True):
            res_msg = self.mgr_client.post(
                url,
                {
                    "status": BookAccessRequest.Status.NEEDS_INFO,
                    "review_note": "لطفاً فهرست اصلاح‌شده را تا فردا ثبت کنید",
                    "expiry_policy": "",
                    "duration_days": "",
                    "ends_on": "",
                    "_send_access_message": "ارسال پیام به استاد",
                },
                follow=True,
            )
        self.assertEqual(res_msg.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            TeacherNotification.objects.filter(
                source_ref=f"access:{access_req.pk}",
                event_type=TeacherNotification.EventType.ACCESS_MESSAGE,
            ).count(),
            1,
        )

    def test_teacher_notification_admin_respects_panel_superuser_and_teacher_view_mode(self):
        notif = TeacherNotification.objects.create(
            recipient=self.teacher,
            event_type=TeacherNotification.EventType.PAYOUT_PAID,
            dedupe_key="admin-perm-test-1",
            source_ref="payout:12345",
            object_id=12345,
            subject="اعلان تست",
            headline="اعلان تست",
            status=TeacherNotification.Status.FAILED,
        )
        list_url = reverse("admin:accounts_teachernotification_changelist")
        detail_url = reverse("admin:accounts_teachernotification_change", args=[notif.pk])
        retry_url = reverse("admin:accounts_teachernotification_retry", args=[notif.pk])
        bulk_payload = {
            "action": "retry_selected_notifications",
            "_selected_action": [str(notif.pk)],
        }

        # 1. Superuser in normal mode has full read + retry access
        self.assertEqual(self.mgr_client.get(list_url).status_code, 200)
        self.assertEqual(self.mgr_client.get(detail_url).status_code, 200)
        self.assertEqual(self.mgr_client.post(retry_url).status_code, 302)
        self.assertEqual(self.mgr_client.post(list_url, bulk_payload).status_code, 302)

        # 2. Superuser switched to "نمای استاد" must be denied (403) on every TeacherNotificationAdmin endpoint
        session = self.mgr_client.session
        session["admin_view_mode"] = "teacher"
        session.save()
        self.assertEqual(self.mgr_client.get(list_url).status_code, 403)
        self.assertEqual(self.mgr_client.get(detail_url).status_code, 403)
        self.assertEqual(self.mgr_client.post(retry_url).status_code, 403)
        self.assertEqual(self.mgr_client.post(list_url, bulk_payload).status_code, 403)
        session = self.mgr_client.session
        session["admin_view_mode"] = "admin"
        session.save()

        # 3. Real teacher is denied (403) everywhere
        t_client = Client()
        t_client.force_login(self.teacher)
        self.assertEqual(t_client.get(list_url).status_code, 403)
        self.assertEqual(t_client.get(detail_url).status_code, 403)
        self.assertEqual(t_client.post(retry_url).status_code, 403)
        self.assertEqual(t_client.post(list_url, bulk_payload).status_code, 403)

    def test_stale_sending_recovery_and_late_error_cannot_overwrite_sent(self):
        from apps.accounts.notifications import dispatch_teacher_notification

        TeacherBankAccount.objects.create(
            teacher=self.teacher,
            account_holder_name="سهراب سپهری",
            iban="IR120170000000123456789012",
            bank_name="ملی",
            is_verified=True,
        )
        TeacherWallet.objects.create(teacher=self.teacher, available_balance=500000)
        payout = request_teacher_payout(self.teacher, 200000)

        notif = TeacherNotification.objects.create(
            recipient=self.teacher,
            event_type=TeacherNotification.EventType.PAYOUT_PAID,
            dedupe_key="stale-sending-recovery-1",
            source_ref=f"payout:{payout.pk}",
            object_id=payout.pk,
            subject="اعلان واریز",
            headline="اعلان واریز",
            status=TeacherNotification.Status.PENDING,
        )

        # Simulate attempt #1 claiming the notification, being retried mid-flight,
        # then timing out stale, recovered by CLI retry, and attempt #1 failing late.
        call_num = 0
        mid_flight_checks = {}

        def fake_send(msg_self, fail_silently=False):
            nonlocal call_num
            call_num += 1
            if call_num == 1:
                snapshot = TeacherNotification.objects.get(pk=notif.pk)
                mid_flight_checks["status"] = snapshot.status
                mid_flight_checks["token"] = snapshot.dispatch_token

                # Fresh SENDING blocks duplicate send on concurrent retry
                mid_flight_checks["fresh_retry"] = dispatch_teacher_notification(notif.pk)
                mid_flight_checks["calls_after_fresh_retry"] = call_num

                # Once SENDING becomes stale (e.g. worker crashed/restarted), CLI retry recovers and sends
                TeacherNotification.objects.filter(pk=notif.pk).update(
                    last_attempt_at=timezone.now() - timedelta(minutes=10)
                )
                out = StringIO()
                call_command("retry_teacher_notifications", stdout=out)
                mid_flight_checks["cli_out"] = out.getvalue()
                mid_flight_checks["calls_after_cli"] = call_num

                # Zombie attempt #1 fails late -> MUST NOT overwrite SENT with FAILED
                raise OSError("zombie attempt #1 timed out late")
            return 1

        with mock.patch("django.core.mail.EmailMultiAlternatives.send", fake_send):
            attempt1_ok = dispatch_teacher_notification(notif.pk)

        self.assertFalse(attempt1_ok)
        self.assertEqual(mid_flight_checks["status"], TeacherNotification.Status.SENDING)
        self.assertTrue(mid_flight_checks["token"])
        self.assertFalse(mid_flight_checks["fresh_retry"])
        self.assertEqual(mid_flight_checks["calls_after_fresh_retry"], 1)
        self.assertIn("Sent=1", mid_flight_checks["cli_out"])
        self.assertEqual(mid_flight_checks["calls_after_cli"], 2)

        notif.refresh_from_db()
        self.assertEqual(notif.status, TeacherNotification.Status.SENT)
        self.assertEqual(notif.attempt_count, 2)
        self.assertEqual(notif.last_error, "")
        self.assertEqual(notif.dispatch_token, "")


class AccountMigration0007Tests(TransactionTestCase):
    migrate_from = [("accounts", "0006_panellogincode_staff_only")]
    migrate_to = [("accounts", "0007_teacher_email_verification_and_notifications")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_0007_invalidates_pending_legacy_tokens_but_preserves_verified_teachers(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldUser = old_apps.get_model("accounts", "User")

        pending_user = OldUser.objects.create(
            phone="09128880001",
            email="pending@example.com",
            email_verified_at=None,
            email_verification_token="legacy-raw-pending-token",
            is_staff=True,
        )
        verified_at = timezone.now() - timedelta(days=5)
        verified_user = OldUser.objects.create(
            phone="09128880002",
            email="verified@example.com",
            email_verified_at=verified_at,
            email_verification_token="legacy-stale-token",
            is_staff=True,
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)

        pending_after = User.objects.get(pk=pending_user.pk)
        self.assertEqual(pending_after.email_verification_token, "")
        self.assertIsNone(pending_after.email_verified_at)
        self.assertFalse(pending_after.is_email_verified)
        self.assertEqual(User.consume_email_verification("legacy-raw-pending-token"), (None, "invalid"))

        verified_after = User.objects.get(pk=verified_user.pk)
        self.assertEqual(verified_after.email, "verified@example.com")
        self.assertIsNotNone(verified_after.email_verified_at)
        self.assertTrue(verified_after.is_email_verified)
        self.assertEqual(verified_after.email_verification_token, "")


class PostgresConcurrentEmailVerificationTests(TransactionTestCase):
    def test_concurrent_verify_and_email_change_never_marks_new_address_verified(self):
        if connection.vendor == "sqlite":
            self.skipTest("SQLite lacks row-level SELECT FOR UPDATE concurrency; covered on PostgreSQL CI.")

        teacher = User.objects.create_user(
            "09129990001",
            email="first@example.com",
            is_staff=True,
        )
        token_first = teacher.generate_email_verification_token()

        barrier = threading.Barrier(2)
        results = {}
        errors = []

        def run_verify():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                _, state = User.consume_email_verification(token_first)
                results["verify_state"] = state
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        def run_change():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                User.objects.get(pk=teacher.pk).begin_email_change("second@example.com")
                results["changed"] = True
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=run_verify)
        t2 = threading.Thread(target=run_change)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertTrue(results.get("changed"))
        teacher.refresh_from_db()
        self.assertEqual(teacher.email, "second@example.com")
        self.assertFalse(teacher.is_email_verified)
        self.assertIsNone(teacher.email_verified_at)
        self.assertEqual(User.consume_email_verification(token_first), (None, "invalid"))


class PostgresConcurrentNotificationDispatchTests(TransactionTestCase):
    def test_concurrent_initial_dispatch_and_manager_retry_send_only_once(self):
        if connection.vendor == "sqlite":
            self.skipTest("SQLite lacks concurrent PostgreSQL row locks; covered on PostgreSQL CI.")

        from apps.accounts.notifications import dispatch_teacher_notification

        manager = User.objects.create_superuser("09120000888", password="Manager-Password-123")
        teacher = User.objects.create_user(
            "09127770001",
            email="concurrent-notif@example.com",
            email_verified_at=timezone.now(),
            is_staff=True,
        )
        TeacherBankAccount.objects.create(
            teacher=teacher,
            account_holder_name="استاد آزمون",
            iban="IR120170000000123456789012",
            bank_name="ملی",
            is_verified=True,
        )
        TeacherWallet.objects.create(teacher=teacher, available_balance=500000)
        payout = request_teacher_payout(teacher, 200000)

        notif = TeacherNotification.objects.create(
            recipient=teacher,
            event_type=TeacherNotification.EventType.PAYOUT_PAID,
            dedupe_key=f"pg-concurrent-dispatch:{payout.pk}",
            source_ref=f"payout:{payout.pk}",
            object_id=payout.pk,
            subject="اعلان تسویه حساب",
            headline="درخواست تسویه حساب شما پرداخت شد.",
            status=TeacherNotification.Status.PENDING,
        )

        mgr_client = Client()
        mgr_client.force_login(manager)
        retry_url = reverse("admin:accounts_teachernotification_retry", args=[notif.pk])

        send_calls = []
        send_lock = threading.Lock()
        barrier = threading.Barrier(2)
        errors = []
        results = {}

        def slow_send(msg_self, fail_silently=False):
            import time

            with send_lock:
                send_calls.append(msg_self.to)
            # Hold SMTP I/O open long enough that the concurrent retry hits the DB while SENDING is active.
            time.sleep(0.25)
            return 1

        def run_initial():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                results["initial_ok"] = dispatch_teacher_notification(notif.pk)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        def run_manager_retry():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                resp = mgr_client.post(retry_url)
                results["retry_status"] = resp.status_code
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        with mock.patch("django.core.mail.EmailMultiAlternatives.send", slow_send):
            t1 = threading.Thread(target=run_initial)
            t2 = threading.Thread(target=run_manager_retry)
            t1.start()
            t2.start()
            t1.join(timeout=15)
            t2.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(results.get("retry_status"), 302)
        self.assertEqual(len(send_calls), 1)

        notif.refresh_from_db()
        self.assertEqual(notif.status, TeacherNotification.Status.SENT)
        self.assertEqual(notif.attempt_count, 1)
        self.assertEqual(notif.dispatch_token, "")
        self.assertEqual(notif.last_error, "")
