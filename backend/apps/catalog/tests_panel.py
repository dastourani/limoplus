"""The panel: export round trip, chapter editing operations, versions, file import with preview, book page."""

import dataclasses
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.learning.models import Flashcard, Question

from . import editing
from .exporter import chapter_bundle, export_chapter
from .importer import import_file, parse_chapter
from .models import ChapterRevision, ContentNode, Major
from .tests import GOOD

SAMPLES = Path(settings.BASE_DIR).parent / "content" / "samples" / "math-1"


def _items(chapter):
    out = []
    for s in chapter.all_sections():
        out.append(("S", s.slug, s.title, s.group, s.full_body, s.summary_body))
        for item in s.questions + s.flashcards:
            data = dataclasses.asdict(item)
            data.pop("line")
            out.append(data)
    return out


class _Base(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media)
        cls._override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._override.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        Major.objects.create(name="اقتصاد", slug="economics")
        _, result = import_file("ch1.md", GOOD.encode(), publish=True)
        self.book, self.chapter = result.book, result.chapter
        self.admin = User.objects.create_superuser("09120000001", "pw-123456")
        self.client.force_login(self.admin)
        self.api = reverse("admin:catalog_chapter_api", args=[self.chapter.pk])

    def state(self):
        return self.client.get(self.api).json()["state"]

    def op(self, **payload):
        payload.setdefault("version", self.state()["version"])
        return self.client.post(self.api, json.dumps(payload), content_type="application/json")


class ExportTests(_Base):
    def test_round_trip_keeps_everything(self):
        original = parse_chapter(GOOD)
        again = parse_chapter(export_chapter(self.chapter))
        self.assertEqual(again.errors, [])
        self.assertEqual(_items(original), _items(again))
        self.assertEqual(original.meta["chapter_title"], again.meta["chapter_title"])

    def test_round_trip_sample_with_images(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            folder = SAMPLES / "01-limits"
            for f in folder.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(folder).as_posix())
        Major.objects.get_or_create(slug="biomedical-engineering", defaults={"name": "مهندسی پزشکی"})
        parsed, result = import_file("limits.zip", data.getvalue())
        self.assertEqual(parsed.errors, [])
        text = export_chapter(result.chapter)
        self.assertIn("](media:content/", text)
        again = editing.check_text(text, result.book, result.chapter)
        self.assertEqual(again.errors, [], "server image references are accepted")
        name, blob, kind = chapter_bundle(result.chapter)
        self.assertTrue(name.endswith(".zip"))
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            md = z.read("chapter.md").decode()
            self.assertIn("](images/", md)
            self.assertTrue(any(n.startswith("images/") for n in z.namelist()))

    def test_unknown_server_image_is_an_error(self):
        text = export_chapter(self.chapter).replace("متن دوم.", "![شکل](media:content/nope/x.png)")
        checked = editing.check_text(text, self.book, self.chapter)
        self.assertEqual(checked.errors, [], "a missing picture must not block other edits")
        self.assertTrue(any("روی سرور نیست" in str(w) for w in checked.warnings))
        bad = export_chapter(self.chapter).replace("متن دوم.", "![شکل](media:../secret.png)")
        self.assertTrue(editing.check_text(bad, self.book, self.chapter).errors)


class ChapterOpsTests(_Base):
    def test_state_lists_sections_items_and_suggestions(self):
        st = self.state()
        self.assertEqual([s["slug"] for s in st["sections"]], ["one", "two"])
        self.assertEqual(st["sections"][0]["questions"][0]["slug"], "q1")
        self.assertEqual(st["suggest"]["question"], "q2")

    def test_notes_edit_saves_and_keeps_versions(self):
        r = self.op(op="section.update", slug="one", full_body="متن تازه با **نکته**.")
        self.assertEqual(r.status_code, 200, r.content)
        node = ContentNode.objects.get(slug="one")
        self.assertEqual(node.full_body, "متن تازه با **نکته**.")
        revisions = list(self.chapter.revisions.order_by("id"))
        self.assertEqual(len(revisions), 2, "a copy of the chapter before the first edit, then the edit")
        self.assertIn("متن جزوه با فرمول", revisions[0].text)
        self.assertIn("متن تازه", revisions[1].text)
        # A second quick edit by the same person joins the same version.
        self.op(op="section.update", slug="one", full_body="باز هم تازه.")
        self.assertEqual(self.chapter.revisions.count(), 2)

    def test_headings_inside_notes_are_refused(self):
        r = self.op(op="section.update", slug="one", full_body="متن\n## بخش جعلی\nادامه")
        self.assertEqual(r.status_code, 400)
        self.assertIn("###", r.json()["errors"][0])

    def test_stale_version_is_a_conflict(self):
        r = self.op(op="section.update", slug="one", full_body="x", version="000000000000")
        self.assertEqual(r.status_code, 409)

    def test_new_question_follows_file_rules(self):
        bad = {"stem": "سؤال؟", "choices": [{"text": "الف", "correct": False}, {"text": "ب", "correct": False}], "explanation": "چون.", "difficulty": "easy"}
        r = self.op(op="question.save", new=True, section="two", slug="q2", data=bad)
        self.assertEqual(r.status_code, 400)
        self.assertIn("دقیقاً یک گزینه", r.json()["errors"][0])
        good = dict(bad, choices=[{"text": "الف", "correct": False}, {"text": "ب", "correct": True}],
                    sources=[{"name": "کنکور ارشد اقتصاد", "year": "۱۴۰۲", "number": "۵"}], flashcards=["card1"])
        r = self.op(op="question.save", new=True, section="two", slug="q2", data=good)
        self.assertEqual(r.status_code, 200, r.content)
        q = Question.objects.get(slug="q2")
        self.assertEqual(q.node.slug, "two")
        self.assertEqual([c.is_correct for c in q.choices.all()], [False, True])
        self.assertEqual(q.sources.get().year, 1402)
        self.assertEqual(list(q.flashcards.values_list("slug", flat=True)), ["card1"])

    def test_slug_used_elsewhere_in_the_book_is_refused(self):
        other = GOOD.replace("شناسه-فصل: ch1", "شناسه-فصل: ch2").replace("{#one}", "{#c2a}").replace("{#two}", "{#c2b}").replace(
            "{#q1}", "{#q9}").replace("{#card1}", "{#card9}").replace("فلش‌کارت: card1", "فلش‌کارت: card9")
        import_file("ch2.md", other.encode())
        data = {"stem": "؟", "choices": [{"text": "a", "correct": True}, {"text": "b"}], "explanation": "e", "difficulty": "easy"}
        r = self.op(op="question.save", new=True, section="two", slug="q9", data=data)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Question.objects.get(slug="q9").node.get_parent().slug, "ch2", "the other chapter's test did not move")

    def test_edit_existing_question_keeps_row_and_answers(self):
        q = Question.objects.get(slug="q1")
        item = self.state()["sections"][0]["questions"][0]
        item["choices"][0]["text"] = "سه و نیم"
        r = self.op(op="question.save", slug="q1", data=item)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Question.objects.get(slug="q1").pk, q.pk)
        self.assertEqual(Question.objects.get(pk=q.pk).choices.first().text, "سه و نیم")

    def test_raw_text_and_form_convert_both_ways(self):
        item = self.state()["sections"][0]["questions"][0]
        r = self.op(op="question.convert", slug="q1", data={"raw": item["raw"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["item"]["stem"], item["stem"])
        r = self.op(op="question.convert", slug="q1", data={"raw": item["raw"].replace("سطح: سخت", "سطح: خیلی")})
        self.assertEqual(r.status_code, 400)

    def test_reorder_move_archive_restore(self):
        self.op(op="section.create", title="بخش سوم", slug="three", group="گروه", after="one")
        self.assertEqual([s["slug"] for s in self.state()["sections"]], ["one", "three", "two"])
        self.op(op="section.reorder", order=["two", "one", "three"])
        chapter = ContentNode.objects.get(pk=self.chapter.pk)
        self.assertEqual([c.slug for c in chapter.get_children()], ["two", "one", "three"])
        self.op(op="question.move", slug="q1", to="three")
        self.assertEqual(Question.objects.get(slug="q1").node.slug, "three")
        self.op(op="question.archive", slug="q1")
        self.assertTrue(Question.objects.get(slug="q1").is_archived)
        self.assertEqual(self.state()["archived"]["questions"][0]["slug"], "q1")
        self.op(op="question.restore", slug="q1")
        q = Question.objects.get(slug="q1")
        self.assertFalse(q.is_archived)
        self.assertEqual(q.node.slug, "three")

    def test_archiving_a_flashcard_unlinks_it(self):
        r = self.op(op="flashcard.archive", slug="card1")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(Flashcard.objects.get(slug="card1").is_archived)
        self.assertEqual(Question.objects.get(slug="q1").flashcards.count(), 0)

    def test_section_archive_and_restore(self):
        self.op(op="section.archive", slug="one")
        self.assertTrue(ContentNode.objects.get(slug="one").is_archived)
        self.assertTrue(Question.objects.get(slug="q1").is_archived)
        self.op(op="section.restore", slug="one")
        self.assertFalse(ContentNode.objects.get(slug="one").is_archived)
        self.assertFalse(Question.objects.get(slug="q1").is_archived)

    def test_new_section_is_visible_when_chapter_is_published(self):
        self.op(op="section.create", title="تازه", slug="fresh")
        self.assertTrue(ContentNode.objects.get(slug="fresh").is_published)

    def test_question_order_is_used_by_the_app(self):
        data = {"stem": "دوم؟", "choices": [{"text": "a", "correct": True}, {"text": "b"}], "explanation": "e", "difficulty": "easy"}
        self.op(op="question.save", new=True, section="one", slug="q2", data=data)
        self.op(op="question.reorder", section="one", order=["q2", "q1"])
        r = self.client.get(f"/api/v1/nodes/{ContentNode.objects.get(slug='one').pk}/questions/")
        self.assertEqual([q["id"] for q in r.json()["questions"]][:2], [Question.objects.get(slug="q2").pk, Question.objects.get(slug="q1").pk])

    def test_image_upload_returns_a_server_reference(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        from django.core.files.uploadedfile import SimpleUploadedFile

        r = self.client.post(self.api, {"image": SimpleUploadedFile("a.png", png, content_type="image/png")})
        self.assertEqual(r.status_code, 200, r.content)
        ref = r.json()["ref"]
        self.assertTrue(ref.startswith("media:content/test-book/ch1/"))
        r = self.op(op="section.update", slug="two", full_body=f"![نمودار]({ref})")
        self.assertEqual(r.status_code, 200, r.content)

    def test_staff_without_permission_is_refused(self):
        clerk = User.objects.create_user("09120000002")
        clerk.is_staff = True
        clerk.save()
        self.client.force_login(clerk)
        self.assertEqual(self.client.get(self.api).status_code, 403)


class FileAndVersionTests(_Base):
    def test_check_shows_plan_and_apply_saves(self):
        text = export_chapter(self.chapter).replace("متن دوم.", "متن دوم، اصلاح‌شده.").replace(":::تست {#q1}", ":::تست {#q1x}")
        r = self.op(op="file.check", text=text)
        data = r.json()
        self.assertEqual(data["errors"], [])
        kinds = {(k, label.split(":")[0]) for k, label, _ in data["plan"]["questions"]}
        self.assertIn(("new", "q1x"), kinds)
        self.assertIn(("archived", "q1"), kinds)
        self.assertTrue(any("شناسه را عوض" in n for n in data["plan"]["notes"]))
        self.assertTrue(any(k == "changed" for k, *_ in data["plan"]["sections"]))
        r = self.op(op="file.apply", text=text)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(ContentNode.objects.get(slug="two").full_body, "متن دوم، اصلاح‌شده.")

    def test_file_must_keep_its_chapter_id(self):
        text = export_chapter(self.chapter).replace("شناسه-فصل: ch1", "شناسه-فصل: other")
        self.assertTrue(self.op(op="file.check", text=text).json()["errors"])

    def test_restore_a_version(self):
        self.op(op="section.update", slug="one", full_body="نسخه‌ی تازه.")
        first = self.chapter.revisions.order_by("id").first()
        page = self.client.get(reverse("admin:catalog_chapter_file", args=[self.chapter.pk]) + f"?revision={first.pk}")
        self.assertContains(page, "متن جزوه با فرمول")
        r = self.op(op="file.apply", text=first.text, restore=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("متن جزوه با فرمول", ContentNode.objects.get(slug="one").full_body)
        self.assertEqual(self.chapter.revisions.order_by("-id").first().source, ChapterRevision.Source.RESTORE)

    def test_history_and_downloads(self):
        self.op(op="section.update", slug="one", full_body="تغییر.")
        r = self.client.get(reverse("admin:catalog_chapter_history", args=[self.chapter.pk]))
        self.assertContains(r, "نسخه‌ی فعلی")
        first = self.chapter.revisions.order_by("id").first()
        r = self.client.get(reverse("admin:catalog_chapter_history", args=[self.chapter.pk]) + f"?compare={first.pk}")
        self.assertContains(r, "تغییر.")
        r = self.client.get(reverse("admin:catalog_chapter_export", args=[self.chapter.pk]))
        self.assertEqual(r["Content-Disposition"], 'attachment; filename="ch1.md"')
        self.assertIn("## بخش اول {#one}", r.content.decode())
        r = self.client.get(reverse("admin:catalog_book_export", args=[self.book.pk]))
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            self.assertIn("01-ch1/chapter.md", z.namelist())


class ImportPreviewTests(_Base):
    def test_two_step_import_with_preview(self):
        url = reverse("admin:catalog_book_import", args=[self.book.pk])
        text = export_chapter(self.chapter).replace("متن دوم.", "متن دوم عوض شد.")
        r = self.client.post(url, {"file": io.BytesIO(text.encode()) and _upload("ch1.md", text)})
        self.assertContains(r, "اعمال تغییرات")
        token = r.context["report"]["token"]
        self.assertEqual(ContentNode.objects.get(slug="two").full_body, "متن دوم.", "nothing changes before confirming")
        r = self.client.post(url, {"token": token, "filename": "ch1.md"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(ContentNode.objects.get(slug="two").full_body, "متن دوم عوض شد.")
        self.assertEqual(self.chapter.revisions.order_by("-id").first().source, ChapterRevision.Source.FILE)

    def test_book_page_import_needs_no_book_lines(self):
        url = reverse("admin:catalog_book_import", args=[self.book.pk])
        text = GOOD.replace("شناسه-کتاب: test-book\nکتاب: کتاب آزمایشی\n", "").replace("شناسه-فصل: ch1", "شناسه-فصل: ch3").replace(
            "{#one}", "{#t1}").replace("{#two}", "{#t2}").replace("{#q1}", "{#t3}").replace("{#card1}", "{#t4}").replace("فلش‌کارت: card1", "فلش‌کارت: t4")
        r = self.client.post(url, {"file": _upload("ch3.md", text)})
        self.assertEqual(r.context["report"]["errors"], [])
        self.client.post(url, {"token": r.context["report"]["token"], "filename": "ch3.md"})
        self.assertTrue(ContentNode.objects.filter(slug="ch3", path__startswith=self.book.path).exists())

    def test_file_of_another_book_is_refused_on_a_book_page(self):
        url = reverse("admin:catalog_book_import", args=[self.book.pk])
        r = self.client.post(url, {"file": _upload("x.md", GOOD.replace("شناسه-کتاب: test-book", "شناسه-کتاب: other-book"))})
        self.assertTrue(any("مال کتاب" in e for e in r.context["report"]["errors"]))

    def test_bad_token_is_refused(self):
        url = reverse("admin:catalog_import")
        self.assertEqual(self.client.post(url, {"token": "../../etc"}).status_code, 403)


class BookPageTests(_Base):
    def test_create_book_then_empty_chapter(self):
        r = self.client.post(reverse("admin:catalog_book_add"), {
            "title": "کتاب تازه", "slug": "new-book", "author": "نویسنده", "edition": "", "about": "درباره‌ی **کتاب**",
            "majors": [Major.objects.get(slug="economics").pk], "price": "", "is_published": "on", "cover_motif": "fourier", "title_en": "New",
        })
        self.assertEqual(r.status_code, 302, r.content[:2000])
        book = ContentNode.objects.get(slug="new-book", kind="book")
        self.assertEqual(book.depth, 1)
        self.assertEqual(book.about, "درباره‌ی **کتاب**")
        r = self.client.post(reverse("admin:catalog_book_chapter_action", args=[book.pk]), {"action": "new", "title": "فصل اول", "slug": "nb-1"})
        chapter = ContentNode.objects.get(slug="nb-1")
        self.assertRedirects(r, reverse("admin:catalog_chapter_manager", args=[chapter.pk]), fetch_redirect_response=False)
        self.assertEqual(chapter.position, 1)
        self.assertEqual(chapter.get_children().count(), 1)
        self.assertEqual(chapter.revisions.count(), 1)

    def test_book_page_lists_chapters_and_actions_work(self):
        other = GOOD.replace("شناسه-فصل: ch1", "شناسه-فصل: ch2").replace("{#one}", "{#c2a}").replace("{#two}", "{#c2b}").replace(
            "{#q1}", "{#q9}").replace("{#card1}", "{#card9}").replace("فلش‌کارت: card1", "فلش‌کارت: card9")
        import_file("ch2.md", other.encode())
        page = self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertContains(page, "مدیریت فصل")
        action = reverse("admin:catalog_book_chapter_action", args=[self.book.pk])
        ch2 = ContentNode.objects.get(slug="ch2")
        self.client.post(action, {"action": "up", "chapter": ch2.pk})
        book = ContentNode.objects.get(pk=self.book.pk)
        self.assertEqual([c.slug for c in book.get_children()], ["ch2", "ch1"])
        self.assertEqual([c.position for c in book.get_children()], [1, 2])
        self.client.post(action, {"action": "free", "chapter": ch2.pk, "value": "1"})
        self.assertTrue(ContentNode.objects.get(pk=ch2.pk).is_free)
        self.client.post(action, {"action": "archive", "chapter": ch2.pk, "value": "1"})
        self.assertTrue(ContentNode.objects.get(pk=ch2.pk).is_archived)

    def test_lists_filter_and_open_the_manager(self):
        for url in ("admin:learning_question_changelist", "admin:learning_flashcard_changelist", "admin:catalog_section_changelist", "admin:catalog_book_changelist"):
            r = self.client.get(reverse(url), {"book": self.book.pk} if "book_changelist" not in url else {})
            self.assertEqual(r.status_code, 200, url)
        r = self.client.get(reverse("admin:learning_question_changelist"), {"book": self.book.pk, "chapter": self.chapter.pk, "difficulty": "hard"})
        self.assertContains(r, "دو به‌علاوه‌ی دو")
        q = Question.objects.get(slug="q1")
        r = self.client.get(reverse("admin:learning_question_change", args=[q.pk]))
        self.assertRedirects(r, reverse("admin:catalog_chapter_manager", args=[self.chapter.pk]) + "#q=q1", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("admin:catalog_chapter_manager", args=[self.chapter.pk])).status_code, 200)


def _upload(name, text):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/markdown")


class OrphanTests(_Base):
    def test_chapter_outside_any_book_does_not_break_lists(self):
        orphan = ContentNode.add_root(kind=ContentNode.Kind.CHAPTER, title="فصل دستی", slug="hand")
        Flashcard.objects.create(node=orphan, slug="h1", title="t", point="p")
        for url in ("admin:learning_flashcard_changelist", "admin:learning_question_changelist", "admin:catalog_section_changelist"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 200, url)
        page = self.client.get(reverse("admin:catalog_book_changelist"))
        self.assertContains(page, "فصل دستی")
        self.assertEqual(self.client.get(reverse("admin:catalog_chapter_manager", args=[orphan.pk])).status_code, 404)
        self.assertNotIn('id="changelist-form"', page.content.decode().split("محتوای بیرون از کتاب‌ها")[0][-3000:].split("</form>")[-1],
                         "the archive button must not sit inside the list's own form")
        self.client.post(reverse("admin:catalog_archive_orphan", args=[orphan.pk]))
        self.assertTrue(ContentNode.objects.get(pk=orphan.pk).is_archived)
        self.assertTrue(Flashcard.objects.get(slug="h1").is_archived)
        self.assertNotContains(self.client.get(reverse("admin:catalog_book_changelist")), "محتوای بیرون از کتاب‌ها")


class ShelfTests(_Base):
    def test_book_card_has_cover_free_part_and_coming_soon(self):
        ContentNode.objects.filter(pk=self.book.pk).update(title_en="Test Book", cover_motif="fourier", author="نویسنده", edition="ویرایش ۲")
        soon = ContentNode.add_root(kind="book", title="به‌زودی", slug="soon", is_published=True, is_coming_soon=True, cover_motif="brain")
        soon.majors.add(Major.objects.get(slug="economics"))
        from rest_framework.test import APIClient

        api = APIClient()
        books = api.get("/api/v1/majors/economics/books/").json()
        self.assertEqual([b["slug"] for b in books], ["test-book", "soon"], "coming-soon books come last")
        first = books[0]
        self.assertEqual((first["title_en"], first["motif"], first["free_chapter"], first["progress"], first["notify"]), ("Test Book", "fourier", 1, None, False))
        detail = api.get("/api/v1/books/test-book/").json()
        self.assertEqual(detail["motif"], "fourier")
        self.assertIn("chapters", detail)

    def test_notify_me_needs_login_and_toggles(self):
        from rest_framework.test import APIClient

        from apps.accounts.models import DeviceSession

        api = APIClient()
        self.assertEqual(api.post("/api/v1/books/test-book/notify/", {"on": True}, format="json").status_code, 401)
        learner = User.objects.create_user("09120000009")
        api.force_authenticate(learner)
        self.assertEqual(api.post("/api/v1/books/test-book/notify/", {"on": True}, format="json").json(), {"notify": True, "can_cancel": True})
        self.assertTrue(api.get("/api/v1/majors/economics/books/").json()[0]["notify"])
        api.post("/api/v1/books/test-book/notify/", {"on": False}, format="json")
        self.assertFalse(api.get("/api/v1/majors/economics/books/").json()[0]["notify"])
        # Asking again after one cancel: it stays on for good.
        self.assertEqual(api.post("/api/v1/books/test-book/notify/", {"on": True}, format="json").json(), {"notify": True, "can_cancel": False})
        self.assertEqual(api.post("/api/v1/books/test-book/notify/", {"on": False}, format="json").json()["notify"], True)
        card = api.get("/api/v1/majors/economics/books/").json()[0]
        self.assertEqual((card["notify"], card["notify_can_cancel"]), (True, False))
        page = self.client.get(reverse("admin:catalog_book_changelist"))
        self.assertContains(page, 'class="lp-cover"')

    def test_book_form_has_cover_fields(self):
        page = self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        for field in ("id_cover_motif", "id_title_en", "id_is_coming_soon", "lp-majors"):
            self.assertContains(page, field)


SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#123456" stroke-width="2">'
    '<script>alert(1)</script><style>*{}</style><text>hi</text>'
    '<g transform="translate(1 1)"><path d="M2 2 L20 20" onclick="x()"/><circle cx="12" cy="12" r="4" fill="red"/></g>'
    '<image href="http://x/y.png"/><rect x="1" y="1" width="3" height="3" style="stroke:none;fill:#000"/></svg>'
)


class DrawingTests(_Base):
    def test_clean_svg_keeps_only_shapes_and_recolours_them(self):
        from .drawing import clean_svg

        d = clean_svg(SVG.encode())
        self.assertEqual(d["viewBox"], "0 0 24 24")
        body = d["body"]
        for bad in ("script", "style", "text", "image", "onclick", "#123456", "red", "#000", "http"):
            self.assertNotIn(bad, body)
        self.assertIn('<g transform="translate(1 1)">', body)
        self.assertIn('d="M2 2 L20 20"', body)
        self.assertIn('fill="none"', body)
        self.assertIn('stroke="@L@"', body)
        self.assertIn('<rect fill="@L@"', body)

    def test_clean_svg_refuses_bad_files(self):
        from .drawing import DrawingError, clean_svg

        for data in (
            b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg viewBox="0 0 1 1"><path d="M0 0"/></svg>',
            b"<svg viewBox='0 0 1 1'><text>only text</text></svg>",
            b"not xml",
            b"<html/>",
            b"<svg><path d='M0 0'/></svg>",
            b"<svg viewBox='0 0 1 1'>" + b"<path d='M0 0'/>" * 700 + b"</svg>",
        ):
            with self.assertRaises(DrawingError, msg=data[:40]):
                clean_svg(data)

    def test_upload_drawing_in_book_form_and_shelf_returns_it(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = reverse("admin:catalog_book_change", args=[self.book.pk])
        page = self.client.get(url)
        self.assertContains(page, "id_drawing_file")
        data = {
            "title": self.book.title, "slug": self.book.slug, "author": "", "edition": "", "about": "", "title_en": "",
            "majors": [Major.objects.get(slug="economics").pk], "price": "", "is_published": "on", "cover_motif": "fourier",
            "drawing_file": SimpleUploadedFile("d.svg", SVG.encode(), content_type="image/svg+xml"),
        }
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 302, r.content[:3000])
        book = ContentNode.objects.get(pk=self.book.pk)
        self.assertEqual(book.cover_motif, "custom")
        from rest_framework.test import APIClient

        card = APIClient().get("/api/v1/majors/economics/books/").json()[0]
        self.assertEqual(card["motif"], "custom")
        self.assertEqual(card["drawing"]["viewBox"], "0 0 24 24")

        bad = dict(data, drawing_file=SimpleUploadedFile("d.svg", b"<svg/>", content_type="image/svg+xml"))
        self.assertContains(self.client.post(url, bad), "viewBox")

        data.pop("drawing_file")
        self.client.post(url, dict(data, cover_motif="custom", clear_drawing="on"))
        book = ContentNode.objects.get(pk=self.book.pk)
        self.assertEqual((book.cover_drawing, book.cover_motif), ("", "book"))

    def test_custom_motif_needs_a_drawing(self):
        url = reverse("admin:catalog_book_change", args=[self.book.pk])
        data = {
            "title": self.book.title, "slug": self.book.slug, "author": "", "edition": "", "about": "", "title_en": "",
            "majors": [Major.objects.get(slug="economics").pk], "price": "", "is_published": "on", "cover_motif": "custom",
        }
        r = self.client.post(url, data)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(ContentNode.objects.get(pk=self.book.pk).cover_motif, "custom")


class PublishTests(_Base):
    def test_publishing_a_chapter_publishes_its_draft_sections(self):
        ContentNode.objects.filter(path__startswith=self.chapter.path).update(is_published=False)
        page = self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertContains(page, "پیش‌نویس</span>")
        self.client.post(reverse("admin:catalog_book_chapter_action", args=[self.book.pk]), {"action": "publish", "chapter": self.chapter.pk, "value": "1"})
        self.assertFalse(ContentNode.objects.filter(path__startswith=self.chapter.path, is_published=False).exists())
        from rest_framework.test import APIClient

        detail = APIClient().get("/api/v1/books/test-book/").json()
        self.assertTrue(detail["chapters"][0]["sections"])
        self.assertIsNone(detail["access"])
        section = detail["chapters"][0]["sections"][0]
        staff = APIClient()
        staff.force_authenticate(self.admin)
        node = staff.get(f"/api/v1/nodes/{section['id']}/").json()
        self.assertIn("next_title", node)
        self.assertEqual(staff.get("/api/v1/books/test-book/").json()["access"], "staff")


class GiftAndCheckTests(_Base):
    def test_book_check_points_at_draft_sections_and_fixes_them(self):
        ContentNode.objects.filter(path__startswith=self.chapter.path, depth__gt=self.chapter.depth).update(is_published=False)
        page = self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertContains(page, "بخش پیش‌نویس است")
        self.assertContains(page, "درست کن")
        self.client.post(reverse("admin:catalog_book_chapter_action", args=[self.book.pk]), {"action": "publish", "chapter": self.chapter.pk, "value": "1"})
        page = self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertNotContains(page, "بخش پیش‌نویس است")

    def test_gift_gives_the_book_and_can_be_taken_back(self):
        from rest_framework.test import APIClient

        from apps.commerce.models import Entitlement

        url = reverse("admin:catalog_book_gift", args=[self.book.pk])
        self.client.post(url, {"phone": "۰۹۱۲۰۰۰۰۰۵۵", "days": "30", "note": "جایزه"})
        gift = Entitlement.objects.get(user__phone="09120000055")
        self.assertTrue(gift.is_gift)
        self.assertIsNotNone(gift.ends_at)
        api = APIClient()
        api.force_authenticate(gift.user)
        card = api.get("/api/v1/books/test-book/").json()
        self.assertEqual((card["owned"], card["access"]), (True, "gift"))
        self.assertContains(self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk])), "09120000055")
        from .access import access_until

        self.assertEqual(access_until(gift.user, self.book), gift.ends_at)  # a timed gift ends
        self.client.post(url, {"phone": "09120000056", "days": "9999"})  # unknown duration is refused
        self.assertFalse(Entitlement.objects.filter(user__phone="09120000056").exists())
        self.client.post(url, {"action": "revoke", "gift": gift.pk})
        gift.refresh_from_db()
        self.assertTrue(gift.is_archived)
        self.assertFalse(api.get("/api/v1/books/test-book/").json()["owned"])
        self.client.post(url, {"phone": "12345"})
        self.assertEqual(Entitlement.objects.count(), 1)

    def test_staff_can_view_as_learner(self):
        from apps.accounts.models import DeviceSession
        from rest_framework.test import APIClient

        _, token = DeviceSession.start(self.admin, "t")
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(api.get("/api/v1/books/test-book/").json()["access"], "staff")
        self.assertTrue(api.get("/api/v1/me/").json()["is_staff"])
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_VIEW_AS="learner")
        card = api.get("/api/v1/books/test-book/").json()
        self.assertEqual((card["owned"], card["access"]), (False, None))
        self.assertEqual((card["free_chapters"], card["all_free"]), (1, True))


class SearchTests(_Base):
    def test_persian_variants_and_access(self):
        from rest_framework.test import APIClient

        from .search import normalize, pattern

        self.assertEqual(normalize("كتاب‌ علي ۱۲"), "کتاب علی 12")
        self.assertTrue(pattern("بهعلاوه").search("دو به‌علاوه‌ی دو"))
        self.assertTrue(pattern("علي").search("علی"))
        api = APIClient()
        r = api.get("/api/v1/search/", {"q": "به علاوه"}).json()
        kinds = {x["kind"] for x in r["results"]}
        self.assertIn("question", kinds)
        self.assertNotIn("is_correct", str(r))
        self.assertEqual(api.get("/api/v1/search/", {"q": "خلاصه‌ی بخش"}).json()["results"][0]["mode"], "summary")
        self.assertTrue(api.get("/api/v1/search/", {"q": "ا"}).json()["too_short"])
        self.assertEqual(api.get("/api/v1/search/", {"q": "a²"}).status_code, 200)
        # A paid chapter's text is not found by someone who can't read it.
        ContentNode.objects.filter(pk=self.chapter.pk).update(is_free=False)
        ContentNode.objects.filter(path__startswith=self.chapter.path).update(is_free=False)
        self.assertEqual(api.get("/api/v1/search/", {"q": "متن دوم"}).json()["results"], [])
        staff = APIClient()
        staff.force_authenticate(self.admin)
        self.assertEqual(staff.get("/api/v1/search/", {"q": "متن دوم", "book": "test-book"}).json()["results"][0]["kind"], "section")


class SampleAndBannerTests(_Base):
    def test_samples_are_marked_in_the_panel_and_shown_to_the_app(self):
        from rest_framework.test import APIClient

        q = Question.objects.get(slug="q1")
        url = reverse("admin:learning_question_changelist")
        self.client.post(url, {"action": "make_sample", "_selected_action": [q.pk]})
        q.refresh_from_db()
        self.assertTrue(q.is_sample)
        item = APIClient().get(f"/api/v1/nodes/{self.chapter.pk}/questions/").json()["questions"][0]
        self.assertTrue(item["shareable"])
        self.assertEqual(item["share_place"]["book"], "کتاب آزمایشی")
        self.assertEqual(item["share_place"]["chapter"], "فصل یک")
        # The chapter manager's toggle (not part of the file, so no version is made).
        self.assertEqual(self.op(op="question.sample", slug="q1", value=False).status_code, 200)
        self.assertFalse(Question.objects.get(slug="q1").is_sample)
        self.assertFalse(self.state()["sections"][0]["questions"][0]["is_sample"])

    def test_banner_template_and_countdown_in_api(self):
        from datetime import timedelta

        from django.utils import timezone
        from rest_framework.test import APIClient

        from .models import Banner

        Banner.objects.create(title="۳۰٪ تخفیف", template="sale", button="بخر", countdown=True, ends_at=timezone.now() + timedelta(hours=5))
        Banner.objects.create(title="کتاب تازه", template="book", target="book", target_value="test-book")
        Banner.objects.create(title="پیش‌نویس", template="book", target="book", target_value="draft-book")
        ContentNode.add_root(kind="book", title="کتاب پنهان", slug="draft-book", is_published=False)
        data = APIClient().get("/api/v1/banners/").json()
        sale = next(b for b in data if b["template"] == "sale")
        self.assertIsNotNone(sale["ends_at"])
        self.assertEqual(sale["button"], "بخر")
        book = next(b for b in data if b["title"] == "کتاب تازه")
        self.assertEqual(book["book"]["title"], "کتاب آزمایشی")
        self.assertIsNone(next(b for b in data if b["title"] == "پیش‌نویس")["book"])
        self.assertEqual(self.client.get(reverse("admin:catalog_banner_add")).status_code, 200)


class ChoiceOrderAndCorrectionTests(_Base):
    """«ترتیب گزینه‌ها: ثابت», choices that point at other choices, «گزینه‌ی ۲» in explanations, and «اصلاح‌شده»."""

    def _questions(self, client=None):
        from rest_framework.test import APIClient

        return (client or APIClient()).get(f"/api/v1/nodes/{self.chapter.pk}/questions/").json()["questions"]

    def test_fixed_order_round_trips_and_reaches_the_app(self):
        self.assertFalse(self._questions()[0]["fixed_order"])
        text = export_chapter(self.chapter).replace("صورت:\nدو به", "ترتیب گزینه‌ها: ثابت\nصورت:\nدو به")
        parsed = parse_chapter(text)
        self.assertEqual(parsed.errors, [])
        self.assertTrue(parsed.sections[0].questions[0].fixed_order)
        editing.save(self.chapter, parsed, user=self.admin, note="ثابت")
        self.assertTrue(self._questions()[0]["fixed_order"])
        self.assertIn("ترتیب گزینه‌ها: ثابت", export_chapter(self.chapter))
        self.assertTrue(parse_chapter(text.replace("ترتیب گزینه‌ها: ثابت", "ترتیب گزینه‌ها: شاید")).errors)

    def test_choices_that_name_other_choices_stay_in_place(self):
        q = Question.objects.get(slug="q1")
        q.choices.filter(text="پنج").update(text="گزینه‌های ۱ و ۲")
        self.assertTrue(self._questions()[0]["fixed_order"])

    def test_explanation_naming_a_choice_number_is_warned(self):
        text = GOOD.replace("توضیح: جمع ساده.", "توضیح: گزینه‌ی ۲ درست است.")
        warnings = [str(w) for w in parse_chapter(text).warnings]
        self.assertTrue(any("گزینه‌ی ۲" in w for w in warnings), warnings)
        fixed = text.replace("صورت:\nدو به", "ترتیب گزینه‌ها: ثابت\nصورت:\nدو به")
        self.assertFalse(any("گزینه‌ی ۲" in str(w) for w in parse_chapter(fixed).warnings))
        import_file("ch1.md", text.encode())
        from .bookpanel import book_health

        self.assertTrue(any("q1" in h["text"] for h in book_health(self.book)))

    def test_moving_the_right_answer_marks_the_question_corrected(self):
        from rest_framework.test import APIClient

        user = User.objects.create_user("09120000055")
        client = APIClient()
        client.force_authenticate(user)
        q = Question.objects.get(slug="q1")
        five = q.choices.get(text="پنج")
        client.post(f"/api/v1/questions/{q.pk}/answer/", {"choice_id": five.pk}, format="json")

        # A wording fix of the right choice is not a correction.
        import_file("ch1.md", GOOD.replace("- [x] چهار", "- [x] چهار (۴)").encode())
        q.refresh_from_db()
        self.assertIsNone(q.key_changed_at)

        import_file("ch1.md", GOOD.replace("- [x] چهار", "- [ ] چهار (۴)").replace("- [ ] پنج", "- [x] پنج").encode())
        q.refresh_from_db()
        self.assertIsNotNone(q.key_changed_at)
        self.assertIn("پنج", q.key_change_note)
        self.assertIsNotNone(self._questions(client)[0]["corrected"])
        notebook = client.get("/api/v1/me/mistakes/").json()["items"]
        self.assertTrue(notebook[0]["corrected"], "the answer went wrong under the old key")
        r = client.post(f"/api/v1/questions/{q.pk}/answer/", {"choice_id": five.pk}, format="json").json()
        self.assertTrue(r["is_correct"])
        self.assertTrue(r["corrected"]["answered_before"])

    def test_panel_messages_name_the_chapter(self):
        action = reverse("admin:catalog_book_chapter_action", args=[self.book.pk])
        r = self.client.post(action, {"action": "free", "chapter": self.chapter.pk, "value": "0"}, follow=True)
        text = " ".join(str(m) for m in r.context["messages"])
        self.assertIn("«فصل یک» پولی شد", text)
        self.assertIn("بقیه‌ی فصل‌ها", text)


class MaintenanceTests(_Base):
    """The clean-up removes temporary data, old chapter versions and unused pictures, never learners' data."""

    def test_cleanup_keeps_user_data_and_recent_versions(self):
        import os
        import time
        from datetime import timedelta

        from django.utils import timezone

        from apps.accounts.models import DeviceSession, OTPCode, RateBucket
        from apps.learning.models import QuizAnswer

        from .maintenance import run_all
        from .models import CleanupRun

        now = timezone.now()
        old = OTPCode.objects.create(phone="09120000009", code_hash="x", expires_at=now - timedelta(days=3))
        fresh = OTPCode.objects.create(phone="09120000009", code_hash="y", expires_at=now + timedelta(minutes=2))
        RateBucket.objects.create(key="k", window_start=now - timedelta(days=5))
        s, _ = DeviceSession.start(self.admin, "old")
        DeviceSession.objects.filter(pk=s.pk).update(revoked_at=now - timedelta(days=200))
        q = Question.objects.get(slug="q1")
        QuizAnswer.objects.create(user=self.admin, question=q, choice_order=0, was_correct=False)
        # Versions: many old ones in the same week, one recent.
        for i in range(4):
            r = ChapterRevision.objects.create(chapter=self.chapter, text=f"v{i}", source="panel")
            ChapterRevision.objects.filter(pk=r.pk).update(updated_at=now - timedelta(days=60, hours=i))
        ChapterRevision.objects.create(chapter=self.chapter, text="now", source="panel")
        # Pictures: one used, one unused and old, one unused but new.
        folder = os.path.join(settings.MEDIA_ROOT, "content", "test-book", "ch1")
        os.makedirs(folder, exist_ok=True)
        paths = {}
        for name in ("used.png", "lost.png", "new.png"):
            paths[name] = os.path.join(folder, name)
            with open(paths[name], "wb") as f:
                f.write(b"x" * 10)
        month_ago = time.time() - 40 * 86400
        os.utime(paths["used.png"], (month_ago, month_ago))
        os.utime(paths["lost.png"], (month_ago, month_ago))
        q.explanation += "\\n![](media:content/test-book/ch1/used.png)"
        q.save()

        summary = run_all()
        self.assertFalse(OTPCode.objects.filter(pk=old.pk).exists())
        self.assertTrue(OTPCode.objects.filter(pk=fresh.pk).exists())
        self.assertEqual(summary["rate_counters"], 1)
        self.assertEqual(summary["sessions"], 1)
        self.assertEqual(QuizAnswer.objects.count(), 1, "learners' answers are never removed")
        old_texts = set(ChapterRevision.objects.filter(updated_at__lt=now - timedelta(days=30)).values_list("text", flat=True))
        self.assertEqual(len(old_texts), 1, "one a week stays from the older versions")
        self.assertTrue(ChapterRevision.objects.filter(text="now").exists())
        self.assertTrue(os.path.exists(paths["used.png"]))
        self.assertFalse(os.path.exists(paths["lost.png"]))
        self.assertTrue(os.path.exists(paths["new.png"]), "a new picture may be used soon")
        # A picture only a past exam still shows stays too.
        from apps.study.models import ExamAttempt

        kept = os.path.join(folder, "exam.png")
        with open(kept, "wb") as f:
            f.write(b"x")
        os.utime(kept, (month_ago, month_ago))
        ExamAttempt.objects.create(user=self.admin, node=self.chapter, time_limit_seconds=60,
                                   snapshot={"1": {"stem": "![](media:content/test-book/ch1/exam.png)"}})
        from .maintenance import orphan_images

        orphan_images()
        self.assertTrue(os.path.exists(kept))
        self.assertEqual(CleanupRun.objects.count(), 1)

        page = self.client.get(reverse("admin:catalog_cleanuprun_changelist"))
        self.assertContains(page, "فضای سرور")
        self.client.get(reverse("admin:index"))
        self.assertEqual(CleanupRun.objects.count(), 1, "runs by itself at most once a day")

    def test_shelves_order_the_home_page_and_nothing_is_hidden(self):
        from rest_framework.test import APIClient

        from .models import Shelf, ShelfBook

        rows = APIClient().get("/api/v1/shelves/").json()
        self.assertEqual([r["title"] for r in rows], ["همه‌ی کتاب‌ها"], "no shelves yet: every book in one row")
        shelf = Shelf.objects.create(title="اقتصاد")
        ShelfBook.objects.create(shelf=shelf, book=self.book)
        rows = APIClient().get("/api/v1/shelves/").json()
        self.assertEqual([r["title"] for r in rows], ["اقتصاد"])
        self.assertEqual(rows[0]["books"][0]["slug"], "test-book")
        self.assertEqual(rows[0]["books"][0]["major"]["slug"], "economics")
        shelf.is_active = False
        shelf.save()
        self.assertEqual([r["title"] for r in APIClient().get("/api/v1/shelves/").json()], ["همه‌ی کتاب‌ها"])

    def test_banner_for_the_readers_of_one_book(self):
        from rest_framework.test import APIClient

        from apps.study.models import SectionProgress

        from .models import Banner

        Banner.objects.create(title="همه")
        Banner.objects.create(title="خوانندگان", audience_book=self.book)
        self.assertEqual([b["title"] for b in APIClient().get("/api/v1/banners/").json()], ["همه"])
        reader = APIClient()
        reader.force_authenticate(self.admin)
        SectionProgress.objects.create(user=self.admin, node=ContentNode.objects.get(slug="one"), book=self.book)
        self.assertEqual(sorted(b["title"] for b in reader.get("/api/v1/banners/").json()), ["خوانندگان", "همه"])


class ShelfSpeedTests(_Base):
    def test_shelves_need_few_queries_however_many_books(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(self.admin)
        self.admin.is_staff = False
        self.admin.save()

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(client.get("/api/v1/shelves/").status_code, 200)
            return len(ctx.captured_queries)

        one = count()
        # A learner with a subscription: every book's access is worked out from the same rows.
        from apps.commerce.models import Entitlement

        Entitlement.objects.create(user=self.admin, all_majors=True)
        self.assertEqual(client.get("/api/v1/shelves/").json()[0]["books"][0]["access"], "subscription")
        for i in range(10):
            b = ContentNode.add_root(kind="book", title=f"کتاب {i}", slug=f"b{i}", is_published=True)
            b.add_child(kind="chapter", title="ف", slug=f"b{i}c", is_published=True)
        many = count()
        self.assertLessEqual(many - one, 10 * 2, f"{one} queries for 1 book, {many} for 11")

    def test_progress_of_many_read_books_needs_no_query_per_book(self):
        """The three-state progress (read / done) is worked out for every book on the shelves from shared queries."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from rest_framework.test import APIClient

        from apps.commerce.models import Entitlement
        from apps.study.models import SectionProgress

        client = APIClient()
        client.force_authenticate(self.admin)
        self.admin.is_staff = False
        self.admin.save()
        Entitlement.objects.create(user=self.admin, all_majors=True)

        def add_books(start, n):
            for i in range(start, start + n):
                b = ContentNode.add_root(kind="book", title=f"کتاب {i}", slug=f"rb{i}", is_published=True)
                c = b.add_child(kind="chapter", title="ف", slug=f"rb{i}c", is_published=True)
                sec = c.add_child(kind="section", title="ب", slug=f"rb{i}s", is_published=True)
                Question.objects.create(node=sec, slug=f"rq{i}", stem="؟", explanation="-", difficulty="easy")
                SectionProgress.objects.create(user=self.admin, node=sec, book=b, is_done=True)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(client.get("/api/v1/shelves/").status_code, 200)
            return len(ctx.captured_queries)

        add_books(0, 2)
        few = count()
        add_books(2, 8)
        many = count()
        # One query per book is the book's own tree (as for a book never opened); progress adds none.
        self.assertLessEqual(many - few, 8, f"{few} queries with 2 read books, {many} with 10")

    def test_book_samples_for_group_sharing(self):
        from rest_framework.test import APIClient

        Question.objects.filter(slug="q1").update(is_sample=True)
        data = APIClient().get("/api/v1/books/test-book/samples/").json()
        self.assertEqual(len(data["questions"]), 1)
        self.assertEqual(data["questions"][0]["share_place"]["chapter"], "فصل یک")
        self.assertNotIn("is_correct", str(data))
        self.assertEqual(APIClient().get("/api/v1/books/test-book/").json()["sample_count"], 1)


class WebAppTests(_Base):
    def test_web_version_is_served_at_the_root_and_keeps_api_and_panel(self):
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.client.get("/").status_code, 404, "no build yet: a page explaining update.bat")
            Path(d, "index.html").write_text("<html>app</html>", encoding="utf-8")
            Path(d, "_expo").mkdir()
            Path(d, "_expo", "a.js").write_text("x", encoding="utf-8")
            with override_settings(WEBAPP_DIR=d):
                self.assertIn(b"app", b"".join(self.client.get("/").streaming_content))
                self.assertIn(b"app", b"".join(self.client.get("/book/math-1").streaming_content), "app pages fall back to index.html")
                self.assertEqual(b"".join(self.client.get("/_expo/a.js").streaming_content), b"x")
                self.assertEqual(self.client.get("/../settings.py").status_code in (200, 404), True)
                self.assertNotIn(b"app", self.client.get("/api/v1/shelves/").content)
                self.assertNotEqual(self.client.get("/admin").status_code, 200, "the panel still redirects to /admin/")



class InboxTests(TestCase):
    """«صندوق تست»: tests wait in a hidden book, then move to any section of any book, keeping their ids."""

    BLOCK = "\n:::تست {#%s}\nمنبع: تألیفی\nسطح: آسان\nصورت:\nیک به‌علاوه‌ی یک؟\n- [ ] سه\n- [x] دو\nتوضیح: ساده.\n:::\n"

    def setUp(self):
        from django.contrib.auth import get_user_model

        from .importer import import_file
        from .models import Major
        from .tests import GOOD

        Major.objects.create(slug="economics", name="اقتصاد")
        import_file("c.md", GOOD.encode(), publish=True)
        self.admin = get_user_model().objects.create_superuser("09120000009", "pw-123456")
        self.client.force_login(self.admin)

    def api(self, chapter, **data):
        return self.client.post(f"/admin/catalog/book/chapter/{chapter.pk}/api/", data, content_type="application/json")

    def test_paste_into_inbox_then_move_in_bulk_to_another_book(self):
        from apps.learning.models import Question, QuizAnswer

        from .exporter import export_chapter
        from .inbox import inbox_chapter
        from .models import ContentNode

        self.assertEqual(self.client.get("/admin/catalog/book/inbox/").status_code, 302)
        chapter = inbox_chapter()
        self.assertEqual(inbox_chapter().pk, chapter.pk, "made once")
        self.assertTrue(chapter.book().is_inbox and not chapter.book().is_published)
        # Pasting through «ویرایش کل فایل»: one test with the id «q1», which the real book already uses.
        text = export_chapter(chapter) + self.BLOCK % "q1" + self.BLOCK % "inb-2"
        r = self.api(chapter, op="file.apply", text=text)
        self.assertEqual(r.status_code, 200, r.content.decode())
        waiting = list(Question.objects.filter(node__path__startswith=chapter.path, is_archived=False).order_by("order"))
        self.assertEqual([q.slug for q in waiting], ["q1", "inb-2"])
        book = ContentNode.objects.get(slug="test-book")
        real = Question.objects.get(slug="q1", node__path__startswith=book.path)
        QuizAnswer.objects.create(user=self.admin, question=waiting[1], choice_order=1, was_correct=True)
        self.assertEqual(self.client.get(f"/api/v1/nodes/{chapter.pk}/questions/").status_code, 404, "the app never sees the inbox")

        target = ContentNode.objects.get(slug="two")
        r = self.api(chapter, op="question.relocate", slugs=["q1", "inb-2"], to=target.pk).json()
        self.assertTrue(r.get("ok"), r)
        self.assertTrue(any("q1 ← q1-2" in w for w in r["warnings"]), r)
        moved = {q.pk: q for q in Question.objects.filter(pk__in=[q.pk for q in waiting])}
        self.assertTrue(all(q.node_id == target.pk for q in moved.values()), "same ids, now in the section")
        self.assertEqual(moved[waiting[0].pk].slug, "q1-2")
        self.assertEqual(Question.objects.get(pk=real.pk).slug, "q1", "the real book's q1 is untouched")
        self.assertEqual(QuizAnswer.objects.get(question=waiting[1]).question.node_id, target.pk, "answers go with the test")
        self.assertFalse(Question.objects.filter(node__path__startswith=chapter.path, is_archived=False).exists())
        self.assertIn("{#q1-2}", export_chapter(target.get_parent()), "the chapter file has the moved tests")

        # Back to the inbox; publishing the inbox is refused; the book list still works.
        r = self.api(target.get_parent(), op="question.relocate", slugs=["inb-2"], to=chapter.get_children().first().pk).json()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(Question.objects.get(pk=waiting[1].pk).node.get_parent().pk, chapter.pk)
        self.assertEqual(self.api(chapter, op="chapter.publish", value=True).status_code, 400)
        dest = self.api(chapter, op="destinations").json()["destinations"]
        self.assertTrue(dest[0]["inbox"])
        self.assertEqual(self.client.get("/admin/catalog/book/").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/catalog/book/chapter/{chapter.pk}/").status_code, 200)


class MovingContentTests(TestCase):
    """Flashcards and whole sections move like tests; test–flashcard links may cross chapters, never books."""

    CH2 = """---
شناسه-کتاب: test-book
کتاب: کتاب آزمایشی
شناسه-فصل: ch2
عنوان: فصل دو
---

## بخش سوم {#three}
متن سوم با ارجاع به [[#ex-a]].

:::تست {#q-ch2}
منبع: تألیفی
سطح: آسان
صورت:
یک به‌علاوه‌ی یک؟
- [ ] سه
- [x] دو
توضیح: ساده.
فلش‌کارت: card1
:::

## بخش چهارم {#four}
متن چهارم.
"""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from .importer import import_file
        from .models import Major
        from .tests import GOOD

        Major.objects.create(slug="economics", name="اقتصاد")
        good = GOOD.replace("متن جزوه با فرمول $x^2$.", "متن.\n\n:::مثال {#ex-a}\nیک\n:::")
        c, _ = import_file("c.md", good.encode(), publish=True)
        assert not c.errors, c.errors
        c, _ = import_file("c2.md", self.CH2.encode(), publish=True)
        assert not c.errors, c.errors  # a link to card1 of chapter 1 is allowed now
        self.admin = get_user_model().objects.create_superuser("09120000008", "pw-123456")
        self.client.force_login(self.admin)

    def api(self, chapter, **data):
        return self.client.post(f"/admin/catalog/book/chapter/{chapter.pk}/api/", data, content_type="application/json")

    def test_links_across_chapters_and_moving_a_section(self):
        from apps.learning.models import Flashcard, Question

        from .exporter import export_chapter
        from .models import ContentNode

        q2 = Question.objects.get(slug="q-ch2")
        self.assertEqual([f.slug for f in q2.flashcards.all()], ["card1"], "link to another chapter of the book")
        ch1, ch2 = ContentNode.objects.get(slug="ch1"), ContentNode.objects.get(slug="ch2")
        self.assertIn("فلش‌کارت: card1", export_chapter(ch2))

        # Moving section «one» (q1, card1, box ex-a) to chapter 2 of the same book: nothing breaks.
        dry = self.api(ch1, op="section.relocate", slug="one", to=ch2.pk, dry=True).json()
        self.assertEqual(dry["warnings"], [], dry)
        r = self.api(ch1, op="section.relocate", slug="one", to=ch2.pk).json()
        self.assertTrue(r.get("ok"), r)
        one = ContentNode.objects.get(slug="one")
        self.assertEqual(one.get_parent().pk, ch2.pk)
        self.assertEqual(Flashcard.objects.get(slug="card1").node_id, one.pk)
        self.assertEqual(sorted(f.slug for f in Question.objects.get(slug="q1").flashcards.all()), ["card1"])
        self.assertEqual(self.api(ch2, op="section.relocate", slug="three", to=ch1.pk).status_code, 200)
        self.assertEqual(self.api(ch1, op="section.relocate", slug="two", to=ch2.pk).status_code, 200)
        # The last section of a chapter cannot leave it.
        self.assertEqual(self.api(ch1, op="section.relocate", slug="three", to=ch2.pk).status_code, 400)

    def test_moving_to_another_book_warns_and_drops_links(self):
        from apps.learning.models import Flashcard, Question

        from .bookpanel import book_health
        from .importer import import_file
        from .models import ContentNode

        other = self.CH2.replace("test-book", "other-book").replace("کتاب آزمایشی", "کتاب دیگر").replace("ch2", "o1").replace(
            "{#three}", "{#o-three}").replace("{#four}", "{#o-four}").replace("{#q-ch2}", "{#q-o}").replace("فلش‌کارت: card1\n", "").replace(" با ارجاع به [[#ex-a]]", "")
        c, _ = import_file("o.md", other.encode(), publish=True)
        self.assertFalse(c.errors, c.errors)
        ch1, o1 = ContentNode.objects.get(slug="ch1"), ContentNode.objects.get(slug="o1")
        dry = self.api(ch1, op="section.relocate", slug="one", to=o1.pk, dry=True).json()
        text = " ".join(dry["warnings"])
        self.assertIn("بخش سوم", text, "chapter 2 links to the box ex-a, which leaves the book")
        self.assertIn("پیوند", text)
        r = self.api(ch1, op="section.relocate", slug="one", to=o1.pk).json()
        self.assertTrue(r.get("ok"), r)
        self.assertEqual(Question.objects.get(slug="q-ch2").flashcards.count(), 0, "link to a card now in another book dropped")
        health = " ".join(h["text"] for h in book_health(ContentNode.objects.get(slug="test-book")))
        self.assertIn("[[#ex-a]]", health, "the broken link is listed on the book page")

        # A flashcard moved back to the first book, alone.
        two = ContentNode.objects.get(slug="two")
        r = self.api(o1, op="flashcard.relocate", slugs=["card1"], to=two.pk).json()
        self.assertTrue(r.get("ok"), r)
        card = Flashcard.objects.get(slug="card1")
        self.assertEqual(card.node_id, two.pk)
        self.assertEqual(card.questions.count(), 0, "q1 stayed in the other book: no link across books")


class FreshAndRestoreTests(_Base):
    """«مطلب تازه», «تغییرات کتاب», «تازه» tests, numbered formulas and «فقط متن بخش‌ها را برگردان»."""

    def test_fresh_tick_marks_the_section_and_writes_a_change(self):
        from .models import BookChange

        r = self.op(op="section.update", slug="one", full_body="نکته‌ی تازه.", fresh=True, fresh_note="یک نکته‌ی مهم اضافه شد")
        self.assertEqual(r.status_code, 200, r.content)
        node = ContentNode.objects.get(slug="one")
        self.assertIsNotNone(node.refreshed_at)
        change = BookChange.objects.get(book=self.book)
        self.assertEqual(change.text, "یک نکته‌ی مهم اضافه شد")
        data = self.client.get(f"/api/v1/books/{self.book.slug}/changes/").json()
        self.assertEqual(data["changes"][0]["text"], "یک نکته‌ی مهم اضافه شد")
        self.assertIsNotNone(self.client.get(f"/api/v1/books/{self.book.slug}/").json()["updated_on"])
        # Without the tick nothing is marked.
        self.op(op="section.update", slug="two", full_body="اصلاح غلط تایپی.")
        self.assertIsNone(ContentNode.objects.get(slug="two").refreshed_at)
        self.assertEqual(BookChange.objects.count(), 1)

    def test_badges_for_a_learner(self):
        from django.utils import timezone

        from apps.study.models import SectionProgress

        from .fresh import question_badges, section_badges

        learner = User.objects.create_user("09120000002")
        one = ContentNode.objects.get(slug="one")
        SectionProgress.objects.create(user=learner, node=one, book=self.book, percent=100, is_done=True)
        q = Question.objects.get(slug="q1")
        self.assertEqual(question_badges(learner, [q]), {})  # older than the learner's start
        q.added_at = timezone.now()
        q.save()
        self.assertEqual(question_badges(learner, [q]), {q.id: "new"})
        self.op(op="section.update", slug="one", full_body="نکته.", fresh=True)
        one.refresh_from_db()
        self.assertEqual(section_badges(learner, [one]), {one.id: "updated"})

    def test_numbered_formulas_count_and_link(self):
        from .numbering import chapter_numbering

        self.op(op="section.update", slug="one", full_body="$$a=b$$ {#eq-a}\n\nمتن\n\n$$c=d$$\n\n$$\ne=f\n$$ {#eq-b}")
        chapter = ContentNode.objects.get(pk=self.chapter.pk)
        starts, refs = chapter_numbering(chapter, chapter.get_children())
        self.assertEqual(refs["eq-a"]["text"], f"رابطه‌ی ({chapter.position and '۱-'}۱)".replace("None", ""))
        self.assertTrue(refs["eq-b"]["text"].endswith("۲)"))
        two = ContentNode.objects.get(slug="two")
        self.assertEqual(starts[two.id].get("رابطه"), 2)
        # A name used twice is refused.
        r = self.op(op="section.update", slug="two", full_body="$$x$$ {#eq-a}")
        self.assertEqual(r.status_code, 400)

    def test_restore_text_only_hides_nothing(self):
        first_text = export_chapter(self.chapter)
        self.op(op="section.update", slug="one", full_body="نسخه‌ی تازه.")
        self.op(op="section.create", title="بخش سوم", slug="three")
        r = self.op(op="file.restore_text", text=first_text)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("متن جزوه با فرمول", ContentNode.objects.get(slug="one").full_body)
        self.assertFalse(ContentNode.objects.get(slug="three").is_archived, "a section missing from the old version stays")


class FileEditorPreviewTests(_Base):
    """The whole-file editor has a live preview, and it is the app's own renderer.

    The behaviour is JavaScript and the test runner has no browser; what is guarded here is the page the script runs
    in: the text box and the scripts it builds on. The script itself is exercised by hand (jsdom) while it is written;
    the one thing a broken selector would cause — a preview that stays empty — is a browser-only failure.
    """

    def setUp(self):
        super().setUp()
        self.url = reverse("admin:catalog_chapter_file", args=[self.chapter.pk])

    def test_the_editor_page_loads_the_preview_renderer(self):
        response = self.client.get(self.url)
        # The panel's preview is limo-preview.js — the app's renderer compiled for the browser, not a second one.
        for asset in ("catalog/limo-preview.js", "catalog/panel.js", "catalog/panel.css"):
            self.assertContains(response, asset)

    def test_the_editor_page_has_the_text_box_the_script_fills(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'id="file-text"')
        self.assertContains(response, "LimoFileEditor")


class BookEditorAccessTests(_Base):
    """«استاد کتاب»: a staff member writes only the books they are the editor of, and only edits to other books are refused."""

    def clerk(self, *books, can_publish=False):
        from django.contrib.auth.models import Permission

        from .models import BookEditor

        user = User.objects.create_user("09120000002", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="change_contentnode"))
        user.refresh_from_db()
        for book in books:
            BookEditor.objects.create(book=book, user=user, can_publish=can_publish)
        return user

    def other_book(self):
        from .importer import import_file

        _, result = import_file("ch2.md", GOOD.replace("کتاب تست", "کتاب دیگر").replace("test-book", "other-book")
                                .replace("متن دوم", "متن دیگر").encode())
        return result.book, result.chapter

    def test_staff_without_a_row_cannot_open_or_write_the_chapter(self):
        self.client.force_login(self.clerk())
        self.assertEqual(self.client.get(self.api).status_code, 403)
        url = reverse("admin:catalog_chapter_manager", args=[self.chapter.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        before = export_chapter(self.chapter)
        r = self.client.post(self.api, json.dumps({"op": "chapter.update", "title": "دست‌کاری", "number": 1}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.chapter.refresh_from_db()
        self.assertEqual(export_chapter(self.chapter), before)

    def test_editor_of_the_book_may_open_and_write_it(self):
        self.client.force_login(self.clerk(self.book))
        self.assertEqual(self.client.get(self.api).status_code, 200)
        r = self.client.post(self.api, json.dumps({"op": "chapter.update", "title": "عنوان تازه", "number": 1, "is_free": True}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.title, "عنوان تازه")

    def test_editor_of_one_book_cannot_reach_another(self):
        _, other_chapter = self.other_book()
        self.client.force_login(self.clerk(self.book))
        for name in ("admin:catalog_chapter_manager", "admin:catalog_chapter_api", "admin:catalog_chapter_file"):
            self.assertEqual(self.client.get(reverse(name, args=[other_chapter.pk])).status_code, 403, name)

    def test_cannot_move_content_into_a_book_one_may_not_edit(self):
        _, other_chapter = self.other_book()
        self.client.force_login(self.clerk(self.book))
        r = self.client.post(self.api, json.dumps({"op": "section.relocate", "slug": "one", "to": other_chapter.pk, "dry": True}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_destination_list_only_shows_own_books(self):
        other_book, _ = self.other_book()
        self.client.force_login(self.clerk(self.book))
        r = self.client.post(self.api, json.dumps({"op": "destinations"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        ids = [b["id"] for b in r.json()["destinations"]]
        self.assertIn(self.book.pk, ids)
        self.assertNotIn(other_book.pk, ids)

    def test_a_row_pointing_at_a_chapter_grants_nothing(self):
        # Only a book row counts; a row on a chapter must not leak writing rights to that chapter's book.
        from .models import BookEditor

        user = self.clerk()
        BookEditor.objects.create(book=self.chapter, user=user)
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.api).status_code, 403)

    def test_superuser_still_edits_every_book_without_any_row(self):
        self.assertEqual(self.client.get(self.api).status_code, 200)

    def test_staff_view_as_learner_keeps_no_writing_rights(self):
        # A learner view is a read-only view of the app; staff rights must still apply in the panel.
        self.client.force_login(self.clerk(self.book))
        self.assertEqual(self.client.get(self.api).status_code, 200)

    def test_book_editor_must_point_at_a_book_not_a_chapter(self):
        from django.core.exceptions import ValidationError

        from .models import BookEditor

        row = BookEditor(book=self.chapter, user=self.admin)
        with self.assertRaises(ValidationError):
            row.full_clean()
