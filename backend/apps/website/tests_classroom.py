from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import ContentNode
from apps.website.group_access import activate_classroom_members
from apps.website.models import Classroom, ClassroomMember

User = get_user_model()


class ClassroomModelTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(phone="09121111111", is_staff=True)
        self.student = User.objects.create(phone="09122222222")
        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="کتاب فیزیک آزمایشی",
            slug="test-phys",
            is_published=True,
        )

    def test_classroom_creation_and_defaults(self):
        classroom = Classroom.objects.create(
            teacher=self.teacher,
            book=self.book,
            title="فیزیک پایه - ترم پاییز",
            capacity=50,
            expiry_policy=Classroom.ExpiryPolicy.FROM_JOIN,
            duration_days=90,
        )
        self.assertTrue(classroom.code)
        self.assertEqual(len(classroom.code), 8)
        self.assertTrue(classroom.is_active)
        self.assertTrue(classroom.has_capacity)
        self.assertEqual(classroom.active_members_count, 0)

    def test_classroom_member_activation_on_otp(self):
        now = timezone.now()
        classroom = Classroom.objects.create(
            teacher=self.teacher,
            book=self.book,
            title="فیزیک پایه",
            capacity=100,
            expiry_policy=Classroom.ExpiryPolicy.FROM_JOIN,
            duration_days=30,
        )
        member = ClassroomMember.objects.create(
            classroom=classroom,
            phone="09122222222",
            join_method=ClassroomMember.JoinMethod.BULK_IMPORT,
            status=ClassroomMember.Status.WAITING_OTP,
        )

        activated = activate_classroom_members(self.student, now=now)
        self.assertEqual(activated, 1)

        member.refresh_from_db()
        self.assertEqual(member.status, ClassroomMember.Status.ACTIVE)
        self.assertEqual(member.user, self.student)
        self.assertIsNotNone(member.entitlement)
        self.assertEqual(member.entitlement.book, self.book)
        self.assertEqual(member.entitlement.granted_by, self.teacher)
        self.assertTrue(member.is_active)
        self.assertAlmostEqual(
            (member.entitlement.ends_at - now).total_seconds(),
            timedelta(days=30).total_seconds(),
            delta=5,
        )

class TeacherPanelClassroomTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from apps.catalog.access import BOOK_EDITOR_GROUP
        self.teacher_group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        self.teacher = User.objects.create(phone="09128887766", is_staff=True)
        self.teacher.groups.add(self.teacher_group)
        self.client.force_login(self.teacher)

    def test_teacher_can_create_draft_book_and_gains_editor_access(self):
        from apps.catalog.models import BookEditor
        res = self.client.post("/admin/catalog/book/new-draft/", {
            "title": "شیمی تجزیه آزمایشی",
            "title_en": "Analytical Chemistry",
            "author": "دکتر آزمایشی",
            "about": "توضیح آزمایشی",
        })
        self.assertEqual(res.status_code, 302)
        book = ContentNode.objects.get(title="شیمی تجزیه آزمایشی")
        self.assertFalse(book.is_published)
        self.assertTrue(book.slug.startswith("analytical-chemistry"))

        editor = BookEditor.objects.get(book=book, user=self.teacher)
        self.assertTrue(editor.can_edit_content)
        self.assertTrue(editor.can_request_group_access)

    def test_teacher_classroom_workflow(self):
        book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="کتاب آزمایشی کلاس",
            slug="test-class-book",
            is_published=False,
        )
        from apps.catalog.models import BookEditor
        BookEditor.objects.create(book=book, user=self.teacher, can_edit_content=True)

        # 1. Create classroom
        res = self.client.post("/admin/website/classroom/add/", {
            "title": "کلاس شیمی",
            "book": book.pk,
            "capacity": 50,
            "expiry_policy": Classroom.ExpiryPolicy.FROM_JOIN,
            "duration_days": 60,
            "member_phones": "09121112233\n09124445566",
        })
        self.assertEqual(res.status_code, 302)
        classroom = Classroom.objects.get(teacher=self.teacher, title="کلاس شیمی")
        self.assertEqual(classroom.members.count(), 2)

        # 2. Bulk add members
        res = self.client.post(f"/admin/website/classroom/{classroom.pk}/add-members/", {
            "member_phones": "09127778899",
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(classroom.members.count(), 3)

        # 3. Revoke member
        member = classroom.members.get(phone="09121112233")
        res = self.client.post(f"/admin/website/classroommember/{member.pk}/revoke/", {
            "reason": "تست لغو",
        })
        self.assertEqual(res.status_code, 302)
        member.refresh_from_db()
        self.assertEqual(member.status, ClassroomMember.Status.REVOKED)

    def test_teacher_can_view_admin_classroom_and_books(self):
        res_index = self.client.get("/admin/")
        self.assertEqual(res_index.status_code, 200)
        self.assertContains(res_index, "کلاس")

        res_books = self.client.get("/admin/catalog/book/")
        self.assertEqual(res_books.status_code, 200)
        self.assertContains(res_books, "ایجاد کتاب پیش‌نویس")

        res_classrooms = self.client.get("/admin/website/classroom/")
        self.assertEqual(res_classrooms.status_code, 200)

class ClassroomJoinLandingTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create(phone="09121119999", is_staff=True)
        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="کتاب آزمایشی فرود",
            slug="landing-test-book",
            is_published=False,
        )
        self.classroom = Classroom.objects.create(
            teacher=self.teacher,
            book=self.book,
            title="کلاس آزمایشی لندینگ",
            capacity=40,
            expiry_policy=Classroom.ExpiryPolicy.FROM_JOIN,
            duration_days=60,
        )

    def test_anonymous_join_landing_renders(self):
        res = self.client.get(f"/join/{self.classroom.code}/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.classroom.title)
        self.assertContains(res, self.book.title)
        self.assertContains(res, "شماره موبایل دانشجو")
        self.assertContains(res, "resend-otp-btn")

    def test_authenticated_student_can_join_and_gain_entitlement(self):
        student = User.objects.create(phone="09123334444")
        self.client.force_login(student)
        res = self.client.post(f"/join/{self.classroom.code}/")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.url, f"/book/{self.book.slug}")

        member = ClassroomMember.objects.get(classroom=self.classroom, phone=student.phone)
        self.assertEqual(member.status, ClassroomMember.Status.ACTIVE)
        self.assertIsNotNone(member.entitlement)
        self.assertEqual(member.entitlement.book, self.book)

        # Check that landing page renders deep link for active members
        res_member = self.client.get(f"/join/{self.classroom.code}/")
        self.assertEqual(res_member.status_code, 200)
        self.assertContains(res_member, f"limookhan://book/{self.book.slug}")
        self.assertContains(res_member, "deep-link-btn")

    def test_inactive_classroom_shows_error_state(self):
        self.classroom.is_active = False
        self.classroom.save()
        res = self.client.get(f"/join/{self.classroom.code}/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "غیرفعال شده است")

    def test_expired_fixed_date_classroom_blocks_join_and_shows_no_success_message(self):
        from django.contrib.messages import get_messages
        from django.core.exceptions import ValidationError
        from apps.catalog.access import owns_book

        yesterday = timezone.localdate() - timedelta(days=1)
        expired_cls = Classroom.objects.create(
            teacher=self.teacher,
            book=self.book,
            title="کلاس منقضی",
            expiry_policy=Classroom.ExpiryPolicy.FIXED_DATE,
            ends_on=yesterday,
        )
        # Model clean rejects active classroom with past ends_on, but allows inactive archival.
        with self.assertRaises(ValidationError):
            expired_cls.full_clean()
        expired_cls.is_active = False
        expired_cls.full_clean()
        expired_cls.is_active = True
        expired_cls.save()

        student = User.objects.create(phone="09123334455")
        self.client.force_login(student)

        res_get = self.client.get(f"/join/{expired_cls.code}/")
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "مهلت کلاس به پایان رسیده است")
        self.assertNotContains(res_get, "افزودن کتاب به کتابخانه من")

        res_post = self.client.post(f"/join/{expired_cls.code}/")
        self.assertEqual(res_post.status_code, 302)
        self.assertEqual(res_post.url, f"/join/{expired_cls.code}/")
        msgs = [str(m) for m in get_messages(res_post.wsgi_request)]
        self.assertFalse(any("با موفقیت" in m for m in msgs))
        self.assertTrue(any("پایان رسیده" in m for m in msgs))
        self.assertFalse(owns_book(student, self.book))

    def test_anonymous_student_otp_verify_logs_in_and_activates_membership(self):
        import json
        from apps.accounts.models import DeviceSession, OTPCode
        from apps.catalog.access import owns_book

        phone = "09125556677"
        _, code = OTPCode.issue(phone)

        res = self.client.post(
            f"/join/{self.classroom.code}/",
            data=json.dumps({"action": "verify_otp", "phone": phone, "code": code}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertTrue(body["ok"])

        user = User.objects.get(phone=phone)
        member = ClassroomMember.objects.get(classroom=self.classroom, phone=phone)
        self.assertEqual(member.status, ClassroomMember.Status.ACTIVE)
        self.assertTrue(member.is_active)
        self.assertTrue(owns_book(user, self.book))
        # Must use a Django web session, without consuming an app DeviceSession slot.
        self.assertEqual(DeviceSession.objects.filter(user=user).count(), 0)

        # Follow-up GET sees the authenticated active membership card immediately.
        res_after = self.client.get(f"/join/{self.classroom.code}/")
        self.assertContains(res_after, "عضو این کلاس شده‌اید")

    def test_capacity_limit_is_enforced_and_revoke_blocks_rejoin(self):
        from apps.catalog.access import owns_book

        self.classroom.capacity = 1
        self.classroom.save(update_fields=["capacity"])

        s1 = User.objects.create(phone="09126660001")
        s2 = User.objects.create(phone="09126660002")

        self.client.force_login(s1)
        self.client.post(f"/join/{self.classroom.code}/")
        self.assertTrue(owns_book(s1, self.book))
        self.assertFalse(self.classroom.has_capacity)

        # Second student sees full classroom and cannot enroll even via direct POST or bulk-import activation.
        self.client.force_login(s2)
        res_full_get = self.client.get(f"/join/{self.classroom.code}/")
        self.assertContains(res_full_get, "ظرفیت کلاس تکمیل است")
        self.client.post(f"/join/{self.classroom.code}/")
        self.assertFalse(owns_book(s2, self.book))

        ClassroomMember.objects.create(
            classroom=self.classroom,
            phone=s2.phone,
            join_method=ClassroomMember.JoinMethod.BULK_IMPORT,
            status=ClassroomMember.Status.WAITING_OTP,
        )
        self.assertEqual(activate_classroom_members(s2), 0)
        self.assertFalse(owns_book(s2, self.book))

        # Revoke s1 -> frees capacity for s2, while s1 remains permanently blocked from rejoining.
        m1 = ClassroomMember.objects.get(classroom=self.classroom, phone=s1.phone)
        m1.status = ClassroomMember.Status.REVOKED
        m1.save(update_fields=["status"])
        m1.entitlement.is_archived = True
        m1.entitlement.save(update_fields=["is_archived"])

        self.client.force_login(s1)
        self.assertContains(self.client.get(f"/join/{self.classroom.code}/"), "دسترسی لغو شده است")
        self.client.post(f"/join/{self.classroom.code}/")
        m1.refresh_from_db()
        self.assertEqual(m1.status, ClassroomMember.Status.REVOKED)
        self.assertFalse(owns_book(s1, self.book))

        self.assertEqual(activate_classroom_members(s2), 1)
        self.assertTrue(owns_book(s2, self.book))

    def test_expired_individual_entitlement_not_shown_as_active_member(self):
        student = User.objects.create(phone="09127770001")
        self.client.force_login(student)
        self.client.post(f"/join/{self.classroom.code}/")

        member = ClassroomMember.objects.get(classroom=self.classroom, phone=student.phone)
        member.entitlement.ends_at = timezone.now() - timedelta(minutes=1)
        member.entitlement.save(update_fields=["ends_at"])

        res = self.client.get(f"/join/{self.classroom.code}/")
        self.assertContains(res, "مهلت کلاس به پایان رسیده است")
        self.assertNotContains(res, "عضو این کلاس شده‌اید")

    def test_cohort_end_time_alignment_between_classroom_and_group_access(self):
        from apps.website.group_access import _approved_end
        from apps.website.models import BookAccessMember, BookAccessRequest

        end_date = timezone.localdate() + timedelta(days=10)
        cls = Classroom.objects.create(
            teacher=self.teacher,
            book=self.book,
            title="هم‌ترازی",
            expiry_policy=Classroom.ExpiryPolicy.FIXED_DATE,
            ends_on=end_date,
        )
        req = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            status=BookAccessRequest.Status.APPROVED,
            expiry_policy=BookAccessRequest.ExpiryPolicy.FIXED_DATE,
            ends_on=end_date,
            review_note="ok",
        )
        bam = BookAccessMember.objects.create(request=req, book=self.book, phone="09129990001")
        self.assertEqual(cls.calculate_end_time(), _approved_end(bam, timezone.now()))

    def test_revoke_hybrid_offline_policy_keep_vs_wipe(self):
        from django.urls import reverse
        from rest_framework.test import APIClient
        from apps.accounts.models import DeviceSession
        from apps.commerce.models import Entitlement

        student = User.objects.create(phone="09128880001")
        self.client.force_login(student)
        self.client.post(f"/join/{self.classroom.code}/")
        member = ClassroomMember.objects.get(classroom=self.classroom, phone=student.phone)

        # Teacher revokes with default "keep" policy -> entitlement archived, offline_revoked_at stays None
        self.teacher.is_superuser = True
        self.teacher.save(update_fields=["is_superuser"])
        self.client.force_login(self.teacher)
        revoke_url = reverse("admin:website_classroommember_revoke", args=[member.pk])
        res = self.client.post(revoke_url, {"reason": "لغو آزمایشی", "offline_policy": "keep"})
        self.assertEqual(res.status_code, 302)
        member.refresh_from_db()
        member.entitlement.refresh_from_db()
        self.assertEqual(member.status, ClassroomMember.Status.REVOKED)
        self.assertTrue(member.entitlement.is_archived)
        self.assertIsNone(member.entitlement.offline_revoked_at)

        _, token = DeviceSession.start(student, "android")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(api.get("/api/v1/me/").data["offline_revocations"], [])

        # Second student revoked with "wipe" -> reported in /api/v1/me/ offline_revocations
        student2 = User.objects.create(phone="09128880002")
        self.client.force_login(student2)
        self.client.post(f"/join/{self.classroom.code}/")
        member2 = ClassroomMember.objects.get(classroom=self.classroom, phone=student2.phone)

        self.client.force_login(self.teacher)
        res2 = self.client.post(
            reverse("admin:website_classroommember_revoke", args=[member2.pk]),
            {"reason": "حذف فوری", "offline_policy": "wipe"},
        )
        self.assertEqual(res2.status_code, 302)
        member2.entitlement.refresh_from_db()
        self.assertIsNotNone(member2.entitlement.offline_revoked_at)

        _, token2 = DeviceSession.start(student2, "android")
        api2 = APIClient()
        api2.credentials(HTTP_AUTHORIZATION=f"Bearer {token2}")
        revs = api2.get("/api/v1/me/").data["offline_revocations"]
        self.assertEqual(len(revs), 1)
        self.assertEqual(revs[0]["slug"], self.book.slug)

        # If student2 acquires a new active entitlement for the same book, offline_revocations stops listing it
        Entitlement.objects.create(user=student2, book=self.book)
        self.assertEqual(api2.get("/api/v1/me/").data["offline_revocations"], [])

    def test_group_access_revoke_hybrid_offline_policy(self):
        from django.urls import reverse
        from apps.accounts.models import DeviceSession
        from apps.website.models import BookAccessMember, BookAccessRequest
        from rest_framework.test import APIClient

        self.teacher.is_superuser = True
        self.teacher.save(update_fields=["is_superuser"])
        student = User.objects.create(phone="09128880003")
        req = BookAccessRequest.objects.create(
            book=self.book,
            requested_by=self.teacher,
            status=BookAccessRequest.Status.APPROVED,
            expiry_policy=BookAccessRequest.ExpiryPolicy.FROM_ACTIVATION,
            duration_days=30,
            reviewed_by=self.teacher,
            reviewed_at=timezone.now(),
            review_note="ok",
        )
        bam = BookAccessMember.objects.create(
            request=req,
            book=self.book,
            phone=student.phone,
            status=BookAccessMember.Status.WAITING_OTP,
        )
        from apps.website.group_access import activate_approved_members

        activate_approved_members(student)
        bam.refresh_from_db()

        self.client.force_login(self.teacher)
        res = self.client.post(
            reverse("admin:website_bookaccessmember_revoke", args=[bam.pk]),
            {"reason": "انصراف از دوره", "offline_policy": "wipe"},
        )
        self.assertEqual(res.status_code, 302)
        bam.entitlement.refresh_from_db()
        self.assertIsNotNone(bam.entitlement.offline_revoked_at)

        _, token = DeviceSession.start(student, "android")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        revs = api.get("/api/v1/me/").data["offline_revocations"]
        self.assertEqual([r["slug"] for r in revs], [self.book.slug])
