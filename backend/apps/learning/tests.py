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
        self.assertTrue(r["quick_solution"])
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
