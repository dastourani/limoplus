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
