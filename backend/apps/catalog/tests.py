import io
import shutil
import tempfile
import zipfile

from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

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
        self.assertIn("«missing»", messages)
        self.assertTrue(all(e.line for e in chapter.errors))

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
