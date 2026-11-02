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

    def test_exam_history_pages_and_summary(self):
        for _ in range(12):
            r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")
            self.client.post(f"/api/v1/exams/{r.data['id']}/submit/", {"answers": {}}, format="json")
        self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")  # left unfinished
        self.assertEqual(len(self.client.get("/api/v1/me/exams/").data), 13)  # old plain list still works
        first = self.client.get("/api/v1/me/exams/?page=1").data
        self.assertEqual((len(first["results"]), first["has_more"]), (10, True))
        self.assertEqual(first["summary"]["count"], 12)
        self.assertEqual(len(first["summary"]["trend"]), 12)
        self.assertEqual(first["books"], [{"slug": "math-1", "title": first["results"][0]["book_title"]}])
        second = self.client.get("/api/v1/me/exams/?page=2&book=math-1").data
        self.assertEqual((len(second["results"]), second["has_more"]), (3, False))
        self.assertEqual(self.client.get("/api/v1/me/exams/?page=1&book=nope").data["summary"]["count"], 12)

    def test_exam_keeps_its_questions_when_content_is_edited(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")
        q = Question.objects.get(pk=r.data["questions"][0]["id"])
        right = q.choices.get(is_correct=True)
        # The content is edited mid-exam: the choices are rebuilt and the answer key changes.
        old = [(c.text, c.is_correct) for c in q.choices.all()]
        q.choices.all().delete()
        for i, (text, ok) in enumerate(old):
            q.choices.create(text=text + " (ویرایش)", is_correct=not ok if i < 2 else ok, order=i)
        res = self.client.post(f"/api/v1/exams/{r.data['id']}/submit/", {"answers": {str(q.id): right.id}}, format="json").data
        self.assertEqual(res["correct"], 1)
        review = next(x for x in res["review"] if x["question_id"] == q.id)
        self.assertEqual(review["picked_choice_id"], right.id)
        self.assertEqual(review["correct_choice_id"], right.id)
        stem = next(x for x in res["questions"] if x["id"] == q.id)
        self.assertNotIn("(ویرایش)", str(stem["choices"]))

    def test_open_exam_never_sends_answers(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")
        for payload in (r.data, self.client.get(f"/api/v1/exams/{r.data['id']}/").data):
            text = str(payload)
            for key in ("'ok'", "is_correct", "explanation", "review", "snapshot"):
                self.assertNotIn(key, text)

    def test_measured_difficulty_counts_first_answers_only(self):
        q = Question.objects.filter(node=self.section, is_archived=False).first()
        wrong = q.choices.filter(is_correct=False).first()
        right = q.choices.get(is_correct=True)
        before = Question.objects.get(pk=q.pk).answer_count
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json")
        self.client.post(f"/api/v1/nodes/{self.section.id}/practice/reset/")
        for _ in range(3):
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": right.id}, format="json")
        q.refresh_from_db()
        self.assertEqual((q.answer_count - before, q.correct_count), (1, 0))

    def test_flashcard_review_sent_twice_counts_once(self):
        card = Flashcard.objects.filter(node=self.section).first()
        for _ in range(2):
            self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"grade": "good", "op": "abc-1"}, format="json")
        self.assertEqual(FlashcardReview.objects.get(user=self.user, flashcard=card).review_count, 1)

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

    def test_notebook_collects_wrong_answers_and_drops_fixed_ones(self):
        q = Question.objects.filter(node=self.section, is_archived=False).first()
        wrong = q.choices.filter(is_correct=False).first()
        right = q.choices.get(is_correct=True)
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json")
        data = self.client.get("/api/v1/me/mistakes/").data
        self.assertEqual([i["question_id"] for i in data["items"]], [q.id])
        self.assertEqual(data["items"][0]["wrong_count"], 1)
        self.assertEqual(len(data["reasons"]), 4)
        self.assertEqual(self.client.post(f"/api/v1/me/mistakes/{q.id}/reason/", {"reason": "careless"}, format="json").data["reason"], "careless")
        self.assertEqual(self.client.get("/api/v1/me/mistakes/").data["items"][0]["reason"], "careless")
        self.assertEqual(self.client.post(f"/api/v1/me/mistakes/{q.id}/reason/", {"reason": "x"}, format="json").status_code, 400)
        never = Question.objects.exclude(pk=q.pk).filter(is_archived=False).first()
        self.assertEqual(self.client.post(f"/api/v1/me/mistakes/{never.id}/reason/", {"reason": "time"}, format="json").status_code, 404)
        practice = self.client.get("/api/v1/me/mistakes/questions/").data["questions"]
        self.assertEqual([p["id"] for p in practice], [q.id])
        self.assertNotIn("is_correct", str(practice))
        self.client.post(f"/api/v1/nodes/{self.section.id}/practice/reset/")
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": right.id}, format="json").data
        # One right answer: «نیازمند تثبیت», back in a few days; not yet out of the notebook.
        self.assertEqual(r["fixed"], {"step": "settling", "days": 0, "due_in": 3})
        self.assertEqual(r["node_id"], q.node_id)
        data = self.client.get("/api/v1/me/mistakes/").data
        self.assertEqual((data["count"], data["open"], data["settling"], data["due"]), (1, 0, 1, 0))
        self.assertEqual(data["items"][0]["state"], "settling")
        self.assertEqual(self.client.get("/api/v1/me/mistakes/questions/").data["questions"], [], "not its day yet")
        self.assertEqual(self.client.post(f"/api/v1/me/mistakes/{q.id}/reason/", {"reason": "time"}, format="json").status_code, 200)
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": right.id}, format="json").data
        self.assertEqual(r["fixed"]["step"], "early")
        # Three days later: right again settles it.
        from datetime import timedelta

        from django.utils import timezone

        QuizAnswer.objects.filter(user=self.user, question=q).update(answered_at=timezone.now() - timedelta(days=3))
        self.assertEqual(self.client.get("/api/v1/me/mistakes/").data["due"], 1)
        self.assertEqual([p["id"] for p in self.client.get("/api/v1/me/mistakes/questions/").data["questions"]], [q.id])
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": right.id}, format="json").data
        self.assertEqual(r["fixed"]["step"], "settled")
        self.assertEqual(self.client.get("/api/v1/me/mistakes/").data["count"], 0)
        imp = self.client.get("/api/v1/me/stats/").data["improvement"]
        self.assertEqual((imp["wrong"], imp["fixed"], imp["settled"]), (1, 1, 1))
        # Wrong again: back to the start.
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json")
        self.assertEqual(self.client.get("/api/v1/me/mistakes/").data["open"], 1)

    def test_blank_exam_answers_are_mistakes_and_locked_questions_are_not_listed(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json")
        self.client.post(f"/api/v1/exams/{r.data['id']}/submit/", {"answers": {}}, format="json")
        items = self.client.get("/api/v1/me/mistakes/").data["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i["blank"] for i in items))

    def test_today_and_quick_session(self):
        from datetime import timedelta

        from django.utils import timezone

        empty = self.client.get("/api/v1/me/today/").data
        self.assertEqual((empty["cards"], empty["mistakes"], empty["minutes"]), (0, 0, 0))
        self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"percent": 30}, format="json")
        q = Question.objects.filter(node=self.section, is_archived=False).first()
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.filter(is_correct=False).first().id}, format="json")
        card = Flashcard.objects.filter(node=self.section).first()
        self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"grade": "again"}, format="json")
        StudyDay.objects.filter(user=self.user).update(date=timezone.localdate() - timedelta(days=5))
        data = self.client.get("/api/v1/me/today/").data
        self.assertEqual((data["cards"], data["mistakes"], data["practise"]), (1, 1, 1))
        self.assertEqual(data["continue"]["id"], self.section.id)
        self.assertTrue(data["comeback"])
        self.assertGreaterEqual(data["minutes"], 5)
        quick = self.client.get("/api/v1/me/quick/").data
        self.assertEqual([c["id"] for c in quick["cards"]], [card.id])
        self.assertEqual(quick["questions"][0]["id"], q.id)
        self.assertLessEqual(len(quick["questions"]), 3)
        self.assertNotIn("is_correct", str(quick["questions"]))

    def test_place_and_mode_follow_the_account(self):
        self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"percent": 60, "position": 60, "mode": "full"}, format="json")
        self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"percent": 0, "position": 35, "mode": "summary"}, format="json")
        state = self.client.get(f"/api/v1/nodes/{self.section.id}/me/").data
        self.assertEqual((state["percent"], state["position"], state["mode"]), (60, 35, "summary"))
        reading = self.client.get("/api/v1/me/library/").data["reading"][0]
        self.assertEqual((reading["position"], reading["mode"]), (35, "summary"))

    def test_review_resent_after_another_still_counts_once(self):
        card = Flashcard.objects.filter(node=self.section).first()
        for op in ("a", "b", "a"):
            self.client.post(f"/api/v1/flashcards/{card.id}/review/", {"grade": "good", "op": op}, format="json")
        self.assertEqual(FlashcardReview.objects.get(user=self.user, flashcard=card).review_count, 2)


class PageEndAndPlacesTests(TestCase):
    """No dead end at the end of a chapter, the section's own status, and the notebook and exams per book."""

    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def test_last_section_of_a_chapter_leads_on(self):
        last = self.chapter.get_children().last()
        data = self.client.get(f"/api/v1/nodes/{last.id}/").data
        self.assertIsNone(data["next_id"])
        end = data["chapter_end"]
        self.assertEqual(end["chapter_id"], self.chapter.id)
        self.assertEqual(end["book_slug"], "math-1")
        self.assertTrue(end["next_chapter"]["locked"], "the next chapter of the sample is paid")
        first = self.chapter.get_children().first()
        if first.id != last.id:
            self.assertIsNone(self.client.get(f"/api/v1/nodes/{first.id}/").data["chapter_end"])

    def test_section_status_counts_what_is_left(self):
        status = self.client.get(f"/api/v1/nodes/{self.section.id}/").data["status"]
        self.assertGreater(status["questions"], 0)
        self.assertEqual(status["questions_left"], status["questions"])
        q = Question.objects.filter(node=self.section, is_archived=False).first()
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.section.id}/").data["status"]["questions_left"], status["questions"] - 1)
        self.assertIsNone(APIClient().get(f"/api/v1/nodes/{self.section.id}/").data["status"], "guests get no status")

    def test_notebook_and_exams_on_library_and_book_page(self):
        lib = self.client.get("/api/v1/me/library/").data
        self.assertEqual(lib["mistakes"]["count"], 0, "shown even when empty")
        q = Question.objects.filter(node=self.section, is_archived=False).first()
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.filter(is_correct=False).first().id}, format="json")
        self.assertEqual(self.client.get("/api/v1/me/library/").data["mistakes"]["due"], 1)
        mine = self.client.get("/api/v1/books/math-1/").data["mine"]
        self.assertEqual((mine["mistakes"]["count"], mine["exams"]), (1, 0))
        self.assertIsNone(APIClient().get("/api/v1/books/math-1/").data["mine"])

    def test_exam_keeps_fixed_order_and_tells_of_a_later_correction(self):
        from django.utils import timezone

        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 2}, format="json").data
        qid = r["questions"][0]["id"]
        self.assertIn("fixed_order", r["questions"][0])
        Question.objects.filter(pk=qid).update(key_changed_at=timezone.now(), key_change_note="پاسخ درست عوض شد.")
        done = self.client.post(f"/api/v1/exams/{r['id']}/submit/", {"answers": {}}, format="json").data
        review = {x["question_id"]: x for x in done["review"]}
        self.assertEqual(review[qid]["corrected"]["note"], "پاسخ درست عوض شد.")


class ReviewCycleTests(TestCase):
    """«چرخه‌ی مرور فصل»: finishing a chapter, what is due, batches of five, the schedule, the monthly exam, doubts."""

    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def _finish_reading(self):
        for s in self.chapter.get_children():
            self.client.post(f"/api/v1/nodes/{s.id}/progress/", {"percent": 100, "done": True}, format="json")

    def _answer_all(self, right=True):
        for q in Question.objects.filter(node__path__startswith=self.chapter.path, is_archived=False):
            c = q.choices.filter(is_correct=right).first()
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": c.id}, format="json")

    def _age(self, days):
        """Move everything back in time, as if `days` days passed."""
        from datetime import timedelta

        from django.utils import timezone

        from .models import ChapterReview

        for r in ChapterReview.objects.all():
            r.due_on -= timedelta(days=days)
            r.save()
        QuizAnswer.objects.update(answered_at=timezone.now() - timedelta(days=days))

    def test_reading_and_most_tests_finish_a_chapter(self):
        from .models import ChapterReview, FlashcardReview

        self._finish_reading()
        self.assertEqual(self.client.get("/api/v1/me/reviews/").data["due"], [], "tests not answered yet")
        self._answer_all()
        self.client.get("/api/v1/me/reviews/")
        review = ChapterReview.objects.get(user=self.user, chapter=self.chapter)
        self.assertEqual(review.finished_by, "auto")
        self.assertEqual((review.due_on - review.finished_at.date()).days, 1)
        self.assertTrue(FlashcardReview.objects.filter(user=self.user).exists(), "the chapter's cards join the Leitner box")

    def test_button_finishes_and_the_day_one_review_runs_in_fives(self):
        r = self.client.post(f"/api/v1/nodes/{self.chapter.id}/finish/")
        self.assertEqual(r.data["days"], 1)
        self._age(1)
        today = self.client.get("/api/v1/me/today/").data
        item = today["reviews"][0]
        self.assertEqual((item["kind"], item["book_title"], item["chapter_id"], item["is_exam"]), ("chapter", "ریاضی عمومی ۱", self.chapter.id, False))
        s = self.client.post("/api/v1/me/reviews/start/", {"kind": "chapter", "id": item["id"]}, format="json").data
        self.assertLessEqual(len(s["questions"]), 5)
        self.assertNotIn("is_correct", str(s["questions"]))
        nodes = {q["node_id"] for q in s["questions"]}
        self.assertGreater(len(nodes), 1, "spread over the sections")
        # Not enough answered: not counted yet.
        self.assertIsNone(self.client.post(f"/api/v1/me/reviews/{s['id']}/finish/").data["next_due_on"])
        for q in s["questions"]:
            right = Question.objects.get(pk=q["id"]).choices.get(is_correct=True)
            self.client.post(f"/api/v1/questions/{q['id']}/answer/", {"choice_id": right.id}, format="json")
        done = self.client.post(f"/api/v1/me/reviews/{s['id']}/finish/").data
        self.assertTrue(done["finished"])
        self.assertGreaterEqual(done["next_in_days"], 7, "a good result moves on to the week step")
        if done["more"]:
            more = self.client.post(f"/api/v1/me/reviews/{s['id']}/more/").data
            self.assertGreater(len(more["questions"]), len(s["questions"]))
            self.assertEqual(len({q["id"] for q in more["questions"]}), len(more["questions"]), "no question twice")

    def test_weak_result_comes_back_sooner(self):
        from .models import ChapterReview

        self.client.post(f"/api/v1/nodes/{self.chapter.id}/finish/")
        self._age(1)
        rid = ChapterReview.objects.get().id
        s = self.client.post("/api/v1/me/reviews/start/", {"kind": "chapter", "id": rid}, format="json").data
        for q in s["questions"]:
            wrong = Question.objects.get(pk=q["id"]).choices.filter(is_correct=False).first()
            self.client.post(f"/api/v1/questions/{q['id']}/answer/", {"choice_id": wrong.id}, format="json")
        done = self.client.post(f"/api/v1/me/reviews/{s['id']}/finish/").data
        self.assertEqual(done["next_in_days"], 1)
        self.assertEqual(ChapterReview.objects.get().stage, 0)
        self.assertGreater(self.client.get("/api/v1/me/mistakes/").data["open"], 0, "wrong review answers go to the notebook")

    def test_month_step_is_an_exam_without_negative_marking_and_doubts_come_back(self):
        from .models import ChapterReview, ExamAnswer

        self.client.post(f"/api/v1/nodes/{self.chapter.id}/finish/")
        ChapterReview.objects.update(stage=2)
        self._age(1)
        rid = ChapterReview.objects.get().id
        s = self.client.post("/api/v1/me/reviews/start/", {"kind": "chapter", "id": rid}, format="json").data
        self.assertIsNotNone(s["exam_id"])
        exam = self.client.get(f"/api/v1/exams/{s['exam_id']}/").data
        self.assertFalse(exam["negative_marking"])
        first = exam["questions"][0]["id"]
        self.client.post(f"/api/v1/exams/{s['exam_id']}/submit/", {"answers": {}, "doubts": [first]}, format="json")
        self.assertTrue(ExamAnswer.objects.get(question_id=first, attempt_id=s["exam_id"]).is_doubtful)
        r = ChapterReview.objects.get()
        self.assertEqual((r.done_count, r.stage), (1, 2), "all blank: stays at the month step, sooner")

    def test_book_page_shows_the_next_review(self):
        self.client.post(f"/api/v1/nodes/{self.chapter.id}/finish/")
        info = self.client.get("/api/v1/books/math-1/").data["reviews"]
        self.assertEqual(info["chapters"][str(self.chapter.id)]["days"], 1)
        self.assertIsNone(info["book"], "the mixed review needs two finished chapters")

    def test_two_finished_chapters_get_a_weekly_mixed_review(self):
        from apps.commerce.models import Entitlement

        from .models import BookReview

        book = self.chapter.get_parent()
        Entitlement.objects.create(user=self.user, book=book)
        for ch in book.get_children():
            self.client.post(f"/api/v1/nodes/{ch.id}/finish/")
        r = BookReview.objects.get(user=self.user)
        BookReview.objects.filter(pk=r.pk).update(due_on=r.due_on.replace(year=r.due_on.year - 1))
        due = [i for i in self.client.get("/api/v1/me/reviews/").data["due"] if i["kind"] == "book"]
        self.assertEqual(due[0]["chapters"], 2)
        s = self.client.post("/api/v1/me/reviews/start/", {"kind": "book", "id": r.id}, format="json").data
        chapters = {Question.objects.get(pk=q["id"]).node.get_parent().id for q in s["questions"]}
        self.assertEqual(len(chapters), 2, "mixed from both chapters")
