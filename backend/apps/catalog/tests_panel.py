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
        self.assertEqual(api.post("/api/v1/books/test-book/notify/", {"on": True}, format="json").json(), {"notify": True})
        self.assertTrue(api.get("/api/v1/majors/economics/books/").json()[0]["notify"])
        api.post("/api/v1/books/test-book/notify/", {"on": False}, format="json")
        self.assertFalse(api.get("/api/v1/majors/economics/books/").json()[0]["notify"])
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
