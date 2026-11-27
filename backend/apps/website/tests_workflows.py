import re
from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, OTPCode, User
from apps.catalog import access
from apps.catalog.access import BOOK_EDITOR_GROUP
from apps.catalog.models import BookEditor, ContentNode
from apps.commerce.models import Entitlement

from .forms import MAX_GROUP_ACCESS_MEMBERS, normalized_phone_list
from .group_access import activate_approved_members
from .models import (
    BookAccessEvent,
    BookAccessMember,
    BookAccessRequest,
    BookAccessRequestEvent,
    PublicationRequest,
    PublicationRequestEvent,
    TeacherApplication,
    TeacherInvitation,
)
from .publication import (
    publication_content_digest,
    respond_to_publication_offer,
    review_publication_request,
    send_publication_offer,
)


class WorkflowFixture(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = User.objects.create_superuser("09120000001", password="Manager-Password-123")
        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="کتاب گردش‌کار",
            slug="workflow-book",
        )

    def make_teacher_application(self, phone="09120000002", *, status=TeacherApplication.Status.APPROVED):
        return TeacherApplication.objects.create(
            name="استاد آزمایشی",
            phone=phone,
            book_or_link="کتاب گردش‌کار",
            explanation="درخواست همکاری آموزشی.",
            sample_work="نمونه‌کار آموزشی.",
            status=status,
        )

    def make_invitation(self, application=None, *, token=None, **capabilities):
        application = application or self.make_teacher_application()
        token = token or TeacherInvitation.new_token()
        invitation = TeacherInvitation.objects.create(
            application=application,
            book=self.book,
            token_hash=TeacherInvitation.digest_token(token),
            created_by=self.manager,
            **capabilities,
        )
        return invitation, token

    @staticmethod
    def issue_otp(phone):
        return OTPCode.issue(phone)

    def verify(self, phone, code, **extra):
        return APIClient().post(
            "/api/v1/auth/verify-otp/",
            {"phone": phone, "code": code, **extra},
            format="json",
        )


class TeacherInvitationWorkflowTests(WorkflowFixture):
    def test_public_invitation_page_is_no_store_and_application_queue_links_to_invite_form(self):
        application = self.make_teacher_application()
        manager_client = Client()
        manager_client.force_login(self.manager)
        queue = manager_client.get(reverse("admin:website_teacherapplication_changelist"))
        invite_link = f"{reverse('admin:website_teacherinvitation_add')}?application={application.pk}"
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, invite_link)

        staff_client = Client()
        staff_client.force_login(User.objects.create_user("09120000005", is_staff=True))
        self.assertEqual(staff_client.get(reverse("admin:website_teacherinvitation_add")).status_code, 403)

        landing = Client().get(reverse("website:teacher-invitation"))
        self.assertEqual(landing.status_code, 200)
        self.assertIn("no-store", landing["Cache-Control"])
        self.assertIn("max-age=0", landing["Cache-Control"])
        self.assertEqual(landing["Referrer-Policy"], "no-referrer")
        self.assertEqual(landing["X-Robots-Tag"], "noindex, nofollow")

    def test_superuser_issues_a_hashed_link_once_and_can_revoke_it_with_a_reason(self):
        application = self.make_teacher_application()
        request = RequestFactory().post(reverse("admin:website_teacherinvitation_add"), HTTP_HOST="testserver")
        request.user = self.manager
        request.session = {}
        request._messages = FallbackStorage(request)
        invitation = TeacherInvitation(
            application=application,
            book=self.book,
            can_edit_content=True,
        )

        admin.site._registry[TeacherInvitation].save_model(request, invitation, form=None, change=False)

        issued_message = " ".join(str(message) for message in get_messages(request))
        tokens = set(re.findall(r"#([A-Za-z0-9_-]{32,80})", issued_message))
        self.assertEqual(len(tokens), 1)
        token = tokens.pop()
        self.assertEqual(invitation.token_hash, TeacherInvitation.digest_token(token))
        self.assertNotIn(token, invitation.token_hash)
        self.assertLessEqual(invitation.expires_at - invitation.created_at, timedelta(hours=72, minutes=1))
        self.assertGreaterEqual(invitation.expires_at - invitation.created_at, timedelta(hours=71, minutes=59))

        manager_client = Client()
        manager_client.force_login(self.manager)
        change_url = reverse("admin:website_teacherinvitation_change", args=[invitation.pk])
        response = manager_client.post(change_url, {
            "status": TeacherInvitation.Status.REVOKED,
            "revocation_reason": "شماره‌ی دعوت اشتباه ثبت شده بود.",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.REVOKED)
        self.assertEqual(invitation.revoked_by, self.manager)
        self.assertIsNotNone(invitation.revoked_at)
        self.assertEqual(invitation.revocation_reason, "شماره‌ی دعوت اشتباه ثبت شده بود.")

    def test_admin_navigation_separates_teacher_workflows_from_site_content(self):
        manager_client = Client()
        manager_client.force_login(self.manager)
        response = manager_client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        app_list = response.context["app_list"]
        site_app = next(app for app in app_list if app["name"] == "سایت")
        workflow_app = next(app for app in app_list if app["name"] == "اساتید و مؤلفان")
        site_models = {model["object_name"] for model in site_app["models"]}
        workflow_models = {model["object_name"] for model in workflow_app["models"]}

        self.assertTrue({"SiteSettings", "SitePage", "HelpPage", "SiteNavItem", "FaqItem"} <= site_models)
        self.assertFalse({"TeacherApplication", "TeacherInvitation", "BookAccessRequest"} & site_models)
        self.assertTrue({
            "BookEditor", "TeacherApplication", "TeacherInvitation", "PublicationRequest",
            "PublicationRequestEvent", "BookAccessRequest", "BookAccessRequestEvent",
            "BookAccessMember", "BookAccessEvent",
        } <= workflow_models)

    def test_invitation_list_and_details_show_effective_status_capabilities_and_audit(self):
        issued_application = self.make_teacher_application(phone="09120000011")
        issued, _ = self.make_invitation(issued_application, can_edit_content=True)

        accepted_application = self.make_teacher_application(phone="09120000012")
        accepted, _ = self.make_invitation(accepted_application, can_request_publication=True)
        accepted_user = User.objects.create_user("09120000013")
        accepted.accepted_by = accepted_user
        accepted.accepted_at = timezone.now() - timedelta(days=2)
        accepted.status = TeacherInvitation.Status.ACCEPTED
        accepted.save(update_fields=("accepted_by", "accepted_at", "status"))

        revoked_application = self.make_teacher_application(phone="09120000014")
        revoked, _ = self.make_invitation(revoked_application, can_request_group_access=True)
        revoked.revoked_by = self.manager
        revoked.revoked_at = timezone.now() - timedelta(hours=3)
        revoked.revocation_reason = "درخواست مدیر برای لغو پیوند آزمایشی."
        revoked.status = TeacherInvitation.Status.REVOKED
        revoked.save(update_fields=("revoked_by", "revoked_at", "revocation_reason", "status"))

        expired_application = self.make_teacher_application(phone="09120000015")
        expired, _ = self.make_invitation(expired_application, can_view_reports=True)
        TeacherInvitation.objects.filter(pk=expired.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        expired.refresh_from_db()
        self.assertEqual(expired.status, TeacherInvitation.Status.ISSUED)

        manager_client = Client()
        manager_client.force_login(self.manager)
        list_url = reverse("admin:website_teacherinvitation_changelist")
        response = manager_client.get(list_url)
        self.assertEqual(response.status_code, 200)
        for label in ("صادرشده", "پذیرفته‌شده", "لغوشده", "منقضی‌شده"):
            self.assertContains(response, label)
        for label in (
            "انقضای پیوند", "قابلیت‌های این دعوت", "دعوت‌کننده · زمان صدور",
            "پذیرنده · زمان پذیرش", "لغوکننده · زمان لغو", "دلیل لغو",
            "ویرایش پیش‌نویس", "درخواست بازبینی انتشار عمومی", "درخواست دسترسی گروهی",
            self.manager.phone, accepted_user.phone, revoked.revocation_reason,
        ):
            self.assertContains(response, label)

        expired_response = manager_client.get(f"{list_url}?effective_status=expired")
        self.assertEqual(expired_response.status_code, 200)
        self.assertEqual(list(expired_response.context["cl"].result_list), [expired])

        accepted_detail = manager_client.get(
            reverse("admin:website_teacherinvitation_change", args=[accepted.pk])
        )
        self.assertEqual(accepted_detail.status_code, 200)
        for label in ("پذیرفته‌شده", "پذیرنده", "زمان پذیرش", accepted_user.phone, "درخواست بازبینی انتشار عمومی"):
            self.assertContains(accepted_detail, label)

        revoked_detail = manager_client.get(
            reverse("admin:website_teacherinvitation_change", args=[revoked.pk])
        )
        self.assertEqual(revoked_detail.status_code, 200)
        for label in (
            "لغوشده", "دعوت‌کننده", "زمان صدور", "لغوکننده", "زمان لغو", "دلیل لغو",
            self.manager.phone, revoked.revocation_reason, "درخواست دسترسی گروهی",
        ):
            self.assertContains(revoked_detail, label)

        expired_detail = manager_client.get(
            reverse("admin:website_teacherinvitation_change", args=[expired.pk])
        )
        self.assertEqual(expired_detail.status_code, 200)
        self.assertContains(expired_detail, "منقضی‌شده")
        self.assertNotContains(expired_detail, "صادرشده")

    def test_invitation_otp_grants_only_the_selected_book_capability_and_creates_admin_session(self):
        invitation, token = self.make_invitation(
            can_request_publication=True,
            can_edit_content=False,
            can_request_group_access=False,
            can_view_reports=False,
            can_view_aggregate_study=False,
            can_view_aggregate_sales=False,
        )
        otp, code = self.issue_otp(invitation.application.phone)

        teacher_client = APIClient()
        response = teacher_client.post(
            "/api/v1/auth/verify-otp/",
            {
                "phone": invitation.application.phone,
                "code": code,
                "teacher_invitation": token,
                "device_name": "Invitation browser",
                "platform": "web",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["accepted"])
        self.assertNotIn("token", response.data)
        user = User.objects.get(phone=invitation.application.phone)
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.groups.filter(name=BOOK_EDITOR_GROUP).exists())
        self.assertTrue(access.is_book_teacher(user))
        editor = BookEditor.objects.get(book=self.book, user=user)
        self.assertFalse(editor.can_edit_content)
        self.assertTrue(editor.can_request_publication)
        self.assertFalse(editor.can_request_group_access)
        self.assertFalse(access.can_edit_book(user, self.book))
        self.assertEqual(DeviceSession.objects.filter(user=user).count(), 0)
        self.assertIsNotNone(otp.__class__.objects.get(pk=otp.pk).consumed_at)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_by, user)
        self.assertIsNotNone(invitation.accepted_at)
        self.assertEqual(response.wsgi_request.session.get("_auth_user_id"), str(user.pk))
        self.assertIn("teacher_invitation", response.wsgi_request.sensitive_post_parameters)
        replay_otp, replay_code = self.issue_otp(invitation.application.phone)
        replay = self.verify(invitation.application.phone, replay_code, teacher_invitation=token)
        self.assertEqual(replay.data["code"], "invitation_unavailable")
        replay_otp.refresh_from_db()
        self.assertIsNone(replay_otp.consumed_at)
        tracker_response = teacher_client.get(reverse("admin:guard_tracker_changelist"))
        self.assertEqual(tracker_response.status_code, 403, tracker_response.content.decode()[:500])
        copy_response = teacher_client.get(reverse("admin:guard_copyevent_changelist"))
        self.assertEqual(copy_response.status_code, 403, copy_response.content.decode()[:500])
        with mock.patch("apps.catalog.maintenance.run_if_due") as cleanup:
            self.assertEqual(teacher_client.get(reverse("admin:index")).status_code, 200)
            cleanup.assert_not_called()

    def test_logged_out_invitation_landing_and_email_verification_redirect_to_teacher_login(self):
        # 1. Logged-out teacher opens the invitation landing page with no prior session:
        #    no ADMIN_URL is exposed, and fallback/login links point to /teacher/login/.
        anon = Client()
        landing = anon.get(reverse("website:teacher-invitation"))
        self.assertEqual(landing.status_code, 200)
        self.assertContains(landing, reverse("teacher-login"))
        self.assertNotContains(landing, reverse("admin:index"))

        # Complete invitation acceptance with no prior session.
        invitation, token = self.make_invitation(can_edit_content=True)
        _, code = self.issue_otp(invitation.application.phone)
        api_anon = APIClient()
        verify_res = api_anon.post(
            "/api/v1/auth/verify-otp/",
            {
                "phone": invitation.application.phone,
                "code": code,
                "teacher_invitation": token,
                "device_name": "Fresh browser",
                "platform": "web",
            },
            format="json",
        )
        self.assertEqual(verify_res.status_code, 200, verify_res.data)
        self.assertTrue(verify_res.data["accepted"])
        self.assertEqual(verify_res.data["redirect"], reverse("teacher-login"))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.ACCEPTED)

        # 2. Logged-out teacher opens email verification magic link with no prior session:
        #    email is verified and redirect goes to /teacher/login/, NOT ADMIN_URL.
        user = User.objects.get(phone=invitation.application.phone)
        user.email = "teacher@example.com"
        user.email_verified_at = None
        user.save(update_fields=["email", "email_verified_at"])
        raw_logged_out = user.generate_email_verification_token()

        logged_out_browser = Client()
        verify_email_url = reverse("website:verify-teacher-email", args=[raw_logged_out])
        email_res = logged_out_browser.get(verify_email_url)
        self.assertEqual(email_res.status_code, 302)
        self.assertEqual(email_res["Location"], reverse("teacher-login"))

        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)
        self.assertEqual(user.email_verification_token, "")

        login_page = logged_out_browser.get(email_res["Location"])
        self.assertEqual(login_page.status_code, 200)
        self.assertContains(login_page, "teacher@example.com")

        # 3. When an authenticated teacher opens a fresh email-verification link, they return to the panel.
        user.email_verified_at = None
        user.save(update_fields=["email_verified_at"])
        raw_logged_in = user.generate_email_verification_token()
        logged_in_browser = Client()
        logged_in_browser.force_login(user)
        signed_in_res = logged_in_browser.get(reverse("website:verify-teacher-email", args=[raw_logged_in]))
        self.assertEqual(signed_in_res.status_code, 302)
        self.assertEqual(signed_in_res["Location"], reverse("admin:index"))
        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

    def test_invitation_phone_mismatch_does_not_create_user_or_consume_otp(self):
        invitation, token = self.make_invitation(can_edit_content=True)
        otp, code = self.issue_otp(invitation.application.phone)

        response = self.verify("09129999999", code, teacher_invitation=token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invitation_phone_mismatch")
        self.assertFalse(User.objects.filter(phone="09129999999").exists())
        otp.refresh_from_db()
        self.assertIsNone(otp.consumed_at)
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.ISSUED)

    def test_expired_invitation_is_marked_unavailable(self):
        invitation, token = self.make_invitation(can_edit_content=True)
        TeacherInvitation.objects.filter(pk=invitation.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        otp, code = self.issue_otp(invitation.application.phone)

        response = self.verify(invitation.application.phone, code, teacher_invitation=token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invitation_unavailable")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.EXPIRED)
        self.assertIsNone(otp.__class__.objects.get(pk=otp.pk).consumed_at)
        self.assertFalse(User.objects.filter(phone=invitation.application.phone).exists())

    def test_unapproved_application_revokes_the_issued_invitation(self):
        application = self.make_teacher_application()
        invitation, token = self.make_invitation(application, can_edit_content=True)
        application.status = TeacherApplication.Status.NEEDS_INFO
        application.save(update_fields=["status"])
        _, code = self.issue_otp(application.phone)

        response = self.verify(application.phone, code, teacher_invitation=token)

        self.assertEqual(response.data["code"], "invitation_unavailable")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.REVOKED)
        self.assertTrue(invitation.revocation_reason)
        self.assertFalse(User.objects.filter(phone=application.phone).exists())

    def test_existing_broad_user_permissions_cannot_become_teacher_admin_access(self):
        application = self.make_teacher_application()
        invitation, token = self.make_invitation(application, can_edit_content=True)
        user = User.objects.create_user(application.phone)
        broad_permission = Permission.objects.get(content_type__app_label="auth", codename="add_group")
        user.user_permissions.add(broad_permission)
        _, code = self.issue_otp(application.phone)

        response = self.verify(application.phone, code, teacher_invitation=token)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invitation_unavailable")
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.groups.filter(name=BOOK_EDITOR_GROUP).exists())
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, TeacherInvitation.Status.ISSUED)


class GroupAccessWorkflowTests(WorkflowFixture):
    def setUp(self):
        super().setUp()
        self.teacher = User.objects.create_user("09120000003", is_staff=True)
        self.teacher.groups.add(Group.objects.get(name=BOOK_EDITOR_GROUP))
        BookEditor.objects.create(
            book=self.book,
            user=self.teacher,
            can_edit_content=False,
            can_request_group_access=True,
        )

    def test_phone_list_is_capped_at_500_unique_numbers(self):
        raw = "\n".join(f"09{number:09d}" for number in range(MAX_GROUP_ACCESS_MEMBERS + 1))
        with self.assertRaisesRegex(ValidationError, "حداکثر 500 شماره"):
            normalized_phone_list(raw)

    def test_teacher_submission_normalizes_deduplicates_and_grants_nothing_until_approval(self):
        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        add_url = reverse("admin:website_bookaccessrequest_add")
        response = teacher_client.post(add_url, {
            "book": self.book.pk,
            "request_note": "دسترسی برای کلاس پاییز.",
            "member_phones": "۰۹۱۲۱۲۳۴۵۶۷\n+98 912 123 4567\n09120000123",
            "_save": "ذخیره",
        })

        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        request = BookAccessRequest.objects.get()
        self.assertEqual(request.status, BookAccessRequest.Status.PENDING)
        self.assertEqual(request.requested_by, self.teacher)
        self.assertEqual(list(request.members.values_list("phone", flat=True)), ["09120000123", "09121234567"])
        self.assertEqual(User.objects.filter(phone__in=["09121234567", "09120000123"]).count(), 0)
        self.assertFalse(Entitlement.objects.filter(book=self.book).exists())
        event = request.events.get()
        self.assertEqual(event.action, BookAccessRequestEvent.Action.SUBMITTED)
        self.assertEqual(event.actor, self.teacher)

    def test_only_manager_can_approve_and_approval_waits_for_each_phone_otp(self):
        request = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            request_note="دسترسی کلاس.",
        )
        member = BookAccessMember.objects.create(
            request=request,
            book=self.book,
            phone="09121234567",
        )
        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        change_url = reverse("admin:website_bookaccessrequest_change", args=[request.pk])
        self.assertEqual(teacher_client.get(change_url).status_code, 200)
        denied_update = teacher_client.post(change_url, {
            "status": BookAccessRequest.Status.APPROVED,
            "review_note": "تلاش برای تأیید.",
            "expiry_policy": BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION,
            "ends_on": "",
            "duration_days": "30",
            "_save": "ذخیره",
        })
        self.assertEqual(denied_update.status_code, 403)

        manager_client = Client()
        manager_client.force_login(self.manager)
        response = manager_client.post(change_url, {
            "status": BookAccessRequest.Status.APPROVED,
            "review_note": "فهرست و کتاب بررسی و تأیید شد.",
            "expiry_policy": BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION,
            "ends_on": "",
            "duration_days": "30",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))

        request.refresh_from_db()
        member.refresh_from_db()
        self.assertEqual(request.status, BookAccessRequest.Status.APPROVED)
        self.assertEqual(request.reviewed_by, self.manager)
        self.assertIsNotNone(request.reviewed_at)
        self.assertEqual(member.status, BookAccessMember.Status.WAITING_OTP)
        self.assertFalse(User.objects.filter(phone=member.phone).exists())
        self.assertFalse(Entitlement.objects.filter(book=self.book).exists())
        decision = request.events.order_by("-pk").first()
        self.assertEqual(decision.action, BookAccessRequestEvent.Action.APPROVED)
        self.assertEqual(decision.actor, self.manager)
        self.assertEqual(decision.reason, "فهرست و کتاب بررسی و تأیید شد.")

        _, code = self.issue_otp(member.phone)
        response = self.verify(member.phone, code)
        self.assertEqual(response.status_code, 200, response.data)
        user = User.objects.get(phone=member.phone)
        member.refresh_from_db()
        self.assertEqual(member.status, BookAccessMember.Status.ACTIVE)
        self.assertEqual(member.user, user)
        self.assertTrue(Entitlement.objects.filter(user=user, book=self.book, granted_by=self.manager).exists())
        self.assertFalse(ContentNode.objects.get(pk=self.book.pk).is_published)
        self.assertEqual(access.access_kind(user, self.book), "gift")
        self.assertTrue(access.AccessMap(user, self.book).visible(self.book.pk))
        api_client = APIClient()
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['token']}")
        shelves = api_client.get("/api/v1/shelves/")
        self.assertEqual(shelves.status_code, 200, shelves.data)
        private_row = next(row for row in shelves.data if row["id"] == -1)
        self.assertEqual(private_row["title"], "کتاب‌های دسترسی گروهی")
        self.assertEqual(private_row["books"][0]["slug"], self.book.slug)
        private_detail = api_client.get(f"/api/v1/books/{self.book.slug}/")
        self.assertEqual(private_detail.status_code, 200, private_detail.data)
        self.assertTrue(private_detail.data["owned"])
        self.assertEqual(APIClient().get(f"/api/v1/books/{self.book.slug}/").status_code, 404)
        entitlement = member.entitlement
        self.assertGreater(entitlement.ends_at, timezone.now() + timedelta(days=29))
        self.assertLess(entitlement.ends_at, timezone.now() + timedelta(days=31))
        activation = member.events.get(action=BookAccessEvent.Action.ACTIVATED)
        self.assertIsNone(activation.actor)
        self.assertTrue(activation.reason)

    def test_fixed_end_date_is_inclusive_and_activation_does_not_start_early(self):
        end_date = timezone.localdate() + timedelta(days=12)
        request = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            status=BookAccessRequest.Status.APPROVED,
            review_note="تأیید مدیر کل.",
            expiry_policy=BookAccessRequest.ExpiryPolicy.FIXED_DATE,
            ends_on=end_date,
            reviewed_by=self.manager,
            reviewed_at=timezone.now(),
        )
        member = BookAccessMember.objects.create(
            request=request,
            book=self.book,
            phone="09121234567",
            status=BookAccessMember.Status.WAITING_OTP,
        )
        user = User.objects.create_user(member.phone)
        now = timezone.now()

        self.assertEqual(activate_approved_members(user, now=now), 1)
        member.refresh_from_db()
        expected = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min))
        self.assertEqual(member.entitlement.ends_at, expected)
        self.assertEqual(member.activated_at, now)

    def test_member_can_be_renewed_and_revoked_with_audited_reasons(self):
        request = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            status=BookAccessRequest.Status.APPROVED,
            review_note="تأیید.",
            expiry_policy=BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION,
            duration_days=10,
            reviewed_by=self.manager,
            reviewed_at=timezone.now(),
        )
        member = BookAccessMember.objects.create(
            request=request,
            book=self.book,
            phone="09121234567",
            status=BookAccessMember.Status.WAITING_OTP,
        )
        student = User.objects.create_user(member.phone)
        activate_approved_members(student)
        member.refresh_from_db()
        manager_client = Client()
        manager_client.force_login(self.manager)

        renew_url = reverse("admin:website_bookaccessmember_renew", args=[member.pk])
        renewed = manager_client.post(renew_url, {"additional_days": "7", "reason": "تمدید برای جبرانی."})
        self.assertEqual(renewed.status_code, 302)
        member.refresh_from_db()
        renewal_event = member.events.get(action=BookAccessEvent.Action.RENEWED)
        self.assertEqual(renewal_event.actor, self.manager)
        self.assertEqual(renewal_event.reason, "تمدید برای جبرانی.")
        self.assertEqual(member.entitlement.ends_at, renewal_event.new_ends_at)
        self.assertGreater(renewal_event.new_ends_at, renewal_event.previous_ends_at)

        revoke_url = reverse("admin:website_bookaccessmember_revoke", args=[member.pk])
        revoked = manager_client.post(revoke_url, {"reason": "پایان همکاری با کلاس."})
        self.assertEqual(revoked.status_code, 302)
        member.refresh_from_db()
        member.entitlement.refresh_from_db()
        self.assertEqual(member.status, BookAccessMember.Status.REVOKED)
        self.assertTrue(member.entitlement.is_archived)
        revoke_event = member.events.get(action=BookAccessEvent.Action.REVOKED)
        self.assertEqual(revoke_event.actor, self.manager)
        self.assertEqual(revoke_event.reason, "پایان همکاری با کلاس.")

    def test_private_group_grant_still_opens_an_unpublished_book_when_user_also_has_purchase_access(self):
        request = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            status=BookAccessRequest.Status.APPROVED,
            review_note="تأیید دسترسی خصوصی.",
            expiry_policy=BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION,
            duration_days=30,
            reviewed_by=self.manager,
            reviewed_at=timezone.now(),
        )
        member = BookAccessMember.objects.create(
            request=request,
            book=self.book,
            phone="09121234567",
            status=BookAccessMember.Status.WAITING_OTP,
        )
        user = User.objects.create_user(member.phone)
        Entitlement.objects.create(user=user, book=self.book, note="دسترسی قبلی")
        activate_approved_members(user)

        self.assertEqual(access.access_kind(user, self.book), "purchase")
        self.assertTrue(access.AccessMap(user, self.book).visible(self.book.pk))
        _, token = DeviceSession.start(user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        shelves = client.get("/api/v1/shelves/")
        private_row = next(row for row in shelves.data if row["id"] == -1)
        self.assertEqual(private_row["books"][0]["slug"], self.book.slug)
        self.assertEqual(client.get(f"/api/v1/books/{self.book.slug}/").status_code, 200)

    def test_expired_fixed_date_member_never_receives_an_entitlement(self):
        request = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            status=BookAccessRequest.Status.APPROVED,
            review_note="تصمیم مدیر برای آزمون انقضا.",
            expiry_policy=BookAccessRequest.ExpiryPolicy.FIXED_DATE,
            ends_on=timezone.localdate() - timedelta(days=2),
            reviewed_by=self.manager,
            reviewed_at=timezone.now(),
        )
        member = BookAccessMember.objects.create(
            request=request,
            book=self.book,
            phone="09121234567",
            status=BookAccessMember.Status.WAITING_OTP,
        )
        user = User.objects.create_user(member.phone)

        self.assertEqual(activate_approved_members(user), 0)
        member.refresh_from_db()
        self.assertEqual(member.status, BookAccessMember.Status.EXPIRED)
        self.assertFalse(Entitlement.objects.filter(user=user, book=self.book).exists())


class PublicationWorkflowTests(WorkflowFixture):
    def setUp(self):
        super().setUp()
        self.teacher = User.objects.create_user("09120000004", is_staff=True)
        self.teacher.groups.add(Group.objects.get(name=BOOK_EDITOR_GROUP))
        BookEditor.objects.create(
            book=self.book,
            user=self.teacher,
            can_edit_content=False,
            can_request_publication=True,
        )
        self.chapter = self.book.add_child(
            kind=ContentNode.Kind.CHAPTER,
            title="فصل نخست",
            slug="chapter-one",
        )

    def test_digest_tracks_content_but_ignores_release_and_volatile_timestamps(self):
        original = publication_content_digest(self.book)
        ContentNode.objects.filter(pk=self.book.pk).update(is_published=True)
        same = publication_content_digest(ContentNode.objects.get(pk=self.book.pk))
        self.assertEqual(original, same)

        ContentNode.objects.filter(pk=self.chapter.pk).update(full_body="متن تازه")
        changed = publication_content_digest(ContentNode.objects.get(pk=self.book.pk))
        self.assertNotEqual(original, changed)

    def test_teacher_submits_exact_snapshot_and_manager_alone_releases_it(self):
        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        add_url = reverse("admin:website_publicationrequest_add")
        response = teacher_client.post(add_url, {
            "book": self.book.pk,
            "request_note": "نسخه‌ی بازبینی‌شده آماده است.",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))

        request = PublicationRequest.objects.get()
        self.assertEqual(request.status, PublicationRequest.Status.PENDING)
        self.assertEqual(request.requested_by, self.teacher)
        self.assertEqual(request.content_digest, publication_content_digest(self.book))
        self.assertFalse(self.book.is_published)
        submitted = request.events.get()
        self.assertEqual(submitted.action, PublicationRequestEvent.Action.SUBMITTED)
        self.assertEqual(submitted.actor, self.teacher)

        duplicate = teacher_client.post(add_url, {
            "book": self.book.pk,
            "request_note": "نسخه‌ی تکراری.",
            "_save": "ذخیره",
        })
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(PublicationRequest.objects.count(), 1)

        change_url = reverse("admin:website_publicationrequest_change", args=[request.pk])
        response = teacher_client.get(change_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(teacher_client.post(change_url, {
            "status": PublicationRequest.Status.APPROVED,
            "review_note": "تلاش استاد برای انتشار.",
            "_save": "ذخیره",
        }).status_code, 403)

        manager_client = Client()
        manager_client.force_login(self.manager)
        # Approval without an accepted offer must fail.
        premature = manager_client.post(change_url, {
            "status": PublicationRequest.Status.APPROVED,
            "review_note": "تلاش بدون ارسال پیشنهاد.",
            "_save": "ذخیره",
        })
        self.assertEqual(premature.status_code, 200)
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_published)

        # Manager explicitly sends v1 offer (25% platform fee).
        sent_res = manager_client.post(change_url, {
            "offer_platform_fee_percent": 25,
            "offer_prep_mode": PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            "offer_distribution_scope": PublicationRequest.DistributionScope.STANDARD,
            "offer_campaign_discount_cap": 30,
            "offer_rate_validity_note": PublicationRequest.DEFAULT_RATE_VALIDITY_NOTE,
            "offer_technical_deliverable": PublicationRequest.DEFAULT_TECH_DELIVERABLE,
            "offer_note": "شرایط نسخه ۱: ۲۵٪ کارمزد آماده‌سازی کامل.",
            "status": PublicationRequest.Status.PENDING,
            "review_note": "",
            "_send_offer": "ارسال پیشنهاد به استاد",
        })
        self.assertEqual(sent_res.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.sent_offer_version, 1)
        self.assertFalse(request.is_current_offer_accepted)

        # Manager cannot accept or respond on behalf of the teacher (Finding 1).
        with self.assertRaises(PermissionError):
            respond_to_publication_offer(
                request.pk,
                actor=self.manager,
                decision=PublicationRequest.TeacherResponse.ACCEPTED,
                expected_offer_digest=request.sent_offer_digest,
                expected_offer_version=request.sent_offer_version,
            )
        manager_respond_res = manager_client.post(
            reverse("admin:catalog_book_respond_offer", args=[self.book.pk]),
            {
                "request_id": request.pk,
                "decision": PublicationRequest.TeacherResponse.ACCEPTED,
                "expected_offer_version": request.sent_offer_version,
                "expected_offer_digest": request.sent_offer_digest,
            },
        )
        self.assertEqual(manager_respond_res.status_code, 403)
        request.refresh_from_db()
        self.assertFalse(request.is_current_offer_accepted)

        # Missing version or digest must be rejected (Finding 2).
        with self.assertRaisesMessage(ValidationError, "تغییر کرده"):
            respond_to_publication_offer(
                request.pk,
                actor=self.teacher,
                decision=PublicationRequest.TeacherResponse.ACCEPTED,
                expected_offer_digest="",
                expected_offer_version=request.sent_offer_version,
            )
        with self.assertRaisesMessage(ValidationError, "تغییر کرده"):
            respond_to_publication_offer(
                request.pk,
                actor=self.teacher,
                decision=PublicationRequest.TeacherResponse.ACCEPTED,
                expected_offer_digest=request.sent_offer_digest,
                expected_offer_version=None,
            )

        # Teacher accepts exact version 1 offer.
        respond_to_publication_offer(
            request.pk,
            actor=self.teacher,
            decision=PublicationRequest.TeacherResponse.ACCEPTED,
            note="موافقم.",
            expected_offer_digest=request.sent_offer_digest,
            expected_offer_version=request.sent_offer_version,
        )

        # Re-sending identical offer terms acts as a reminder of v1 without breaking acceptance (Finding 2).
        send_publication_offer(
            request.pk,
            actor=self.manager,
            platform_fee_percent=25,
            prep_mode=PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            distribution_scope=PublicationRequest.DistributionScope.STANDARD,
            campaign_discount_cap=30,
            rate_validity_note=PublicationRequest.DEFAULT_RATE_VALIDITY_NOTE,
            technical_deliverable=PublicationRequest.DEFAULT_TECH_DELIVERABLE,
            offer_note="شرایط نسخه ۱: ۲۵٪ کارمزد آماده‌سازی کامل.",
        )
        request.refresh_from_db()
        self.assertEqual(request.sent_offer_version, 1)
        self.assertTrue(request.is_current_offer_accepted)

        response = manager_client.post(change_url, {
            "offer_platform_fee_percent": 25,
            "offer_prep_mode": PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            "offer_distribution_scope": PublicationRequest.DistributionScope.STANDARD,
            "offer_campaign_discount_cap": 30,
            "offer_rate_validity_note": PublicationRequest.DEFAULT_RATE_VALIDITY_NOTE,
            "offer_technical_deliverable": PublicationRequest.DEFAULT_TECH_DELIVERABLE,
            "offer_note": "شرایط نسخه ۱: ۲۵٪ کارمزد آماده‌سازی کامل.",
            "status": PublicationRequest.Status.APPROVED,
            "review_note": "نسخه بررسی و برای انتشار تأیید شد.",
            "_save": "ذخیره",
        })
        self.assertEqual(response.status_code, 302, getattr(response, "context", None))
        request.refresh_from_db()
        self.book.refresh_from_db()
        self.chapter.refresh_from_db()
        self.assertEqual(request.status, PublicationRequest.Status.APPROVED)
        self.assertEqual(request.reviewed_by, self.manager)
        self.assertTrue(self.book.is_published)
        self.assertTrue(self.chapter.is_published)
        self.assertFalse(self.book.single_sale_only)
        self.assertEqual(self.book.campaign_discount_cap_percent, 30)
        self.assertEqual(self.book.royalty_rule.custom_platform_share_percent, 25)
        self.assertTrue(self.book.royalty_rule.is_custom_split)
        approved = request.events.order_by("-pk").first()
        self.assertEqual(approved.action, PublicationRequestEvent.Action.APPROVED)
        self.assertEqual(approved.actor, self.manager)
        self.assertEqual(approved.offer_version, 1)
        self.assertEqual(approved.reason, "نسخه بررسی و برای انتشار تأیید شد.")
        self.assertFalse(Entitlement.objects.filter(book=self.book).exists())

    def test_draft_offer_save_is_hidden_from_teacher_and_blocks_approval(self):
        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            content_digest=publication_content_digest(self.book),
        )
        manager_client = Client()
        manager_client.force_login(self.manager)
        change_url = reverse("admin:website_publicationrequest_change", args=[request.pk])
        res = manager_client.post(change_url, {
            "offer_platform_fee_percent": 22,
            "offer_prep_mode": PublicationRequest.OfferPrepMode.READY_FILES,
            "offer_distribution_scope": PublicationRequest.DistributionScope.STANDARD,
            "offer_campaign_discount_cap": 25,
            "offer_rate_validity_note": PublicationRequest.DEFAULT_RATE_VALIDITY_NOTE,
            "offer_technical_deliverable": PublicationRequest.DEFAULT_TECH_DELIVERABLE,
            "offer_note": "پیش‌نویس محرمانه مدیر",
            "status": PublicationRequest.Status.PENDING,
            "review_note": "",
            "_save": "ذخیره",
        })
        self.assertEqual(res.status_code, 302)
        request.refresh_from_db()
        self.assertFalse(request.has_sent_offer)
        self.assertTrue(request.has_unsent_offer_changes)

        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        book_page = teacher_client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertEqual(book_page.status_code, 200)
        self.assertNotContains(book_page, "پیش‌نویس محرمانه مدیر")

        with self.assertRaisesMessage(ValidationError, "پیشنهاد مالی"):
            review_publication_request(
                request.pk,
                actor=self.manager,
                status=PublicationRequest.Status.APPROVED,
                review_note="انتشار بدون ارسال پیشنهاد",
            )

    def test_offer_change_invalidates_prior_acceptance_while_internal_note_preserves_it(self):
        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            content_digest=publication_content_digest(self.book),
        )
        send_publication_offer(
            request.pk,
            actor=self.manager,
            platform_fee_percent=20,
            prep_mode=PublicationRequest.OfferPrepMode.READY_FILES,
            distribution_scope=PublicationRequest.DistributionScope.STANDARD,
            campaign_discount_cap=25,
            offer_note="نسخه اول با نرخ ۲۰ درصد",
        )
        request.refresh_from_db()
        respond_to_publication_offer(
            request.pk,
            actor=self.teacher,
            decision=PublicationRequest.TeacherResponse.ACCEPTED,
            expected_offer_digest=request.sent_offer_digest,
            expected_offer_version=request.sent_offer_version,
        )
        request.refresh_from_db()
        self.assertTrue(request.is_current_offer_accepted)

        # Changing internal review_note does NOT invalidate teacher acceptance AND never renders on teacher pages.
        review_publication_request(
            request.pk,
            actor=self.manager,
            status=PublicationRequest.Status.PENDING,
            review_note="یادداشت داخلی مدیر: در حال کنترل نهایی جلد",
        )
        request.refresh_from_db()
        self.assertTrue(request.is_current_offer_accepted)
        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        for url in (
            reverse("admin:catalog_book_change", args=[self.book.pk]),
            reverse("admin:catalog_book_request_publication", args=[self.book.pk]),
        ):
            page = teacher_client.get(url)
            self.assertEqual(page.status_code, 200)
            self.assertNotContains(page, "یادداشت داخلی مدیر: در حال کنترل نهایی جلد")

        # Sending v2 with 25% MUST invalidate v1 acceptance and block approval until re-accepted.
        send_publication_offer(
            request.pk,
            actor=self.manager,
            platform_fee_percent=25,
            prep_mode=PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            distribution_scope=PublicationRequest.DistributionScope.STANDARD,
            campaign_discount_cap=25,
            offer_note="نسخه دوم با نرخ ۲۵ درصد",
        )
        request.refresh_from_db()
        self.assertEqual(request.sent_offer_version, 2)
        self.assertEqual(request.accepted_offer_version, 1)
        self.assertFalse(request.is_current_offer_accepted)
        self.assertTrue(request.has_superseded_acceptance)
        self.assertEqual(request.workflow_summary()["code"], "offer_pending")

        with self.assertRaisesMessage(ValidationError, "آخرین نسخهٔ پیشنهاد"):
            review_publication_request(
                request.pk,
                actor=self.manager,
                status=PublicationRequest.Status.APPROVED,
                review_note="تلاش با پذیرش قبلی",
            )

        # Stale expected_offer_digest or stale expected_offer_version from v1 must be rejected too.
        with self.assertRaisesMessage(ValidationError, "تغییر کرده"):
            respond_to_publication_offer(
                request.pk,
                actor=self.teacher,
                decision=PublicationRequest.TeacherResponse.ACCEPTED,
                expected_offer_digest="0" * 64,
                expected_offer_version=2,
            )
        with self.assertRaisesMessage(ValidationError, "تغییر کرده"):
            respond_to_publication_offer(
                request.pk,
                actor=self.teacher,
                decision=PublicationRequest.TeacherResponse.ACCEPTED,
                expected_offer_digest=request.sent_offer_digest,
                expected_offer_version=1,
            )

    def test_needs_info_content_fix_is_distinct_from_financial_offer_and_hides_internal_note(self):
        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            content_digest=publication_content_digest(self.book),
        )
        # NEEDS_INFO requires teacher-facing content_feedback, keeping internal review_note private.
        with self.assertRaisesMessage(ValidationError, "پیام قابل مشاهده برای استاد"):
            review_publication_request(
                request.pk,
                actor=self.manager,
                status=PublicationRequest.Status.NEEDS_INFO,
                review_note="فقط یادداشت داخلی",
            )
        review_publication_request(
            request.pk,
            actor=self.manager,
            status=PublicationRequest.Status.NEEDS_INFO,
            content_feedback="فصل اول نیاز به اصلاح فرمول‌ها دارد.",
            review_note="یادداشت محرمانه داخلی شماره دو",
        )
        request.refresh_from_db()
        summary = request.workflow_summary()
        self.assertEqual(summary["code"], "content_fix")
        self.assertIn("اصلاح محتوای کتاب", summary["stage_label"])

        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        for url in (
            reverse("admin:catalog_book_change", args=[self.book.pk]),
            reverse("admin:catalog_book_request_publication", args=[self.book.pk]),
        ):
            page = teacher_client.get(url)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "فصل اول نیاز به اصلاح فرمول‌ها دارد.")
            self.assertNotContains(page, "یادداشت محرمانه داخلی شماره دو")

    def test_accepted_terms_execute_immediately_in_commerce_and_single_sale_access(self):
        from unittest.mock import patch
        from apps.catalog.access import access_kind, owns_book
        from apps.catalog.models import Major
        from apps.commerce.models import Order, Plan, SaleCampaign
        from apps.commerce.pricing import book_price_quote
        from apps.commerce.royalty import calculate_and_save_order_royalty

        major = Major.objects.create(name="ریاضی", slug="math-workflow")
        self.book.majors.add(major)
        self.book.price = 400_000
        self.book.save(update_fields=["price"])

        # Pre-existing active/scheduled 30% campaign (> agreed 15% cap) MUST block final approval.
        incompatible = SaleCampaign.objects.create(
            title="کمپین قدیمی ۳۰ درصد",
            book=self.book,
            discounted_price=280_000,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=5),
            is_active=True,
        )

        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            requested_distribution_scope=PublicationRequest.DistributionScope.SINGLE_SALE_ONLY,
            single_sale_exception_reason="توافق ویژه فقط تک‌فروش",
            content_digest=publication_content_digest(self.book),
        )
        send_publication_offer(
            request.pk,
            actor=self.manager,
            platform_fee_percent=25,
            prep_mode=PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            distribution_scope=PublicationRequest.DistributionScope.SINGLE_SALE_ONLY,
            campaign_discount_cap=15,
            offer_note="توافق ۲۵٪ پلتفرم با استثنای فقط فروش تکی و سقف کمپین ۱۵٪.",
        )
        request.refresh_from_db()
        respond_to_publication_offer(
            request.pk,
            actor=self.teacher,
            decision=PublicationRequest.TeacherResponse.ACCEPTED,
            expected_offer_digest=request.sent_offer_digest,
            expected_offer_version=request.sent_offer_version,
        )
        with self.assertRaisesMessage(ValidationError, "کمپین قدیمی ۳۰ درصد"):
            review_publication_request(
                request.pk,
                actor=self.manager,
                status=PublicationRequest.Status.APPROVED,
                review_note="انتشار با کمپین ناسازگار",
            )
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_published)

        # Deactivating the incompatible campaign lets approval succeed.
        incompatible.is_active = False
        incompatible.save(update_fields=["is_active"])
        review_publication_request(
            request.pk,
            actor=self.manager,
            status=PublicationRequest.Status.APPROVED,
            review_note="انتشار با شرایط توافق‌شده",
        )
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_published)
        self.assertTrue(self.book.single_sale_only)
        self.assertEqual(self.book.campaign_discount_cap_percent, 15)

        # Single-book order settles at exact 25% platform / 75% author.
        buyer = User.objects.create_user("09120000098")
        order = Order.objects.create(
            user=buyer,
            book=self.book,
            amount=400_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        snapshot = calculate_and_save_order_royalty(order)
        self.assertEqual(snapshot.platform_share_amount, 100_000)
        self.assertEqual(snapshot.total_authors_amount, 300_000)

        # Subscriber with all-majors subscription must NOT get access to a single_sale_only book.
        subscriber = User.objects.create_user("09120000099")
        plan = Plan.objects.create(title="اشتراک کل", months=1, price=200_000, scope=Plan.Scope.ALL)
        Entitlement.objects.create(
            user=subscriber,
            all_majors=True,
            starts_at=timezone.now() - timedelta(days=1),
            ends_at=timezone.now() + timedelta(days=29),
        )
        self.assertFalse(owns_book(subscriber, self.book))
        self.assertIsNone(access_kind(subscriber, self.book))

        offers_res = self.client.get(f"/api/v1/offers/?book={self.book.slug}")
        self.assertEqual(offers_res.status_code, 200)
        self.assertEqual(offers_res.json()["plans"], [])
        self.assertTrue(offers_res.json()["book"]["single_sale_only"])

        # Campaign discount exceeding agreed 15% cap is blocked by validation.
        too_high_discount = SaleCampaign(
            title="تخفیف غیرمجاز",
            book=self.book,
            discounted_price=320_000,  # 20% > 15% cap
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=3),
        )
        with self.assertRaises(ValidationError):
            too_high_discount.full_clean()

        # Runtime safety net: even if an out-of-cap campaign exists directly in DB, quotes & real orders enforce the cap.
        SaleCampaign.objects.create(
            title="کمپین خارج از سقف در دیتابیس",
            book=self.book,
            discounted_price=280_000,  # 30% > 15% cap
            starts_at=timezone.now() - timedelta(minutes=5),
            ends_at=timezone.now() + timedelta(days=2),
            is_active=True,
        )
        self.assertEqual(book_price_quote(self.book).price, 400_000)

        # Valid 10% campaign (<= 15% cap) creates a real order at 360,000 Toman.
        SaleCampaign.objects.filter(book=self.book).update(is_active=False)
        valid_discount = SaleCampaign(
            title="تخفیف مجاز",
            book=self.book,
            discounted_price=360_000,  # 10% <= 15% cap
            starts_at=timezone.now() - timedelta(minutes=5),
            ends_at=timezone.now() + timedelta(days=3),
            is_active=True,
        )
        valid_discount.full_clean()
        valid_discount.save()

        from django.test import override_settings
        from rest_framework.test import APIClient
        from apps.commerce.models import OrderAuthorRevenue, OrderRevenueSnapshot, TeacherWallet, WalletTransaction

        shopper = User.objects.create_user("09120000100")
        shopper_client = APIClient()
        shopper_client.force_authenticate(user=shopper)
        with patch("apps.commerce.zibal.request_payment", return_value="track-cap-1"):
            order_res = shopper_client.post(
                "/api/v1/orders/",
                data={"book": self.book.slug},
                format="json",
            )
        self.assertEqual(order_res.status_code, 201)
        created_order = Order.objects.get(pk=order_res.json()["order_id"])
        self.assertEqual(created_order.amount, 360_000)
        self.assertEqual(created_order.regular_amount, 400_000)
        self.assertEqual(created_order.discount_amount, 40_000)

        # End-to-end payment settlement through Zibal callback -> Entitlement -> RevenueSnapshot -> TeacherWallet.
        with override_settings(PAYMENTS_ENABLED=True):
            with patch(
                "apps.commerce.zibal.verify",
                return_value={"result": 100, "amount": 360_000 * 10, "refNumber": "REF-CAP-1", "cardNumber": "6037****1234"},
            ):
                cb_res = self.client.get("/api/v1/payments/zibal/callback/?trackId=track-cap-1&success=1")
        self.assertEqual(cb_res.status_code, 200)
        created_order.refresh_from_db()
        self.assertEqual(created_order.status, Order.Status.PAID)
        self.assertTrue(owns_book(shopper, self.book))

        cb_snapshot = OrderRevenueSnapshot.objects.get(order=created_order)
        self.assertEqual(cb_snapshot.platform_share_amount, 90_000)   # 25% of 360,000
        self.assertEqual(cb_snapshot.total_authors_amount, 270_000)   # 75% of 360,000
        author_rev = OrderAuthorRevenue.objects.get(snapshot=cb_snapshot, author=self.teacher)
        self.assertEqual(author_rev.amount, 270_000)
        wallet = TeacherWallet.objects.get(teacher=self.teacher)
        # Order #1 (400k * 75% = 300k) + Order #2 via Zibal callback (360k * 75% = 270k) = 570k
        self.assertEqual(wallet.pending_balance, 570_000)
        tx = WalletTransaction.objects.get(
            wallet=wallet,
            author_revenue=author_rev,
            event_type=WalletTransaction.EventType.EARN_PENDING,
        )
        self.assertEqual(tx.amount, 270_000)
        plan.delete()

    def test_model_b_technical_export_disabled_enforced_across_downloads_emails_and_ui(self):
        from apps.catalog.models import ChapterRevision

        # Grant content-edit capability so teacher normally has export/email permissions before Model B lock.
        BookEditor.objects.filter(book=self.book, user=self.teacher).update(can_edit_content=True)
        # Ensure email is verified on teacher so email-export buttons are visible before lock.
        self.teacher.email = "author@example.com"
        self.teacher.email_verified_at = timezone.now()
        self.teacher.save(update_fields=["email", "email_verified_at"])
        rev = ChapterRevision.objects.create(
            chapter=self.chapter,
            text="نسخه آزمایشی فصل",
            source=ChapterRevision.Source.PANEL,
            note="تست",
            user=self.teacher,
        )

        export_urls = [
            reverse("admin:catalog_book_export", args=[self.book.pk]),
            reverse("admin:catalog_book_tex_export", args=[self.book.pk]),
            reverse("admin:catalog_book_email_export", args=[self.book.pk]),
            reverse("admin:catalog_chapter_export", args=[self.chapter.pk]),
            reverse("admin:catalog_chapter_tex", args=[self.chapter.pk]),
            reverse("admin:catalog_chapter_email_tex", args=[self.chapter.pk]),
        ]
        rev_url = reverse("admin:catalog_revision_text", args=[self.chapter.pk, rev.pk])

        teacher_client = Client()
        teacher_client.force_login(self.teacher)
        # Before approval with technical_export_disabled=True, exports and links are available.
        before_book_page = teacher_client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertEqual(before_book_page.status_code, 200)
        for url in export_urls:
            self.assertContains(before_book_page, url)
        self.assertEqual(teacher_client.get(export_urls[0]).status_code, 200)
        self.assertEqual(teacher_client.get(export_urls[1]).status_code, 200)
        self.assertEqual(teacher_client.get(rev_url).status_code, 200)

        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            author_prep_preference=PublicationRequest.PrepPreference.NEEDS_PREP,
            content_digest=publication_content_digest(self.book),
        )
        # v1 with export allowed; then v2 toggles technical_export_disabled=True -> must bump version.
        send_publication_offer(
            request.pk,
            actor=self.manager,
            platform_fee_percent=30,
            prep_mode=PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            distribution_scope=PublicationRequest.DistributionScope.STANDARD,
            campaign_discount_cap=20,
            technical_export_disabled=False,
            offer_note="نسخه ۱ بدون قفل خروجی.",
        )
        request.refresh_from_db()
        respond_to_publication_offer(
            request.pk,
            actor=self.teacher,
            decision=PublicationRequest.TeacherResponse.ACCEPTED,
            expected_offer_digest=request.sent_offer_digest,
            expected_offer_version=request.sent_offer_version,
        )
        send_publication_offer(
            request.pk,
            actor=self.manager,
            platform_fee_percent=30,
            prep_mode=PublicationRequest.OfferPrepMode.PLATFORM_PREP,
            distribution_scope=PublicationRequest.DistributionScope.STANDARD,
            campaign_discount_cap=20,
            technical_deliverable="دریافت فایل فنی این کتاب غیرفعال است.",
            technical_export_disabled=True,
            offer_note="مدل ب با آماده‌سازی کامل و مسدودسازی خروجی فنی.",
        )
        request.refresh_from_db()
        self.assertEqual(request.sent_offer_version, 2)
        self.assertFalse(request.is_current_offer_accepted)

        offer_page = teacher_client.get(reverse("admin:catalog_book_request_publication", args=[self.book.pk]))
        self.assertContains(offer_page, "دریافت و ارسال ایمیلی فایل‌های فنی (Markdown / LaTeX) پس از تأیید انتشار غیرفعال خواهد بود")

        respond_to_publication_offer(
            request.pk,
            actor=self.teacher,
            decision=PublicationRequest.TeacherResponse.ACCEPTED,
            expected_offer_digest=request.sent_offer_digest,
            expected_offer_version=request.sent_offer_version,
        )
        review_publication_request(
            request.pk,
            actor=self.manager,
            status=PublicationRequest.Status.APPROVED,
            review_note="انتشار مدل ب با قفل خروجی‌های فنی.",
        )
        self.book.refresh_from_db()
        self.assertTrue(self.book.technical_export_disabled)

        # Book page & chapter history must hide all export/email links and show restriction notice.
        book_page = teacher_client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertEqual(book_page.status_code, 200)
        self.assertContains(book_page, "دریافت و ارسال ایمیلی فایل‌های فنی (Markdown / LaTeX) برای این کتاب غیرفعال شده است")
        for url in export_urls:
            self.assertNotContains(book_page, url)
            self.assertEqual(teacher_client.get(url).status_code, 403, f"Expected 403 for teacher on {url}")

        history_page = teacher_client.get(reverse("admin:catalog_chapter_history", args=[self.chapter.pk]))
        self.assertEqual(history_page.status_code, 200)
        self.assertNotContains(history_page, rev_url)
        self.assertEqual(teacher_client.get(rev_url).status_code, 403)

        # Superuser in teacher-preview mode is also blocked; normal superuser can still export.
        manager_client = Client()
        manager_client.force_login(self.manager)
        session = manager_client.session
        session["admin_view_mode"] = "teacher"
        session.save()
        self.assertEqual(manager_client.get(export_urls[0]).status_code, 403)
        session["admin_view_mode"] = "admin"
        session.save()
        self.assertEqual(manager_client.get(export_urls[0]).status_code, 200)
        self.assertEqual(manager_client.get(export_urls[1]).status_code, 200)
        self.assertEqual(manager_client.get(rev_url).status_code, 200)

    def test_changed_snapshot_cannot_be_approved(self):
        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            content_digest=publication_content_digest(self.book),
        )
        self.chapter.full_body = "محتوا پس از درخواست تغییر کرد"
        self.chapter.save(update_fields=["full_body"])

        with self.assertRaisesMessage(ValidationError, "محتوا پس از ثبت درخواست تغییر کرده"):
            review_publication_request(
                request.pk,
                actor=self.manager,
                status=PublicationRequest.Status.APPROVED,
                review_note="نسخه‌ی قدیمی.",
            )

        request.refresh_from_db()
        self.book.refresh_from_db()
        self.assertEqual(request.status, PublicationRequest.Status.PENDING)
        self.assertFalse(self.book.is_published)
        self.assertFalse(request.events.exists())

    def test_non_superuser_cannot_make_publication_decision(self):
        request = PublicationRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            content_digest=publication_content_digest(self.book),
        )
        with self.assertRaises(PermissionError):
            review_publication_request(
                request.pk,
                actor=self.teacher,
                status=PublicationRequest.Status.APPROVED,
            )
        request.refresh_from_db()
        self.assertEqual(request.status, PublicationRequest.Status.PENDING)
