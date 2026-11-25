import io
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

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

    def test_paid_book_with_free_chapter_shows_price_and_sample_state_with_small_sale_chip(self):
        from apps.commerce.models import SaleCampaign

        book = ContentNode.objects.get(slug="math-1")
        detail = Client().get(f"/site/books/{book.slug}/")
        self.assertEqual(detail.context["product_status"], {"state": "paid", "preview": "sample", "promotion": "none"})
        self.assertEqual(detail.context["sample_label"], "فصل اول رایگان")
        self.assertContains(detail, "۲۴۹ هزار تومان")
        self.assertContains(detail, "شروع رایگان از فصل")

        now = timezone.now()
        SaleCampaign.objects.create(
            title="تخفیف کوچک کنار قیمت",
            book=book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
        )
        index = Client().get("/site/books/")
        card = next(item for item in index.context["books"] if item["book"].slug == book.slug)
        self.assertEqual(card["product_status"], {"state": "paid", "preview": "sample", "promotion": "discount"})
        self.assertEqual(card["label"]["text"], "۱۹۹ هزار تومان")
        self.assertEqual(card["sample_label"], "فصل اول رایگان")
        self.assertContains(index, 'class="bk-discount-chip"')
        self.assertContains(index, "۱۹۹ هزار تومان")
        self.assertContains(index, "فصل اول رایگان")

    def test_book_buttons_have_no_native_tooltip_title(self):
        """The browser's own tooltip repeated the button's text in a dark box on hover: only the site's own bubble."""
        from apps.commerce.models import SaleCampaign

        book = ContentNode.objects.get(slug="math-1")
        now = timezone.now()
        SaleCampaign.objects.create(
            title="تخفیف برای تست تولتیپ",
            book=book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(hours=1),
        )
        index = Client().get("/site/books/")
        self.assertContains(index, 'class="bk-action"')
        self.assertNotContains(index, 'title="')
        # The price itself is still there, and the site's own bubble still carries the details.
        self.assertContains(index, "۱۹۹ هزار تومان")
        self.assertContains(index, 'class="tip-bubble"')
        self.assertContains(index, "٪ تخفیف زمان‌دار")
        self.assertNotContains(index, "صرفه‌جویی")

    def test_home_lists_published_books_only(self):
        book = ContentNode.objects.get(slug="math-1")
        r = Client().get("/site/")
        self.assertContains(r, book.title)
        book.is_published = False
        book.save()
        self.assertNotContains(Client().get("/site/books/"), f'href="/site/books/{book.slug}/"')
        self.assertEqual(Client().get(f"/site/books/{book.slug}/").status_code, 404)

    def test_books_index_paginates_filtered_books_and_keeps_actions_in_a_shared_row(self):
        from apps.catalog.models import Major

        major = Major.objects.create(slug="batch-major", name="رشته‌ی آزمایشی")
        for i in range(13):
            book = ContentNode.add_root(
                kind=ContentNode.Kind.BOOK,
                title=f"کتاب آزمایشی {i:02d}",
                slug=f"batch-book-{i:02d}",
                is_published=True,
            )
            book.majors.add(major)

        client = Client()
        first = client.get("/site/books/", {"major": major.slug})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.context["page_obj"].paginator.count, 13)
        self.assertEqual(len(first.context["books"]), 12)
        self.assertEqual(first.context["selected_major"], major.slug)
        self.assertContains(first, 'class="shelf book-index-track"')
        self.assertContains(first, 'data-shelf-scroll')
        self.assertContains(first, 'class="bk-action"')
        self.assertContains(first, 'href="?major=batch-major&amp;page=2"')
        self.assertContains(first, "نمایش کتاب‌های بیشتر")

        second = client.get("/site/books/", {"major": major.slug, "page": 2})
        self.assertEqual(second.context["page_obj"].number, 2)
        self.assertEqual(len(second.context["books"]), 1)
        self.assertEqual(second.context["books"][0]["book"].slug, "batch-book-12")

    def test_book_page_samples_never_show_answers(self):
        q = Question.objects.filter(node__path__startswith=ContentNode.objects.get(slug="math-1").path, is_archived=False).first()
        q.is_sample = True
        q.is_free = True
        q.save()
        r = Client().get("/site/books/math-1/")
        self.assertContains(r, f'data-id="{q.id}"')
        html = r.content.decode()
        self.assertNotIn("is_correct", html)
        self.assertIn("limo-labels", html)
        self.assertIn("sec-list", html)
        if q.explanation:
            self.assertNotIn(q.explanation[:40], html)

    def test_auto_samples_and_coming_soon_and_home_dynamic(self):
        from apps.catalog.models import Banner, BookChange
        from .models import SiteSettings

        book = ContentNode.objects.get(slug="math-1")
        # Even when no question has is_sample=True, readable questions from free chapters are shown automatically.
        Question.objects.filter(node__path__startswith=book.path).update(is_sample=False)
        book.about = ""
        book.save()
        r = Client().get("/site/books/math-1/")
        self.assertContains(r, 'class="feat sample"')
        self.assertContains(r, "درباره‌ی کتاب")

        # Home page shows editable features, live stats, sample test, banners and book changes.
        s = SiteSettings.get()
        s.features_title = "چهار ابزار ویژه"
        s.save()
        Banner.objects.create(title="بنر تستی خانه", subtitle="زیرعنوان بنر", is_active=True)
        BookChange.objects.create(book=book, text="به‌روزرسانی فصل اول")
        home_r = Client().get("/site/")
        self.assertContains(home_r, "چهار ابزار ویژه")
        self.assertContains(home_r, "بنر تستی خانه")
        self.assertContains(home_r, "به‌روزرسانی فصل اول")
        self.assertContains(home_r, "یک تست واقعی را همین الان امتحان کن")

        # Coming-soon (or empty) book page shows structured preparation card, release estimate and related books.
        soon = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="فیزیک نوین", slug="modern-phys",
            is_published=True, is_coming_soon=False, release_estimate="آذر ۱۴۰۵",
        )
        soon_r = Client().get(f"/site/books/{soon.slug}/")
        self.assertEqual(soon_r.status_code, 200)
        self.assertContains(soon_r, "در حال برنامه‌ریزی")
        self.assertContains(soon_r, "آذر ۱۴۰۵")
        self.assertContains(soon_r, book.title)
        soon_list = Client().get("/site/books/")
        self.assertContains(soon_list, "در حال برنامه‌ریزی")
        self.assertContains(soon_list, "این کتاب در حال برنامه‌ریزی است")
        self.assertContains(soon_list, "وضعیت آن به «به‌زودی» تغییر می‌کند")

        # Content protection page renders on the website and in the app API.
        prot_r = Client().get("/site/p/protection/")
        self.assertEqual(prot_r.status_code, 200)
        self.assertContains(prot_r, "حفاظت از محتوا")
        self.assertContains(prot_r, "انگشت‌نگاری دیجیتال")
        api_prot = Client().get("/api/v1/app/pages/protection/")
        self.assertEqual(api_prot.status_code, 200)
        self.assertEqual(api_prot.json()["title"], "حفاظت از محتوا")

        # Admin can add custom pages and custom navigation items.
        from .models import SiteNavItem, SitePage

        SitePage.objects.create(slug="konkur-1405", title="راهنمای کنکور ۱۴۰۵", body="متن راهنما", show_in_nav=True)
        SiteNavItem.objects.create(title="لینک سفارشی منو", url="https://example.com", order=99)
        custom_r = Client().get("/site/p/konkur-1405/")
        self.assertEqual(custom_r.status_code, 200)
        self.assertContains(custom_r, "راهنمای کنکور ۱۴۰۵")
        self.assertContains(custom_r, "لینک سفارشی منو")

    def test_home_separates_updates_from_vertical_offers_and_does_not_drop_valid_banners_after_four(self):
        from apps.catalog.models import Banner, BookChange
        from apps.commerce.models import SaleCampaign
        from .models import SiteSettings

        now = timezone.now()
        book = ContentNode.objects.get(slug="math-1")
        long_title = "پیشنهاد ویژه‌ی کتاب ریاضی برای مطالعه‌ی دقیق‌تر و کامل‌تر " * 2
        long_subtitle = "این توضیح بلند باید بدون بریده‌شدن در کارت پیشنهاد دیده شود؛ " * 2

        # These overlapping legacy rows are intentionally invalid as banner payloads; the newest campaign is the
        # checkout winner and appears after them in display priority. Filtering happens before any presentation cap.
        for i in range(5):
            campaign = SaleCampaign.objects.create(
                title=f"کمپین قدیمی {i}", book=book, discounted_price=210_000 + i * 1_000,
                starts_at=now - timedelta(hours=10 - i), ends_at=now + timedelta(hours=2),
            )
            Banner.objects.create(
                title=f"بنر کمپین قدیمی {i}", template="sale", sale_campaign=campaign, priority=100 - i,
            )
        winner = SaleCampaign.objects.create(
            title="کمپین برنده", book=book, discounted_price=199_000,
            starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=3),
        )
        Banner.objects.create(
            title=long_title, subtitle=long_subtitle, template="sale", sale_campaign=winner, priority=0,
            button="همین حالا بخوان",
        )
        for i in range(6):
            Banner.objects.create(
                title="خبر کوتاه" if i == 0 else f"خبر شماره‌ی {i} از تازه‌های بلند لیموخوان",
                subtitle="اطلاعیه‌ی تازه" if i == 0 else "جزئیات کامل اطلاعیه؛ این متن در بخش تازه‌ها نمایش داده می‌شود.",
                is_active=True, priority=50 - i,
            )
        BookChange.objects.create(book=book, text="به‌روزرسانی مهم فصل اول")

        home = Client().get("/site/")
        self.assertEqual(home.status_code, 200)
        html = home.content.decode()
        for i in range(6):
            self.assertIn("خبر کوتاه" if i == 0 else f"خبر شماره‌ی {i} از تازه‌های بلند لیموخوان", html)
        self.assertIn("به‌روزرسانی مهم فصل اول", html)
        self.assertIn(long_title, html)
        self.assertIn(long_subtitle, html)
        self.assertIn("۱۹۹ هزار تومان", html)
        self.assertIn("id=\"latest-updates\"", html)
        self.assertIn("id=\"special-offers\"", html)
        self.assertIn("offer-card", html)
        self.assertNotIn("بنر کمپین قدیمی", html)

        features = html.index('class="grid4"')
        offers = html.index('id="special-offers"')
        books = html.index('class="shelf"')
        feature_band = html.index('class="band"')
        sample = html.index("یک تست واقعی را همین الان امتحان کن")
        latest = html.index('id="latest-updates"')
        prices = html.index('class="prices"')
        self.assertLess(features, offers)
        self.assertLess(offers, books)
        self.assertLess(books, feature_band)
        self.assertLess(feature_band, sample)
        self.assertLess(sample, latest)
        self.assertLess(latest, prices)
        self.assertNotIn("پیشنهادهای ویژه", html[latest:prices])

        settings = SiteSettings.get()
        settings.show_updates = False
        settings.show_sample_test = False
        settings.save(update_fields=["show_updates", "show_sample_test"])
        quiet_home = Client().get("/site/")
        self.assertNotContains(quiet_home, "خبر کوتاه")
        self.assertNotContains(quiet_home, "به‌روزرسانی مهم فصل اول")
        self.assertNotContains(quiet_home, "یک تست واقعی را همین الان امتحان کن")
        self.assertContains(quiet_home, long_title)
        quiet_html = quiet_home.content.decode()
        self.assertLess(quiet_html.index('id="special-offers"'), quiet_html.index('class="prices"'))

    def test_offer_cards_wrap_and_remain_compact_for_one_or_many_campaigns(self):
        css = (Path(__file__).resolve().parent / "static/website/site.css").read_text(encoding="utf-8")
        self.assertIn("flex-wrap: wrap", css)
        self.assertIn("justify-content: center", css)
        self.assertIn("flex: 1 1 300px", css)
        self.assertIn("max-width: 360px", css)

    def test_discount_prices_and_the_same_campaign_banner_render_on_the_website(self):
        from apps.catalog.models import Banner
        from apps.commerce.models import Plan, SaleCampaign
        from .models import SiteSettings

        now = timezone.now()
        book = ContentNode.objects.get(slug="math-1")
        book_campaign = SaleCampaign.objects.create(
            title="کمپین کتاب ریاضی",
            book=book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=4),
        )
        plan = Plan.objects.get(title="اشتراک سه‌ماهه")
        plan_campaign = SaleCampaign.objects.create(
            title="کمپین اشتراک سه‌ماهه",
            plan=plan,
            discounted_price=499_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=4),
        )
        Banner.objects.create(title="بنر تخفیف کتاب", subtitle="قیمت ویژه تا پایان کمپین", template="sale", sale_campaign=book_campaign, priority=100)
        Banner.objects.create(title="بنر تخفیف اشتراک", subtitle="همه‌ی کتاب‌ها", template="sale", sale_campaign=plan_campaign, priority=99)
        settings = SiteSettings.get()
        settings.show_updates = False
        settings.save(update_fields=["show_updates"])

        home = Client().get("/site/")
        self.assertContains(home, "بنر تخفیف کتاب")
        self.assertContains(home, "بنر تخفیف اشتراک")
        self.assertContains(home, "/subscribe")
        self.assertContains(home, "۱۹۹ هزار تومان")
        self.assertContains(home, "۲۰٫۱٪ تخفیف")
        self.assertContains(home, "اشتراک سه‌ماهه")
        self.assertContains(home, "قیمت ویژه")
        self.assertNotContains(home, "صرفه‌جویی")

        book_page = Client().get("/site/books/math-1/")
        self.assertContains(book_page, "قیمت عادی")
        self.assertContains(book_page, "قیمت ویژه")
        self.assertContains(book_page, "۵۰ هزار تومان تخفیف")
        self.assertNotContains(book_page, "صرفه‌جویی")

        books_page = Client().get("/site/books/")
        self.assertRegex(
            books_page.content.decode(),
            r'(?s)<a class="bk" href="/site/books/math-1/"[^>]*>.*?<div class="cover".*?'
            r'<span class="bk-ribbon">.*?فصل اول رایگان</span>.*?'
            r'<div class="bk-action">.*?<span class="bk-price">۱۹۹ هزار تومان</span>\s*'
            r'<span class="bk-discount-chip">۲۰٫۱٪</span>',
        )

        pricing = Client().get("/site/pricing/")
        self.assertContains(pricing, "۶۶۹ هزار تومان")
        self.assertContains(pricing, "۴۹۹ هزار تومان")
        self.assertContains(pricing, "هزینه‌ی کلِ ۳ ماه اشتراک")

    def test_sitemap_and_robots(self):
        c = Client()
        self.assertContains(c.get("/site/sitemap.xml"), "/site/books/math-1/")
        self.assertContains(c.get("/site/robots.txt"), "Sitemap:")

    def test_a_book_with_only_a_free_section_is_labelled_with_chapter_number(self):
        """وقتی فقط بخشی از یک فصل رایگان است، روی جلد سایت هم مانند اپ «بخشی از فصل N رایگان» می‌آید."""
        from apps.catalog.models import Major

        major = Major.objects.create(slug="free-part-major", name="رشته‌ی نمونه")
        book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب با بخش رایگان", slug="free-part-book",
                                    is_published=True, price=120_000)
        book.majors.add(major)
        chapter = book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل اول", slug="ch1", is_published=True)
        chapter.add_child(kind=ContentNode.Kind.SECTION, title="بخش اول", slug="s1", is_published=True, is_free=True)

        card = next(c for c in Client().get("/site/books/").context["books"] if c["book"].slug == book.slug)
        self.assertEqual(card["product_status"], {"state": "paid", "preview": "sample", "promotion": "none"})
        self.assertEqual(card["sample_label"], "بخشی از فصل ۱ رایگان")
        html = Client().get("/site/books/").content.decode()
        self.assertIn('<span class="bk-ribbon">', html)
        self.assertIn("بخشی از فصل ۱ رایگان", html)

        detail = Client().get(f"/site/books/{book.slug}/")
        self.assertEqual(detail.context["sample_label"], "بخشی از فصل ۱ رایگان")
        self.assertContains(detail, "بخشی از فصل ۱ رایگان")

        # Partial free section in chapter 2 while chapter 1 is locked.
        ContentNode.objects.filter(pk=chapter.pk).update(is_free=False)
        ContentNode.objects.filter(slug="s1").update(is_free=False)
        ch2 = book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل دوم", slug="ch2", is_published=True)
        ch2.add_child(kind=ContentNode.Kind.SECTION, title="بخش دوم", slug="s2", is_published=True, is_free=True)
        card2 = next(c for c in Client().get("/site/books/").context["books"] if c["book"].slug == book.slug)
        self.assertEqual(card2["sample_label"], "بخشی از فصل ۲ رایگان")

        # Whole free book matches the app's «کل کتاب رایگان» cover label.
        free_book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب کاملاً رایگان", slug="all-free-book",
                                         is_published=True, is_free=True)
        free_book.majors.add(major)
        free_card = next(c for c in Client().get("/site/books/").context["books"] if c["book"].slug == free_book.slug)
        self.assertEqual(free_card["sample_label"], "کل کتاب رایگان")
        self.assertEqual(Client().get(f"/site/books/{free_book.slug}/").context["sample_label"], "کل کتاب رایگان")

    def test_website_book_page_renders_author_and_reviews_tabs_from_app_source(self):
        from apps.accounts.models import User
        from apps.catalog.models import BookEditor, BookOpinion, TeacherProfile

        book = ContentNode.objects.get(slug="math-1")
        teacher = User.objects.create_user("09129990001", first_name="دکتر", last_name="احمدی")
        TeacherProfile.objects.create(
            user=teacher,
            academic_title="عضو هیئت علمی ریاضی",
            bio="توضیحات کامل سوابق علمی مؤلف کتاب.",
            contact_email="ahmadi@example.com",
        )
        BookEditor.objects.create(user=teacher, book=book)

        reviewer = User.objects.create_user("09129990002", first_name="مریم", last_name="رضایی")
        BookOpinion.objects.create(
            book=book, user=reviewer, rating=5, satisfaction_percent=95, study_percent=65, test_percent=40,
            body="کتاب بسیار دقیق و روان است.", teacher_reply="ممنون از نظر ارزشمند شما.",
            status=BookOpinion.Status.APPROVED,
        )
        BookOpinion.objects.create(
            book=book, user=teacher, rating=1, body="نظر تأییدنشده نباید دیده شود",
            status=BookOpinion.Status.PENDING,
        )

        r = Client().get(f"/site/books/{book.slug}/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-book-tabs')
        self.assertContains(r, "درباره‌ی کتاب")
        self.assertContains(r, "درباره‌ی نویسنده")
        self.assertContains(r, "نظرات (۱)")
        self.assertContains(r, "عضو هیئت علمی ریاضی")
        self.assertContains(r, "توضیحات کامل سوابق علمی مؤلف کتاب.")
        self.assertContains(r, "ahmadi@example.com")
        self.assertContains(r, "مریم رضایی")
        self.assertContains(r, "کتاب بسیار دقیق و روان است.")
        self.assertContains(r, "ممنون از نظر ارزشمند شما.")
        self.assertNotContains(r, "نظر تأییدنشده نباید دیده شود")

        css = (Path(__file__).resolve().parent / "static/website/site.css").read_text(encoding="utf-8")
        self.assertIn(".book-tabs-body", css)
        self.assertIn("overflow-y: auto", css)
        js = (Path(__file__).resolve().parent / "static/website/site.js").read_text(encoding="utf-8")
        self.assertIn("bookTabs()", js)

    def test_website_cover_payload_carries_approved_rating(self):
        import json
        from apps.accounts.models import User
        from apps.catalog.models import BookOpinion, ContentNode

        book = ContentNode.objects.get(slug="math-1")
        user1 = User.objects.create_user("09121230001")
        user2 = User.objects.create_user("09121230002")
        BookOpinion.objects.create(book=book, user=user1, rating=5, body="عالی", status=BookOpinion.Status.APPROVED)
        BookOpinion.objects.create(book=book, user=user2, rating=4, body="خوب", status=BookOpinion.Status.APPROVED)

        card = next(c for c in Client().get("/site/books/").context["books"] if c["book"].slug == "math-1")
        cover_data = json.loads(card["cover"])
        self.assertEqual(cover_data["rating"], 4.5)
        self.assertEqual(cover_data["rating_count"], 2)

        detail_ctx = Client().get("/site/books/math-1/").context
        detail_cover = json.loads(detail_ctx["cover"])
        self.assertEqual(detail_cover["rating"], 4.5)
        self.assertEqual(detail_cover["rating_count"], 2)

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

    def test_the_app_links_leave_the_site_host_for_the_web_app(self):
        """The website's own host serves no web app, so «ورود» must point at the host that does."""
        with override_settings(WEBSITE_HOSTS=["limookhan.ir"], ALLOWED_HOSTS=["limookhan.ir", "testserver"],
                               APP_URL="/", SITE_URL="https://api.example.ir"):
            home = Client(HTTP_HOST="limookhan.ir").get("/")
            self.assertEqual(home.status_code, 200)
            self.assertEqual(home.context["app_url"], "https://api.example.ir")
            self.assertContains(home, "https://api.example.ir")


class AppPagesTests(TestCase):
    """«راهنما» and «قوانین» in the app."""

    def setUp(self):
        from .models import HelpPage, SitePage

        self.terms, _ = SitePage.objects.update_or_create(slug="terms", defaults={"title": "قوانین", "body": "## یک\n\nمتن", "show_in_app": True})
        self.about, _ = SitePage.objects.update_or_create(slug="about", defaults={"title": "درباره", "body": "x", "show_in_app": False})
        HelpPage.objects.create(title="دوم", body="b", order=2)
        HelpPage.objects.create(title="اول", body="$x^2$", order=1)
        HelpPage.objects.create(title="پنهان", body="h", is_hidden=True)

    def test_lists_only_what_is_shown(self):
        d = self.client.get("/api/v1/app/pages/").json()
        self.assertEqual([h["title"] for h in d["help"]], ["اول", "دوم"])
        slugs = [p["slug"] for p in d["pages"]]
        self.assertIn("terms", slugs)
        self.assertNotIn("about", slugs)
        self.assertIsNone(d["pages"][slugs.index("terms")]["important_at"])

    def test_pages_open_by_rule(self):
        from .models import HelpPage

        first = HelpPage.objects.get(title="اول")
        self.assertEqual(self.client.get(f"/api/v1/app/help/{first.id}/").json()["body"], "$x^2$")
        hidden = HelpPage.objects.get(title="پنهان")
        self.assertEqual(self.client.get(f"/api/v1/app/help/{hidden.id}/").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/app/pages/about/").status_code, 404)
        # Linked under the login button: opens even when not listed.
        self.terms.show_in_app = False
        self.terms.save()
        self.assertEqual(self.client.get("/api/v1/app/pages/terms/").json()["title"], "قوانین")

    def test_important_tick_sets_the_date_only_when_ticked(self):
        from apps.accounts.models import User

        admin = User.objects.create_superuser("09120000009", password="Pass-12345")
        self.client.force_login(admin)
        url = f"/admin/website/sitepage/{self.terms.id}/change/"
        form = {"slug": "terms", "title": "قوانین", "body": "تازه", "show_in_app": "on"}
        self.assertEqual(self.client.post(url, form).status_code, 302)
        self.terms.refresh_from_db()
        self.assertIsNone(self.terms.important_at)
        self.client.post(url, {**form, "important": "on"})
        self.terms.refresh_from_db()
        self.assertIsNotNone(self.terms.important_at)
        self.assertEqual(self.client.get("/admin/website/helppage/add/").status_code, 200)
        self.assertContains(self.client.get("/admin/website/helppage/add/"), "data-md-editor")

    def test_navigation_and_footer_contain_teacher_portal_links(self):
        from django.urls import reverse
        r = Client().get("/site/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "درگاه اساتید")
        self.assertContains(r, "ورود اساتید و مؤلفان")
        self.assertContains(r, reverse("admin:login"))

    def test_public_book_page_signs_authorized_media_and_blocks_cross_book_and_locked(self):
        import shutil
        import tempfile
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage
        from django.core.management import call_command
        from django.test import override_settings
        from apps.catalog.models import ContentNode
        from apps.learning.models import Choice, Question

        media_dir = tempfile.mkdtemp()
        try:
            with override_settings(MEDIA_ROOT=media_dir):
                call_command("load_samples", stdout=io.StringIO())
                free_img = default_storage.save("content/math-1/limits/444444444444444444444444.png", ContentFile(b"PNG"))
                locked_img = default_storage.save("content/math-1/derivatives/555555555555555555555555.png", ContentFile(b"PNG"))
                other_img = default_storage.save("content/other-book/ch/666666666666666666666666.png", ContentFile(b"PNG"))

                book = ContentNode.objects.get(slug="math-1")
                book.about = f"![ok](media:{free_img}) ![locked](media:{locked_img}) ![other](media:{other_img})"
                book.save(update_fields=["about"])

                sec = ContentNode.objects.get(slug="limit-idea")
                q = Question.objects.create(
                    node=sec,
                    slug="site-img-q",
                    stem=f"متن ![q](media:{free_img}) ![qlocked](media:{locked_img}) ![qother](media:{other_img})",
                    is_sample=True,
                )
                Choice.objects.create(question=q, order=1, text=f"یک ![c](media:{locked_img})", is_correct=True)
                Choice.objects.create(question=q, order=2, text="دو", is_correct=False)

                r = Client().get("/site/books/math-1/")
                self.assertEqual(r.status_code, 200)
                body = r.content.decode("utf-8")
                self.assertIn(f"/media/{free_img}?exp=", body)
                self.assertNotIn(f"/media/{locked_img}?exp=", body)
                self.assertNotIn(f"/media/{other_img}?exp=", body)
        finally:
            shutil.rmtree(media_dir, ignore_errors=True)

