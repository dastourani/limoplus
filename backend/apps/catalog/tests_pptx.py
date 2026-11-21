"""PowerPoint import: a .pptx of slides becomes a chapter of sections (one section per slide)."""

import io
import re
import zipfile

from django.test import TestCase

from .importer import read_upload
from .models import ContentNode, Major
from .pptx import images_of, read_pptx, report, to_chapter

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _text_runs(paragraphs):
    """The a:p XML of one shape, from [(level, text), …]."""
    out = []
    for level, text in paragraphs:
        out.append(
            f'<a:p><a:pPr lvl="{level}"/><a:r><a:t>{text}</a:t></a:r></a:p>'
        )
    return "".join(out)


def _shape(shape_id, paragraphs, *, x=0, y=0, title=False, cx=100, cy=100):
    ph = '<p:ph type="title"/>' if title else '<p:ph idx="1"/>'
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="s{shape_id}"/><p:cNvSpPr/>{ph and "<p:nvPr>" + ph + "</p:nvPr>"}</p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm></p:spPr>'
        f'<p:txBody><a:bodyPr/><a:lstStyle/>{_text_runs(paragraphs)}</p:txBody></p:sp>'
    )


def _picture(shape_id, rid, *, x=0, y=0):
    return (
        f'<p:pic><p:nvPicPr><p:cNvPr id="{shape_id}" name="p{shape_id}"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{rid}"/></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="10" cy="10"/></a:xfrm></p:spPr></p:pic>'
    )


def _slide(shapes):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:a="{_A}" xmlns:p="{_P}" xmlns:r="{_R}">'
        f"<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id=\"1\" name=\"\"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>"
        f"<p:grpSpPr/>" + "".join(shapes) + "</p:spTree></p:cSld></p:sld>"
    )


def _pptx(slides, pictures=None):
    """A .pptx byte string holding `slides` (a list of XML strings), in that order."""
    pictures = pictures or {}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml",
                         '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        ids = "".join(f'<p:sldId id="{256 + n}" r:id="rId{n + 1}"/>' for n in range(len(slides)))
        archive.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{_P}" xmlns:r="{_R}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>')
        rels = "".join(f'<Relationship Id="rId{n + 1}" Target="slides/slide{n + 1}.xml"/>' for n in range(len(slides)))
        archive.writestr("ppt/_rels/presentation.xml.rels", f'<Relationships xmlns="{_REL}">{rels}</Relationships>')
        for n, xml in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{n}.xml", xml)
            if pictures.get(n):
                image_rels = "".join(
                    f'<Relationship Id="{rid}" Target="../media/{name}"/>' for rid, name in pictures[n].items()
                )
                archive.writestr(f"ppt/slides/_rels/slide{n}.xml.rels", f'<Relationships xmlns="{_REL}">{image_rels}</Relationships>')
                for name in pictures[n].values():
                    archive.writestr(f"ppt/media/{name}", b"\x89PNG\r\n\x1a\n")
    return buffer.getvalue()


class PptxReadingTests(TestCase):
    def test_each_slide_becomes_a_section_with_its_title(self):
        data = _pptx([
            _slide([_shape(2, [(0, "مفهوم حد")], title=True), _shape(3, [(0, "متن اول")])]),
            _slide([_shape(2, [(0, "حد چپ")], title=True), _shape(3, [(0, "متن دوم")])]),
        ])
        reading = read_pptx(data)
        self.assertEqual(reading.fatal, "")
        self.assertEqual([s.title for s in reading.slides], ["مفهوم حد", "حد چپ"])

    def test_slides_follow_the_presentation_order_not_the_file_names(self):
        # slide2.xml is shown first: the sldId list decides, not the numbering inside the ZIP.
        data = _pptx([_slide([_shape(2, [(0, "اول")], title=True)]), _slide([_shape(2, [(0, "دوم")], title=True)])])
        # rewrite the relationship list to show the second slide first
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            parts = {n: source.read(n) for n in source.namelist()}
        parts["ppt/presentation.xml"] = (
            f'<p:presentation xmlns:p="{_P}" xmlns:r="{_R}"><p:sldIdLst>'
            f'<p:sldId id="257" r:id="rId2"/><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>'
        ).encode()
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as target:
            for name, body in parts.items():
                target.writestr(name, body)
        reading = read_pptx(out.getvalue())
        self.assertEqual([s.title for s in reading.slides], ["دوم", "اول"])

    def test_two_column_slide_reads_top_to_bottom_then_left_to_right(self):
        data = _pptx([_slide([
            _shape(2, [(0, "صفحه دو ستون")], title=True, x=0, y=0),
            _shape(3, [(0, "ستون راست")], x=5000000, y=1000000),
            _shape(4, [(0, "ستون چپ")], x=0, y=1000000),
            _shape(5, [(0, "زیر هر دو")], x=0, y=3000000),
        ])])
        reading = read_pptx(data)
        self.assertEqual([t for _, t in reading.slides[0].lines], ["ستون چپ", "ستون راست", "زیر هر دو"])

    def test_list_levels_become_bullets(self):
        data = _pptx([_slide([_shape(2, [(0, "فهرست")], title=True),
                              _shape(3, [(0, "سرفصل"), (1, "زیرشاخه"), (2, "زیرتر")])])])
        markdown = to_chapter(read_pptx(data), book_slug="b", book_title="کتاب", chapter_slug="c", chapter_title="فصل")
        self.assertIn("سرفصل\n- زیرشاخه\n  - زیرتر", markdown)

    def test_a_slide_without_a_title_keeps_its_text_and_is_named_after_its_number(self):
        data = _pptx([_slide([_shape(3, [(0, "متن بی‌عنوان")])])])
        reading = read_pptx(data)
        self.assertEqual(reading.slides[0].title, "")
        markdown = to_chapter(reading, book_slug="b", book_title="کتاب", chapter_slug="c", chapter_title="فصل")
        self.assertIn("## اسلاید 1 {#slide-1}", markdown)
        self.assertIn("متن بی‌عنوان", markdown)
        self.assertTrue(any("عنوان نداشتند" in w for w in report(reading)))

    def test_slide_numbers_are_unique_even_with_repeated_titles(self):
        data = _pptx([_slide([_shape(2, [(0, "تکرار")], title=True)]), _slide([_shape(2, [(0, "تکرار")], title=True)])])
        markdown = to_chapter(read_pptx(data), book_slug="b", book_title="کتاب", chapter_slug="c", chapter_title="فصل")
        self.assertIn("{#slide-1}", markdown)
        self.assertIn("{#slide-2}", markdown)

    def test_a_latin_title_gives_a_readable_slug(self):
        data = _pptx([_slide([_shape(2, [(0, "Limits and Continuity")], title=True)])])
        markdown = to_chapter(read_pptx(data), book_slug="b", book_title="کتاب", chapter_slug="c", chapter_title="فصل")
        self.assertIn("{#limits-and-continuity}", markdown)

    def test_pictures_are_carried_over(self):
        data = _pptx([_slide([_shape(2, [(0, "شکل")], title=True), _picture(3, "rId9")])],
                     pictures={1: {"rId9": "image1.png"}})
        reading = read_pptx(data)
        self.assertEqual(reading.slides[0].pictures, ["ppt/media/image1.png"])
        images = images_of(data, reading)
        self.assertEqual(list(images), ["image1.png"])

    def test_a_file_that_is_not_a_pptx_is_refused_with_a_reason(self):
        reading = read_pptx(b"this is not a zip at all")
        self.assertTrue(reading.fatal)
        self.assertIn("باز نشد", reading.fatal)

    def test_a_zip_without_presentation_xml_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("hello.txt", "hi")
        self.assertIn("پاورپوینت نیست", read_pptx(buffer.getvalue()).fatal)

    def test_a_presentation_with_no_slides_is_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("ppt/presentation.xml", f'<p:presentation xmlns:p="{_P}"><p:sldIdLst/></p:presentation>')
        self.assertIn("هیچ اسلایدی", read_pptx(buffer.getvalue()).fatal)

    def test_a_slideshow_of_only_pictures_says_so(self):
        data = _pptx([_slide([_picture(3, "rId9")])], pictures={1: {"rId9": "image1.png"}})
        self.assertIn("عکس", read_pptx(data).fatal)

    def test_slide_number_fields_are_not_the_authors_words(self):
        data = _pptx([_slide([_shape(2, [(0, "عنوان")], title=True),
                              _shape(3, []) ])])
        # a paragraph holding only a field (slide number) must not become text
        xml = _slide([_shape(2, [(0, "عنوان")], title=True),
                      '<p:sp><p:nvSpPr><p:cNvPr id="9" name="n"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:txBody><a:bodyPr/>'
                      '<a:lstStyle/><a:p><a:fld id="{GUID}" type="slidenum"><a:t>3</a:t></a:fld></a:p></p:txBody></p:sp>'])
        reading = read_pptx(_pptx([xml]))
        self.assertEqual(reading.slides[0].lines, [])


class PptxUploadTests(TestCase):
    def setUp(self):
        Major.objects.create(name="اقتصاد", slug="economics")

    def test_upload_becomes_a_chapter_the_importer_understands(self):
        data = _pptx([
            _slide([_shape(2, [(0, "مفهوم حد")], title=True), _shape(3, [(0, "حد، نزدیک شدن است.")])]),
            _slide([_shape(2, [(0, "پیوستگی")], title=True), _shape(3, [(0, "تابع پیوسته است اگر…")])]),
        ])
        parsed = read_upload("limits.pptx", data)
        self.assertEqual([str(e) for e in parsed.errors], [])
        self.assertEqual(parsed.meta["chapter_slug"], "limits")
        self.assertEqual(len(parsed.sections), 2)
        self.assertEqual(parsed.sections[0].title, "مفهوم حد")
        self.assertEqual(parsed.sections[1].title, "پیوستگی")

    def test_upload_inside_a_book_takes_the_book_from_the_page(self):
        book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="math-1", title="ریاضی عمومی ۱")
        data = _pptx([_slide([_shape(2, [(0, "بخش")], title=True), _shape(3, [(0, "متن")])])])
        parsed = read_upload("ch.pptx", data, book)
        self.assertEqual([str(e) for e in parsed.errors], [])
        self.assertEqual(parsed.meta["book_slug"], "math-1")


class TeacherGuideTests(TestCase):
    """The guide's examples must actually work: a guide with broken syntax wastes a professor's afternoon."""

    def test_the_chapter_skeleton_in_the_guide_parses(self):
        from pathlib import Path

        from django.conf import settings

        from .importer import parse_chapter

        guide = (Path(settings.BASE_DIR).parent / "docs" / "teacher-guide.md").read_text(encoding="utf-8")
        # Every ```markdown fenced block that starts with the chapter header is a claim we must be able to keep.
        blocks = re.findall(r"```markdown\n(.*?)```", guide, re.S)
        chapters = [b for b in blocks if b.lstrip().startswith("---")]
        self.assertTrue(chapters, "راهنما باید دست‌کم یک نمونه‌ی کامل فصل داشته باشد")
        for text in chapters:
            parsed = parse_chapter(text)
            self.assertEqual([str(e) for e in parsed.errors], [], "نمونه‌ی راهنما خطا دارد")
