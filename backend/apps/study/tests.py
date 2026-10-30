import io
import shutil
import tempfile

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, User
from apps.catalog.models import ContentNode
from apps.learning.models import Flashcard, Question, QuizAnswer

from .models import ExamAttempt, FlashcardReview, Note, StudyDay


class StudyTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.user = User.objects.create_user("09120000001")
        _, token = DeviceSession.start(self.user, "test")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.chapter = ContentNode.objects.get(slug="limits")
        self.section = self.chapter.get_children().first()
        self.paid_section = ContentNode.objects.get(slug="derivatives").get_children().first()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_progress_bookmark_and_notes(self):
        r = self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"percent": 95}, format="json")
        self.assertTrue(r.data["is_done"])
        self.assertTrue(self.client.post(f"/api/v1/nodes/{self.section.id}/bookmark/").data["bookmarked"])
        note = self.client.post(f"/api/v1/nodes/{self.section.id}/notes/", {"quote": "حد", "body": "مهم"}, format="json").data
        state = self.client.get(f"/api/v1/nodes/{self.section.id}/me/").data
        self.assertTrue(state["bookmarked"])
        self.assertEqual(len(state["notes"]), 1)
        self.client.delete(f"/api/v1/notes/{note['id']}/")
        self.assertTrue(Note.objects.get(pk=note["id"]).is_archived)  # archived, not deleted
        self.assertFalse(self.client.post(f"/api/v1/nodes/{self.section.id}/bookmark/").data["bookmarked"])
        lib = self.client.get("/api/v1/me/library/").data
        self.assertEqual(lib["reading"][0]["book_slug"], "math-1")
        self.assertEqual(StudyDay.objects.get(user=self.user).sections, 1)

    def test_locked_section_has_no_notes(self):
        r = self.client.post(f"/api/v1/nodes/{self.paid_section.id}/notes/", {"body": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_notes_are_private(self):
        note = self.client.post(f"/api/v1/nodes/{self.section.id}/notes/", {"body": "mine"}, format="json").data
        other = User.objects.create_user("09120000002")
        _, token = DeviceSession.start(other, "x")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.delete(f"/api/v1/notes/{note['id']}/").status_code, 404)

    def test_practice_reset_keeps_history(self):
        q = Question.objects.filter(node__path__startswith=self.chapter.path).first()
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        self.assertEqual(len(self.client.get(f"/api/v1/nodes/{self.chapter.id}/practice/").data["answered"]), 1)
        self.client.post(f"/api/v1/nodes/{self.chapter.id}/practice/reset/")
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.chapter.id}/practice/").data["answered"], {})
        self.assertEqual(QuizAnswer.objects.filter(user=self.user).count(), 1)
        self.assertEqual(self.client.get("/api/v1/me/stats/").data["answers"], 1)

    def test_leitner_boxes(self):
        card = Flashcard.objects.filter(node__path__startswith=self.chapter.path).first()
        self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"known": True}, format="json")
        self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"known": True}, format="json")
        self.assertEqual(FlashcardReview.objects.get(user=self.user, flashcard=card).box, 3)
        self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"known": False}, format="json")
        state = self.client.get(f"/api/v1/nodes/{self.chapter.id}/flashcards/me/").data
        self.assertEqual({k: state["cards"][str(card.id)][k] for k in ("box", "due")}, {"box": 1, "due": True})

    def test_four_grades_and_due_review(self):
        cards = list(Flashcard.objects.filter(node__path__startswith=self.chapter.path)[:4])
        for card, grade in zip(cards, ("again", "hard", "good", "easy")):
            self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"grade": grade}, format="json")
        boxes = {r.flashcard_id: r.box for r in FlashcardReview.objects.filter(user=self.user)}
        self.assertEqual([boxes[c.id] for c in cards], [1, 1, 2, 3])
        due = self.client.get("/api/v1/me/flashcards/due/").data
        self.assertEqual([c["id"] for c in due["flashcards"]], [cards[0].id])  # only «again» is due now
        self.assertEqual(due["flashcards"][0]["hints"], {"again": 0, "hard": 1, "good": 1, "easy": 3})
        state = self.client.get(f"/api/v1/nodes/{self.chapter.id}/flashcards/me/").data
        self.assertEqual(state["new_hints"]["easy"], 3)

    def test_old_app_known_flag_still_works(self):
        card = Flashcard.objects.filter(node__path__startswith=self.chapter.path).first()
        self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"known": True}, format="json")
        self.assertEqual(FlashcardReview.objects.get(user=self.user, flashcard=card).box, 2)

    def test_report_shows_as_reported(self):
        q = Question.objects.filter(node__path__startswith=self.chapter.path).first()
        r = self.client.post(f"/api/v1/questions/{q.id}/report/", {"reason": "typo", "note": "x"}, format="json")
        self.assertEqual(r.data["status"], "گزارش داده شد")
        self.client.post(f"/api/v1/questions/{q.id}/report/", {"reason": "typo"}, format="json")  # no duplicate
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.chapter.id}/practice/").data["reported"], [q.id])

    def test_exam_with_negative_marking(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 4}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("is_correct", str(r.data))
        self.assertNotIn("review", r.data)
        qs = {q.id: q for q in Question.objects.filter(pk__in=[q["id"] for q in r.data["questions"]])}
        ids = list(qs)
        answers = {
            str(ids[0]): qs[ids[0]].choices.get(is_correct=True).id,
            str(ids[1]): qs[ids[1]].choices.filter(is_correct=False).first().id,
            str(ids[2]): qs[ids[2]].choices.filter(is_correct=False).first().id,
        }
        res = self.client.post(f"/api/v1/exams/{r.data['id']}/submit/", {"answers": answers}, format="json").data
        self.assertEqual((res["correct"], res["wrong"], res["blank"]), (1, 2, 1))
        penalty = sum(1 / (qs[i].choices.count() - 1) for i in ids[1:3])
        self.assertAlmostEqual(res["score_percent"], round((1 - penalty) / 4 * 100, 1))
        self.assertEqual(len(res["review"]), 4)
        again = self.client.post(f"/api/v1/exams/{r.data['id']}/submit/", {"answers": {}}, format="json").data
        self.assertEqual(again["correct"], 1)  # submitting twice changes nothing

    def test_exam_excludes_locked_questions(self):
        book = self.chapter.get_parent()
        r = self.client.post(f"/api/v1/nodes/{book.id}/exams/", {"count": 50}, format="json")
        self.assertEqual(len(r.data["questions"]), 6)

    def test_exam_of_other_user_is_hidden(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")
        other = User.objects.create_user("09120000002")
        _, token = DeviceSession.start(other, "x")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.get(f"/api/v1/exams/{r.data['id']}/").status_code, 404)

    def test_stats(self):
        self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"done": True}, format="json")
        s = self.client.get("/api/v1/me/stats/").data
        self.assertEqual(s["sections_done"], 1)
        self.assertEqual(s["streak_days"], 1)
        self.assertEqual(s["books"][0]["done"], 1)

    def test_offline_bundle_only_readable_sections(self):
        data = self.client.get("/api/v1/books/math-1/offline/").data
        ids = {s["id"] for s in data["sections"]}
        self.assertIn(self.section.id, ids)
        self.assertNotIn(self.paid_section.id, ids)

    def test_guest_needs_login(self):
        self.assertEqual(APIClient().get("/api/v1/me/stats/").status_code, 401)

    def test_admin_dashboard_renders(self):
        admin = User.objects.create_superuser("09120000009", password="x-Pass-123")
        self.client.force_login(admin)
        r = self.client.get("/admin/study/dashboard/")
        self.assertContains(r, "داشبورد آمار")

    def test_practice_cannot_reveal_open_exam_answers(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")
        qid = r.data["questions"][0]["id"]
        q = Question.objects.get(pk=qid)
        res = self.client.post(f"/api/v1/questions/{qid}/answer/", {"choice_id": q.choices.first().id}, format="json")
        self.assertEqual(res.status_code, 409)
        self.client.post(f"/api/v1/exams/{r.data['id']}/submit/", {"answers": {}}, format="json")
        res = self.client.post(f"/api/v1/questions/{qid}/answer/", {"choice_id": q.choices.first().id}, format="json")
        self.assertEqual(res.status_code, 200)
