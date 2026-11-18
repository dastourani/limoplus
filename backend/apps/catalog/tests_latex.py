"""LaTeX → chapter Markdown (apps/catalog/latex.py).

Every test here stands for something that broke while this module was written; they are the memory of it.
"""

import io
import shutil
import tempfile
import zipfile

from django.core.management import call_command
from django.urls import reverse
from django.test import SimpleTestCase, TestCase, override_settings

from .importer import read_upload
from .latex import Converter, collect_macros, is_junk, read_latex
from .models import ContentNode

PROJECT = r"""
\documentclass[12pt]{article}
\usepackage{xepersian}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{graphicx}
\usepackage{tikz}
\usepackage{pgfplots}
\newcommand{\R}{\mathbb{R}}
\DeclareMathOperator{\sgn}{sgn}

\begin{document}
\chapter{حد و پیوستگی}

\section{مفهوم حد}
وقتی می‌نویسیم $\lim_{x \to a} f(x) = L$ یعنی هرچه $x$ به $a$ نزدیک می‌شود، $f(x)$ به $L$ نزدیک می‌شود.

\begin{definition}
حد تابع $f$ در نقطه‌ی $a$ برابر $L$ است اگر برای هر $\varepsilon > 0$ یک $\delta > 0$ باشد.
\end{definition}

\begin{example}\label{ex:hole}
تابع $f(x)=\frac{x^2-1}{x-1}$ در $x=1$ تعریف نشده است.
\end{example}

طبق \ref{ex:hole} حد برابر ۲ است و $\sgn(x)\in\R$.

\subsection{حدهای مهم}
\begin{equation}\label{eq:sinx}
\lim_{x\to 0}\frac{\sin x}{x}=1
\end{equation}

\begin{itemize}
\item اول
\item دوم
\end{itemize}

\begin{enumerate}
\item یک
\item دو
\end{enumerate}
\end{document}
"""


class ConvertTests(SimpleTestCase):
    def setUp(self):
        self.text = Converter(PROJECT).to_markdown()

    def test_a_chapter_becomes_the_book_sections(self):
        """\\chapter names the chapter (the front matter's «عنوان»); \\section is «##», \\subsection «###»."""
        converter = Converter(PROJECT)
        text = converter.to_markdown()
        self.assertEqual(converter.title, "حد و پیوستگی")
        self.assertNotIn("## حد و پیوستگی", text)  # the chapter's own title is not a section of itself
        self.assertIn("## مفهوم حد", text)
        self.assertIn("### حدهای مهم", text)

    def test_a_definition_is_a_box(self):
        self.assertIn(":::تعریف", self.text)
        self.assertIn("\n:::", self.text)

    def test_a_labelled_example_can_be_referenced(self):
        self.assertIn(":::مثال {#hole}", self.text)
        self.assertIn("[[#hole]]", self.text)

    def test_a_display_formula_keeps_its_label(self):
        self.assertIn(r"\lim_{x\to 0}\frac{\sin x}{x}=1", self.text)
        self.assertIn("{#sinx}", self.text)

    def test_inline_math_is_never_touched(self):
        """The first version of this module stripped \\frac inside $…$ and left «$$» behind: the formula was gone."""
        self.assertIn(r"$\lim_{x \to a} f(x) = L$", self.text)
        # A formula inside a box keeps its \frac too (it is written inside $f(x)=…$ there).
        self.assertIn(r"\frac{x^2-1}{x-1}", self.text)
        # No formula turned into a bare pair of dollars.
        for line in self.text.split("\n"):
            if line.startswith("$$"):
                continue
            self.assertNotIn("$$", line)

    def test_a_macro_in_the_prose_becomes_a_formula(self):
        """\R written out bare reads as nothing: it is a formula, so it goes in dollars."""
        text = Converter(r"\newcommand{\R}{\mathbb{R}} مجموعه‌ی \R\ است").to_markdown()
        self.assertIn(r"$\mathbb{R}$", text)

    def test_a_macro_inside_formula_is_left_to_katex(self):
        """In $…$ the panel's «دستورهای فرمول» has it; rewriting there would break the formula."""
        text = Converter(r"\newcommand{\R}{\mathbb{R}} $x \in \R$").to_markdown()
        self.assertIn(r"$x \in \R$", text)

    def test_macro_definitions_do_not_leak_into_the_text(self):
        self.assertNotIn(r"\newcommand", self.text)
        self.assertNotIn(r"\documentclass", self.text)
        self.assertNotIn(r"\usepackage", self.text)

    def test_lists_become_markdown(self):
        self.assertIn("- اول\n- دوم", self.text)
        self.assertIn("1. یک\n2. دو", self.text)


class CommandTests(SimpleTestCase):
    def test_decorative_commands_are_dropped_with_their_arguments(self):
        text = Converter(r"a\vspace{2cm}b\noindent c\newpage d").to_markdown()
        # The words stay, the spacing commands are gone (a space left where one was written is fine).
        self.assertEqual(text.split(), ["ab", "cd"])

    def test_an_unknown_command_keeps_its_words(self):
        text = Converter(r"\foo{نگه‌داشته}").to_markdown()
        self.assertIn("نگه‌داشته", text)

    def test_an_unknown_command_is_reported_once(self):
        warnings = Converter(r"\foo{یک} \foo{دو} \bar{سه}").report()
        self.assertEqual(len(warnings), 1)
        self.assertIn("\\foo", warnings[0])
        self.assertIn("\\bar", warnings[0])

    def test_bold_and_italic(self):
        text = Converter(r"\textbf{پررنگ} و \textit{مورب}").to_markdown()
        self.assertIn("**پررنگ**", text)
        self.assertIn("*مورب*", text)

    def test_highlight_takes_a_colour(self):
        """The renderer only knows «==رنگ:متن==»; a bare ==متن== shows as raw text."""
        text = Converter(r"\hl{زرد} و \hlc{قرمز}").to_markdown()
        self.assertIn("==آبی:زرد==", text)
        self.assertIn("==قرمز:قرمز==", text)

    def test_a_footnote_stays_where_it_was(self):
        text = Converter(r"متن\footnote{توضیح}. ادامه").to_markdown()
        self.assertIn("(توضیح)", text)

    def test_a_comment_is_dropped(self):
        text = Converter("متن % این کامنت است\nادامه").to_markdown()
        self.assertNotIn("کامنت", text)
        self.assertIn("متن", text)

    def test_an_escaped_percent_is_not_a_comment(self):
        self.assertIn("%", Converter(r"بیست درصد \% است").to_markdown())


class MacroTests(SimpleTestCase):
    def test_macros_are_collected_with_their_arguments(self):
        macros = collect_macros(r"\newcommand{\norm}[1]{\lVert #1 \rVert}")
        self.assertEqual(macros[r"\norm"], (r"\lVert #1 \rVert", 1))

    def test_an_operator_becomes_operatorname(self):
        self.assertEqual(collect_macros(r"\DeclareMathOperator{\sgn}{sgn}")[r"\sgn"], (r"\operatorname{sgn}", 0))

    def test_a_macro_is_not_touched_inside_math(self):
        """Inside $…$ KaTeX has the panel's «دستورهای فرمول»; rewriting there would break the formula."""
        text = Converter(r"\newcommand{\R}{\mathbb{R}} $x\in\R$").to_markdown()
        self.assertIn(r"$x\in\R$", text)


class TableTests(SimpleTestCase):
    def test_booktabs_becomes_a_markdown_table(self):
        text = Converter(r"""
\begin{tabular}{lcc}
\toprule
نام & تعداد & قیمت \\
\midrule
الف & ۱ & ۱۰ \\
ب & ۲ & ۲۰ \\
\bottomrule
\end{tabular}
""").to_markdown()
        lines = [line for line in text.splitlines() if line.strip()]
        self.assertEqual(lines[0], "| نام | تعداد | قیمت |")
        self.assertEqual(lines[1], "| --- | --- | --- |")
        self.assertIn("| الف | ۱ | ۱۰ |", lines)

    def test_multicolumn_is_kept_as_its_text(self):
        text = Converter(r"\begin{tabular}{cc} \multicolumn{2}{c}{جمع} \\ ۱ & ۲ \end{tabular}").to_markdown()
        self.assertIn("| جمع |", text)

    def test_a_cell_cannot_break_the_table(self):
        text = Converter(r"\begin{tabular}{c} a|b \\ c \end{tabular}").to_markdown()
        self.assertIn(r"a\|b", text)


class FigureTests(SimpleTestCase):
    def test_a_figure_is_an_image_with_its_caption(self):
        text = Converter(r"""
\begin{figure}
\centering
\includegraphics[width=0.6\textwidth]{images/plot.pdf}
\caption{نمودار تابع}
\label{fig:plot}
\end{figure}
""").to_markdown()
        self.assertIn("![نمودار تابع](images/plot.png)", text)

    def test_an_image_without_a_caption_keeps_an_empty_one(self):
        text = Converter(r"\includegraphics{a.png}").to_markdown()
        self.assertIn("![](a.png)", text)


class CodeTests(SimpleTestCase):
    def test_a_listing_becomes_a_code_block(self):
        text = Converter("\\begin{lstlisting}\nx = 1\n\\end{lstlisting}").to_markdown()
        self.assertIn("```\nx = 1\n```", text)

    def test_a_minted_block_keeps_its_language(self):
        text = Converter("\\begin{minted}{python}\nx = 1\n\\end{minted}").to_markdown()
        self.assertIn("```python", text)

    def test_code_is_not_treated_as_text(self):
        text = Converter("\\begin{lstlisting}\n\\textbf{نه پررنگ}\n\\end{lstlisting}").to_markdown()
        self.assertIn(r"\textbf{نه پررنگ}", text)


class TikzTests(SimpleTestCase):
    def test_a_pgfplots_plot_becomes_a_plot_box(self):
        text = Converter(r"""
\begin{tikzpicture}
\begin{axis}[xmin=-3, xmax=3]
\addplot {sin(x)};
\end{axis}
\end{tikzpicture}
""").to_markdown()
        self.assertIn(":::نمودار", text)
        self.assertIn("sin(x)", text)
        self.assertIn("بازه: -3 تا 3", text)

    def test_a_drawing_says_what_to_do_instead(self):
        warnings = Converter(r"\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}").report()
        self.assertTrue(any("SVG" in w for w in warnings))


class AlgorithmTests(SimpleTestCase):
    def test_an_algorithm_is_a_box(self):
        text = Converter(r"""
\begin{algorithm}
\caption{جست‌وجوی دودویی}
\begin{algorithmic}
\State $low \gets 0$
\If{$low \le high$}
\State برگردان
\EndIf
\end{algorithmic}
\end{algorithm}
""").to_markdown()
        self.assertIn(":::الگوریتم", text)
        self.assertIn("جست‌وجوی دودویی", text)
        self.assertIn("برگردان", text)


class ZipTests(SimpleTestCase):
    def _zip(self, files: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return buffer.getvalue()

    def test_a_class_file_is_not_junk_but_not_text(self):
        """A .cls carries the author's shortcuts, so it must be read; it never becomes the chapter's text itself."""
        self.assertFalse(is_junk("myclass.cls"))
        self.assertFalse(is_junk("myclass.sty"))
        self.assertTrue(is_junk("main.pdf"))

    def test_build_output_is_dropped(self):
        for name in ("main.aux", "main.log", "main.toc", "main.out", "main.synctex.gz", "main.pdf", "main.bbl",
                     "__MACOSX/._main.tex", ".DS_Store"):
            self.assertTrue(is_junk(name), name)
        for name in ("main.tex", "images/plot.png", "chapters/ch1.tex"):
            self.assertFalse(is_junk(name), name)

    def test_input_files_are_inlined(self):
        data = self._zip({
            "main.tex": r"\documentclass{article}\begin{document}\input{ch1}\end{document}".encode(),
            "ch1.tex": r"\section{یک} متن".encode(),
        })
        text, _images, warnings = read_latex("project.zip", data)
        self.assertIn("## یک", text)
        self.assertIn("متن", text)
        self.assertFalse(warnings)

    def test_only_referenced_images_are_kept(self):
        data = self._zip({
            "main.tex": r"\includegraphics{images/a.png}".encode(),
            "images/a.png": b"PNG",
            "images/old-screenshot.png": b"PNG",
        })
        _text, images, _warnings = read_latex("project.zip", data)
        self.assertIn("images/a.png", images)
        self.assertNotIn("images/old-screenshot.png", images)

    def test_a_missing_input_is_a_warning_not_a_crash(self):
        data = self._zip({"main.tex": r"\input{nope}".encode()})
        text, _images, warnings = read_latex("project.zip", data)
        self.assertIn("nope", " ".join(warnings))

    def test_classes_are_read_for_macros_only(self):
        data = self._zip({
            "main.tex": r"\R".encode(),
            "myclass.cls": r"\newcommand{\R}{\mathbb{R}}".encode(),
        })
        text, _images, _warnings = read_latex("project.zip", data)
        self.assertIn(r"$\mathbb{R}$", text)

    def test_a_zip_without_tex_is_an_error(self):
        data = self._zip({"readme.txt": b"hi"})
        _text, images, warnings = read_latex("project.zip", data)
        self.assertEqual(images, {})
        self.assertTrue(warnings)

    def test_a_broken_zip_is_an_error(self):
        _text, _images, warnings = read_latex("project.zip", b"not a zip at all")
        self.assertTrue(warnings)


class UploadTests(TestCase):
    """A .tex file uploaded into a book: the same path as chapter.md, all of the format's checks included."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.book = ContentNode.objects.get(slug="math-1")

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_a_tex_file_becomes_a_chapter(self):
        data = (r"""
\chapter{حد و پیوستگی}
\section{مفهوم حد}
متن بخش اول.
\subsection{زیربخش}
متن زیر.
""").encode()
        chapter = read_upload("limits.tex", data, self.book)
        self.assertEqual([str(e) for e in chapter.errors], [])
        self.assertEqual(chapter.meta["chapter_title"], "حد و پیوستگی")
        self.assertEqual(chapter.meta["chapter_slug"], "limits")
        self.assertEqual([s.title for s in chapter.sections], ["مفهوم حد"])

    def test_the_book_lines_come_from_the_book(self):
        chapter = read_upload("c.tex", r"\section{یک} متن".encode(), self.book)
        self.assertEqual(chapter.meta["book_slug"], "math-1")
        self.assertEqual([str(e) for e in chapter.errors], [])

    def test_a_latex_zip_is_read_as_latex_not_as_markdown_zip(self):
        data = self._zip({
            "main.tex": r"\documentclass{article}\begin{document}\section{یک} متن\end{document}".encode(),
            "images/a.png": b"PNG",
        })
        chapter = read_upload("project.zip", data, self.book)
        self.assertEqual([str(e) for e in chapter.errors], [])
        self.assertEqual([s.title for s in chapter.sections], ["یک"])

    def test_a_markdown_zip_still_works(self):
        data = self._zip({"chapter.md": "---\nشناسه-فصل: ch1\nعنوان: یک\n---\n\n## بخش\nمتن\n".encode()})
        chapter = read_upload("chapter.zip", data, self.book)
        self.assertEqual([str(e) for e in chapter.errors], [])
        self.assertEqual(len(chapter.sections), 1)

    def test_converter_warnings_reach_the_author(self):
        chapter = read_upload("c.tex", r"\section{یک} \unknowncmd{متن}".encode(), self.book)
        self.assertTrue(any("unknowncmd" in str(w) for w in chapter.warnings))

    def _zip(self, files):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, body in files.items():
                archive.writestr(name, body)
        return buffer.getvalue()

    def test_a_tikz_drawing_does_not_stop_the_import(self):
        data = (r"""
\section{یک}
\begin{tikzpicture}\draw (0,0) -- (1,1);\end{tikzpicture}
""").encode()
        chapter = read_upload("c.tex", data, self.book)
        self.assertEqual([str(e) for e in chapter.errors], [])
        self.assertTrue(any("SVG" in str(w) for w in chapter.warnings))


class PanelImportTests(TestCase):
    """The panel's own import screen («فصل از فایل») with a .tex file: the path a professor actually takes."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        from apps.accounts.models import User

        self.user = User.objects.create_superuser(phone="09120000000", password="x")
        self.client.force_login(self.user)
        self.book = ContentNode.objects.get(slug="math-1")
        self.url = reverse("admin:catalog_book_import", args=[self.book.pk])

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_a_tex_file_is_previewed_then_imported(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        tex = r"""
\chapter{حد و پیوستگی}
\section{قضیه‌ی حد}
\begin{theorem}\label{thm:limit}
حد یکتاست.
\end{theorem}
"""
        upload = SimpleUploadedFile("limits.tex", tex.encode(), content_type="text/x-tex")
        response = self.client.post(self.url, {"file": upload})
        report = response.context["report"]
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["target_book"], self.book.title)
        self.assertEqual(report["counts"]["sections"], 1)
        # Confirming writes it, exactly like a chapter.md.
        self.client.post(self.url, {"token": report["token"], "filename": "limits.tex"})
        node = ContentNode.objects.get(slug="limits", path__startswith=self.book.path)
        self.assertEqual(node.title, "حد و پیوستگی")
        self.assertTrue(node.get_children().exists())


class MacroArgumentTests(SimpleTestCase):
    def test_a_two_argument_macro_in_the_prose(self):
        text = Converter(r"\newcommand{\pair}[2]{\left(#1,#2\right)} نقطه‌ی \pair{a}{b}").to_markdown()
        self.assertIn("(a,b)", text)

    def test_a_macro_built_on_another_macro(self):
        text = Converter(r"\newcommand{\R}{\mathbb{R}}\newcommand{\Rp}{\R^{+}} مقدار \Rp").to_markdown()
        self.assertIn(r"\mathbb{R}", text)

    def test_an_optional_argument_is_read(self):
        text = Converter(r"\newcommand{\limx}[1][x]{\lim_{#1}} نتیجه \limx").to_markdown()
        self.assertIn("\\lim_{x}", text)


class TableFloatPlacementTests(TestCase):
    """«\\begin{table}[H]»: the placement option is a setting, not the author's words.

    It used to survive as a bare «[H]» line above the table — a professor saw it in the imported chapter and could not
    tell what it was.
    """

    def _read(self, source: str):
        from .latex import Converter

        converter = Converter(source)
        converter.slug = "t"
        return converter.to_chapter(), converter.report()

    def test_placement_option_is_not_text(self):
        markdown, _ = self._read(
            r"\begin{document}" "\n" r"\begin{table}[H]" "\n" r"\begin{tabular}{ll}" "\n"
            r"a & b \\" "\n" r"\end{tabular}" "\n" r"\end{table}" "\n" r"\end{document}"
        )
        self.assertNotIn("[H]", markdown)
        self.assertIn("| a | b |", markdown)

    def test_other_placements_too(self):
        for option in ("[htbp]", "[t]", "[!h]", "[H]"):
            markdown, _ = self._read(
                r"\begin{document}" "\n" f"\\begin{{table}}{option}" "\n" r"\begin{tabular}{l}" "\n"
                r"x \\" "\n" r"\end{tabular}" "\n" r"\end{table}" "\n" r"\end{document}"
            )
            self.assertNotIn(option, markdown, option)


class UnknownCommandReportTests(TestCase):
    """The warning about unknown commands is read by a professor, not by a LaTeX user."""

    def _report(self, source: str):
        from .latex import Converter

        converter = Converter(source)
        converter.slug = "t"
        converter.to_chapter()
        return " ".join(converter.report())

    def test_it_says_what_happened_and_how_many(self):
        report = self._report(r"\begin{document}" "\n" r"\note{یک نکته}" "\n" r"\end{document}")
        self.assertIn("۱ دستور", report)
        self.assertIn("متن داخلشان", report)

    def test_a_known_but_missing_command_gets_a_hint(self):
        report = self._report(r"\begin{document}" "\n" r"\note{یک نکته}" "\n" r"\end{document}")
        self.assertIn(":::نکته", report)

    def test_no_html_reaches_the_warning(self):
        # Warnings are printed as text (createTextNode), so a tag in one shows up literally.
        report = self._report(r"\begin{document}" "\n" r"\note{x}" "\n" r"\end{document}")
        self.assertNotIn("<b>", report)
        self.assertNotIn("<", report)
