"""The reverse of the import: a chapter of the book → a .tex file that compiles and comes back unchanged.

The baseline this file guards is the round trip: apply_chapter writes the chapter, chapter_to_tex exports it, and
read_upload + parse_chapter must give back exactly the same chapter. Everything the format can carry must survive.
"""

import ast
import io
import posixpath
import re
import shutil
import tempfile

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.catalog import latex_export
from apps.catalog.exporter import chapter_from_db
from apps.catalog.importer import apply_chapter, read_upload
from apps.catalog.labels import DEFAULT_LABELS, NUMBERED
from apps.catalog.latex_export import (
    chapter_node_to_tex,
    chapter_tex_bundle,
    chapter_to_tex,
    environment_of,
    inline,
)
from apps.catalog.models import ContentNode

# DEFAULT_LABELS is (name, group, style, role, aliases, columns, hidden): only the first field is the label.
LABEL_NAMES = [label[0] for label in DEFAULT_LABELS]

# A tiny picture: the export names it by its content hash, so only the bytes matter.
SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>"""


class EscapeTests(SimpleTestCase):
    """Plain words must never reach LaTeX as markup."""

    def test_percent_and_ampersand_are_escaped(self):
        self.assertEqual(inline("۵۰% و A&B"), r"۵۰\% و A\&B")

    def test_underscore_and_caret_are_escaped(self):
        self.assertIn(r"a\_b", inline("a_b"))
        self.assertIn(r"\textasciicircum{}", inline("x^2"))

    def test_braces_are_escaped(self):
        self.assertEqual(inline("{x}"), r"\{x\}")

    def test_hash_and_dollar_are_escaped(self):
        self.assertIn(r"\#", inline("شماره‌ی #"))
        self.assertIn(r"\$", inline("قیمت ۵$"))

    def test_arabic_text_is_left_alone(self):
        line = "حد تابع در نقطه‌ی a"
        self.assertEqual(inline(line), line)

    def test_zwnj_survives(self):
        # «می‌شود» with ZWNJ must not be normalised away: the app draws it like this.
        self.assertIn("\u200c", inline("می‌شود"))

class MarkdownTests(SimpleTestCase):
    """Markdown → LaTeX, in the order that keeps the commands from being escaped."""

    def test_bold_becomes_textbf_not_escaped_words(self):
        self.assertEqual(inline("**پررنگ**"), r"\textbf{پررنگ}")

    def test_italic_becomes_emph(self):
        self.assertEqual(inline("*کج*"), r"\emph{کج}")

    def test_red_becomes_hlc_and_blue_becomes_hl(self):
        self.assertEqual(inline("==قرمز:توجه=="), r"\hlc{توجه}")
        self.assertEqual(inline("==آبی:توجه=="), r"\hl{توجه}")
        self.assertEqual(inline("==green:x=="), r"\hl{x}")

    def test_cross_reference_becomes_ref(self):
        self.assertEqual(inline("طبق [[#sin-hamarz]]"), r"طبق \ref{sin-hamarz}")

    def test_a_word_reference_becomes_bold(self):
        self.assertEqual(inline("[[واژه]]"), r"\textbf{واژه}")

    def test_image_becomes_a_figure(self):
        tex = inline("![نمودار](media:content/math-1/a.svg)")
        self.assertIn(r"\begin{figure}[H]", tex)
        self.assertIn(r"\includegraphics[width=0.8\textwidth]{images/a.svg}", tex)
        self.assertIn(r"\caption{نمودار}", tex)

    def test_an_image_without_media_prefix_is_found_too(self):
        self.assertIn("{images/a.png}", inline("![](content/a.png)"))

    def test_a_caption_is_escaped(self):
        self.assertIn(r"\caption{۵۰\%}", inline("![۵۰%](media:a.png)"))

class MathTests(SimpleTestCase):
    """KaTeX's TeX is TeX: a formula goes out exactly as it came in."""

    def test_inline_math_is_untouched(self):
        self.assertEqual(inline(r"$\frac{a}{b} + x_1$"), r"$\frac{a}{b} + x_1$")

    def test_math_survives_bold_next_to_it(self):
        self.assertEqual(inline(r"$\frac{a}{b}$ و **b**"), r"$\frac{a}{b}$ و \textbf{b}")

    def test_a_formula_is_not_escaped(self):
        self.assertIn(r"a_b", inline("$a_b$"))
        self.assertNotIn(r"a\_b", inline("$a_b$"))

    def test_a_display_formula_becomes_brackets(self):
        out = latex_export.blocks([r"$$\lim_{x\to a} f(x)$$"])
        self.assertEqual(out, [r"\[", r"\lim_{x\to a} f(x)", r"\]"])

    def test_a_named_formula_becomes_an_equation_with_a_label(self):
        out = latex_export.blocks([r"$$e^{i\pi}+1=0$$ {#euler}"])
        self.assertEqual(out, [r"\begin{equation}\label{euler}", r"e^{i\pi}+1=0", r"\end{equation}"])
        # The named form must be checked before the unnamed one, or the name stays in the text.
        self.assertEqual(out[0].count("label"), 1)

class EnvironmentTests(SimpleTestCase):
    """Every one of the book's labels has an environment that the preamble defines."""

    def test_every_default_label_maps_to_an_environment(self):
        for label in LABEL_NAMES:
            self.assertIn(environment_of(label), latex_export.ENVIRONMENT_NAMES.values())

    def test_a_new_panel_label_gets_a_name_of_its_own(self):
        # A label added in the panel has no ASCII name yet: the fallback is one environment, and it is defined.
        self.assertEqual(environment_of("برچسب تازه"), "bookbox")
        self.assertIn(r"\newenvironment{bookbox}", "\n".join(latex_export._preamble(["برچسب تازه"])))

    def test_environment_names_are_ascii_and_lowercase(self):
        for name in latex_export.ENVIRONMENT_NAMES.values():
            self.assertRegex(name, r"^[a-z][a-z0-9]*$")

    def test_a_box_becomes_its_environment(self):
        out = latex_export.blocks([":::تعریف {#d1}", "متن", ":::"])
        # The \\label rides on the \\begin line: the reader looks for the box's name there.
        self.assertEqual(out, [r"\begin{definition}\label{d1}", "متن", r"\end{definition}"])

    def test_a_box_without_a_name_has_no_label(self):
        out = latex_export.blocks([":::نکته", "متن", ":::"])
        self.assertEqual(out, [r"\begin{note}", "متن", r"\end{note}"])

    def test_a_box_holds_other_blocks(self):
        out = latex_export.blocks([":::مثال", "- یک", "- دو", ":::"])
        self.assertIn(r"\item یک", out)

    def test_a_latin_box_is_left_to_right(self):
        out = latex_export.blocks([":::لاتین", "text", ":::"])
        self.assertEqual(out, [r"\begin{latin}", "text", r"\end{latin}"])

    def test_numbered_labels_are_the_three_the_app_numbers(self):
        self.assertEqual(NUMBERED, {"مثال", "نمودار", "تمرین"})

class PreambleTests(SimpleTestCase):
    """The file must stand alone: no package that Overleaf lacks, no undefined environment."""

    def preamble(self, labels):
        return "\n".join(latex_export._preamble(labels))

    def test_the_document_class_and_the_persian_package_are_there(self):
        preamble = self.preamble(["تعریف"])
        self.assertIn(r"\documentclass", preamble)
        self.assertIn(r"\usepackage{xepersian}", preamble)

    def test_the_compiler_is_named_in_the_file(self):
        self.assertIn("XeLaTeX", self.preamble(["تعریف"]))

    def test_every_environment_used_is_defined(self):
        for label in LABEL_NAMES:
            name = environment_of(label)
            self.assertIn(r"\newenvironment{" + name + "}", self.preamble([label]),
                          "برچسب «%s» محیط %s را می‌خواهد که پشتوانه تعریف نمی‌کند" % (label, name))

    def test_the_box_environment_is_defined_before_it_is_used(self):
        preamble = self.preamble(["تعریف"])
        # \\newenvironment{definition} opens a group whose body calls mdframed; the package must come first.
        self.assertLess(preamble.index(r"\usepackage{mdframed}"), preamble.index(r"\newenvironment{definition}"))

    def test_a_box_has_a_counter_of_its_own(self):
        preamble = self.preamble(["تعریف", "مثال"])
        self.assertIn(r"\newcounter{definitionbox}", preamble)
        self.assertIn(r"\newcounter{examplebox}", preamble)

    def test_one_environment_per_label_and_no_duplicates(self):
        preamble = self.preamble(["تعریف", "تعریف", "مثال"])
        self.assertEqual(preamble.count(r"\newenvironment{definition}"), 1)

    def test_an_unused_environment_is_not_defined(self):
        self.assertNotIn(r"\newenvironment{note}", self.preamble(["تعریف"]))

    def test_the_highlight_commands_are_defined(self):
        preamble = self.preamble([])
        self.assertIn(r"\newcommand{\hl}", preamble)
        self.assertIn(r"\newcommand{\hlc}", preamble)

    def test_a_second_definition_of_a_command_would_not_compile(self):
        # \\newcommand of an existing name is an error, not a warning: no name may appear twice.
        preamble = self.preamble(LABEL_NAMES)
        defined = [line.split("{")[1].split("}")[0] for line in preamble.splitlines()
                   if line.startswith(r"\newenvironment{")]
        self.assertEqual(len(defined), len(set(defined)))

class DocumentTests(SimpleTestCase):
    """The whole file, rather than single lines."""

    def test_a_chapter_has_one_document_environment(self):
        tex = chapter_to_tex({"title": "حد", "book_title": "ریاضی ۱", "number": 1}, [], [])
        self.assertEqual(tex.count(r"\begin{document}"), 1)
        self.assertEqual(tex.count(r"\end{document}"), 1)

    def test_the_title_and_the_book_are_printed(self):
        tex = chapter_to_tex({"title": "حد", "book_title": "ریاضی ۱", "number": 1}, [], [])
        title = next(line for line in tex.splitlines() if line.startswith(r"\title{"))
        self.assertIn("حد", title)
        self.assertIn("ریاضی ۱", title)

    def test_the_chapter_number_is_not_poured_into_the_section_counter(self):
        # `article` has no chapters: setting the section counter to the chapter's position printed «بخش ۹۸» for the
        # 99th chapter. The chapter's number is on the title instead.
        tex = chapter_to_tex({"title": "حد", "number": 3}, [], [])
        self.assertNotIn(r"\setcounter{section}", tex)
        self.assertIn("حد", next(line for line in tex.splitlines() if line.startswith(r"\title{")))

    def test_a_chapter_section_is_a_section_with_a_label(self):
        tex = chapter_to_tex({"title": "حد", "number": 1}, [], [("یک‌طرفه", "one-sided", ["متن"])])
        self.assertIn(r"\section{یک‌طرفه}\label{one-sided}", tex)

    def test_a_section_without_a_slug_has_no_label(self):
        tex = chapter_to_tex({"title": "حد", "number": 1}, [], [("یک‌طرفه", "", [])])
        self.assertIn(r"\section{یک‌طرفه}", tex)
        self.assertNotIn(r"\label{}", tex)

    def test_an_inner_heading_goes_deeper_not_to_a_section(self):
        out = latex_export.blocks(["## زیربخش {#sub}"])
        self.assertEqual(out, [r"\subsection{زیربخش}\label{sub}"])

    def test_a_group_heading_is_unnumbered(self):
        out = latex_export.blocks(["# گروه"])
        self.assertEqual(out, [r"\subsection*{گروه}"])

    def test_no_line_keeps_the_markdown_marker(self):
        tex = chapter_to_tex({"title": "حد", "number": 1}, ["**a** و [[#r]]"], [("s", "s", ["**b**"])])
        body = tex[tex.index(r"\begin{document}") :]
        self.assertNotIn("**", body)
        self.assertNotIn("[[#", body)

    def test_there_are_never_three_blank_lines(self):
        tex = chapter_to_tex({"title": "حد", "number": 1}, ["a", "", "", "b"], [])
        self.assertNotIn("\n\n\n", tex)

    def test_the_file_is_utf8_without_a_bom(self):
        tex = chapter_to_tex({"title": "حد", "number": 1}, [], [])
        self.assertTrue(tex.startswith("%"))
        self.assertFalse(tex.startswith("\ufeff"))
        tex.encode("utf-8")

    def test_both_converters_are_python(self):
        # A syntax error in either file is a 500 on the export button, not a bad .tex: catch it here.
        for module in (latex_export, __import__("apps.catalog.latex", fromlist=["latex"])):
            with open(module.__file__, encoding="utf-8") as handle:
                ast.parse(handle.read())

class RoundTripTests(TestCase):
    """The chapter → .tex → chapter loop: what the format can carry must come back unchanged.
    This is the test the whole step exists for. If it goes red, a professor who took a chapter to Overleaf and brought
    it back would lose something — a label, a formula, a reference — and the book would quietly get worse.
    """

    def setUp(self):
        # The sample chapter has a picture: the bundle can only carry it if the storage is the test's own folder.
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.book = ContentNode.objects.get(slug="math-1")
        self.chapter = self.book.get_children().filter(kind=ContentNode.Kind.CHAPTER).first()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def tex_of(self, chapter):
        return chapter_node_to_tex(chapter)[0]

    def back(self, chapter):
        """The chapter as a professor gets it back: the bundle the panel's download button hands out.
        The bundle, not the bare .tex: a chapter with pictures cannot be read back from a .tex alone, because the
        reader would look for files that the archive never held.
        """
        name, data, _content_type = chapter_tex_bundle(chapter)
        self.assertIn(data[:2], (b"% ", b"PK"))
        return read_upload(name, data, self.book)

    def test_the_exported_file_is_whole(self):
        tex = self.tex_of(self.chapter)
        self.assertIn(r"\begin{document}", tex)
        self.assertTrue(tex.rstrip().endswith(r"\end{document}"))
        self.assertGreater(len(tex), 1000)

    def test_the_chapter_comes_back_without_errors(self):
        after = self.back(self.chapter)
        self.assertEqual([str(e) for e in after.errors], [])

    def test_the_same_sections_come_back(self):
        before = chapter_from_db(self.chapter)
        after = self.back(self.chapter)
        self.assertEqual([s.title for s in after.sections], [s.title for s in before.sections])
        self.assertEqual([s.slug for s in after.sections], [s.slug for s in before.sections])

    def test_the_same_words_come_back(self):
        # The words a chapter is read back by are the ones the importer keeps — `apply_chapter` is the step that
        # stores the pictures and rewrites their links to media:, exactly as the panel does after an upload.
        before = chapter_from_db(self.chapter)
        self.apply_back()
        after = chapter_from_db(ContentNode.objects.get(pk=self.chapter.pk))
        def words(lines):
            return " ".join(" ".join(lines).split())
        for old, new in zip(before.sections, after.sections):
            self.assertEqual(words(new.full_lines), words(old.full_lines),
                             "متن بخش «%s» در رفت‌وبرگشت عوض شد" % old.title)

    def apply_back(self):
        """Read the export back and write it over the chapter, as the panel's import does."""
        name, data, _content_type = chapter_tex_bundle(self.chapter)
        parsed = read_upload(name, data, self.book)
        self.assertEqual([str(e) for e in parsed.errors], [])
        apply_chapter(parsed)
        return parsed

    def test_a_named_box_comes_back(self):
        # The sample chapter has no named box, so the round trip of \\label has a chapter of its own here.
        self.chapter.full_body = ":::تعریف {#limit-def}\nحد …\n:::\n\n:::تله {#trap-1}\nمواظب باش.\n:::\n"
        self.chapter.save()
        after = self.back(self.chapter)
        body = "\n".join(after.intro.full_lines)
        self.assertIn(":::تعریف {#limit-def}", body)
        self.assertIn(":::تله {#trap-1}", body)

    def test_every_label_of_the_chapter_comes_back(self):
        # The chapter's own labels: each :::kind of the sample, with and without a name.
        self.chapter.full_body = ":::%s\nمتن\n:::\n" % "\n".join(
            ["تعریف {#d1}", "نکته", "تله {#t1}", "در یک نگاه", "مثال {#e1}"])
        self.chapter.save()
        before = chapter_from_db(self.chapter)
        after = self.back(self.chapter)
        def labels(parsed):
            text = "\n".join(parsed.intro.full_lines)
            return sorted(set(re.findall(r":::\s*([^\s{]+)\s*(?:\{#([^}]+)\})?", text)))
        self.assertEqual(labels(after), labels(before))

    def test_a_formula_comes_back_unchanged(self):
        self.chapter.full_body = "متن با $\\frac{a}{b}$ و\n\n$$e^{i\\pi}+1=0$$\n"
        self.chapter.save()
        body = "\n".join(self.back(self.chapter).intro.full_lines)
        self.assertIn(r"$\frac{a}{b}$", body)
        self.assertIn(r"$$e^{i\pi}+1=0$$", body)

    def test_an_image_comes_back_from_a_zip_with_its_file(self):
        # A bare .tex cannot name a stored path — the picture is not in the book yet. The ZIP of the export holds both
        # the .tex and images/, and that is the file a professor brings back. The new chapter is added next to the
        # samples: deleting them is refused (their questions and flashcards point at them).
        chapter = ContentNode.objects.get(pk=self.book.pk).add_child(
            kind=ContentNode.Kind.CHAPTER, title="فصل تصویر", slug="picture", position=99,
            full_body="![نمودار](media:%s)\n" % self._store_picture(),
        )
        self.chapter = chapter
        self.apply_back()
        stored = ContentNode.objects.get(pk=chapter.pk)
        text = stored.full_body + "\n" + "\n".join(
            child.full_body for child in stored.get_children())
        self.assertIn("![نمودار](media:", text)

    def _store_picture(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        return default_storage.save("content/math-1/picture/a.svg", ContentFile(SVG))

    def test_the_title_and_the_book_are_in_the_file(self):
        meta = chapter_from_db(self.chapter).meta
        tex = self.tex_of(self.chapter)
        self.assertIn(meta["chapter_title"], tex)
        self.assertIn(meta["book_title"], tex)

    def test_the_images_of_the_chapter_are_listed_with_their_stored_paths(self):
        # The .tex carries images/<basename>; the stored path is what the bundle opens to read the bytes.
        tex, paths = chapter_node_to_tex(self.chapter)
        self.assertTrue(paths)
        for path in paths:
            self.assertIn(posixpath.basename(path), tex)

class PanelTexTests(TestCase):
    """The «📥 .tex» button: the route the panel shows, and who may press it."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        from apps.accounts.models import User
        self.user = User.objects.create_superuser(phone="09120000001", password="x")
        self.client.force_login(self.user)
        self.book = ContentNode.objects.get(slug="math-1")
        self.chapter = self.book.get_children().filter(kind=ContentNode.Kind.CHAPTER).first()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_the_tex_button_is_on_the_book_page(self):
        response = self.client.get(reverse("admin:catalog_book_change", args=[self.book.pk]))
        self.assertContains(response, reverse("admin:catalog_chapter_tex", args=[self.chapter.pk]))

    def test_the_route_returns_a_tex_file(self):
        response = self.client.get(reverse("admin:catalog_chapter_tex", args=[self.chapter.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])

    def test_a_chapter_with_images_comes_as_a_zip(self):
        response = self.client.get(reverse("admin:catalog_chapter_tex", args=[self.chapter.pk]))
        # The sample chapter has a picture, so the download is the archive that carries it.
        self.assertTrue(response["Content-Disposition"].endswith('.zip"'), response["Content-Disposition"])

    def test_the_download_is_not_open_to_everyone(self):
        from apps.accounts.models import User
        self.client.logout()
        stranger = User.objects.create_user(phone="09120000002", password="x")
        self.client.force_login(stranger)
        response = self.client.get(reverse("admin:catalog_chapter_tex", args=[self.chapter.pk]))
        self.assertNotEqual(response.status_code, 200)