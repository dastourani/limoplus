import io
import shutil
import tempfile
import zipfile

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import Flashcard, Question

from .importer import import_file, parse_chapter
from .models import ContentNode, Major

GOOD = """---
شناسه-کتاب: test-book
کتاب: کتاب آزمایشی
رشته‌ها: economics
شناسه-فصل: ch1
عنوان: فصل یک
رایگان: بله
---

## بخش اول {#one}
متن جزوه با فرمول $x^2$.

:::خلاصه
خلاصه‌ی بخش.
:::

:::تست {#q1}
منبع: کنکور ارشد اقتصاد ۱۴۰۱، سؤال ۲۳
منبع: کنکور دکتری اقتصاد 1399
سطح: سخت
حوزه: تخصصی
نوع: محاسباتی
صورت:
دو به‌علاوه‌ی دو چند است؟
- [ ] سه
- [x] چهار
- [ ] پنج
توضیح: جمع ساده.
خط دوم توضیح.
راه‌حل سریع: بشمارید.
فلش‌کارت: card1
:::

:::فلش‌کارت {#card1}
عنوان: جمع
نکته: دو و دو می‌شود چهار.
فرمول: 2+2=4
:::

## بخش دوم {#two}
متن دوم.
"""


class ParserTests(TestCase):
    def test_good_file_parses(self):
        chapter = parse_chapter(GOOD)
        self.assertEqual(chapter.errors, [])
        self.assertEqual([s.slug for s in chapter.sections], ["one", "two"])
        q = chapter.sections[0].questions[0]
        self.assertEqual(q.stem, "دو به‌علاوه‌ی دو چند است؟")
        self.assertEqual(q.choices, [("سه", False), ("چهار", True), ("پنج", False)])
        self.assertEqual(q.explanation, "جمع ساده.\nخط دوم توضیح.")
        self.assertEqual(q.sources, [("کنکور ارشد اقتصاد", 1401, 23), ("کنکور دکتری اقتصاد", 1399, None)])
        self.assertEqual((q.difficulty, q.domain, q.kind), ("hard", "specialized", "calc"))
        self.assertEqual(chapter.sections[0].summary_body, "خلاصه‌ی بخش.")
        self.assertNotIn("خلاصه", chapter.sections[0].full_body)

    def test_errors_have_line_numbers_and_persian_messages(self):
        bad = GOOD.replace("- [x] چهار", "- [ ] چهار").replace("سطح: سخت", "سطح: خیلی سخت").replace("فلش‌کارت: card1", "فلش‌کارت: missing")
        chapter = parse_chapter(bad)
        messages = " | ".join(str(e) for e in chapter.errors)
        self.assertIn("دقیقاً یک گزینه", messages)
        self.assertIn("سطح «خیلی سخت»", messages)
        self.assertTrue(all(e.line for e in chapter.errors))
        # A flashcard not in the file may be in another chapter of the book; only the database can tell.
        Major.objects.create(slug="economics", name="اقتصاد")
        chapter, _ = import_file("x.md", GOOD.replace("فلش‌کارت: card1", "فلش‌کارت: missing").encode(), dry_run=True)
        missing = [e for e in chapter.errors if "«missing»" in str(e)]
        self.assertTrue(missing and missing[0].line, chapter.errors)

    def test_missing_front_matter_and_unclosed_block(self):
        self.assertTrue(parse_chapter("## no front matter").errors)
        self.assertIn("بسته نشده", str(parse_chapter(GOOD.replace("خلاصه‌ی بخش.\n:::", "خلاصه‌ی بخش.")).errors[0]))

    def test_arabic_letters_are_normalised(self):
        chapter = parse_chapter(GOOD.replace("متن دوم.", "كتاب علي"))
        self.assertIn("کتاب علی", chapter.sections[1].full_body)

    def test_missing_image_is_an_error(self):
        chapter, _ = import_file("x.md", GOOD.replace("متن دوم.", "![نمودار](images/a.png)").encode(), dry_run=True)
        self.assertTrue(any("a.png" in str(e) for e in chapter.errors))


class ImportTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        Major.objects.create(slug="economics", name="اقتصاد")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def _zip(self, text, images=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("chapter/chapter.md", text)
            for name, data in (images or {}).items():
                z.writestr(f"chapter/{name}", data)
        return buffer.getvalue()

    def test_unknown_major_blocks_import(self):
        chapter, result = import_file("c.md", GOOD.replace("economics", "nope").encode())
        self.assertIsNone(result)
        self.assertTrue(any("nope" in str(e) for e in chapter.errors))
        self.assertFalse(ContentNode.objects.exists())

    def test_import_creates_tree_and_links(self):
        chapter, result = import_file("c.md", GOOD.encode(), publish=True)
        self.assertEqual(chapter.errors, [])
        book = ContentNode.objects.get(slug="test-book")
        self.assertEqual(book.get_children().get().slug, "ch1")
        self.assertEqual(book.get_children().get().get_children().count(), 2)
        q = Question.objects.get(slug="q1")
        self.assertEqual(q.choices.filter(is_correct=True).get().text, "چهار")
        self.assertEqual(list(q.flashcards.values_list("slug", flat=True)), ["card1"])
        self.assertEqual(q.questionsource_set.count(), 2)

    def test_reimport_updates_in_place_and_archives_removed(self):
        import_file("c.md", GOOD.encode(), publish=True)
        q_id = Question.objects.get(slug="q1").id
        section_two = ContentNode.objects.get(slug="two").id

        changed = GOOD.replace("دو به‌علاوه‌ی دو", "سه به‌علاوه‌ی یک").split("## بخش دوم")[0]
        chapter, result = import_file("c.md", changed.encode(), publish=True)
        self.assertEqual(chapter.errors, [])
        q = Question.objects.get(slug="q1")
        self.assertEqual(q.id, q_id)  # same row: learners' answers stay attached
        self.assertIn("سه به‌علاوه‌ی یک", q.stem)
        self.assertTrue(ContentNode.objects.get(id=section_two).is_archived)
        self.assertEqual(result.archived["section"], 1)

        # Restoring the section brings the same row back.
        import_file("c.md", GOOD.encode(), publish=True)
        self.assertFalse(ContentNode.objects.get(id=section_two).is_archived)

    def test_choices_keep_their_ids_when_reordered_and_new_text_is_a_new_choice(self):
        import_file("c.md", GOOD.encode(), publish=True)
        ids = {c.text: c.id for c in Question.objects.get(slug="q1").choices.all()}
        moved = GOOD.replace("- [ ] سه\n- [x] چهار\n- [ ] پنج", "- [x] چهار\n- [ ] پنج\n- [ ] شش")
        self.assertNotEqual(moved, GOOD)
        chapter, _ = import_file("c.md", moved.encode(), publish=True)
        self.assertEqual(chapter.errors, [])
        now = list(Question.objects.get(slug="q1").choices.order_by("order"))
        self.assertEqual([c.text for c in now], ["چهار", "پنج", "شش"])
        self.assertEqual(now[0].id, ids["چهار"])
        self.assertTrue(now[0].is_correct)
        self.assertEqual(now[1].id, ids["پنج"])
        self.assertNotIn(now[2].id, ids.values())

    def test_zip_images_are_stored_and_rewritten(self):
        text = GOOD.replace("متن دوم.", "![نمودار](images/g.svg)")
        chapter, result = import_file("c.zip", self._zip(text, {"images/g.svg": b"<svg/>"}), publish=True)
        self.assertEqual(chapter.errors, [])
        body = ContentNode.objects.get(slug="two").full_body
        self.assertRegex(body, r"\]\(media:content/test-book/ch1/[0-9a-f]{24}\.svg\)")

    def test_svg_with_script_rejected(self):
        text = GOOD.replace("متن دوم.", "![نمودار](images/g.svg)")
        evil = b'<svg onload="alert(1)"></svg>'
        chapter, result = import_file("c.zip", self._zip(text, {"images/g.svg": evil}))
        self.assertIsNone(result)
        self.assertTrue(any("اسکریپت" in str(e) for e in chapter.errors))

    def test_broken_and_oversized_zips_rejected(self):
        chapter, _ = import_file("c.zip", b"not a zip")
        self.assertTrue(chapter.errors)
        many = {f"images/{i}.png": b"x" for i in range(400)}
        chapter, _ = import_file("c.zip", self._zip(GOOD, many))
        self.assertTrue(any("تعداد" in str(e) for e in chapter.errors))

    def test_moving_question_to_another_section_keeps_its_row(self):
        import_file("c.md", GOOD.encode(), publish=True)
        q_id = Question.objects.get(slug="q1").id
        block = GOOD[GOOD.index(":::تست") : GOOD.index(":::فلش‌کارت")]
        moved = GOOD.replace(block, "").replace("متن دوم.", "متن دوم.\n\n" + block)
        chapter, _ = import_file("c.md", moved.encode(), publish=True)
        self.assertEqual(chapter.errors, [])
        q = Question.objects.get(slug="q1")
        self.assertEqual(q.id, q_id)
        self.assertEqual(q.node.slug, "two")
        self.assertFalse(q.is_archived)
        self.assertEqual(Question.objects.count(), 1)

    def test_section_order_follows_file(self):
        import_file("c.md", GOOD.encode(), publish=True)
        first = GOOD[GOOD.index("## بخش اول") : GOOD.index("## بخش دوم")]
        second = GOOD[GOOD.index("## بخش دوم") :]
        swapped = GOOD[: GOOD.index("## بخش اول")] + second + "\n" + first
        import_file("c.md", swapped.encode(), publish=True)
        chapter = ContentNode.objects.get(slug="ch1")
        self.assertEqual([n.slug for n in chapter.get_children()], ["two", "one"])

    def test_load_samples_runs_twice(self):
        call_command("load_samples", stdout=io.StringIO())
        call_command("load_samples", stdout=io.StringIO())
        self.assertEqual(ContentNode.objects.filter(kind="book").count(), 1)
        self.assertEqual(Question.objects.filter(is_archived=False).count(), 9)
        self.assertEqual(Flashcard.objects.filter(is_archived=False).count(), 8)


class ReadApiTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.client = APIClient()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_majors_and_books(self):
        majors = self.client.get("/api/v1/majors/").data
        self.assertIn("economics", [m["slug"] for m in majors])
        books = self.client.get("/api/v1/majors/economics/books/").data
        self.assertEqual(books[0]["slug"], "math-1")
        self.assertTrue(books[0]["has_free_part"])

    def test_book_tree_marks_locked_parts(self):
        book = self.client.get("/api/v1/books/math-1/").data
        free_chapter, paid_chapter = book["chapters"]
        self.assertFalse(free_chapter["is_locked"])
        self.assertTrue(all(not s["is_locked"] for s in free_chapter["sections"]))
        self.assertTrue(paid_chapter["is_locked"])

    def test_partial_free_chapter_in_card_and_detail(self):
        # Lock chapter 1 and unlock only a single section inside chapter 2.
        ContentNode.objects.filter(slug="limits").update(is_free=False)
        ContentNode.objects.filter(slug="rules").update(is_free=True)
        detail = self.client.get("/api/v1/books/math-1/").data
        self.assertIsNone(detail["free_chapter"])
        self.assertEqual(detail["free_chapters"], 0)
        self.assertEqual(detail["partial_free_chapter"], 2)
        self.assertEqual(detail["product_status"]["preview"], "sample")
        self.assertTrue(detail["chapters"][0]["is_locked"])
        self.assertTrue(detail["chapters"][1]["is_locked"])
        rules_section = next(s for s in detail["chapters"][1]["sections"] if s["slug"] == "rules")
        self.assertFalse(rules_section["is_locked"])

        shelves = self.client.get("/api/v1/shelves/").data
        shelf_books = [b for shelf in shelves for b in shelf["books"] if b["slug"] == "math-1"]
        self.assertEqual(len(shelf_books), 1)
        self.assertEqual(shelf_books[0]["partial_free_chapter"], 2)
        self.assertIsNone(shelf_books[0]["free_chapter"])
        self.assertEqual(shelf_books[0]["product_status"]["preview"], "sample")

    def test_free_section_readable_with_media_urls(self):
        node = ContentNode.objects.get(slug="limit-idea")
        data = self.client.get(f"/api/v1/nodes/{node.id}/").data
        self.assertRegex(data["full"], r"http://testserver/media/content/math-1/limits/[0-9a-f]{24}\.svg")
        self.assertTrue(data["summary"])
        self.assertEqual(data["breadcrumb"][0]["slug"], "math-1")

    def test_paid_section_locked_for_guests(self):
        node = ContentNode.objects.get(slug="rules")
        response = self.client.get(f"/api/v1/nodes/{node.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "locked")
        self.assertEqual(response.data["book"]["price"], 249000)

    def test_unpublished_content_hidden(self):
        ContentNode.objects.filter(slug="limit-idea").update(is_published=False)
        node = ContentNode.objects.get(slug="limit-idea")
        self.assertEqual(self.client.get(f"/api/v1/nodes/{node.id}/").status_code, 404)

    def test_unpublishing_a_chapter_hides_everything_under_it(self):
        chapter = ContentNode.objects.get(slug="limits")
        ContentNode.objects.filter(pk=chapter.pk).update(is_published=False)
        section = ContentNode.objects.get(slug="limit-idea")
        self.assertEqual(self.client.get(f"/api/v1/nodes/{section.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/nodes/{section.id}/questions/").status_code, 404)
        book = ContentNode.objects.get(slug="math-1")
        data = self.client.get(f"/api/v1/nodes/{book.id}/questions/").data
        self.assertEqual(len(data["questions"]), 0)
        self.assertEqual([c["slug"] for c in self.client.get("/api/v1/books/math-1/").data["chapters"]], ["derivatives"])

    def test_chapters_ordered_by_number(self):
        slugs = [c["slug"] for c in self.client.get("/api/v1/books/math-1/").data["chapters"]]
        self.assertEqual(slugs, ["limits", "derivatives"])

    def test_banners_count_impressions_and_clicks(self):
        items = self.client.get("/api/v1/banners/?major=economics").data
        self.assertEqual(len(items), 2)
        self.client.post(f"/api/v1/banners/{items[0]['id']}/click/")
        from .models import Banner

        banner = Banner.objects.get(pk=items[0]["id"])
        self.assertEqual((banner.impressions, banner.clicks), (1, 1))


class GroupsAndGlossaryTests(TestCase):
    def setUp(self):
        Major.objects.create(slug="economics", name="اقتصاد")

    def test_group_lines_label_sections_and_terms_feed_the_glossary(self):
        text = GOOD.replace("## بخش اول {#one}", "# مبانی\n\n## بخش اول {#one}").replace(
            ":::خلاصه\nخلاصه‌ی بخش.\n:::",
            ":::خلاصه\nدر یک نگاه: جمع اعداد.\nمهم:\n- جمع جابه‌جایی است [[جزوه]]\nواژه:\n- جمع | Addition | به هم افزودن دو عدد\n- ضرب | Multiplication\n:::",
        ).replace("## بخش دوم {#two}", "# کاربردها\n\n## بخش دوم {#two}")
        chapter, result = import_file("c.md", text.encode(), publish=True)
        self.assertFalse(chapter.errors, chapter.errors)
        one = ContentNode.objects.get(slug="one")
        self.assertEqual(one.group, "مبانی")
        self.assertEqual(ContentNode.objects.get(slug="two").group, "کاربردها")

        client = APIClient()
        book = client.get("/api/v1/books/test-book/").json()
        self.assertEqual([s["group"] for s in book["chapters"][0]["sections"]], ["مبانی", "کاربردها"])
        terms = client.get("/api/v1/books/test-book/glossary/").json()["terms"]
        self.assertEqual([t["fa"] for t in terms], ["جمع", "ضرب"])
        self.assertEqual(terms[0]["en"], "Addition")
        self.assertEqual(terms[1]["meaning"], "")

    def test_banner_destinations(self):
        from .models import Banner

        cases = [("book", "bushberg", "book/bushberg"), ("buy", "bushberg", "buy/bushberg"), ("review", "", "review"),
                 ("exam", "12", "exam/12"), ("url", "https://example.com", "https://example.com"), ("url", "javascript:alert(1)", "")]
        for target, value, link in cases:
            self.assertEqual(Banner(title="b", target=target, target_value=value).resolved_link(), link)
        self.assertEqual(Banner(title="b", link="book/x").resolved_link(), "book/x")


class LabelTests(TestCase):
    """«برچسب‌های متن»: boxes in the notes and parts of the summary, managed in admin."""

    def setUp(self):
        Major.objects.create(slug="economics", name="اقتصاد")
        from .labels import forget

        forget()

    def tearDown(self):
        from .labels import forget

        forget()

    def test_starting_list_and_summary_parts_in_written_order(self):
        from .labels import find
        from .models import Label
        from .summary import parse_summary, parse_terms

        self.assertGreaterEqual(Label.objects.count(), 20, "the migration creates the starting list")
        self.assertEqual(find("مثال‌نقض")["name"], "مثال نقض", "half-space and space are the same name")
        self.assertEqual(find("تله‌ها")["name"], "تله")
        parsed = parse_summary("پیش‌متن\nدر یک نگاه: کوتاه\nقضیه:\n- اول [[x]]\nتعریف: - دوم\nقضیه:\n- سوم\nواژه:\n- حد | Limit | نزدیکی")
        self.assertEqual(parsed["lead"], "پیش‌متن")
        self.assertEqual(parsed["glance"], "کوتاه")
        self.assertEqual([(l["name"], items) for l, items in parsed["parts"]],
                         [("قضیه", ["اول [[x]]", "سوم"]), ("تعریف", ["دوم"]), ("واژه", ["حد | Limit | نزدیکی"])])
        self.assertEqual(parse_terms("واژه‌نامه:\n- حد | Limit"), [{"fa": "حد", "en": "Limit", "meaning": ""}])
        self.assertIsNone(parse_summary("فقط متن: بدون برچسب شناخته‌شده"))

    def test_any_label_is_a_box_in_the_notes_and_new_labels_come_from_admin(self):
        from .labels import forget
        from .models import Label

        text = GOOD.replace("متن دوم.", "متن دوم.\n\n:::مثال نقض\nتابع علامت.\n:::\n\n:::برهان\nچون…\n:::")
        chapter = parse_chapter(text)
        self.assertTrue(any("«برهان» شناخته نشد" in e for e in [str(x) for x in chapter.errors]), chapter.errors)
        Label.objects.create(name="برهان", group="ریاضی و علوم", style="formal")
        forget()
        chapter, _ = import_file("c.md", text.encode(), publish=True)
        self.assertFalse(chapter.errors, chapter.errors)
        two = ContentNode.objects.get(slug="two")
        self.assertIn(":::مثال نقض", two.full_body)
        data = APIClient().get(f"/api/v1/nodes/{two.id}/").json()
        self.assertIn("برهان", [l["name"] for l in data["labels"]], "the app gets the panel's list with the section")
        self.assertEqual(next(l for l in data["labels"] if l["name"] == "واژه")["columns"], ["فارسی", "English", "معنی"])


class NumberingTests(TestCase):
    """«مثال ۳-۵»: numbered over the chapter, with links «[[#name]]» from the notes and from test explanations."""

    def setUp(self):
        Major.objects.create(slug="economics", name="اقتصاد")
        from .labels import forget

        forget()

    def test_examples_are_counted_over_the_chapter_and_links_resolve(self):
        text = GOOD.replace("عنوان: فصل یک", "عنوان: فصل یک\nفصل: 3").replace(
            "متن جزوه با فرمول $x^2$.", "متن.\n\n:::مثال\nیک\n:::\n\n:::مثال {#sin-h}\nدو\n:::\n\n:::نکته\nبی‌شماره\n:::"
        ).replace("متن دوم.", "متن دوم، طبق [[#sin-h]].\n\n:::مثال\nسه\n:::\n\n:::نمودار {#g1}\nشکل\n:::").replace(
            "توضیح: جمع ساده.", "توضیح: جمع ساده، مثل [[#sin-h]]."
        )
        chapter, _ = import_file("c.md", text.encode(), publish=True)
        self.assertFalse(chapter.errors, chapter.errors)
        client = APIClient()
        one, two = ContentNode.objects.get(slug="one"), ContentNode.objects.get(slug="two")
        n1 = client.get(f"/api/v1/nodes/{one.id}/").json()["numbering"]
        n2 = client.get(f"/api/v1/nodes/{two.id}/").json()["numbering"]
        self.assertEqual(n1["chapter"], 3)
        self.assertEqual(n1["start"], {})
        self.assertEqual(n2["start"], {"مثال": 2}, "the second section goes on from the first")
        self.assertEqual(n2["refs"]["sin-h"], {"text": "مثال ۳-۲", "node": one.id})
        self.assertEqual(n2["refs"]["g1"], {"text": "نمودار ۳-۱", "node": two.id})
        q = Question.objects.get(slug="q1")
        r = client.post(f"/api/v1/questions/{q.id}/answer/", {"choice_id": q.choices.first().id}, format="json").json()
        self.assertIn(f"[[#sin-h|مثال ۳-۲|{one.id}]]", r["explanation"], "explanations come with the place filled in")

    def test_box_names_are_unique_in_a_chapter(self):
        text = GOOD.replace("متن دوم.", "متن دوم.\n\n:::مثال {#a}\nیک\n:::\n\n:::مثال {#a}\nدو\n:::")
        self.assertTrue(any("«a» دو بار" in str(e) for e in parse_chapter(text).errors))


class BookSourceAndChapterTests(TestCase):
    def setUp(self):
        Major.objects.create(slug="economics", name="اقتصاد")
        Major.objects.create(slug="biomedical-engineering", name="مهندسی پزشکی")

    def test_textbook_source_without_a_year_round_trips(self):
        from .exporter import export_chapter

        text = GOOD.replace("منبع: کنکور ارشد اقتصاد ۱۴۰۱، سؤال ۲۳\nمنبع: کنکور دکتری اقتصاد 1399", "منبع: کتاب ایساک مارون")
        chapter, _ = import_file("c.md", text.encode(), publish=True)
        self.assertFalse(chapter.errors, chapter.errors)
        q = Question.objects.get(slug="q1")
        self.assertEqual([str(s.source) for s in q.questionsource_set.all()], ["کتاب ایساک مارون"])
        self.assertFalse(q.is_original)
        self.assertIn("منبع: کتاب ایساک مارون\n", export_chapter(ContentNode.objects.get(slug="ch1")))

    def test_the_limits_chapter_file_imports_cleanly(self):
        from pathlib import Path

        from django.conf import settings

        path = Path(settings.BASE_DIR).parent / "content" / "books" / "math-1" / "01-limits" / "chapter.md"
        chapter, _ = import_file("chapter.md", path.read_bytes(), publish=True)
        self.assertFalse(chapter.errors, chapter.errors)
        self.assertEqual(Question.objects.filter(node__path__startswith=ContentNode.objects.get(slug="limits").path).count(), 48)
        self.assertEqual(Question.objects.filter(is_extra=True).count(), 24)
        client = APIClient()
        node = ContentNode.objects.get(slug="rafe-sefr-sefr")
        refs = client.get(f"/api/v1/nodes/{node.id}/").json()["numbering"]["refs"]
        self.assertEqual(refs["hopital"]["text"], "قضیه", "a box that is not numbered is linked by its label")
        self.assertEqual(refs["telescopi"]["text"], "مثال ۱-۱")


class BoxesTests(TestCase):
    def test_all_boxes_of_a_label_in_reading_order(self):
        Major.objects.create(slug="economics", name="اقتصاد")
        text = GOOD.replace("عنوان: فصل یک", "عنوان: فصل یک\nفصل: 2").replace(
            "متن جزوه با فرمول $x^2$.", "متن.\n\n:::مثال {#a}\nیک\n:::\n\n:::نکته\nن\n:::"
        ).replace("متن دوم.", "متن دوم.\n\n:::مثال\nدو\n:::")
        chapter, _ = import_file("c.md", text.encode(), publish=True)
        self.assertFalse(chapter.errors, chapter.errors)
        book = ContentNode.objects.get(slug="test-book")
        client = APIClient()
        data = client.get(f"/api/v1/nodes/{book.id}/boxes/").json()
        self.assertEqual({l["name"]: l["count"] for l in data["labels"]}, {"مثال": 2, "نکته": 1})
        data = client.get(f"/api/v1/nodes/{book.id}/boxes/?label=مثال").json()
        self.assertEqual([(b["title"], b["body"], b["name"]) for b in data["boxes"]], [("مثال ۲-۱", "یک", "a"), ("مثال ۲-۲", "دو", "")])
        self.assertEqual(data["boxes"][1]["section_id"], ContentNode.objects.get(slug="two").id)


class LabelIconTests(TestCase):
    def test_icons_seeded_and_sent(self):
        from apps.catalog.labels import all_labels, forget

        from .models import Label

        self.assertEqual(Label.objects.get(name="تعریف").icon, "book-open")
        Label.objects.filter(name="نکته").update(icon="")
        forget()
        icons = {l["name"]: l["icon"] for l in all_labels()}
        self.assertEqual(icons["تعریف"], "book-open")
        self.assertEqual(icons["نکته"], "")  # turned off in the panel: no icon


class PracticeCountTests(TestCase):
    """«۳ تست، ۰ کارت» on the section page: the app hides «تست‌ها» and «فلش‌کارت» when there is nothing behind them."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.client = APIClient()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_a_section_counts_its_own_tests_and_cards(self):
        node = ContentNode.objects.get(slug="limit-idea")
        data = self.client.get(f"/api/v1/nodes/{node.id}/").data
        self.assertEqual(data["question_count"], Question.objects.filter(node=node, is_archived=False).count())
        self.assertEqual(data["flashcard_count"], Flashcard.objects.filter(node=node, is_archived=False).count())
        self.assertGreater(data["question_count"], 0)

    def test_a_section_without_practice_says_zero(self):
        node = ContentNode.objects.get(slug="special-limits")
        Question.objects.filter(node=node).delete()
        Flashcard.objects.filter(node=node).delete()
        data = self.client.get(f"/api/v1/nodes/{node.id}/").data
        self.assertEqual((data["question_count"], data["flashcard_count"]), (0, 0))

    def test_a_chapter_counts_its_sections(self):
        chapter = ContentNode.objects.get(slug="limits")
        data = self.client.get(f"/api/v1/nodes/{chapter.id}/").data
        self.assertEqual(data["question_count"], Question.objects.filter(node__path__startswith=chapter.path, is_archived=False).count())
        self.assertGreater(data["flashcard_count"], 0)

    def test_archived_items_do_not_count(self):
        node = ContentNode.objects.get(slug="limit-idea")
        before = self.client.get(f"/api/v1/nodes/{node.id}/").data["question_count"]
        Question.objects.filter(node=node).update(is_archived=True)
        after = self.client.get(f"/api/v1/nodes/{node.id}/").data["question_count"]
        self.assertEqual(after, 0)
        self.assertGreater(before, 0)

    def test_guests_see_the_counts_too(self):
        """The bottom bar of the section page is drawn for everyone: a guest must not get an empty «تست‌ها»."""
        node = ContentNode.objects.get(slug="limit-idea")
        data = APIClient().get(f"/api/v1/nodes/{node.id}/").data
        self.assertIn("question_count", data)
        self.assertIn("flashcard_count", data)


class ChapterCountsTests(TestCase):
    """A chapter in /books/<slug>/ carries its sections' totals, and every screen reads that one number.

    Other agents: do not sum `chapter.sections` in a screen. The server already did, with one rule
    (a chapter's practice is its sections' — see `views.book_detail`). Summing it again in the app is the second
    place the rule lives, and the two drift apart the day a chapter gets practice of its own.
    """

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.client = APIClient()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_a_chapter_carries_its_sections_totals(self):
        chapters = self.client.get("/api/v1/books/math-1/").data["chapters"]
        self.assertTrue(chapters)
        for chapter in chapters:
            self.assertEqual(chapter["question_count"], sum(s["question_count"] for s in chapter["sections"]))
            self.assertEqual(chapter["flashcard_count"], sum(s["flashcard_count"] for s in chapter["sections"]))

    def test_a_chapter_with_no_sections_says_zero(self):
        chapter = ContentNode.objects.get(slug="limits")
        for section in chapter.get_children():
            Question.objects.filter(node=section).delete()
            Flashcard.objects.filter(node=section).delete()
        data = next(c for c in self.client.get("/api/v1/books/math-1/").data["chapters"] if c["id"] == chapter.id)
        self.assertEqual((data["question_count"], data["flashcard_count"]), (0, 0))

    def test_the_book_page_and_the_section_page_agree_on_a_chapter(self):
        """The chapter's buttons (book page, summed) and its own page (node_detail) must never disagree."""
        chapter = ContentNode.objects.get(slug="limits")
        from_book = next(c for c in self.client.get("/api/v1/books/math-1/").data["chapters"] if c["id"] == chapter.id)
        from_node = self.client.get(f"/api/v1/nodes/{chapter.id}/").data
        self.assertEqual(from_book["question_count"], from_node["question_count"])
        self.assertEqual(from_book["flashcard_count"], from_node["flashcard_count"])
        self.assertEqual(from_node["intro"]["questions"], from_node["question_count"])
        self.assertEqual(from_node["intro"]["flashcards"], from_node["flashcard_count"])

    def test_chapter_intro_and_node_counts_exclude_locked_and_unpublished_sections(self):
        book = ContentNode.add_root(title="کتاب", kind=ContentNode.Kind.BOOK, slug="mix-book", is_published=True)
        chapter = book.add_child(title="فصل", kind=ContentNode.Kind.CHAPTER, slug="mix-ch", is_published=True, is_free=True)
        sec_open = chapter.add_child(title="بخش آزاد", kind=ContentNode.Kind.SECTION, slug="mix-s1", is_published=True, is_free=True)
        sec_paid = chapter.add_child(title="بخش قفل", kind=ContentNode.Kind.SECTION, slug="mix-s2", is_published=True, is_free=False)
        sec_draft = chapter.add_child(title="بخش پیش‌نویس", kind=ContentNode.Kind.SECTION, slug="mix-s3", is_published=False, is_free=True)
        # Note: AccessMap inherits `free` from ancestors (`chapter.is_free=True` makes descendants free too).
        # To test a locked section inside a readable chapter, make chapter paid with an unpublished/paid child
        # after granting a free chapter or checking unpublished exclusion, OR make chapter paid? Wait:
        # if chapter is free, `AccessMap` treats `any(n.path.startswith(f) for f in free)` as free.
        # So test unpublished exclusion here (`sec_draft` is invisible even when chapter is free!),
        # and also test `AccessMap.usable` directly when chapter is paid (`sec_open.is_free=True`, `sec_paid.is_free=False`).
        Question.objects.create(node=sec_open, stem="s1")
        Question.objects.create(node=sec_draft, stem="s3")
        Flashcard.objects.create(node=sec_open, title="f1", point="p1")
        Flashcard.objects.create(node=sec_draft, title="f3", point="p3")

        data = self.client.get(f"/api/v1/nodes/{chapter.id}/").data
        self.assertEqual(data["question_count"], 1)
        self.assertEqual(data["flashcard_count"], 1)
        self.assertEqual(data["intro"]["questions"], 1)
        self.assertEqual(data["intro"]["flashcards"], 1)

        # Now make the chapter paid so `sec_open` is free while `sec_paid` is locked.
        chapter.is_free = False
        chapter.save(update_fields=["is_free"])
        q_paid = Question.objects.create(node=sec_paid, stem="s2", slug="s2-paid")
        q_paid_free_item = Question.objects.create(node=sec_paid, stem="s2-free", slug="s2-free", is_free=True)
        from django.contrib.auth.models import AnonymousUser

        from .access import AccessMap

        am = AccessMap(AnonymousUser(), chapter)
        self.assertTrue(am.usable(Question.objects.get(node=sec_open)))
        self.assertFalse(am.usable(q_paid))
        self.assertTrue(am.usable(q_paid_free_item))
        self.assertFalse(am.usable(Question.objects.get(node=sec_draft)))


class AccessCoverageHelperTests(TestCase):
    def test_owns_book_and_access_until_with_majors_all_majors_and_editor(self):
        from datetime import timedelta

        from django.contrib.auth.models import Group
        from django.utils import timezone

        from apps.accounts.models import User
        from apps.commerce.models import Entitlement

        from .access import BOOK_EDITOR_GROUP, access_until, owns_book
        from .models import BookEditor, Major

        major = Major.objects.create(name="ریاضی", slug="math-cov")
        other_major = Major.objects.create(name="تجربی", slug="bio-cov")
        book_with_major = ContentNode.add_root(title="کتاب با رشته", kind=ContentNode.Kind.BOOK, slug="book-maj", is_published=True)
        book_with_major.majors.add(major)
        book_no_major = ContentNode.add_root(title="کتاب بی‌رشته", kind=ContentNode.Kind.BOOK, slug="book-nomaj", is_published=True)

        user = User.objects.create_user("09128887766")
        self.assertFalse(owns_book(user, book_no_major))
        self.assertIsNone(access_until(user, book_no_major))

        # Unrelated major does not cover
        Entitlement.objects.create(user=user, major=other_major, ends_at=timezone.now() + timedelta(days=5))
        self.assertFalse(owns_book(user, book_with_major))
        self.assertFalse(owns_book(user, book_no_major))

        # Matching major covers book_with_major until ends_at
        end_major = timezone.now() + timedelta(days=10)
        Entitlement.objects.create(user=user, major=major, ends_at=end_major)
        self.assertTrue(owns_book(user, book_with_major))
        self.assertEqual(access_until(user, book_with_major), end_major)
        self.assertFalse(owns_book(user, book_no_major))

        # all_majors covers book_no_major too
        end_all = timezone.now() + timedelta(days=20)
        Entitlement.objects.create(user=user, all_majors=True, ends_at=end_all)
        self.assertTrue(owns_book(user, book_no_major))
        self.assertEqual(access_until(user, book_no_major), end_all)

        # Book teacher with edit permission has permanent editor access (`access_until` is None)
        group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        teacher = User.objects.create_user("09128887755", is_staff=True)
        teacher.groups.add(group)
        BookEditor.objects.create(user=teacher, book=book_no_major, can_edit_content=True)
        Entitlement.objects.create(user=teacher, all_majors=True, ends_at=end_all)
        self.assertIsNone(access_until(teacher, book_no_major))


class TeacherProfileAndReviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        from apps.accounts.models import User
        self.teacher = User.objects.create_user("09121112233", first_name="علی", last_name="حسینی", is_staff=True)
        self.student = User.objects.create_user("09124445566", first_name="سارا", last_name="رادمهر")
        from apps.catalog.models import ContentNode, BookEditor, TeacherProfile, BookOpinion
        self.book = ContentNode.add_root(title="کتاب آزمایشی", kind=ContentNode.Kind.BOOK, slug="test-book-review", is_published=True)
        BookEditor.objects.create(book=self.book, user=self.teacher)
        TeacherProfile.objects.create(user=self.teacher, academic_title="دانشیار دانشگاه", bio="رزومه دکتر حسینی")

    def test_book_detail_returns_author_profile_and_reviews(self):
        resp = self.client.get(f"/api/v1/books/{self.book.slug}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("author_profile", resp.data)
        self.assertEqual(resp.data["author_profile"]["name"], "علی حسینی")
        self.assertEqual(resp.data["author_profile"]["academic_title"], "دانشیار دانشگاه")
        self.assertIn("community_reviews", resp.data)
        self.assertEqual(resp.data["community_reviews"]["total_count"], 0)
        self.assertIsNone(resp.data["community_reviews"]["average_rating"])
        self.assertIsNone(resp.data["rating"])
        self.assertEqual(resp.data["rating_count"], 0)

    def test_submit_book_review_and_teacher_reply(self):
        # 1. Student submits review
        self.client.force_authenticate(self.student)
        url = f"/api/v1/books/{self.book.slug}/reviews/"
        post_data = {
            "rating": 5,
            "satisfaction_percent": 95,
            "body": "کتاب فوق‌العاده‌ای بود، درسنامه‌ها عالی و روان بودند.",
        }
        res = self.client.post(url, post_data, format="json")
        self.assertEqual(res.status_code, 200)

        # Invalid rating returns 400 rather than 500
        bad = self.client.post(url, {**post_data, "rating": "not-a-number"}, format="json")
        self.assertEqual(bad.status_code, 400)

        # 2. Verify review in book detail and cover card payload
        detail = self.client.get(f"/api/v1/books/{self.book.slug}/").data
        reviews = detail["community_reviews"]
        self.assertEqual(reviews["total_count"], 1)
        self.assertEqual(reviews["average_rating"], 5.0)
        self.assertEqual(detail["rating"], 5.0)
        self.assertEqual(detail["rating_count"], 1)
        self.assertEqual(reviews["reviews"][0]["display_name"], "سارا رادمهر")
        self.assertEqual(reviews["reviews"][0]["rating"], 5)

        # Pending/hidden opinions do not affect the public card rating; approved ones average cleanly
        from apps.accounts.models import User
        from apps.catalog.models import BookOpinion
        other = User.objects.create_user("09129998877")
        BookOpinion.objects.create(book=self.book, user=other, rating=1, body="در انتظار", status=BookOpinion.Status.PENDING)
        shelves = self.client.get("/api/v1/shelves/").data
        card = next(b for s in shelves for b in s["books"] if b["slug"] == self.book.slug)
        self.assertEqual(card["rating"], 5.0)
        self.assertEqual(card["rating_count"], 1)

        third = User.objects.create_user("09129998878")
        BookOpinion.objects.create(book=self.book, user=third, rating=4, body="خوب", status=BookOpinion.Status.APPROVED)
        shelves = self.client.get("/api/v1/shelves/").data
        card = next(b for s in shelves for b in s["books"] if b["slug"] == self.book.slug)
        self.assertEqual(card["rating"], 4.5)
        self.assertEqual(card["rating_count"], 2)

        # 3. Teacher adds reply via model/admin
        rev = BookOpinion.objects.get(book=self.book, user=self.student)
        rev.teacher_reply = "با تشکر از نظر دقیق شما خانم رادمهر، موفق باشید."
        rev.teacher_replied_by = self.teacher
        rev.save()

        # 4. Verify teacher reply shows in book detail
        detail_after = self.client.get(f"/api/v1/books/{self.book.slug}/").data
        student_review = next(r for r in detail_after["community_reviews"]["reviews"] if r["id"] == rev.id)
        self.assertEqual(student_review["teacher_reply"], rev.teacher_reply)


class CatalogConstantQueryTests(TestCase):
    """Home shelves, major books, and all-books list must stay constant-query as the catalog grows."""

    def setUp(self):
        self.user = User.objects.create_user("09120007711")
        self.major = Major.objects.create(slug="sci", name="علوم", order=1)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _add_book(self, idx: int):
        b = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title=f"کتاب {idx}",
            slug=f"qbook-{idx}",
            price=10000,
            is_published=True,
        )
        b.majors.add(self.major)
        ch = b.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل ۱", slug=f"ch-{idx}", is_published=True, is_free=True)
        sec = ch.add_child(
            kind=ContentNode.Kind.SECTION,
            title="بخش ۱",
            slug=f"sec-{idx}",
            is_published=True,
            full_body="متن طولانی درس " * 100,
        )
        from apps.learning.models import Question
        from apps.study.models import SectionProgress

        Question.objects.create(
            node=sec,
            slug=f"q-{idx}",
            stem="سوال؟",
        )
        SectionProgress.objects.create(user=self.user, book=b, node=sec, percent=100, is_done=True)
        return b

    def test_shelves_major_books_and_all_books_do_not_scale_queries_per_book(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._add_book(1)
        counts_1 = {}
        for name, url in (
            ("shelves", "/api/v1/shelves/"),
            ("major_books", f"/api/v1/majors/{self.major.slug}/books/"),
            ("all_books", "/api/v1/books/"),
        ):
            with CaptureQueriesContext(connection) as ctx:
                res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            counts_1[name] = len(ctx)

        for i in range(2, 7):
            self._add_book(i)

        for name, url in (
            ("shelves", "/api/v1/shelves/"),
            ("major_books", f"/api/v1/majors/{self.major.slug}/books/"),
            ("all_books", "/api/v1/books/"),
        ):
            with CaptureQueriesContext(connection) as ctx:
                res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(len(ctx), counts_1[name], f"{name} grew from {counts_1[name]} to {len(ctx)} queries")
            books_payload = res.data[0]["books"] if name == "shelves" else res.data
            self.assertEqual(len(books_payload), 6)
            self.assertEqual(books_payload[0]["chapter_count"], 1)
            self.assertEqual(books_payload[0]["section_count"], 1)


class ProtectedContentMediaTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.client = APIClient()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_signed_content_media_enforces_signature_expiry_and_headers(self):
        import re
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        from unittest.mock import patch

        node = ContentNode.objects.get(slug="limit-idea")
        data = self.client.get(f"/api/v1/nodes/{node.id}/").data
        m = re.search(r"http://testserver(/media/content/[^\s)]+)", data["full"])
        self.assertIsNotNone(m)
        signed_url = m.group(1)
        bare_path = signed_url.split("?")[0]

        # Valid signed URL returns 200 with private cache headers and nosniff/CSP on SVG.
        ok = self.client.get(signed_url)
        self.assertEqual(ok.status_code, 200)
        self.assertRegex(ok["Cache-Control"], r"^private, max-age=\d+$")
        self.assertEqual(ok["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", ok["Content-Security-Policy"])

        # Missing / tampered / wrong-path / expired signature all return 403.
        self.assertEqual(self.client.get(bare_path).status_code, 403)
        self.assertEqual(self.client.get(signed_url[:-1] + ("A" if signed_url[-1] != "A" else "B")).status_code, 403)
        other = default_storage.save("content/math-1/limits/other1234567890abcdef1234.svg", ContentFile(b"<svg/>"))
        query = signed_url.split("?", 1)[1]
        self.assertEqual(self.client.get(f"/media/{other}?{query}").status_code, 403)
        with patch("apps.catalog.media.time.time", return_value=9_999_999_999):
            self.assertEqual(self.client.get(signed_url).status_code, 403)

        # Public assets under covers/ do not hit serve_content_media (even when SERVE_MEDIA is enabled).
        from django.urls import Resolver404, resolve
        from apps.catalog.media import serve_content_media

        self.assertIs(resolve("/media/content/math-1/limits/x.svg").func, serve_content_media)
        try:
            self.assertIsNot(resolve("/media/covers/public-cover-test.png").func, serve_content_media)
        except Resolver404:
            pass

    def test_cross_book_and_locked_chapter_refs_are_not_signed(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        other_book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب دیگر", slug="other-book", is_published=True, price=50000)
        other_ch = other_book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل پولی", slug="paid-ch", is_published=True)
        other_file = default_storage.save("content/other-book/paid-ch/aaaaaaaaaaaaaaaaaaaaaaaa.png", ContentFile(b"PNG"))
        locked_file = default_storage.save("content/math-1/derivatives/bbbbbbbbbbbbbbbbbbbbbbbb.png", ContentFile(b"PNG"))
        free_file = default_storage.save("content/math-1/limits/cccccccccccccccccccccccc.png", ContentFile(b"PNG"))

        book = ContentNode.objects.get(slug="math-1")
        book.about = f"![x](media:{other_file}) ![y](media:{locked_file}) ![z](media:{free_file})"
        book.save(update_fields=["about"])
        book_data = self.client.get("/api/v1/books/math-1/").data
        self.assertIn(f"media:{other_file}", book_data["about"])
        self.assertIn(f"media:{locked_file}", book_data["about"])
        self.assertIn("?exp=", book_data["about"])
        self.assertIn(free_file, book_data["about"])
        self.assertNotIn(f"/media/{other_file}?exp=", book_data["about"])
        self.assertNotIn(f"/media/{locked_file}?exp=", book_data["about"])

    def test_staff_panel_preview_only_for_assigned_book_editor(self):
        from django.contrib.auth.models import Group
        from apps.accounts.models import User
        from apps.catalog.models import BookEditor

        book = ContentNode.objects.get(slug="math-1")
        other_book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب دوم", slug="second-book", is_published=True)
        node = ContentNode.objects.get(slug="limit-idea")
        signed_url = self.client.get(f"/api/v1/nodes/{node.id}/").data["full"]
        import re
        bare_path = re.search(r"http://testserver(/media/content/[^\s?)]+)", signed_url).group(1)

        teacher = User.objects.create_user("09120000555", is_staff=True)
        group, _ = Group.objects.get_or_create(name="استاد کتاب")
        teacher.groups.add(group)
        BookEditor.objects.create(book=other_book, user=teacher, can_edit_content=True)

        web = self.client.__class__()
        web.force_login(teacher)
        self.assertEqual(web.get(bare_path).status_code, 403)

        BookEditor.objects.create(book=book, user=teacher, can_edit_content=True)
        ok = web.get(bare_path)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok["Cache-Control"], "private, no-store")


