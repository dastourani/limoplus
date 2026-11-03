import io
import shutil
import tempfile

from django.core.management import call_command
from django.test import Client, TestCase, override_settings

from apps.catalog.models import ContentNode
from apps.learning.models import Question


class WebsiteTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_pages_render(self):
        c = Client()
        for url in ["/site/", "/site/books/", "/site/books/math-1/", "/site/download/", "/site/pricing/", "/site/faq/",
                    "/site/p/about/", "/site/p/terms/", "/site/p/privacy/", "/site/p/contact/"]:
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertContains(r, "لیموخوان")
        self.assertEqual(c.get("/site/books/nope/").status_code, 404)
        self.assertEqual(c.get("/site/p/nope/").status_code, 404)

    def test_home_lists_published_books_only(self):
        book = ContentNode.objects.get(slug="math-1")
        r = Client().get("/site/")
        self.assertContains(r, book.title)
        book.is_published = False
        book.save()
        self.assertNotContains(Client().get("/site/books/"), f'href="/site/books/{book.slug}/"')
        self.assertEqual(Client().get(f"/site/books/{book.slug}/").status_code, 404)

    def test_book_page_samples_never_show_answers(self):
        q = Question.objects.filter(node__path__startswith=ContentNode.objects.get(slug="math-1").path, is_archived=False).first()
        q.is_sample = True
        q.is_free = True
        q.save()
        r = Client().get("/site/books/math-1/")
        self.assertContains(r, f'data-id="{q.id}"')
        html = r.content.decode()
        self.assertNotIn("is_correct", html)
        if q.explanation:
            self.assertNotIn(q.explanation[:40], html)

    def test_sitemap_and_robots(self):
        c = Client()
        self.assertContains(c.get("/site/sitemap.xml"), "/site/books/math-1/")
        self.assertContains(c.get("/site/robots.txt"), "Sitemap:")

    @override_settings(WEBSITE_HOSTS=["limookhan.ir"], ALLOWED_HOSTS=["limookhan.ir", "testserver"], APP_URL="https://app.example")
    def test_own_host_serves_site_at_root(self):
        c = Client(HTTP_HOST="limookhan.ir")
        r = c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="/books/"')  # links without /site/
        self.assertContains(r, "https://app.example")
        self.assertEqual(c.get("/books/math-1/").status_code, 200)
        self.assertEqual(c.get("/api/v1/health/").status_code, 200)  # the API stays
        # Another host: the site only under /site/.
        self.assertEqual(Client().get("/site/").status_code, 200)

    def test_simple_text_is_escaped(self):
        from .views import simple_text

        html = simple_text("## سر\n\n<script>x</script>\n- یک\n- دو")
        self.assertIn("<h2>سر</h2>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<ul><li>یک</li><li>دو</li></ul>", html)
