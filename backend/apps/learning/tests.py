import io
import shutil
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, User
from apps.catalog.models import ContentNode

from .models import Question, QuizAnswer


class QuizApiTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.client = APIClient()
        self.free_chapter = ContentNode.objects.get(slug="limits")
        self.paid_chapter = ContentNode.objects.get(slug="derivatives")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_questions_never_reveal_answers(self):
        data = self.client.get(f"/api/v1/nodes/{self.free_chapter.id}/questions/").data
        self.assertEqual(len(data["questions"]), 6)
        flat = str(data)
        self.assertNotIn("is_correct", flat)
        self.assertNotIn("explanation", flat)

    def test_paid_questions_are_counted_but_hidden(self):
        book = self.free_chapter.get_parent()
        data = self.client.get(f"/api/v1/nodes/{book.id}/questions/").data
        self.assertEqual(len(data["questions"]), 6)
        self.assertEqual(data["locked_count"], 3)

    def _question(self, slug):
        return Question.objects.get(slug=slug)

    def test_answer_is_graded_on_server(self):
        q = self._question("q-sin3x")
        wrong = q.choices.get(is_correct=False, order=0)
        right = q.choices.get(is_correct=True)
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json").data
        self.assertFalse(r["is_correct"])
        self.assertEqual(r["correct_choice_id"], right.id)
        self.assertEqual(r["solutions"][0]["title"], "راه‌حل سریع")
        self.assertEqual([f["title"] for f in r["flashcards"]][:1], ["حد معروف سینوس"])
        q.refresh_from_db()
        self.assertEqual((q.answer_count, q.correct_count), (0, 0))  # guests do not count

    def test_choice_from_another_question_rejected(self):
        q, other = self._question("q-sin3x"), self._question("q-cos2x")
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": other.choices.first().id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_paid_question_cannot_be_answered_by_guest(self):
        q = self._question("q-chain")
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_signed_in_answers_are_saved(self):
        user = User.objects.create_user("09120000000")
        _, token = DeviceSession.start(user, "test")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        q = self._question("q-sin3x")
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.get(is_correct=True).id}, format="json")
        saved = QuizAnswer.objects.get()
        self.assertTrue(saved.was_correct)
        q.refresh_from_db()
        self.assertEqual((q.answer_count, q.correct_count), (1, 1))

    def test_flashcards_free_and_locked(self):
        book = self.free_chapter.get_parent()
        data = self.client.get(f"/api/v1/nodes/{book.id}/flashcards/").data
        self.assertEqual(len(data["flashcards"]), 5)
        self.assertEqual(data["locked_count"], 3)
        self.assertTrue(all(f["title"] and f["point"] for f in data["flashcards"]))

    def test_staff_can_read_paid_content(self):
        staff = User.objects.create_user("09121111111", is_staff=True)
        _, token = DeviceSession.start(staff, "admin")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        node = ContentNode.objects.get(slug="rules")
        self.assertEqual(self.client.get(f"/api/v1/nodes/{node.id}/").status_code, 200)


class PastExamTests(QuizApiTests):
    """«کنکورهای سال‌های قبل», «مشابه», «تکراری‌ها و مشابه‌ها» and titled solutions."""

    def _setup_sources(self):
        from .models import ExamSource, QuestionSource

        free = list(Question.objects.filter(node__path__startswith=self.free_chapter.path, is_archived=False).order_by("id"))
        a = ExamSource.objects.create(name="کنکور ارشد اقتصاد", year=1401)
        b = ExamSource.objects.create(name="کنکور دکتری اقتصاد", year=1403)
        QuestionSource.objects.create(question=free[0], source=a, number=7)
        QuestionSource.objects.create(question=free[1], source=a, number=3)
        QuestionSource.objects.create(question=free[0], source=b, number=1)  # the same test again: «تکراری»
        QuestionSource.objects.create(question=free[2], source=b, number=2)
        free[2].similar_to.add(free[1])  # came back with a change: «مشابه»
        return free, a, b

    def test_past_exams_list_and_order(self):
        free, a, b = self._setup_sources()
        book = self.free_chapter.get_parent()
        data = self.client.get(f"/api/v1/books/{book.slug}/past/").data
        self.assertEqual([(x["year"], x["count"]) for x in data["exams"]], [(1403, 2), (1401, 2)])
        self.assertEqual(data["repeats"], 2)  # free[0] in two exams; free[1] ~ free[2]
        qs = self.client.get(f"/api/v1/books/{book.slug}/past/questions/?source={a.id}").data["questions"]
        self.assertEqual([q["id"] for q in qs], [free[1].id, free[0].id])  # by question number
        rep = self.client.get(f"/api/v1/books/{book.slug}/past/repeats/", {"names": "کنکور دکتری اقتصاد"}).data
        self.assertEqual(rep["groups"], 2)
        flat = str(rep)
        self.assertNotIn("is_correct", flat)

    def test_panel_filters(self):
        """The panel's list filters answer (on PostgreSQL too: the solutions count runs in the database)."""
        from django.contrib.auth import get_user_model

        free, a, b = self._setup_sources()
        free[0].solutions = [{"title": "", "body": "یک"}, {"title": "", "body": "دو"}]
        free[0].save()
        free[1].solutions = [{"title": "", "body": "یک"}]
        free[1].save()
        admin_user = get_user_model().objects.create_superuser("09120000077", "pw-123456")
        self.client.force_login(admin_user)
        url = "/admin/learning/question/"

        def ids(params):
            r = self.client.get(url, params)
            self.assertEqual(r.status_code, 200)
            return {q.pk for q in r.context["cl"].result_list}

        many = {q.pk for q in Question.objects.all() if len(q.solutions or []) > 1}
        self.assertIn(free[0].pk, many)
        self.assertEqual(ids({"alt": "1"}), many)
        self.assertEqual(ids({"similar": "1"}), {free[1].pk, free[2].pk})
        self.assertEqual(ids({"konkur": "کنکور دکتری اقتصاد"}), {free[0].pk, free[2].pk})
        self.assertEqual(ids({"year": "1401"}), {free[0].pk, free[1].pk})
        self.assertNotIn(free[0].pk, ids({"key": "1"}))
        self.assertTrue(ids({"role": "core"}))
        for page, params in [("/admin/learning/report/", {"about": "question"}), ("/admin/learning/examsource/", {"name": "کنکور ارشد اقتصاد"}),
                             ("/admin/catalog/banner/", {"audience": "all"}), ("/admin/accounts/user/", {"bought": "0", "week": "1"})]:
            self.assertEqual(self.client.get(page, params).status_code, 200, page)

    def test_similar_shown_under_the_answer_and_solutions_titled(self):
        free, a, b = self._setup_sources()
        right = free[1].choices.get(is_correct=True)
        r = self.client.post(f"/api/v1/questions/{free[1].id}/answer/", {"choice_id": right.id}, format="json").data
        self.assertEqual([x["id"] for x in r["similar"]], [free[2].id])
        self.assertIn("۱۴۰۳", r["similar"][0]["source"])
        free[1].solutions = [{"title": "راه‌حل تستی", "body": "میانبر"}]
        free[1].save()
        r = self.client.post(f"/api/v1/questions/{free[1].id}/answer/", {"choice_id": right.id}, format="json").data
        self.assertEqual(r["solutions"], [{"title": "راه‌حل تستی", "body": "میانبر"}])

    def test_solutions_and_similar_round_trip_through_the_file(self):
        from apps.catalog.exporter import export_chapter
        from apps.catalog.importer import apply_chapter, check_against_db, parse_chapter

        free, a, b = self._setup_sources()
        free[0].solutions = [{"title": "راه‌حل تستی", "body": "میانبر"}, {"title": "حل دیگر", "body": "دید هندسی"}]
        free[0].save()
        text = export_chapter(self.free_chapter)
        self.assertIn("راه‌حل (راه‌حل تستی): میانبر", text)
        self.assertIn(f"مشابه: {free[1].slug}", text)
        parsed = parse_chapter(text)
        check_against_db(parsed)
        self.assertFalse(parsed.errors, parsed.errors)
        apply_chapter(parsed)
        free[0].refresh_from_db()
        self.assertEqual([x["title"] for x in free[0].solutions], ["راه‌حل تستی", "حل دیگر"])
        self.assertEqual(list(free[2].similar_to.values_list("id", flat=True)), [free[1].id])
        self.assertEqual(export_chapter(self.free_chapter), text)

    def test_konkur_only_exam_and_similar_never_together(self):
        free, a, b = self._setup_sources()
        user = User.objects.create_user("09120000055")
        self.client.force_authenticate(user)
        e = self.client.post(f"/api/v1/nodes/{self.free_chapter.id}/exams/", {"count": 20, "negative_marking": True, "konkur_only": True}, format="json")
        self.assertEqual(e.status_code, 201, e.content)
        ids = {q["id"] for q in e.data["questions"]}
        self.assertTrue(ids <= {free[0].id, free[1].id, free[2].id})
        self.assertFalse({free[1].id, free[2].id} <= ids, "two «مشابه» tests in one exam")
        e = self.client.post(f"/api/v1/nodes/{self.free_chapter.id}/exams/", {"count": 20, "negative_marking": True, "years": [1401]}, format="json")
        self.assertEqual({q["id"] for q in e.data["questions"]}, {free[0].id, free[1].id})

    def test_readiness_warning_and_report_by_chapter(self):
        from apps.study.models import ChapterReview

        free, a, b = self._setup_sources()
        book = self.free_chapter.get_parent()
        user = User.objects.create_user("09120000066")
        self.client.force_authenticate(user)
        data = self.client.get(f"/api/v1/books/{book.slug}/past/").data
        self.assertEqual({x["ready"] for x in data["exams"]}, {0})
        info = self.client.get(f"/api/v1/nodes/{book.id}/exam-info/", {"source": a.id}).data
        self.assertEqual((info["source"]["count"], info["source"]["unread"]), (2, 2))
        # The learner says the chapter is finished: ready, and «فقط فصل‌های خوانده‌شده» keeps its tests.
        from datetime import date

        ChapterReview.objects.create(user=user, chapter=self.free_chapter, book=book, finished_at="2026-01-01T00:00Z", due_on=date(2026, 1, 2))
        data = self.client.get(f"/api/v1/books/{book.slug}/past/").data
        self.assertEqual({x["ready"] for x in data["exams"]}, {100})
        e = self.client.post(f"/api/v1/nodes/{book.id}/exams/", {"count": 20, "negative_marking": False, "source": a.id, "only_studied": True}, format="json")
        self.assertEqual(e.status_code, 201, e.content)
        attempt = e.data["id"]
        right = {q.id: q.choices.get(is_correct=True).id for q in free[:2]}
        r = self.client.post(f"/api/v1/exams/{attempt}/submit/", {"answers": {str(free[1].id): right[free[1].id]}}, format="json").data
        rows = r["by_chapter"]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["chapter_id"], rows[0]["total"], rows[0]["right"], rows[0]["blank"]), (self.free_chapter.id, 2, 1, 1))
