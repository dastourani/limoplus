from django.utils import timezone
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
        from django.core.cache import cache

        cache.clear()  # «کارهای امروز» and the finished-chapter check are kept in the cache per learner
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

    def test_exam_focus_on_mistakes_takes_up_to_half_from_them(self):
        qs = list(Question.objects.filter(node__path__startswith=self.chapter.path, is_archived=False))
        self.assertGreaterEqual(len(qs), 5)
        wrong = qs[:2]
        for q in wrong:
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.filter(is_correct=False).first().id}, format="json")
        e = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 4, "focus_mistakes": True}, format="json").data
        self.assertEqual(e["focused"], 2, "both mistakes, which is half of 4")
        self.assertTrue({q.id for q in wrong} <= {x["id"] for x in e["questions"]})
        self.assertEqual(len(e["questions"]), 4)
        # Left blank, its questions join the mistakes: still never more than half.
        self.client.post(f"/api/v1/exams/{e['id']}/submit/", {"answers": {}}, format="json")
        e = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 4, "focus_mistakes": True}, format="json").data
        self.assertEqual(e["focused"], 2)
        self.client.post(f"/api/v1/exams/{e['id']}/submit/", {"answers": {}}, format="json")
        plain = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 4}, format="json").data
        self.assertEqual(plain["focused"], 0, "off: all at random")

    def test_exam_report_knows_the_previous_score(self):
        first = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 3}, format="json").data
        self.client.post(f"/api/v1/exams/{first['id']}/submit/", {"answers": {}}, format="json")
        second = self.client.post(f"/api/v1/nodes/{self.chapter.id}/exams/", {"count": 3}, format="json").data
        self.client.post(f"/api/v1/exams/{second['id']}/submit/", {"answers": {}}, format="json")
        r = self.client.get(f"/api/v1/exams/{second['id']}/").data
        self.assertIsNotNone(r["previous_score"])
        self.assertIsNone(self.client.get(f"/api/v1/exams/{first['id']}/").data["previous_score"])

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
        self.assertEqual(first["results"][0]["number"], 13, "the newest is the 13th exam on this chapter")
        self.assertEqual(second["results"][-1]["number"], 1)
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
        self.assertEqual([t["kind"] for t in data["tasks"]], ["cards", "notebook"])
        self.assertEqual(data["minutes"], sum(t["minutes"] for t in data["tasks"]))
        quick = self.client.get("/api/v1/me/quick/").data
        self.assertEqual([c["id"] for c in quick["cards"]], [card.id])
        self.assertEqual(quick["questions"][0]["id"], q.id)
        self.assertLessEqual(len(quick["questions"]), 3)
        self.assertNotIn("is_correct", str(quick["questions"]))

    def test_notebook_tile_leaves_after_five_today(self):
        from datetime import timedelta

        from django.utils import timezone

        qs = list(Question.objects.filter(node__path__startswith=self.chapter.path, is_archived=False)[:6])
        for q in qs:
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.filter(is_correct=False).first().id}, format="json")
        QuizAnswer.objects.update(answered_at=timezone.now() - timedelta(days=1))
        self.assertIn("notebook", [t["kind"] for t in self.client.get("/api/v1/me/today/").data["tasks"]])
        for q in qs[:5]:
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.get(is_correct=True).id}, format="json")
        self.assertNotIn("notebook", [t["kind"] for t in self.client.get("/api/v1/me/today/").data["tasks"]])

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
        # Reading goes on into the next chapter (its first section: that chapter is paid, so its introduction is skipped).
        nxt = self.chapter.get_next_sibling()
        self.assertEqual(data["next_id"], nxt.get_children().first().id)
        end = data["chapter_end"]
        self.assertEqual(end["chapter_id"], self.chapter.id)
        self.assertEqual(end["book_slug"], "math-1")
        self.assertTrue(end["next_chapter"]["locked"], "the next chapter of the sample is paid")
        first = self.chapter.get_children().first()
        if first.id != last.id:
            self.assertIsNone(self.client.get(f"/api/v1/nodes/{first.id}/").data["chapter_end"])

    def test_reading_order_runs_through_chapter_introductions(self):
        from apps.catalog.models import ContentNode

        self.chapter.full_body = "مقدمه"
        self.chapter.save()
        first = self.chapter.get_children().first()
        intro = self.client.get(f"/api/v1/nodes/{self.chapter.id}/").data
        self.assertEqual(intro["next_id"], first.id)
        self.assertEqual(intro["summary"], "")
        self.assertEqual(intro["intro"]["sections"][0]["id"], first.id)
        self.assertEqual(intro["intro"]["continue_id"], first.id)
        self.assertIsNone(intro["chapter_end"])
        self.assertEqual(self.client.get(f"/api/v1/nodes/{first.id}/").data["previous_id"], self.chapter.id)
        self.assertEqual(ContentNode.objects.get(pk=self.chapter.pk).full_body, "مقدمه")

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

    def test_two_quick_taps_open_one_sitting(self):
        from .models import ChapterReview, ReviewSession

        self.client.post(f"/api/v1/nodes/{self.chapter.id}/finish/")
        ChapterReview.objects.update(stage=2)
        rid = ChapterReview.objects.get().id
        a = self.client.post("/api/v1/me/reviews/start/", {"kind": "chapter", "id": rid}, format="json").data
        b = self.client.post("/api/v1/me/reviews/start/", {"kind": "chapter", "id": rid}, format="json").data
        self.assertEqual((a["id"], a["exam_id"]), (b["id"], b["exam_id"]))
        self.assertEqual(ReviewSession.objects.count(), 1)

    def test_steps_count_from_the_day_the_chapter_was_finished(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import ChapterReview
        from .reviews import next_due

        finished = timezone.now() - timedelta(days=1)
        r = ChapterReview(finished_at=finished, stage=0)
        day = timezone.localdate(finished)
        # Perfect results never push the steps later: 1, 7 and 30 days after the chapter.
        stage, due = next_due(r, 1.0, day + timedelta(days=1))
        self.assertEqual((stage, (due - day).days), (1, 7))
        r.stage = 1
        stage, due = next_due(r, 1.0, day + timedelta(days=7))
        self.assertEqual((stage, (due - day).days), (2, 30))
        r.stage = 2
        stage, due = next_due(r, 1.0, day + timedelta(days=30))
        self.assertEqual((stage, (due - day).days), (3, 30 + 75))
        # A weak result repeats the same step sooner.
        r.stage = 1
        stage, due = next_due(r, 0.4, day + timedelta(days=7))
        self.assertEqual((stage, (due - day).days), (1, 10))


class ReviewOpTests(TestCase):
    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def test_a_resent_review_counts_once_however_many_came_between(self):
        from .models import FlashcardReview

        card = Flashcard.objects.filter(node=self.section).first()
        url = f"/api/v1/flashcards/{card.id}/review/"
        self.client.post(url, {"grade": "good", "op": "first"}, format="json")
        for i in range(7):
            self.client.post(url, {"grade": "good", "op": f"other-{i}"}, format="json")
        before = FlashcardReview.objects.get(user=self.user, flashcard=card).review_count
        self.client.post(url, {"grade": "good", "op": "first"}, format="json")
        self.assertEqual(FlashcardReview.objects.get(user=self.user, flashcard=card).review_count, before)


class ContinueReadingTests(TestCase):
    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def test_finished_chapter_continues_at_the_next_chapter(self):
        last = self.chapter.get_children().last()
        self.client.post(f"/api/v1/nodes/{last.id}/progress/", {"percent": 100, "done": True}, format="json")
        item = self.client.get("/api/v1/me/library/").data["reading"][0]
        nxt = item["next"]
        self.assertTrue(nxt["new_chapter"])
        self.assertTrue(nxt["locked"], "the next chapter of the sample is paid")
        self.assertEqual(nxt["chapter_title"], ContentNode.objects.get(slug="derivatives").title)
        first = self.chapter.get_children().first()
        self.client.post(f"/api/v1/nodes/{first.id}/progress/", {"percent": 40}, format="json")
        self.assertIsNone(self.client.get("/api/v1/me/library/").data["reading"][0]["next"], "not finished: continue where it was")


class SectionStateTests(TestCase):
    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def test_green_tick_needs_reading_and_most_questions(self):
        from .progress import needed

        self.assertEqual([needed(n) for n in (0, 1, 2, 3, 4, 5, 10, 20)], [0, 1, 2, 3, 3, 4, 7, 14], "at least 70%, rounded up")
        s = self.section
        self.client.post(f"/api/v1/nodes/{s.id}/progress/", {"percent": 100, "done": True}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        questions = list(Question.objects.filter(node=s, is_archived=False))
        if questions:
            self.assertIn(s.id, data["read_ids"])
            self.assertNotIn(s.id, data["done_ids"], "only read: no green tick yet")
            for q in questions[: needed(len(questions))]:
                self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.filter(is_correct=False).first().id}, format="json")
            data = self.client.get("/api/v1/books/math-1/").data
        self.assertIn(s.id, data["done_ids"], "wrong answers count too")
        self.assertNotIn(s.id, data["read_ids"])

    def test_tests_alone_give_half_and_reading_then_finishes(self):
        from .progress import needed

        s = self.section
        questions = list(Question.objects.filter(node=s, is_archived=False))
        self.assertTrue(questions)
        for q in questions[: needed(len(questions))]:
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertIn(s.id, data["read_ids"], "tests alone: half, like reading alone")
        self.assertNotIn(s.id, data["done_ids"])
        self.client.post(f"/api/v1/nodes/{s.id}/progress/", {"percent": 100, "done": True}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertIn(s.id, data["done_ids"], "both: green tick")

    def test_questions_and_cards_name_their_chapter(self):
        qs = self.client.get(f"/api/v1/nodes/{self.section.id}/questions/").data["questions"]
        self.assertTrue(qs)
        self.assertEqual({q["chapter_number"] for q in qs}, {1}, "«فصل ۱، …» above the counter")
        cards = self.client.get(f"/api/v1/nodes/{self.section.id}/flashcards/").data["flashcards"]
        self.assertTrue(all(c["chapter_number"] == 1 for c in cards))

    def test_chapter_end_says_what_is_left_and_book_has_a_share_link(self):
        from apps.catalog.models import ShareSettings

        last = list(self.chapter.get_children())[-1]
        end = self.client.get(f"/api/v1/nodes/{last.id}/").data["chapter_end"]
        self.assertIn(end["progress"]["state"], ("notes", "tests"))
        self.assertGreater(end["progress"]["tests_left"] + end["progress"]["notes_left"], 0)
        for s in self.chapter.get_children():
            self.client.post(f"/api/v1/nodes/{s.id}/progress/", {"percent": 100, "done": True}, format="json")
        for q in Question.objects.filter(node__path__startswith=self.chapter.path, is_archived=False):
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        end = self.client.get(f"/api/v1/nodes/{last.id}/").data["chapter_end"]
        self.assertEqual(end["progress"], {"state": "complete", "tests_left": 0, "notes_left": 0})
        self.assertEqual(self.client.get("/api/v1/books/math-1/").data["share_link"], "")
        ShareSettings.objects.create(default_link="https://t.me/example")
        self.assertEqual(self.client.get("/api/v1/books/math-1/").data["share_link"], "https://t.me/example")
        ContentNode.objects.filter(slug="math-1").update(share_link="https://example.com/math-1")
        self.assertEqual(self.client.get("/api/v1/books/math-1/").data["share_link"], "https://example.com/math-1", "the book's own link wins")

    def test_too_few_tests_leave_the_circle_empty(self):
        from .progress import needed

        s = self.section
        questions = list(Question.objects.filter(node=s, is_archived=False))
        if needed(len(questions)) < 2:
            self.skipTest("the sample section has too few questions")
        q = questions[0]
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertNotIn(s.id, data["read_ids"])
        self.assertNotIn(s.id, data["done_ids"])


    def test_extra_tests_do_not_count_toward_progress(self):
        from .progress import core, needed

        self.assertEqual(core([(1, False), (2, True)]), [1])
        self.assertEqual(core([(1, True), (2, True)]), [1, 2], "all marked extra: they all count")
        s = self.section
        questions = list(Question.objects.filter(node=s, is_archived=False).order_by("id"))
        self.assertGreaterEqual(len(questions), 2)
        core_q, extras = questions[:1], questions[1:]
        Question.objects.filter(id__in=[q.id for q in extras]).update(is_extra=True)
        listed = self.client.get(f"/api/v1/nodes/{s.id}/questions/").data["questions"]
        self.assertEqual({q["id"] for q in listed if q["extra"]}, {q.id for q in extras}, "extras are still sent, marked")
        for q in extras:
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertNotIn(s.id, data["read_ids"], "only extra tests answered: nothing yet")
        self.client.post(f"/api/v1/questions/{core_q[0].id}/answer/", {"choice_id": core_q[0].choices.first().id}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertIn(s.id, data["read_ids"], "the core test counts")
        self.assertEqual(needed(1), 1)

    def test_role_round_trips_through_the_chapter_file(self):
        from apps.catalog.exporter import export_chapter
        from apps.catalog.importer import parse_chapter

        q = Question.objects.filter(node=self.section, is_archived=False).first()
        Question.objects.filter(id=q.id).update(is_extra=True)
        text = export_chapter(self.chapter)
        self.assertIn("نقش: تکمیلی", text)
        parsed = parse_chapter(text)
        self.assertFalse(parsed.errors, parsed.errors)
        flags = {pq.slug: pq.is_extra for sec in parsed.sections for pq in sec.questions}
        self.assertTrue(flags[q.slug])
        self.assertEqual(sum(flags.values()), 1)


    def test_book_flashcards_come_only_from_finished_sections(self):
        from apps.learning.models import Flashcard

        from .progress import needed

        book = ContentNode.objects.get(slug="math-1")
        s = self.section
        cards = Flashcard.objects.filter(node=s, is_archived=False).count()
        if not cards:
            self.skipTest("the sample section has no flashcards")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertEqual(data["done_card_count"], 0)
        self.assertEqual(self.client.get(f"/api/v1/nodes/{book.id}/flashcards/?done=1").data["flashcards"], [])
        self.client.post(f"/api/v1/nodes/{s.id}/progress/", {"percent": 100, "done": True}, format="json")
        qs = list(Question.objects.filter(node=s, is_archived=False))
        for q in qs[: needed(len(qs))]:
            self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json")
        data = self.client.get("/api/v1/books/math-1/").data
        self.assertIn(s.id, data["done_ids"])
        self.assertEqual(data["done_card_count"], cards)
        got = self.client.get(f"/api/v1/nodes/{data['id']}/flashcards/?done=1").data["flashcards"]
        self.assertEqual({c["node_id"] for c in got}, {s.id}, "only the green section's cards")


    def test_linked_cards_open_and_wrong_answers_bring_them_to_today(self):
        from apps.learning.models import Flashcard

        from .models import FlashcardReview

        q = Question.objects.filter(flashcards__isnull=False, is_archived=False, node__path__startswith=self.chapter.path).first()
        card = q.flashcards.first()
        wrong = q.choices.filter(is_correct=False).first()
        r = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json").data
        self.assertEqual(r["cards_queued"], q.flashcards.count())
        self.assertTrue(FlashcardReview.objects.filter(flashcard=card, due_at__lte=timezone.now()).exists())
        self.assertIn(card.id, [c["id"] for c in self.client.get("/api/v1/me/flashcards/due/").data["flashcards"]], "in «مرور امروز»")
        again = self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json").data
        self.assertEqual(again["cards_queued"], 0, "already due: not counted twice")
        book = r["book_id"]
        cards = self.client.get(f"/api/v1/nodes/{book}/flashcards/?ids={card.id}").data["flashcards"]
        self.assertEqual([c["id"] for c in cards], [card.id])
        self.assertIn(q.id, cards[0]["question_ids"])
        qs = self.client.get(f"/api/v1/nodes/{book}/questions/?ids={q.id}").data["questions"]
        self.assertEqual([x["id"] for x in qs], [q.id], "«تست‌های این نکته»")
        self.assertTrue(Flashcard.objects.filter(pk=card.pk).exists())


class StudyTimeTests(TestCase):
    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def test_seconds_add_up_exactly_and_are_checked(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models import StudyTime

        for _ in range(10):  # ten chunks of 5 minutes 20 seconds
            self.client.post("/api/v1/me/time/", {"entries": [{"node_id": self.section.id, "kind": "read", "seconds": 320}]}, format="json")
        self.assertEqual(StudyTime.objects.get().seconds, 3200, "exact: no second lost to rounding")
        old = (timezone.localdate() - timedelta(days=90)).isoformat()
        r = self.client.post("/api/v1/me/time/", {"entries": [
            {"node_id": self.paid_section.id, "kind": "read", "seconds": 60, "day": old},
            {"node_id": self.section.id, "kind": "nonsense", "seconds": 60},
            {"node_id": self.section.id, "kind": "quiz", "seconds": 99999},
        ]}, format="json").data
        self.assertEqual(r["added"], 15 * 60, "too old and unknown kinds dropped; one chunk is capped")
        mine = self.client.get("/api/v1/books/math-1/").data["mine"]
        self.assertEqual(mine["time_seconds"], 3200 + 900)
        self.assertEqual(mine["chapter_seconds"][str(self.chapter.id)], 3200 + 900)
        self.assertEqual(self.client.get("/api/v1/me/stats/").data["time"]["week_seconds"], 4100)

    def test_a_report_sent_twice_counts_once(self):
        from .models import StudyTime

        body = {"id": "r-1234567890", "entries": [{"node_id": self.section.id, "kind": "read", "seconds": 60}]}
        self.assertEqual(self.client.post("/api/v1/me/time/", body, format="json").data["added"], 60)
        again = self.client.post("/api/v1/me/time/", body, format="json").data
        self.assertEqual((again["added"], again.get("repeated")), (0, True))
        self.assertEqual(StudyTime.objects.get().seconds, 60)
        body["id"] = "r-0987654321"
        self.client.post("/api/v1/me/time/", body, format="json")
        self.assertEqual(StudyTime.objects.get().seconds, 120, "a new report is added")

    def test_owner_sees_each_learner(self):
        from django.urls import reverse

        self.client.post("/api/v1/me/time/", {"entries": [{"node_id": self.section.id, "kind": "read", "seconds": 75}]}, format="json")
        admin = User.objects.create_superuser("09120000099", "pw-123456")
        from django.test import Client

        c = Client()
        c.force_login(admin)
        url = reverse("admin:study_studytime_changelist")
        self.assertContains(c.get(url), self.user.phone)
        self.assertContains(c.get(url, {"user": self.user.id}), "۱ دقیقه و ۱۵ ثانیه")
        self.assertContains(c.get(url, {"book": "math-1"}), self.section.title)


class NeedsReviewTests(TestCase):
    """«نیاز به مرور»: sections with wrong answers still open, then sections finished long ago."""

    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def _needs(self):
        from django.core.cache import cache

        cache.clear()
        return self.client.get("/api/v1/me/today/").data["needs_review"]

    def test_wrong_answer_then_right(self):
        q = Question.objects.filter(node=self.section, is_archived=False).first()
        wrong = q.choices.filter(is_correct=False).first()
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": wrong.id}, format="json")
        needs = self._needs()
        self.assertEqual(needs["items"][0]["id"], self.section.id)
        self.assertEqual(needs["items"][0]["reason"], "mistakes")
        self.assertEqual(needs["items"][0]["mistakes"], 1)
        self.assertEqual(needs["items"][0]["question_ids"], [q.id])
        right = q.choices.filter(is_correct=True).first()
        self.client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": right.id}, format="json")
        self.assertEqual(self._needs()["items"], [])

    def test_old_section_until_opened_again(self):
        from datetime import timedelta

        from .models import ChapterReview, SectionProgress

        self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"percent": 100, "done": True}, format="json")
        self.assertEqual(self._needs()["items"], [])  # just read
        SectionProgress.objects.filter(node=self.section).update(updated_at=timezone.now() - timedelta(days=40))
        self.assertFalse(ChapterReview.objects.filter(is_archived=False).exists())
        item = self._needs()["items"][0]
        self.assertEqual((item["id"], item["reason"]), (self.section.id, "old"))
        self.assertGreaterEqual(item["days"], 40)
        # In a chapter review cycle: asked for there, not here.
        cycle = ChapterReview.objects.create(user=self.user, chapter=self.chapter, book=self.chapter.get_parent(),
                                             finished_at=timezone.now(), due_on=timezone.localdate() + timedelta(days=5))
        self.assertEqual(self._needs()["items"], [])
        cycle.is_archived = True
        cycle.save()
        # Opened again: off the list at once (no waiting for the cache).
        self.client.get("/api/v1/me/today/")
        self.client.post(f"/api/v1/nodes/{self.section.id}/progress/", {"percent": 10, "position": 10, "mode": "full"}, format="json")
        self.assertEqual(self.client.get("/api/v1/me/today/").data["needs_review"]["items"], [])

    def test_locked_sections_are_not_suggested(self):
        from datetime import timedelta

        from .models import SectionProgress

        SectionProgress.objects.create(user=self.user, node=self.paid_section, book=self.chapter.get_parent(), percent=100, is_done=True)
        SectionProgress.objects.filter(node=self.paid_section).update(updated_at=timezone.now() - timedelta(days=60))
        self.assertEqual(self._needs()["items"], [])


class KnownWordsTests(TestCase):
    setUp = StudyTests.setUp
    tearDown = StudyTests.tearDown

    def test_mark_unmark_and_private(self):
        from .models import WordKnown

        url = "/api/v1/books/math-1/words/me/"
        self.assertEqual(self.client.get(url).data["known"], [])
        self.assertEqual(self.client.post(url, {"term": "حد", "known": True}, format="json").data["known"], ["حد"])
        self.client.post(url, {"terms": ["پیوستگی", "مشتق"], "known": True}, format="json")
        self.assertEqual(sorted(self.client.get(url).data["known"]), ["حد", "مشتق", "پیوستگی"])
        self.client.post(url, {"term": "حد", "known": False}, format="json")
        self.assertNotIn("حد", self.client.get(url).data["known"])
        self.assertTrue(WordKnown.objects.filter(term="حد", known=False).exists())  # kept, not deleted
        self.assertEqual(APIClient().get(url).status_code, 401)
        other = User.objects.create_user("09120000009")
        _, token = DeviceSession.start(other, "x")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.get(url).data["known"], [])
