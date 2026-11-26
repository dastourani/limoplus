from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
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
        out = StringIO()
        call_command("send_test_email", "probe@example.com", stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["probe@example.com"])
        self.assertIn("سرور ایمیل پیام را", out.getvalue())

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
