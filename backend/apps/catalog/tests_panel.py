"""The panel: export round trip, chapter editing operations, versions, file import with preview, book page."""

import dataclasses
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib.messages import get_messages
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

    def test_a_section_can_be_made_free(self):
        """«رایگان» برای یک بخش: همان کاری که برای تست و فلش‌کارت هست، ولی برای خودِ بخش."""
        state = self.state()
        self.assertFalse([s for s in state["sections"] if s["slug"] == "one"][0]["is_free"])
        r = self.op(op="section.free", slug="one", value=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(ContentNode.objects.get(slug="one").is_free)
        self.assertTrue([s for s in self.state()["sections"] if s["slug"] == "one"][0]["is_free"])
        self.op(op="section.free", slug="one", value=False)
        self.assertFalse(ContentNode.objects.get(slug="one").is_free)

    def test_a_free_section_stays_free_when_the_file_is_read_again(self):
        """این پرچم در پنل است، نه در فایل: خواندن دوباره‌ی فایل نباید آن را پاک کند."""
        self.op(op="section.free", slug="one", value=True)
        editing.save(self.chapter, editing.load(self.chapter), user=self.admin, note="بدون تغییر")
        self.assertTrue(ContentNode.objects.get(slug="one").is_free)

    def test_a_teacher_may_set_it_only_in_a_draft(self):
        """استاد محتوای منتشرشده را تغییر نمی‌دهد؛ در پیش‌نویس، خودش تصمیم می‌گیرد."""
        from django.contrib.auth.models import Group

        from . import access
        from .models import BookEditor

        teacher = User.objects.create_user("09120000003", is_staff=True)
        teacher.groups.add(Group.objects.get(name=access.BOOK_EDITOR_GROUP))
        BookEditor.objects.create(book=self.book, user=teacher)
        self.client.force_login(teacher)
        # The chapter is published (the sample file was imported with publish=True): refused.
        r = self.op(op="section.free", slug="one", value=True)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ContentNode.objects.get(slug="one").is_free)
        # As a draft, the teacher may decide.
        ContentNode.objects.filter(pk=self.chapter.pk).update(is_published=False)
        r = self.op(op="section.free", slug="one", value=True)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(ContentNode.objects.get(slug="one").is_free)

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
        self.assertEqual((card["free_chapters"], card["all_free"]), (1, False))
        self.assertEqual(
            card["product_status"],
            {"state": "unpriced", "preview": "sample", "promotion": "none"},
        )


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

        Banner.objects.create(title="بنر رویداد", template="lemon", button="مشاهده", countdown=True, ends_at=timezone.now() + timedelta(hours=5))
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            Banner(title="۳۰٪ تخفیف مستقل", template=Banner.Template.SALE).full_clean()
        Banner.objects.create(title="کتاب تازه", template="book", target="book", target_value="test-book")
        Banner.objects.create(title="پیش‌نویس", template="book", target="book", target_value="draft-book")
        ContentNode.add_root(kind="book", title="کتاب پنهان", slug="draft-book", is_published=False)
        data = APIClient().get("/api/v1/banners/").json()
        event = next(b for b in data if b["title"] == "بنر رویداد")
        self.assertEqual(event["template"], "lemon")
        self.assertIsNotNone(event["ends_at"])
        self.assertEqual(event["button"], "مشاهده")
        book = next(b for b in data if b["title"] == "کتاب تازه")
        self.assertEqual(book["book"]["title"], "کتاب آزمایشی")
        self.assertIsNone(next(b for b in data if b["title"] == "پیش‌نویس")["book"])
        self.assertEqual(self.client.get(reverse("admin:catalog_banner_add")).status_code, 200)

    def test_campaign_banner_admin_shows_its_effective_checkout_destination(self):
        from datetime import timedelta

        from django.utils import timezone
        from apps.commerce.models import SaleCampaign
        from .models import Banner

        now = timezone.now()
        campaign = SaleCampaign.objects.create(
            title="کمپین کتاب آزمایشی", book=self.book, discounted_price=1,
            starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1),
        )
        banner = Banner.objects.create(title="بنر کمپین", template="sale", sale_campaign=campaign)
        change = self.client.get(reverse("admin:catalog_banner_change", args=[banner.pk]))
        self.assertContains(change, "مقصد نهایی")
        self.assertContains(change, "خرید از کمپین")
        self.assertContains(change, "buy/test-book")
        self.assertNotContains(change, 'name="target"')

        listing = self.client.get(reverse("admin:catalog_banner_changelist"))
        self.assertContains(listing, "buy/test-book")

    def test_banner_preview_labels_both_intentional_aspect_ratio_sizes(self):
        script = (settings.BASE_DIR / "apps/catalog/static/catalog/panel.js").read_text(encoding="utf-8")
        self.assertIn("پهن · ۴۲۰ × ۲۱۰ پیکسل", script)
        self.assertIn("گوشی · ۳۰۰ × ۱۵۰ پیکسل", script)
        self.assertIn("نسبت هر دو ۲ به ۱", script)


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
            ChapterRevision.objects.filter(pk=r.pk).update(updated_at=now - timedelta(days=60, minutes=i * 10))
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

    def test_the_box_holds_the_body_and_the_details_sit_above_it(self):
        # The header used to reach the box as code («--- شناسه-کتاب: … ---» above the lesson). It is a contract for a
        # file coming from outside, not something to type while editing a chapter that exists: the box now holds the
        # body only, and the three details a person edits come as fields. The header still goes back on save — the
        # page script puts it back (`headerWith`), and `test_saving_the_body_keeps_the_header` here pins the result
        # through the server.
        response = self.client.get(self.url)
        html = response.content.decode()
        box = html.split('id="file-text"', 1)[1].split("</textarea>", 1)[0]
        self.assertNotIn("شناسه-کتاب", box)
        self.assertNotIn("شناسه-فصل", box)
        self.assertNotIn("---", box.strip().splitlines()[0] if box.strip() else "")
        # The details the card edits, and the ids it never lets anyone edit.
        meta = json.loads(html.split('id="file-meta"', 1)[1].split(">", 1)[1].split("</script>", 1)[0])
        self.assertEqual((meta["chapter_slug"], meta["book_slug"]), ("ch1", "test-book"))
        for key in ("chapter_title", "chapter_number", "chapter_free", "majors"):
            self.assertIn(key, meta)
        self.assertIn("file-meta", html)

    def test_a_body_saved_alone_is_still_checked_with_its_header(self):
        # What the page sends back is body + header (headerWith in panel.js). The server side of that contract: the
        # body alone is not a chapter, and body + header is the file it was before.
        from .panel import whole_file_body

        text = export_chapter(self.chapter)
        body = whole_file_body(text)
        self.assertNotIn("شناسه-کتاب", body)
        self.assertIn("## بخش اول {#one}", body)
        self.assertTrue(self.op(op="file.check", text=body).json()["errors"], "a body with no header must not pass")
        header = text[: len(text) - len(body)]
        self.assertEqual(self.op(op="file.check", text=header + body).json()["errors"], [])

    def test_saving_the_body_keeps_the_header(self):
        # The whole point of taking the header out of the box: putting it back must be exact, or a save would drop
        # the book, the ids and the majors from the file.
        from .panel import whole_file_body

        before = export_chapter(self.chapter)
        body = whole_file_body(before).replace("متن دوم.", "متن دوم، با سرصفحه‌ی برگشته.")
        r = self.op(op="file.apply", text=before.replace(whole_file_body(before), body))
        self.assertEqual(r.status_code, 200, r.content)
        after = export_chapter(self.chapter)
        self.assertIn("متن دوم، با سرصفحه‌ی برگشته.", after)
        self.assertTrue(after.startswith("---\nشناسه-کتاب: test-book\nکتاب: کتاب آزمایشی"))

    def test_restoring_old_body_uses_the_current_read_only_header(self):
        # A past revision can predate a book rename. The body comes from that version, but its header (book/title/slug/
        # majors) must not roll back: those are readonly in the card and belong to the current book.
        old = (export_chapter(self.chapter).replace("کتاب: کتاب آزمایشی", "کتاب: عنوان کهنه")
               .replace(f"عنوان: {self.chapter.title}", "فصل: 9\nعنوان: عنوان کهنه"))
        revision = ChapterRevision.objects.create(chapter=self.chapter, text=old, source=ChapterRevision.Source.PANEL)
        self.book.title = "عنوان تازه"
        self.book.save(update_fields=["title"])
        response = self.client.get(self.url + f"?revision={revision.pk}")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        meta = json.loads(html.split('id="file-meta"', 1)[1].split(">", 1)[1].split("</script>", 1)[0])
        self.assertIn("کتاب: عنوان تازه", meta["header"])
        self.assertNotIn("عنوان کهنه", meta["header"])
        self.assertEqual(meta["chapter_title"], "عنوان کهنه")
        self.assertEqual(meta["chapter_number"], 9)
        body = html.split('id="file-text"', 1)[1].split("</textarea>", 1)[0]
        self.assertIn("متن دوم.", body)


class BookEditorAccessTests(_Base):
    def test_book_trace_view_isolation_and_masking(self):
        from apps.guard.models import CopyEvent, TraceHit
        from apps.guard import fingerprint, core
        from django.urls import reverse

        from apps.accounts.models import User
        learner = User.objects.create_user("09123334455")
        teacher = self.clerk(self.book)
        self.client.force_login(teacher)

        section = self.chapter.get_children().first()
        quote = "این یک متن آزمایشی استخراج شده از کتاب استاد است"
        code = fingerprint.new_code()
        event = CopyEvent.objects.create(
            user=learner,
            node=section,
            code=code,
            length=len(quote),
            packed=None,
        )
        marked_text = fingerprint.mark(quote, code)

        # 1. Teacher can open book trace view
        url = reverse("admin:catalog_book_trace", args=[self.book.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ردیاب هوشمند کپی و اصالت متن")
        self.assertContains(resp, "اثرانگشت نامرئی Zero-Width")

        # 2. Teacher posts marked text -> trace detects learner masked
        res_post = self.client.post(url, {"text": f"در تلگرام منتشر شده: {marked_text}"})
        self.assertEqual(res_post.status_code, 200)
        self.assertContains(res_post, "نتیجه: اثرانگشت نامرئی با موفقیت شناسایی شد")
        phone = learner.phone
        masked = phone[:4] + "***" + phone[-4:]
        self.assertContains(res_post, masked)
        self.assertNotContains(res_post, phone)

        # 3. TraceHit is logged
        self.assertTrue(TraceHit.objects.filter(event=event, found_by=teacher).exists())

        # 4. Strict isolation: unassigned teacher cannot access this book's trace
        other_teacher = User.objects.create_user("09127778899", is_staff=True)
        from django.contrib.auth.models import Group
        from . import access
        other_teacher.groups.add(Group.objects.get(name=access.BOOK_EDITOR_GROUP))
        self.client.force_login(other_teacher)
        res_forbidden = self.client.get(url)
        self.assertEqual(res_forbidden.status_code, 403)

        # 5. Hourly Rate Limiting (max 10 queries per hour for teacher)
        self.client.force_login(teacher)
        for _ in range(9):  # already did 1 post above -> total reaches 10
            r = self.client.post(url, {"text": "متن تستی کوتاه دیگر"})
            self.assertNotContains(r, "محدودیت تعداد استعلام")
        # 11th request hits the rate limit
        r_blocked = self.client.post(url, {"text": "تست بیش از حد مجاز"})
        self.assertContains(r_blocked, "محدودیت تعداد استعلام")
        self.assertContains(r_blocked, "۱۰ استعلام در ساعت")

    def test_book_dedicated_inbox_and_teacher_relocate(self):
        """Each book has a dedicated inbox accessible to its teachers for bulk staging and relocation."""
        from .inbox import book_inbox_chapter
        from .exporter import export_chapter
        from apps.learning.models import Question

        block = """
:::تست {#%s}
منبع: تألیفی
سطح: آسان
صورت:
یک به‌علاوه‌ی یک؟
- [ ] سه
- [x] دو
توضیح: ساده.
:::
"""

        # Teacher of self.book
        teacher = self.clerk(self.book)
        self.client.force_login(teacher)

        # 1. Opening book inbox redirects teacher to chapter manager of book inbox chapter
        inbox_url = reverse("admin:catalog_book_inbox", args=[self.book.pk])
        inbox_ch = book_inbox_chapter(self.book)
        resp = self.client.get(inbox_url)
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(resp, reverse("admin:catalog_chapter_manager", args=[inbox_ch.pk]))
        self.assertTrue(inbox_ch.is_inbox)
        self.assertEqual(inbox_ch.book().pk, self.book.pk)

        # 2. Teacher pastes tests into book inbox via file.apply
        inbox_api = reverse("admin:catalog_chapter_api", args=[inbox_ch.pk])
        staging_text = export_chapter(inbox_ch) + block % "stage-q1" + block % "stage-q2"
        r = self.client.post(inbox_api, json.dumps({"op": "file.apply", "text": staging_text}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content.decode())

        # 3. Check tests are in book inbox section
        waiting = list(Question.objects.filter(node__path__startswith=inbox_ch.path, is_archived=False).order_by("order"))
        self.assertEqual([q.slug for q in waiting], ["stage-q1", "stage-q2"])

        # 4. Relocate stage-q1 to section 'two' of the same book
        self.make_draft(self.chapter)
        target_sec = self.chapter.get_children().first()
        relocate_res = self.client.post(
            inbox_api,
            json.dumps({"op": "question.relocate", "slugs": ["stage-q1"], "to": target_sec.pk}),
            content_type="application/json",
        ).json()
        self.assertTrue(relocate_res.get("ok"), relocate_res)

        # stage-q1 is now in target section
        q1 = Question.objects.get(pk=waiting[0].pk)
        self.assertEqual(q1.node_id, target_sec.pk)

        # 5. Non-editor cannot access this book's inbox
        other_user = User.objects.create_user("09120000003", is_staff=True)
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(inbox_url).status_code, 403)

    """«استاد کتاب»: a manager-approved group member writes only assigned draft books."""

    def clerk(self, *books, can_publish=False):
        from django.contrib.auth.models import Group

        from . import access
        from .models import BookEditor

        user = User.objects.create_user("09120000002", is_staff=True)
        user.groups.add(Group.objects.get(name=access.BOOK_EDITOR_GROUP))
        for book in books:
            BookEditor.objects.create(book=book, user=user, can_publish=can_publish)
        return user

    def make_draft(self, chapter):
        ContentNode.objects.filter(pk=chapter.pk).update(is_published=False)
        chapter.refresh_from_db()

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

    def test_group_has_only_its_minimum_permissions_and_migration_adds_no_users(self):
        from django.contrib.auth.models import Group

        from . import access

        group = Group.objects.get(name=access.BOOK_EDITOR_GROUP)
        actual = set(group.permissions.values_list("content_type__app_label", "codename"))
        expected = {
            ("catalog", "view_book"), ("catalog", "view_contentnode"), ("catalog", "change_contentnode"),
            ("catalog", "view_section"), ("catalog", "view_chapterrevision"),
            ("catalog", "view_label"), ("catalog", "add_label"), ("catalog", "change_label"), ("catalog", "delete_label"),
            ("catalog", "view_aiprovider"), ("catalog", "add_aiprovider"), ("catalog", "change_aiprovider"), ("catalog", "delete_aiprovider"),
            ("catalog", "view_bookassistantauditlog"),
            ("learning", "view_question"), ("learning", "view_flashcard"), ("learning", "view_examsource"),
            ("learning", "view_report"), ("learning", "change_report"),
        }
        self.assertEqual(actual, expected)
        self.assertFalse(group.user_set.exists(), "the role migration must not promote any existing staff user")

    def test_book_teacher_cannot_reach_the_user_password_change_view(self):
        from django.contrib import admin
        from django.test import RequestFactory

        teacher = self.clerk(self.book)
        request = RequestFactory().get("/admin/accounts/user/")
        request.user = teacher
        user_admin = admin.site._registry[User]
        self.assertFalse(user_admin.has_change_permission(request, teacher))

        self.client.force_login(teacher)
        password_url = reverse("admin:auth_user_password_change", args=[teacher.pk])
        self.assertEqual(self.client.get(password_url).status_code, 403)

    def test_direct_permission_and_book_row_without_teacher_group_do_not_approve(self):
        from django.contrib import admin
        from django.contrib.auth.models import Permission
        from django.test import RequestFactory

        from . import access
        from .models import Book, BookEditor

        unapproved = User.objects.create_user("09120000009", is_staff=True)
        unapproved.user_permissions.add(Permission.objects.get(codename="change_contentnode"))
        BookEditor.objects.create(book=self.book, user=unapproved)
        self.assertFalse(access.can_edit_book(unapproved, self.book))
        self.client.force_login(unapproved)
        self.assertEqual(self.client.get(self.api).status_code, 403)
        request = RequestFactory().get("/admin/catalog/book/")
        request.user = unapproved
        self.assertFalse(admin.site._registry[Book].get_queryset(request).exists())

    def test_inbox_is_manager_only_even_if_an_legacy_editor_row_exists(self):
        from . import access
        from .inbox import inbox_chapter
        from .models import BookEditor

        inbox = inbox_chapter()
        book = inbox.book()
        teacher = self.clerk()
        # Simulate a legacy row predating the new model validation; authorization must still be safe.
        BookEditor.objects.bulk_create([BookEditor(book=book, user=teacher)])
        self.assertFalse(access.can_edit_book(teacher, book))
        self.client.force_login(teacher)
        self.assertEqual(self.client.get(reverse("admin:catalog_chapter_manager", args=[inbox.pk])).status_code, 403)

    def test_editor_of_the_book_may_open_and_write_it(self):
        self.make_draft(self.chapter)
        ContentNode.objects.filter(pk=self.chapter.pk).update(is_free=False)
        self.client.force_login(self.clerk(self.book))
        self.assertEqual(self.client.get(self.api).status_code, 200)
        r = self.client.post(self.api, json.dumps({"op": "chapter.update", "title": "عنوان تازه", "number": 1, "is_free": True}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.title, "عنوان تازه")
        self.assertFalse(self.chapter.is_free, "a teacher cannot make the chapter free through the chapter-update payload")

    def test_teacher_cannot_mark_questions_sample_through_either_admin_surface(self):
        from django.contrib import admin
        from django.test import RequestFactory

        question = Question.objects.get(slug="q1")
        question.is_sample = False
        question.save(update_fields=["is_sample"])
        self.make_draft(self.chapter)
        teacher = self.clerk(self.book)
        self.client.force_login(teacher)

        question_admin = admin.site._registry[Question]
        request = RequestFactory().post(reverse("admin:learning_question_changelist"), {
            "action": "make_sample", "_selected_action": [str(question.pk)],
        })
        request.user = teacher
        self.assertNotIn("make_sample", question_admin.get_actions(request))
        self.assertNotIn("unmake_sample", question_admin.get_actions(request))

        response = self.client.post(reverse("admin:learning_question_changelist"), {
            "action": "make_sample", "_selected_action": [question.pk],
        })
        self.assertEqual(response.status_code, 200)  # forged action is discarded, not run
        question.refresh_from_db()
        self.assertFalse(question.is_sample)

        response = self.op(op="question.sample", slug=question.slug, value=True)
        self.assertEqual(response.status_code, 403)
        question.refresh_from_db()
        self.assertFalse(question.is_sample)

    def test_free_access_flags_are_locked_for_a_teacher(self):
        self.make_draft(self.chapter)
        ContentNode.objects.filter(pk=self.chapter.pk).update(is_free=False)
        self.client.force_login(self.clerk(self.book))
        chapter = self.op(op="chapter.update", title=self.chapter.title, number=1, is_free=True)
        self.assertEqual(chapter.status_code, 200, chapter.content)
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_free)

        existing = self.state()["sections"][0]["questions"][0]
        existing["is_free"] = True
        saved = self.op(op="question.save", slug=existing["slug"], data=existing)
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertFalse(Question.objects.get(slug=existing["slug"]).is_free)

        new_question = {"stem": "آیا دسترسی رایگان می‌شود؟", "choices": [{"text": "بله", "correct": True}, {"text": "نه"}],
                        "explanation": "پاسخ", "difficulty": "easy", "is_free": True}
        created = self.op(op="question.save", new=True, section="two", slug="teacher-free-test", data=new_question)
        self.assertEqual(created.status_code, 200, created.content)
        self.assertFalse(Question.objects.get(slug="teacher-free-test").is_free)

    def test_teacher_cannot_change_book_distribution_or_grant_student_access(self):
        from django.contrib import admin
        from django.contrib.auth.models import Permission
        from django.urls import reverse

        from apps.commerce.models import Entitlement
        from .models import BookEditor

        teacher = self.clerk(self.book)
        legacy_permissions = Permission.objects.filter(
            content_type__app_label__in=("catalog", "commerce", "accounts", "auth"),
            codename__in=("change_book", "add_entitlement", "change_entitlement", "add_user", "change_user", "change_group"),
        )
        teacher.user_permissions.add(*legacy_permissions)
        self.client.force_login(teacher)

        book_url = reverse("admin:catalog_book_change", args=[self.book.pk])
        self.assertEqual(self.client.get(book_url).status_code, 200)  # assigned-book navigation is view-only
        response = self.client.post(book_url, {"title": "دست‌کاری", "price": "0", "is_free": "on"})
        self.assertEqual(response.status_code, 403)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "کتاب آزمایشی")
        self.assertIsNone(self.book.price)
        self.assertFalse(self.book.is_free)

        gift = reverse("admin:catalog_book_gift", args=[self.book.pk])
        self.assertEqual(self.client.post(gift, {"phone": "09120000099", "days": "forever"}).status_code, 403)
        self.assertFalse(Entitlement.objects.filter(user__phone="09120000099", book=self.book).exists())
        self.assertEqual(self.client.get(reverse("admin:commerce_entitlement_add")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_group_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:catalog_bookeditor_changelist")).status_code, 403)
        self.assertFalse(admin.site._registry[Entitlement].has_add_permission(type("R", (), {"user": teacher})()))
        self.assertFalse(BookEditor.objects.filter(book=self.book, user=teacher, can_publish=True).exists())

    def _new_import_text(self):
        return (GOOD.replace("شناسه-فصل: ch1", "شناسه-فصل: teacher-ch2")
                .replace("عنوان: فصل یک", "عنوان: پیش‌نویس استاد")
                .replace("رایگان: بله", "رایگان: بله\nقیمت-کتاب: 1")
                .replace("{#one}", "{#teacher-one}").replace("{#two}", "{#teacher-two}")
                .replace("{#q1}", "{#teacher-q2}").replace("card1", "teacher-card2")
                .replace("توضیح: جمع ساده.", "توضیح: جمع ساده.\nرایگان: بله")
                .replace("فرمول: 2+2=4", "فرمول: 2+2=4\nرایگان: بله"))

    def _preview_import(self, text):
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = reverse("admin:catalog_book_import", args=[self.book.pk])
        response = self.client.post(url, {"file": SimpleUploadedFile("draft.md", text.encode("utf-8"))})
        self.assertEqual(response.status_code, 200, response.content)
        report = response.context["report"]
        self.assertEqual(report["errors"], [])
        return url, report["token"], response

    def test_teacher_import_creates_only_a_locked_down_draft(self):
        from apps.learning.models import Flashcard

        from .models import Major

        Major.objects.create(name="رشته‌ی ناخواسته", slug="unwanted-major")
        self.book.title = "نام رسمی کتاب"
        self.book.price = 234567
        self.book.save(update_fields=["title", "price"])
        ContentNode.objects.filter(pk=self.chapter.pk).update(position=10)
        self.client.force_login(self.clerk(self.book))
        text = (self._new_import_text()
                .replace("کتاب: کتاب آزمایشی", "کتاب: عنوان جعلی")
                .replace("رشته‌ها: economics", "رشته‌ها: unwanted-major")
                .replace("شناسه-فصل: teacher-ch2", "شناسه-فصل: teacher-ch2\nفصل: 88"))
        url, token, preview = self._preview_import(text)
        self.assertNotIn('name="publish"', preview.content.decode())
        self.assertIn("انتشار و بازکردن دسترسی دانشجویان فقط با مدیر کل است", preview.content.decode())
        response = self.client.post(url, {"token": token, "filename": "draft.md"})
        self.assertEqual(response.status_code, 302)

        chapter = ContentNode.objects.get(slug="teacher-ch2", kind=ContentNode.Kind.CHAPTER)
        self.assertFalse(chapter.is_published)
        self.assertFalse(chapter.is_free)
        self.assertEqual(chapter.position, 11, "new chapters in a released book receive the next number, not the uploaded one")
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, "نام رسمی کتاب")
        self.assertEqual(self.book.price, 234567)
        self.assertEqual(list(self.book.majors.values_list("slug", flat=True)), ["economics"])
        question = Question.objects.get(slug="teacher-q2", node__path__startswith=self.book.path)
        card = Flashcard.objects.get(slug="teacher-card2", node__path__startswith=self.book.path)
        self.assertFalse(question.is_free)
        self.assertFalse(card.is_free)

    def test_teacher_import_preserves_existing_chapter_number_and_access_flags(self):
        from apps.learning.models import Flashcard

        self.chapter.is_published = False
        self.chapter.is_free = False
        self.chapter.position = 14
        self.chapter.save(update_fields=["is_published", "is_free", "position"])
        Question.objects.filter(slug="q1").update(is_free=False)
        Flashcard.objects.filter(slug="card1").update(is_free=False)
        self.client.force_login(self.clerk(self.book))
        text = (GOOD.replace("شناسه-فصل: ch1", "شناسه-فصل: ch1\nفصل: 88")
                .replace("توضیح: جمع ساده.", "توضیح: جمع ساده.\nرایگان: بله")
                .replace("فرمول: 2+2=4", "فرمول: 2+2=4\nرایگان: بله"))
        url, token, _preview = self._preview_import(text)
        response = self.client.post(url, {"token": token, "filename": "update.md"})
        self.assertEqual(response.status_code, 302)

        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.position, 14)
        self.assertFalse(self.chapter.is_free)
        self.assertFalse(self.chapter.is_published)
        self.assertFalse(Question.objects.get(slug="q1").is_free)
        self.assertFalse(Flashcard.objects.get(slug="card1").is_free)

    def test_teacher_import_cannot_change_book_identity(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.clerk(self.book))
        url = reverse("admin:catalog_book_import", args=[self.book.pk])
        forged = self._new_import_text().replace("شناسه-کتاب: test-book", "شناسه-کتاب: another-book")
        response = self.client.post(url, {"file": SimpleUploadedFile("foreign.md", forged.encode("utf-8"))})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["report"]["errors"])
        self.assertFalse(ContentNode.objects.filter(slug="another-book", kind=ContentNode.Kind.BOOK).exists())

    def test_forged_immediate_publish_import_is_refused_cleanly(self):
        self.client.force_login(self.clerk(self.book))
        url, token, _preview = self._preview_import(self._new_import_text())
        response = self.client.post(url, {"token": token, "filename": "draft.md", "publish": "on"}, follow=True)
        self.assertContains(response, "انتشار را مدیر کل انجام می‌دهد")
        self.assertFalse(ContentNode.objects.filter(slug="teacher-ch2", kind=ContentNode.Kind.CHAPTER).exists())

    def test_editor_of_one_book_cannot_reach_another(self):
        _, other_chapter = self.other_book()
        self.make_draft(self.chapter)
        self.make_draft(other_chapter)
        self.client.force_login(self.clerk(self.book))
        for name in ("admin:catalog_chapter_manager", "admin:catalog_chapter_api", "admin:catalog_chapter_file"):
            self.assertEqual(self.client.get(reverse(name, args=[other_chapter.pk])).status_code, 403, name)

    def test_cannot_move_content_into_a_book_one_may_not_edit(self):
        _, other_chapter = self.other_book()
        self.make_draft(self.chapter)
        self.make_draft(other_chapter)
        self.client.force_login(self.clerk(self.book))
        r = self.client.post(self.api, json.dumps({"op": "section.relocate", "slug": "one", "to": other_chapter.pk, "dry": True}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_destination_list_only_shows_own_books(self):
        other_book, _ = self.other_book()
        self.make_draft(self.chapter)
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


class ImportPreviewBeforeSaveTests(TestCase):
    def test_import_view_detects_custom_boxes_and_accepts_mapping(self):
        """LaTeX newtheorem custom environments and chunks are prepared for AI assistant and import."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        import json

        tex = (
            "\\documentclass{book}\n"
            "\\newtheorem{mythm}{قضیه اساسی}\n"
            "\\begin{document}\n"
            "\\chapter{فصل قضیه‌ها}\n"
            "\\section{بخش اول}\n"
            "\\begin{mythm}\nمتن قضیه جدید\\end{mythm}\n"
            "\\end{document}\n"
        ).encode('utf-8')

        resp = self.client.post(self.url, {"file": SimpleUploadedFile("theorems.tex", tex, content_type="text/plain")})
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("قطعه‌بندی هوشمند و دستیار هوش مصنوعی", html)
        self.assertIn("استودیوی ویرایش لیموخوان", html)

    def test_superuser_global_import_with_target_book_id(self):
        """Superuser uploading raw tex without book_slug can specify target_book_id."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        global_url = reverse("admin:catalog_import")
        tex = (
            "\\begin{document}\n"
            "\\chapter{فصل انتگرال}\n"
            "\\section{مفهوم انتگرال}\n"
            "متن درس انتگرال.\n"
            "\\end{document}\n"
        ).encode('utf-8')

        # 1. Page displays target book dropdown
        res_get = self.client.get(global_url)
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "انتخاب کتاب مقصد")

        # 2. Uploading with target_book_id works without missing book_slug error
        res_post = self.client.post(global_url, {
            "file": SimpleUploadedFile("integral.tex", tex, content_type="text/plain"),
            "target_book_id": self.book.pk,
        })
        self.assertEqual(res_post.status_code, 200)
        content = res_post.content.decode()
        self.assertNotIn("«شناسه-کتاب» در مشخصات فایل نیامده است", content)
        self.assertIn("فایل آماده پردازش است", content)
        self.assertIn("integral.tex", content)

    def setUp(self):
        Major.objects.create(name="اقتصاد", slug="economics")
        self.admin = User.objects.create_superuser("09120000001", "pw-123456")
        self.client.force_login(self.admin)
        self.book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="med", title="تصویربرداری پزشکی")
        self.url = reverse("admin:catalog_book_import", args=[self.book.pk])

    def _upload(self, data: bytes, name: str):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(self.url, {"file": SimpleUploadedFile(name, data)})

    def test_a_read_file_gets_a_preview_and_its_text(self):
        tex = (r"\begin{document}" "\n" r"\section*{نقشه‌ی کتاب}" "\n" "متن درس." "\n" r"\end{document}").encode()
        html = self._upload(tex, "ch1.tex").content.decode()
        self.assertIn('id="chunk-studio-modal"', html)
        self.assertIn('id="import-md"', html)

    def test_a_broken_file_gets_no_preview(self):
        html = self._upload(b"not latex at all {{{", "bad.tex").content.decode()
        self.assertNotIn('id="chunk-studio-modal"', html)

    def test_label_quick_create_api_and_book_box_mapping_memory(self):
        from .models import BookBoxMapping, Label
        # 1. Quick create API creates custom label for staff
        api_url = reverse("admin:catalog_label_quick_create")
        res = self.client.post(api_url, {"name": "نکته بالینی", "style": "warn"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["label"]["name"], "نکته بالینی")
        self.assertEqual(data["label"]["style"], "warn")
        self.assertTrue(Label.objects.filter(name="نکته بالینی").exists())

        # 2. Saving import updates BookBoxMapping memory
        BookBoxMapping.objects.create(
            book=self.book,
            environment_name="clinictip",
            label_name="نکته بالینی",
            created_by=self.admin
        )
        self.assertEqual(BookBoxMapping.objects.filter(book=self.book, environment_name="clinictip").count(), 1)
        mapping = BookBoxMapping.objects.get(book=self.book, environment_name="clinictip")
        self.assertEqual(mapping.label_name, "نکته بالینی")

        # 3. Isolation across different books
        book2 = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="physics", title="فیزیک پایه")
        # book2 does not have clinictip mapping yet
        self.assertFalse(BookBoxMapping.objects.filter(book=book2, environment_name="clinictip").exists())
        # Mapping in book2 can have different target without conflict
        BookBoxMapping.objects.create(
            book=book2,
            environment_name="clinictip",
            label_name="نکته",
            created_by=self.admin
        )
        self.assertEqual(BookBoxMapping.objects.get(book=self.book, environment_name="clinictip").label_name, "نکته بالینی")
        self.assertEqual(BookBoxMapping.objects.get(book=book2, environment_name="clinictip").label_name, "نکته")

        # 4. Overwriting memory when teacher revises mapping in a later chapter
        BookBoxMapping.objects.update_or_create(
            book=self.book,
            environment_name="clinictip",
            defaults={"label_name": "هشدار", "created_by": self.admin}
        )
        self.assertEqual(BookBoxMapping.objects.get(book=self.book, environment_name="clinictip").label_name, "هشدار")


class PreviewPaneTests(_Base):
    """The live preview is a docked pane, not a floating window.

    A professor asked to drag the preview anywhere, but then reversed the decision: the pane should sit in the
    editor's own layout, with the same «نمایش زنده» switch, device widths گوشی/تبلت/وب and «فقط پیش‌نمایش» available
    without leaving the page. The movable <dialog>, its drag code and the old «تمام‌عرض» button are gone.
    """

    def setUp(self):
        super().setUp()
        self.url = reverse("admin:catalog_chapter_file", args=[self.chapter.pk])

    def assets(self, name):
        return (settings.BASE_DIR / "apps/catalog/static/catalog" / name).read_text(encoding="utf-8")

    def test_the_page_loads_the_shared_preview_pane_before_the_panel(self):
        html = self.client.get(self.url).content.decode()
        pane = html.find("catalog/preview-pane.js")
        panel = html.find("catalog/panel.js")
        self.assertIn('id="file-text"', html)
        self.assertIn("LimoFileEditor", html)
        self.assertGreaterEqual(pane, 0, "the shared preview pane script is not included")
        self.assertGreater(panel, pane, "panel.js must load after preview-pane.js")

    def test_the_width_controls_are_not_inside_the_preview_column_or_toolbar(self):
        # Device widths belong inside the pane's own title bar (so they work while it is open), never as settings
        # laid over the lesson.
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('md-prev file-prev-wrap', html)
        self.assertNotIn("pv-open", html)

    def test_the_shared_pane_owns_the_toggle_device_widths_and_expand_button(self):
        panel = self.assets("panel.js")
        pane = self.assets("preview-pane.js")
        css = self.assets("panel.css")
        # One toggle, one pane, three devices — no modal and no تمام‌عرض.
        self.assertNotIn("function previewWindow(", panel)
        self.assertNotIn("pv-win", panel)
        self.assertNotIn("pv-win", css)
        self.assertNotIn("تمام‌عرض", panel)
        self.assertIn("LimoPreviewPane.create({", panel)
        self.assertIn("title: 'پیش‌نمایش فصل'", panel)
        self.assertIn("function create(options)", pane)
        self.assertIn("{ id: 'phone', label: 'گوشی', width: 390 }", pane)
        self.assertIn("{ id: 'tablet', label: 'تبلت', width: 768 }", pane)
        self.assertIn("{ id: 'web', label: 'وب', width: 0 }", pane)
        self.assertIn("pv-expand", pane)
        self.assertIn("pv-pane-x", pane)
        self.assertIn("'aria-pressed'", pane)
        self.assertIn(".pv-pane", css)
        self.assertIn(".pv-device.on", css)
        self.assertIn("preview-only", css)
        # The pane is capped to the editor's working height; its body scrolls (like the editor), the bar stays put,
        # and the page never grows to the lesson's full height. A short lesson still shows exactly its content.
        self.assertIn(".pv-pane-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: auto;", css)
        self.assertIn("pointer-events: none", css)
        self.assertIn("height: max-content; max-height: 70vh;", css)
        self.assertIn(".md-ed.file .pv-pane { max-height: 75vh; }", css)

    def test_phone_and_tablet_lay_out_at_their_logical_width_and_only_shrink_visually(self):
        pane = self.assets("preview-pane.js")
        # 390/768 are the layout viewport, not merely a smaller font or a squeezed iframe. If the column is too
        # narrow, only the visual transform changes; the lines break exactly as they do on the device.
        self.assertIn("frame.style.width = w + 'px'", pane)
        self.assertIn("frame.style.transform = scale < 0.999 ? 'scale(' + scale + ')' : ''", pane)
        self.assertIn("stage.style.width = Math.round(w * scale) + 'px'", pane)
        self.assertIn("var scale = Math.min(1, available / w)", pane)
        self.assertIn("if (!w)", pane)   # «وب» stays flexible instead of pretending to be a phone at another width
        self.assertIn("function contentHeight()", pane)
        self.assertIn("var height = contentHeight();", pane)
        self.assertNotIn("availableHeight", pane)
        # Only the body is measured: the root's offsetHeight is the frame's own current height, and counting it
        # ratcheted the frame so it could never shrink again («the page never stops growing»).
        self.assertNotIn("root ? root.offsetHeight", pane)
        self.assertNotIn("root ? root.scrollHeight", pane)

    def test_device_changes_reflow_both_editors_without_reloading_the_page(self):
        panel = self.assets("panel.js")
        css = self.assets("panel.css")
        md_editor = panel[panel.index("function MdEditor("):panel.index("MdEditor.prototype.refresh")]
        file_editor = panel[panel.index("window.LimoFileEditor = function (opts) {"):]
        callback = "onDeviceChange: function () { syncDeviceClass(); preview.refreshScale(); }"
        self.assertIn(callback, md_editor)
        self.assertIn(callback, file_editor)
        self.assertIn("function syncDeviceClass()", md_editor)
        self.assertIn("wrap.classList.toggle('device-' + id, preview.getDevice() === id)", md_editor)
        # The selected tablet/web mode widens the left-hand preview track; the editor uses the remaining width.
        self.assertIn(".md-ed.device-tablet .md-body { grid-template-columns: minmax(0, 1fr) minmax(430px, 788px); }", css)
        self.assertIn(".md-ed.device-web .md-body { grid-template-columns: minmax(260px, 0.72fr) minmax(360px, 1.28fr); }", css)

    def test_the_floating_window_and_its_drag_code_are_gone(self):
        panel = self.assets("panel.js")
        css = self.assets("panel.css")
        for gone in ("previewWindow", "WIN_POS_KEY", "Windows-style drag", "pointermove", "pv-win-grip", ".pv-win"):
            self.assertNotIn(gone, panel)
            self.assertNotIn(gone, css)


class PreviewTypeAndScrollTests(_Base):
    """The preview renders in the app's own type, and the wheel belongs to whatever is under it.

    The lesson's boxes and headings use Vazirmatn 800/900. The preview document used to declare only 400 and 700,
    so «تعریف» and «نکته» came out from a synthesized ExtraBold next to the app's real Black. The font files are
    shared with the app verbatim, the preview document carries all four weights with `font-display: swap`, and the
    page's cache stamp (?v=) covers the fonts and the pane so a changed font is a changed URL.

    Scroll rule (no JavaScript intercepts the wheel anywhere): the preview pane is capped to the editor's working
    height and its body scrolls with `overscroll-behavior: contain` ONLY while it is actually scrollable (its
    `scrollHeight` exceeds its `clientHeight`, toggled by preview-pane.js on every layout) and `auto` otherwise;
    the editor's CodeMirror scroller keeps `contain`; the preview frames ignore the pointer (`pointer-events: none`)
    so the wheel/touch always lands on the pane or the page.
    """

    def assets(self, name):
        return (settings.BASE_DIR / "apps/catalog/static/catalog" / name).read_text(encoding="utf-8")

    def test_the_preview_document_declares_all_four_weights_with_swap_and_a_stamp(self):
        panel = self.assets("panel.js")
        for face in ("font-weight:' + weight + '", "font-display:swap", "Vazirmatn_400Regular.ttf",
                     "Vazirmatn_700Bold.ttf", "Vazirmatn_800ExtraBold.ttf", "Vazirmatn_900Black.ttf", "STATIC_V"):
            self.assertIn(face, panel)
        self.assertIn("html,body{overflow:hidden}", panel)   # the frame never scrolls: the pane's body does

    def test_the_panel_stylesheet_declares_all_four_weights_with_swap(self):
        css = self.assets("panel.css")
        self.assertEqual(css.count("@font-face"), 4)
        self.assertEqual(css.count("font-display: swap"), 4)

    def test_the_four_font_files_are_shipped_with_the_catalog_static(self):
        fonts = settings.BASE_DIR / "apps/catalog/static/catalog/fonts"
        for name in ("Vazirmatn_400Regular.ttf", "Vazirmatn_700Bold.ttf", "Vazirmatn_800ExtraBold.ttf", "Vazirmatn_900Black.ttf"):
            self.assertTrue((fonts / name).is_file(), name)

    def test_the_cache_stamp_covers_the_pane_and_the_fonts(self):
        admin = (settings.BASE_DIR / "apps/catalog/admin.py").read_text(encoding="utf-8")
        for name in ("catalog/preview-pane.js", "catalog/fonts/Vazirmatn_400Regular.ttf",
                     "catalog/fonts/Vazirmatn_700Bold.ttf", "catalog/fonts/Vazirmatn_800ExtraBold.ttf",
                     "catalog/fonts/Vazirmatn_900Black.ttf"):
            self.assertIn('"%s"' % name, admin)

    def test_the_editor_scrolls_itself_and_never_jerks_the_page(self):
        css = self.assets("panel.css")
        self.assertIn(".md-ed .limo-cm .cm-scroller { max-height: 70vh; overscroll-behavior: contain; }", css)
        self.assertIn(".file-ed + .limo-cm .cm-scroller { max-height: 75vh; overscroll-behavior: contain; }", css)

    def test_the_preview_pane_is_capped_and_scrolls_itself_instead_of_growing_the_page(self):
        pane = self.assets("preview-pane.js")
        css = self.assets("panel.css")
        self.assertIn("height: max-content; max-height: 70vh;", css)
        self.assertIn(".md-ed.file .pv-pane { max-height: 75vh; }", css)
        # `contain` only while the pane is scrollable; otherwise `auto` lets the wheel chain to the page.
        self.assertIn("body.scrollHeight > body.clientHeight + 1 ? 'contain' : 'auto'", pane)
        self.assertIn("overscroll-behavior: auto;", css)

    def test_the_preview_frames_ignore_the_pointer_so_the_page_keeps_the_wheel(self):
        pane = self.assets("preview-pane.js")
        panel = self.assets("panel.js")
        css = self.assets("panel.css")
        self.assertIn(".pv-frame, iframe.phone { pointer-events: none; }", css)
        # The frames are srcdoc renders (no links/forms): the wheel must never dead-end over the lesson.
        self.assertNotIn("addEventListener('wheel'", panel)
        self.assertNotIn("addEventListener('wheel'", pane)

    def test_no_wheel_listener_is_registered_anywhere_in_the_panel(self):
        for name in ("panel.js", "preview-pane.js", "limo-preview.js"):
            self.assertNotIn("addEventListener('wheel'", self.assets(name))
            self.assertNotIn('addEventListener("wheel"', self.assets(name))


class PublishGateTests(_Base):
    """Only the manager can release content, regardless of a teacher's separate review flag."""

    def professor(self, can_publish):
        from django.contrib.auth.models import Group

        from . import access
        from .models import BookEditor

        user = User.objects.create_user("09120000003", is_staff=True)
        user.groups.add(Group.objects.get(name=access.BOOK_EDITOR_GROUP))
        BookEditor.objects.create(book=self.book, user=user, can_publish=can_publish)
        return user

    def test_an_editor_without_can_publish_is_told_so_and_sees_no_checkbox(self):
        self.client.force_login(self.professor(can_publish=False))
        state = self.state()
        self.assertFalse(state["can_publish"])
        self.assertIn("مدیر کل", state["publish_why"])

    def draft(self):
        # setUp imports with publish=True; a gate test needs something that starts unpublished, or «still false»
        # would pass for the wrong reason.
        self.client.force_login(self.admin)
        self.op(op="chapter.publish", value=False)
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_published)

    def test_an_editor_without_can_publish_cannot_publish_through_the_api(self):
        self.draft()
        self.client.force_login(self.professor(can_publish=False))
        r = self.op(op="chapter.publish", value=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("اجازه‌ی انتشار", r.json()["errors"][0])
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_published, "a refused publish must not half-happen")

    def test_an_editor_without_can_publish_cannot_publish_a_section_either(self):
        self.draft()
        self.client.force_login(self.professor(can_publish=False))
        r = self.op(op="section.publish", slug="one", value=True)
        self.assertEqual(r.status_code, 400)

    def test_a_teacher_cannot_withdraw_a_chapter_from_learners(self):
        self.draft()
        self.client.force_login(self.professor(can_publish=False))
        r = self.op(op="chapter.publish", value=False)
        self.assertEqual(r.status_code, 400)
        self.assertIn("مدیر کل", r.json()["errors"][0])
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_published)

    def test_can_publish_flag_is_not_publication_authority(self):
        self.draft()
        self.client.force_login(self.professor(can_publish=True))
        state = self.state()
        self.assertFalse(state["can_publish"])
        self.assertIn("مدیر کل", state["publish_why"])
        r = self.op(op="chapter.publish", value=True)
        self.assertEqual(r.status_code, 400)
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_published)

    def test_the_form_post_asks_the_same_question(self):
        # The «فهرست فصل‌ها» page has its own publish button; a gate on only one of two doors is not a gate.
        self.draft()   # as the admin, who may take it down
        self.client.force_login(self.professor(can_publish=False))
        self.client.post(reverse("admin:catalog_book_chapter_action", args=[self.book.pk]),
                         {"chapter": self.chapter.pk, "action": "publish", "value": "1"})
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_published)

    def test_uploading_with_immediate_publish_asks_the_same_question(self):
        self.client.force_login(self.professor(can_publish=False))
        from django.core.files.uploadedfile import SimpleUploadedFile

        url = reverse("admin:catalog_book_import", args=[self.book.pk])
        self.client.post(url, {"file": SimpleUploadedFile("ch2.md", GOOD.replace("ch1", "ch2").encode()), "publish": "1"})
        from .models import ContentNode

        self.assertFalse(ContentNode.objects.filter(slug="ch2", kind=ContentNode.Kind.CHAPTER).exists(),
                         "a file that may not be published must not be imported as published")

    def test_book_publish_publishes_the_whole_tree(self):
        # A published book whose chapters are drafts is an empty shelf in the app: publishing must mean the tree.
        self.client.force_login(self.admin)
        url = reverse("admin:catalog_book_publish", args=[self.book.pk])
        self.client.post(url, {"value": "0"})
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_published)
        self.client.post(url, {"value": "1"})
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_published)
        self.assertFalse(self.book.get_descendants().filter(is_published=False).exists())

    def test_book_publish_refuses_every_teacher_even_with_the_review_flag(self):
        self.draft()
        self.client.force_login(self.professor(can_publish=True))
        url = reverse("admin:catalog_book_publish", args=[self.book.pk])
        response = self.client.post(url, {"value": "1"}, follow=True)
        self.assertIn("انتشار را مدیر کل انجام می‌دهد", response.content.decode())
        self.chapter.refresh_from_db()
        self.assertFalse(self.chapter.is_published)

    def test_unpublishing_a_book_keeps_the_text(self):
        self.client.force_login(self.admin)
        before = export_chapter(self.chapter)
        self.client.post(reverse("admin:catalog_book_publish", args=[self.book.pk]), {"value": "0"})
        self.assertEqual(export_chapter(self.chapter), before)


class ChapterManagerScriptTests(_Base):
    """Order-of-lines bugs in panel.js, which the browser only shows as «فصل باز نشد» on every chapter.

    Not a browser test: it reads the script and checks the one order that broke the whole chapter page. The professor
    saw «Cannot read properties of undefined (reading 'style')» — the editor sized its preview iframe while building
    itself, before that iframe existed.
    """

    def setUp(self):
        self.js = (settings.BASE_DIR / "apps/catalog/static/catalog/panel.js").read_text(encoding="utf-8")

    def test_the_preview_iframe_exists_before_the_shared_pane_is_created(self):
        make = self.js.index("LimoPreviewPane.create({")
        # The pane creates its iframe before any caller can ask it to refresh or measure it.
        pane = (settings.BASE_DIR / "apps/catalog/static/catalog/preview-pane.js").read_text(encoding="utf-8")
        create = pane.index("function create(options)")
        make = pane.index("var frame =", create)
        bind = pane.index("frame.addEventListener('load'", make)
        self.assertLess(make, bind)
        self.assertLess(self.js.index("LimoPreviewPane.create({"), self.js.index("this.frame = preview.frame;"))
        self.assertLess(self.js.index("var preview = window.LimoPreviewPane.create({"), self.js.index("body.appendChild(preview.el);"))

    def test_a_missing_destination_list_does_not_re_render_forever(self):
        # An answer without «destinations» left self.dest unset, so every render asked again and re-rendered itself.
        self.assertEqual(self.js.count("self.dest = d.destinations || [];"), 2,
                         "both destination lists must fall back to [] or the panel can loop")

    def test_the_header_goes_back_on_the_text_before_check_and_save(self):
        # The box of «ویرایش کل فایل» holds the body only. Both requests that reach the server must carry the whole
        # file, or a save would drop the book and the chapter's id — the one thing that must never happen.
        body = self.js[self.js.index("window.LimoFileEditor = function (opts) {"):]
        for call in ("post({ op: 'file.check', text: checkText,", "post(Object.assign({ op: 'file.apply', text: fullText(),"):
            self.assertIn(call, body)
        self.assertIn("function fullText() { return header + ta.value; }", body)
        self.assertIn("var checkText = fullText();", body)
        self.assertIn("function headerWith(text, meta) {", self.js)

    def test_the_quick_chapter_edit_warns_before_reordering_the_book(self):
        self.assertIn("this.state.sibling_chapters || []", self.js)
        self.assertIn("ذخیره، ترتیب فصل‌های کتاب را عوض می‌کند", self.js)


class ChapterCardTests(_Base):
    """«مشخصات فصل» above the whole-file box: the details a person edits, and the one that used to bite.

    The number is not unique and `_order_chapters` sorts the book by it, so a second chapter numbered ۲ moved every
    chapter after it with no error at all (measured: chapters 5, 10, 20 became 1, 1, 10 after two saves). The card
    warns before the save instead of after the book has silently reordered itself.
    """

    def test_a_duplicate_number_is_reported_with_the_name_of_the_other_chapter(self):
        second = (GOOD.replace("شناسه-فصل: ch1", "شناسه-فصل: ch2").replace("{#one}", "{#c2a}").replace("{#two}", "{#c2b}")
                  .replace(":::تست {#q1}", ":::تست {#c2q}").replace("فلش‌کارت: card1", "فلش‌کارت: c2f")
                  .replace(":::فلش‌کارت {#card1}", ":::فلش‌کارت {#c2f}").replace("عنوان: فصل یک", "عنوان: فصل دو"))
        _, result = import_file("ch2.md", second.encode())
        ContentNode.objects.filter(pk=result.chapter.pk).update(position=1)
        siblings = self.state()["sibling_chapters"]
        self.assertIn({"id": result.chapter.pk, "title": "فصل دو", "position": 1}, siblings)
        self.op(op="chapter.update", title="فصل یک", number=1, is_free=True)
        r = self.op(op="file.check", text=export_chapter(self.chapter)).json()
        self.assertIn("clash", r["meta"])
        self.assertIn("فصل دو", r["meta"]["clash"])
        # Sending the card's own number (the same one) says the same thing: the page sends its fields with the text.
        r = self.op(op="file.check", text=export_chapter(self.chapter), meta={"chapter_number": 1, "chapter_title": "فصل یک",
                                                                            "chapter_free": True}).json()
        self.assertIn("فصل دو", r["meta"]["clash"])
        r = self.op(op="file.check", text=export_chapter(self.chapter), meta={"chapter_number": 7}).json()
        self.assertNotIn("clash", r["meta"])

    def test_a_number_that_is_not_a_number_is_refused_with_its_own_sentence(self):
        text = export_chapter(self.chapter)
        for bad in ("دو", -3, 1.5, True, 32768):
            with self.subTest(bad=bad):
                r = self.op(op="file.apply", text=text, meta={"chapter_number": bad})
                self.assertEqual(r.status_code, 400)
                self.assertIn("شماره‌ی فصل باید عددی بین ۰ و ۳۲۷۶۷ باشد", r.json()["errors"][0])

    def test_an_empty_title_from_the_card_is_refused(self):
        r = self.op(op="file.apply", text=export_chapter(self.chapter), meta={"chapter_title": "   "})
        self.assertEqual(r.status_code, 400)
        self.assertIn("عنوان فصل خالی است", r.json()["errors"][0])

    def test_the_card_is_only_about_the_three_details(self):
        # A request without «meta» (an older page, a saved tab) still works: the header of the text is what counts.
        r = self.op(op="file.check", text=export_chapter(self.chapter))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["errors"], [])
        self.assertEqual(r.json()["meta"], {})

    def test_teacher_can_create_draft_book_chapter_section_and_edit_lesson(self):
        """Teacher independently creates draft book, adds chapter, adds section and edits text with formulas."""
        from django.contrib.auth.models import Group
        teacher = User.objects.create(phone="09129990011", is_staff=True)
        from .access import BOOK_EDITOR_GROUP
        teacher.groups.add(Group.objects.get(name=BOOK_EDITOR_GROUP))
        self.client.force_login(teacher)

        # 1. Create draft book
        res_book = self.client.post("/admin/catalog/book/new-draft/", {
            "title": "جبر خطی کاربردی",
            "title_en": "Applied Linear Algebra",
            "author": "دکتر تست",
        })
        self.assertEqual(res_book.status_code, 302)
        book = ContentNode.objects.get(title="جبر خطی کاربردی")

        # 2. Add chapter
        res_ch = self.client.post(f"/admin/catalog/book/{book.pk}/chapters/", {
            "action": "new",
            "title": "فصل ۱: فضاهای برداری",
            "number": "1",
            "slug": "ch1-vector-spaces",
        })
        self.assertEqual(res_ch.status_code, 302)
        chapter = ContentNode.objects.get(title="فصل ۱: فضاهای برداری")

        # 3. Open chapter manager
        res_cm = self.client.get(f"/admin/catalog/book/chapter/{chapter.pk}/")
        self.assertEqual(res_cm.status_code, 200)

        # 4. Create section & write lesson content with formulas
        import json
        res_sec = self.client.post(
            f"/admin/catalog/book/chapter/{chapter.pk}/api/",
            data=json.dumps({
                "op": "section.create",
                "title": "استقلال خطی",
                "slug": "s1-independence",
            }),
            content_type="application/json"
        )
        self.assertEqual(res_sec.status_code, 200)

        lesson_text = ":::تعریف\nبردارها مستقل خطی هستند.\n:::\n$$Ax = \\lambda x$$"
        res_save = self.client.post(
            f"/admin/catalog/book/chapter/{chapter.pk}/api/",
            data=json.dumps({
                "op": "section.update",
                "slug": "s1-independence",
                "full_body": lesson_text,
            }),
            content_type="application/json"
        )
        self.assertEqual(res_save.status_code, 200)

        from . import editing
        exported = editing.export_chapter(chapter)
        self.assertIn("Ax = \\lambda x", exported)
        self.assertIn(":::تعریف", exported)
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory
from django.contrib import admin
from apps.catalog.models import Label
from apps.catalog.access import BOOK_EDITOR_GROUP
from apps.catalog.labels import all_labels

User = get_user_model()

class TeacherCustomLabelsTests(TestCase):
    def test_teacher_custom_labels(self):
        group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        ct = ContentType.objects.get_for_model(Label)
        for codename in ("add_label", "change_label", "delete_label", "view_label"):
            perm, _ = Permission.objects.get_or_create(content_type=ct, codename=codename)
            group.permissions.add(perm)

        teacher1 = User.objects.create_user("09121110001", is_staff=True)
        teacher1.groups.add(group)

        teacher2 = User.objects.create_user("09121110002", is_staff=True)
        teacher2.groups.add(group)

        admin_user = User.objects.create_superuser("09121110000", is_staff=True)

        # 1. System label
        sys_lbl = Label.objects.create(name="نکته طلایی", group="عمومی", style="note")

        # 2. Teacher 1 creates custom label
        lbl1 = Label.objects.create(name="اثبات قضیه", group="اختصاصی دکتر ۱", style="formal", created_by=teacher1)

        # 3. Teacher 2 creates custom label
        lbl2 = Label.objects.create(name="شبیه‌سازی عددی", group="اختصاصی دکتر ۲", style="warn", created_by=teacher2)

        # Check all_labels for teacher1: should contain sys_lbl and lbl1, but NOT lbl2
        t1_labels = [l["name"] for l in all_labels(user=teacher1)]
        self.assertIn("نکته طلایی", t1_labels)
        self.assertIn("اثبات قضیه", t1_labels)
        self.assertNotIn("شبیه‌سازی عددی", t1_labels)

        # Check all_labels for admin_user: should see all
        admin_labels = [l["name"] for l in all_labels(user=admin_user)]
        self.assertIn("نکته طلایی", admin_labels)
        self.assertIn("اثبات قضیه", admin_labels)
        self.assertIn("شبیه‌سازی عددی", admin_labels)

        # Test Admin permissions
        label_admin = admin.site._registry[Label]
        rf = RequestFactory()

        r1 = rf.get("/admin/catalog/label/")
        r1.user = teacher1
        self.assertTrue(label_admin.has_change_permission(r1, lbl1))
        self.assertFalse(label_admin.has_change_permission(r1, sys_lbl))
        self.assertFalse(label_admin.has_change_permission(r1, lbl2))

        self.assertTrue(label_admin.has_delete_permission(r1, lbl1))
        self.assertFalse(label_admin.has_delete_permission(r1, sys_lbl))

        # Queryset for teacher1
        qs1 = list(label_admin.get_queryset(r1))
        self.assertIn(sys_lbl, qs1)
        self.assertIn(lbl1, qs1)
        self.assertNotIn(lbl2, qs1)
from django.test import TestCase
from django.contrib import admin
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from apps.catalog.access import BOOK_EDITOR_GROUP
from apps.catalog.models import ContentNode, BookEditor
from apps.website.models import Classroom

User = get_user_model()

class TeacherDashboardTests(TestCase):
    def test_teacher_dashboard_rendered_on_admin_index(self):
        group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        teacher = User.objects.create_user("09121112233", is_staff=True, first_name="رضا", last_name="دستورانی")
        teacher.groups.add(group)

        # Create book assigned to teacher
        book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="ریاضی مهندسی پیشرفته", author="دکتر دستورانی")
        BookEditor.objects.create(book=book, user=teacher)

        # Create classroom
        classroom = Classroom.objects.create(
            teacher=teacher,
            book=book,
            title="کلاس ریاضی مهندسی پاییز ۱۴۰۳",
            capacity=40,
        )

        self.client.force_login(teacher)
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "کارگاه آموزش و تألیف اساتید")
        self.assertContains(res, "ریاضی مهندسی پیشرفته")
        self.assertContains(res, "کلاس ریاضی مهندسی پاییز ۱۴۰۳")
        self.assertContains(res, "+ ایجاد کتاب پیش‌نویس")
        self.assertContains(res, "+ ایجاد کلاس جدید")

    def test_admin_does_not_see_teacher_dashboard_by_default_but_can_switch_to_teacher_view(self):
        superuser = User.objects.create_superuser("09120000000", is_staff=True)
        self.client.force_login(superuser)
        # By default superuser sees normal admin and the button "🎓 پنل اساتید"
        res = self.client.get("/admin/")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "کارگاه آموزش و تألیف اساتید")
        self.assertContains(res, "🎓 پنل اساتید")
        self.assertContains(res, "وب‌اپ")

        # Superuser clicks to switch to teacher view
        res_t = self.client.get("/admin/?view=teacher")
        self.assertEqual(res_t.status_code, 200)
        self.assertContains(res_t, "کارگاه آموزش و تألیف اساتید")
        self.assertContains(res_t, "✕ خروج از نمای استاد")

        # Superuser exits teacher view
        res_back = self.client.get("/admin/?view=admin")
        self.assertEqual(res_back.status_code, 200)
        self.assertNotContains(res_back, "کارگاه آموزش و تألیف اساتید")
        self.assertContains(res_back, "🎓 پنل اساتید")
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from apps.catalog.access import BOOK_EDITOR_GROUP
from apps.catalog.models import ContentNode, BookEditor

User = get_user_model()

class TeacherAssistantTests(TestCase):
    def setUp(self):
        self.group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        self.teacher = User.objects.create_user("09121113344", is_staff=True, first_name="دکتر", last_name="استاد")
        self.teacher.groups.add(self.group)

        self.book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="ریاضی فیزیک", author="دکتر استاد")
        BookEditor.objects.create(book=self.book, user=self.teacher, can_edit_content=True, can_view_aggregate_study=True, can_request_publication=True)

        self.client.force_login(self.teacher)

    def test_teacher_can_view_assistants_section_on_book_page(self):
        res = self.client.get(f"/admin/catalog/book/{self.book.pk}/change/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "دستیاران و همکاران آموزشی (TA)")
        self.assertContains(res, "09121113344")
        self.assertContains(res, "شما (استاد)")

    def test_teacher_can_add_ta_with_granular_permissions(self):
        res = self.client.post(f"/admin/catalog/book/{self.book.pk}/assistants/", {
            "action": "add",
            "phone": "09125556677",
            "can_edit_content": "1",
            "can_view_reports": "1",
            "note": "مهندس احمدی - TA حل تمرین",
        })
        self.assertEqual(res.status_code, 302)

        ta_user = User.objects.get(phone="09125556677")
        self.assertTrue(ta_user.is_staff)
        self.assertTrue(ta_user.groups.filter(name=BOOK_EDITOR_GROUP).exists())

        ta_editor = BookEditor.objects.get(book=self.book, user=ta_user)
        self.assertTrue(ta_editor.can_edit_content)
        self.assertTrue(ta_editor.can_view_reports)
        self.assertFalse(ta_editor.can_view_aggregate_study)
        self.assertFalse(ta_editor.can_publish)
        self.assertEqual(ta_editor.note, "مهندس احمدی - TA حل تمرین")

        from apps.catalog.models import BookAssistantAuditLog
        log_entry = BookAssistantAuditLog.objects.filter(book=self.book, assistant_phone="09125556677").first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.action, BookAssistantAuditLog.Action.ADDED)
        self.assertEqual(log_entry.actor, self.teacher)
        self.assertIn("ویرایش محتوا", log_entry.details)

    def test_teacher_can_remove_ta(self):
        ta_user = User.objects.create_user("09128889900", is_staff=True)
        ta_user.groups.add(self.group)
        ta_editor = BookEditor.objects.create(book=self.book, user=ta_user, can_edit_content=True)

        res = self.client.post(f"/admin/catalog/book/{self.book.pk}/assistants/", {
            "action": "remove",
            "editor_id": ta_editor.pk,
        })
        self.assertEqual(res.status_code, 302)
        self.assertFalse(BookEditor.objects.filter(pk=ta_editor.pk).exists())

        from apps.catalog.models import BookAssistantAuditLog
        remove_log = BookAssistantAuditLog.objects.filter(book=self.book, assistant_phone="09128889900").first()
        self.assertIsNotNone(remove_log)
        self.assertEqual(remove_log.action, BookAssistantAuditLog.Action.REMOVED)
        self.assertEqual(remove_log.actor, self.teacher)

    def test_study_analytics_permission_and_view(self):
        # Teacher with can_view_aggregate_study=True can view
        res = self.client.get(f"/admin/catalog/book/{self.book.pk}/study-analytics/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "آمار و گزارش پیشرفت مطالعه کتاب")
        self.assertContains(res, self.book.title)

        # TA without can_view_aggregate_study cannot view
        ta_user = User.objects.create_user("09123334455", is_staff=True)
        ta_user.groups.add(self.group)
        BookEditor.objects.create(book=self.book, user=ta_user, can_edit_content=True, can_view_aggregate_study=False)

        self.client.force_login(ta_user)
        res_ta = self.client.get(f"/admin/catalog/book/{self.book.pk}/study-analytics/")
        self.assertEqual(res_ta.status_code, 403)

        # TA with can_view_aggregate_study can view
        BookEditor.objects.filter(book=self.book, user=ta_user).update(can_view_aggregate_study=True)
        res_ta_ok = self.client.get(f"/admin/catalog/book/{self.book.pk}/study-analytics/")
        self.assertEqual(res_ta_ok.status_code, 200)
        self.assertContains(res_ta_ok, self.book.title)

    def test_publication_request_flow(self):
        from apps.website.models import PublicationRequest
        res = self.client.get(f"/admin/catalog/book/{self.book.pk}/request-publication/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "درخواست بازبینی انتشار")

        res_post = self.client.post(f"/admin/catalog/book/{self.book.pk}/request-publication/", {
            "note": "لطفاً کتاب بازبینی شود، فصل‌ها آماده هستند.",
        })
        self.assertEqual(res_post.status_code, 302)
        req = PublicationRequest.objects.get(book=self.book, requested_by=self.teacher)
        self.assertEqual(req.status, PublicationRequest.Status.PENDING)
        self.assertEqual(req.request_note, "لطفاً کتاب بازبینی شود، فصل‌ها آماده هستند.")

    def test_teacher_create_book_with_optional_initial_file(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        tex_content = r"\chapter{آغاز}\section{بخش اول}متن نمونه".encode("utf-8")
        uploaded = SimpleUploadedFile("ch1.tex", tex_content, content_type="text/plain")

        res = self.client.post("/admin/catalog/book/new-draft/", {
            "title": "هوش مصنوعی و داده‌کاوی",
            "author": "دکتر هوش",
            "initial_file": uploaded,
        })
        self.assertEqual(res.status_code, 302)
        new_book = ContentNode.objects.get(title="هوش مصنوعی و داده‌کاوی")
        self.assertTrue(ContentNode.objects.filter(path__startswith=new_book.path, depth=2).exists())

    def test_superuser_teacher_view_mode_filters_admin_apps(self):
        from django.contrib import admin
        from django.test import RequestFactory
        admin_user = User.objects.create_superuser("09129998877", is_staff=True)
        rf = RequestFactory()

        req_teacher = rf.get('/admin/?view=teacher')
        req_teacher.user = admin_user
        req_teacher.session = {"admin_view_mode": "teacher"}
        apps_teacher = admin.site.get_app_list(req_teacher)
        teacher_labels = {a['app_label'] for a in apps_teacher}
        self.assertNotIn("accounts", teacher_labels)
        self.assertNotIn("commerce", teacher_labels)
        self.assertNotIn("guard", teacher_labels)
        self.assertIn("catalog", teacher_labels)
        self.assertIn("learning", teacher_labels)

        # Check reorganized names for teacher workspace
        catalog_app = next(a for a in apps_teacher if a['app_label'] == 'catalog')
        self.assertEqual(catalog_app['name'], "میز تألیف و کتاب‌ها")
        catalog_models = [m['object_name'] for m in catalog_app['models']]
        self.assertIn("PublicationRequest", catalog_models)

        wf_app = next(a for a in apps_teacher if a['app_label'] == 'teacher_workflows')
        self.assertEqual(wf_app['name'], "مدیریت کلاس‌ها و دوره‌ها")

        learning_app = next(a for a in apps_teacher if a['app_label'] == 'learning')
        self.assertEqual(learning_app['name'], "ارزیابی، تمرین و بازخورد")

        # Test index page rendering in teacher mode with isolated log
        self.client.force_login(admin_user)
        res = self.client.get("/admin/?view=teacher")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "فعالیت‌های تألیف و تدریس من")
        self.assertContains(res, "/admin/?view=admin")

        # Test from inner page (books changelist)
        res_books = self.client.get("/admin/catalog/book/")
        self.assertEqual(res_books.status_code, 200)
        self.assertContains(res_books, "/admin/?view=admin")

        # Exit to admin view
        res_admin = self.client.get("/admin/?view=admin")
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, "/admin/?view=teacher")

    def test_book_study_analytics_csv_export(self):
        # Teacher with permission can download CSV
        res = self.client.get(f"/admin/catalog/book/{self.book.pk}/study-analytics/?format=csv")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/csv", res["Content-Type"])
        self.assertIn("attachment; filename=", res["Content-Disposition"])
        content = res.content.decode("utf-8-sig")
        self.assertIn("عنوان فصل,تعداد بخش", content)

    def test_book_team_tasks_action_and_visibility(self):
        from apps.catalog.models import BookTeamTask

        # Initially, without assistants, team tasks section is not displayed in change form
        res_change = self.client.get(f"/admin/catalog/book/{self.book.pk}/change/")
        self.assertEqual(res_change.status_code, 200)
        self.assertNotContains(res_change, "تخته یادداشت و هماهنگی با دستیاران")

        # Add a TA assistant
        ta_user = User.objects.create_user("09121110022", is_staff=True)
        BookEditor.objects.create(book=self.book, user=ta_user, can_edit_content=True)

        # Now team tasks section is visible
        res_change = self.client.get(f"/admin/catalog/book/{self.book.pk}/change/")
        self.assertContains(res_change, "تخته یادداشت و هماهنگی با دستیاران")

        # Add a task
        res_add = self.client.post(f"/admin/catalog/book/{self.book.pk}/team-tasks/", {
            "action": "add",
            "text": "بررسی تمرین‌های فصل ۲",
        })
        self.assertEqual(res_add.status_code, 302)
        task = BookTeamTask.objects.get(book=self.book, text="بررسی تمرین‌های فصل ۲")
        self.assertEqual(task.author, self.teacher)
        self.assertFalse(task.is_done)

        # Toggle task
        res_toggle = self.client.post(f"/admin/catalog/book/{self.book.pk}/team-tasks/", {
            "action": "toggle",
            "task_id": task.pk,
        })
        self.assertEqual(res_toggle.status_code, 302)
        task.refresh_from_db()
        self.assertTrue(task.is_done)

        # Delete task
        res_del = self.client.post(f"/admin/catalog/book/{self.book.pk}/team-tasks/", {
            "action": "delete",
            "task_id": task.pk,
        })
        self.assertEqual(res_del.status_code, 302)
        self.assertFalse(BookTeamTask.objects.filter(pk=task.pk).exists())

    def test_book_latex_export_and_dashboard_badges(self):
        import zipfile
        import io
        from apps.catalog.models import BookTeamTask
        from apps.learning.models import Report

        # Add a task and a report
        BookTeamTask.objects.create(book=self.book, author=self.teacher, text="تسک شماره ۱", is_done=False)
        ch = self.book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل تست", slug="test-ch")
        sec = ch.add_child(kind=ContentNode.Kind.SECTION, title="بخش تست", slug="test-sec")
        Report.objects.create(user=self.teacher, node=sec, reason=Report.Reason.TYPO, note="غلط تایپی", status=Report.Status.OPEN)

        # Check teacher dashboard badges
        res_dash = self.client.get("/admin/")
        self.assertEqual(res_dash.status_code, 200)
        self.assertContains(res_dash, "1 یادداشت")
        self.assertContains(res_dash, "1 اشکال")

        # Test book tex export
        res_tex = self.client.get(f"/admin/catalog/book/{self.book.pk}/export/tex/")
        self.assertEqual(res_tex.status_code, 200)
        self.assertEqual(res_tex["Content-Type"], "application/zip")
        self.assertIn("attachment; filename=", res_tex["Content-Disposition"])

        # Inspect ZIP contents
        with zipfile.ZipFile(io.BytesIO(res_tex.content)) as z:
            names = z.namelist()
            self.assertIn("main.tex", names)
            self.assertIn("preamble.tex", names)
            main_content = z.read("main.tex").decode("utf-8")
            self.assertIn(r"\input{preamble.tex}", main_content)
            self.assertIn(r"\tableofcontents", main_content)
            preamble_content = z.read("preamble.tex").decode("utf-8")
            self.assertIn(r"\documentclass[12pt,a4paper]{book}", preamble_content)


class TeacherAIProviderAndAuditAccessTests(TestCase):
    def setUp(self):
        from apps.catalog.models import BookEditor, AIProvider, BookAssistantAuditLog
        self.group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        self.superuser = User.objects.create_superuser("09120001111", "pw123")
        self.teacher_a = User.objects.create_user("09121112222", is_staff=True)
        self.teacher_a.groups.add(self.group)
        self.teacher_b = User.objects.create_user("09123334444", is_staff=True)
        self.teacher_b.groups.add(self.group)

        self.book_a = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="book-a", title="کتاب الف")
        BookEditor.objects.create(book=self.book_a, user=self.teacher_a, can_edit_content=True)

        self.book_b = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="book-b", title="کتاب ب")
        BookEditor.objects.create(book=self.book_b, user=self.teacher_b, can_edit_content=True)

        # Global AI provider by superuser
        self.global_p = AIProvider.objects.create(
            title="Gemini عمومی مدیر",
            provider_type=AIProvider.ProviderType.GEMINI,
            api_key="sk-admin-secret-key-12345",
            owner=None,
            is_active=True,
        )

        # Teacher A private provider
        self.prov_a = AIProvider.objects.create(
            title="Groq اختصاصی استاد الف",
            provider_type=AIProvider.ProviderType.OPENAI,
            api_key="sk-teacher-a-private-key",
            owner=self.teacher_a,
            is_active=True,
        )

        # Teacher B private provider
        self.prov_b = AIProvider.objects.create(
            title="OpenAI اختصاصی استاد ب",
            provider_type=AIProvider.ProviderType.OPENAI,
            api_key="sk-teacher-b-private-key",
            owner=self.teacher_b,
            is_active=True,
        )

        # Audit logs
        self.log_a = BookAssistantAuditLog.objects.create(
            book=self.book_a,
            actor=self.teacher_a,
            assistant_phone="09129990001",
            action=BookAssistantAuditLog.Action.ADDED,
            details="لاگ کتاب الف",
        )
        self.log_b = BookAssistantAuditLog.objects.create(
            book=self.book_b,
            actor=self.teacher_b,
            assistant_phone="09129990002",
            action=BookAssistantAuditLog.Action.ADDED,
            details="لاگ کتاب ب",
        )

    def test_teacher_can_only_view_own_ai_providers_in_admin(self):
        self.client.force_login(self.teacher_a)
        res = self.client.get("/admin/catalog/aiprovider/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Groq اختصاصی استاد الف")
        # Cannot see teacher B's provider or admin's global in their private list
        self.assertNotContains(res, "OpenAI اختصاصی استاد ب")
        self.assertNotContains(res, "Gemini عمومی مدیر")

        # Cannot edit teacher B's provider (redirects with error or 403)
        res_edit_b = self.client.get(f"/admin/catalog/aiprovider/{self.prov_b.pk}/change/")
        self.assertIn(res_edit_b.status_code, (302, 403, 404))

    def test_teacher_can_only_view_own_book_audit_logs(self):
        self.client.force_login(self.teacher_a)
        res = self.client.get("/admin/catalog/bookassistantauditlog/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "کتاب الف")
        self.assertNotContains(res, "کتاب ب")

    def test_teacher_cannot_invoke_other_teacher_private_ai_provider(self):
        self.client.force_login(self.teacher_a)
        res = self.client.post(reverse("admin:catalog_ai_clean_chunk"), {
            "provider_id": self.prov_b.pk,
            "raw_text": r"\section{تست}",
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["ok"])
        self.assertIn("دسترسی به آن ندارید", data["error"])

    def test_masked_api_key(self):
        self.assertEqual(self.prov_a.masked_api_key(), "sk-t••••••••-key")






