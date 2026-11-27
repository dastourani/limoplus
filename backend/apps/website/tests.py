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
        self.assertContains(soon_r, 'class="bk-ribbon bk-ribbon-planning"')
        self.assertContains(soon_r, "آذر ۱۴۰۵")
        self.assertContains(soon_r, "وضعیت آن به «به‌زودی» تغییر می‌کند")
        self.assertContains(soon_r, book.title)
        soon_list = Client().get("/site/books/")
        self.assertContains(soon_list, "در حال برنامه‌ریزی")
        self.assertContains(soon_list, 'class="bk-ribbon bk-ribbon-planning"')
        self.assertContains(soon_list, "این کتاب در حال برنامه‌ریزی است")
        self.assertContains(soon_list, "در صف تولید محتوا قرار دارد.")
        self.assertNotContains(soon_list, "وضعیت آن به «به‌زودی» تغییر می‌کند")

        # Content protection page renders on the website and in the app API.
        prot_r = Client().get("/site/p/protection/")
        self.assertEqual(prot_r.status_code, 200)
        self.assertContains(prot_r, "حقوق مؤلفان و ناشران و حفاظت از محتوا")
        self.assertContains(prot_r, "AES-256-GCM")
        self.assertContains(prot_r, "رویداد کپی ثبت‌شده")
        api_prot = Client().get("/api/v1/app/pages/protection/")
        self.assertEqual(api_prot.status_code, 200)
        self.assertEqual(api_prot.json()["title"], "حقوق مؤلفان و ناشران و حفاظت از محتوا")
        self.assertIsNotNone(api_prot.json()["important_at"])

        # Admin can add custom pages and custom navigation items.
        from .models import SiteNavItem, SitePage

        SitePage.objects.create(slug="konkur-1405", title="راهنمای کنکور ۱۴۰۵", body="متن راهنما", show_in_nav=True)
        SiteNavItem.objects.create(title="لینک سفارشی منو", url="https://example.com", order=99)
        custom_r = Client().get("/site/p/konkur-1405/")
        self.assertEqual(custom_r.status_code, 200)
        self.assertContains(custom_r, "راهنمای کنکور ۱۴۰۵")
        self.assertContains(custom_r, "لینک سفارشی منو")

    def test_categorized_faq_and_teacher_links(self):
        from .models import FaqItem

        faq_r = Client().get("/site/faq/")
        self.assertEqual(faq_r.status_code, 200)
        self.assertContains(faq_r, "پاسخ‌های فوری و پرسش‌های اصلی")
        self.assertContains(faq_r, "لیموخوان چیست و داخل هر کتاب چه امکاناتی دارم؟")
        self.assertNotContains(faq_r, "هر کتاب یک خلاصه، یک درسنامه‌ی کامل، تست با پاسخ تشریحی")
        self.assertContains(faq_r, 'id="books"')
        self.assertContains(faq_r, 'id="account-payment"')
        self.assertContains(faq_r, 'id="study-offline"')
        self.assertContains(faq_r, 'id="review-quiz"')
        self.assertContains(faq_r, 'id="classroom"')
        self.assertContains(faq_r, 'id="teachers"')
        self.assertContains(faq_r, "استاد یا مؤلف هستید؟")
        self.assertContains(faq_r, "معنای «لیموهای من» و رنگ برش‌های لیمو")
        self.assertContains(faq_r, 'href="/site/download/"')
        self.assertContains(faq_r, 'href="/site/p/contact/"')
        self.assertContains(faq_r, 'href="/site/p/protection/"')

        self.assertEqual(FaqItem.objects.filter(is_hidden=False, group=FaqItem.Group.TOP).count(), 8)
        self.assertEqual(FaqItem.objects.filter(is_hidden=False, group=FaqItem.Group.TEACHERS).count(), 10)

        home_r = Client().get("/site/")
        self.assertContains(home_r, "لیموخوان چیست و داخل هر کتاب چه امکاناتی دارم؟")
        self.assertNotContains(home_r, "اگر گوشی عوض کنم، کتاب‌ها، یادداشت‌ها و پیشرفتم چه می‌شود؟")

        pricing_r = Client().get("/site/pricing/")
        self.assertContains(pricing_r, "اگر گوشی عوض کنم، کتاب‌ها، یادداشت‌ها و پیشرفتم چه می‌شود؟")
        self.assertNotContains(pricing_r, "پول از حسابم کم شده ولی کتاب یا اشتراکم فعال نشده؛ چه کنم؟")

        teacher_login_r = Client().get("/teacher/login/")
        self.assertEqual(teacher_login_r.status_code, 200)
        self.assertContains(teacher_login_r, "/site/faq/#teachers")

        teacher_app_r = Client().get("/site/teacher-application/")
        self.assertEqual(teacher_app_r.status_code, 200)
        self.assertContains(teacher_app_r, "/site/faq/#teachers")
        self.assertContains(teacher_app_r, "پیام‌رسان بله")

    def test_privacy_page_reflects_live_data_flows_retention_and_support_actions(self):
        priv_r = Client().get("/site/p/privacy/")
        self.assertEqual(priv_r.status_code, 200)
        self.assertContains(priv_r, "حریم خصوصی در لیموخوان")
        self.assertNotContains(priv_r, "فقط برای خود شما")
        self.assertContains(priv_r, 'href="#sec-5"')
        self.assertContains(priv_r, 'id="sec-5"')
        self.assertContains(priv_r, "پیام‌رسان بله")
        self.assertContains(priv_r, "ابزار آماده‌سازی محتوای تألیفی")
        self.assertContains(priv_r, "۷ روز کاری")
        self.assertContains(priv_r, "درخواست دربارهٔ اطلاعات حساب من")
        self.assertContains(priv_r, "گزارش مشاهدهٔ اطلاعات شخص دیگری")
        api_priv = Client().get("/api/v1/app/pages/privacy/")
        self.assertEqual(api_priv.status_code, 200)
        self.assertEqual(api_priv.json()["title"], "حریم خصوصی در لیموخوان")
        self.assertIsNotNone(api_priv.json()["important_at"])

    def test_terms_page_reflects_live_access_refund_and_support_actions(self):
        from .views import simple_text

        terms_r = Client().get("/site/p/terms/")
        self.assertEqual(terms_r.status_code, 200)
        self.assertContains(terms_r, "شرایط استفاده و خرید در لیموخوان")
        self.assertNotContains(terms_r, "خرید هر کتاب برای همیشه است")
        self.assertContains(terms_r, 'href="#sec-1"')
        self.assertContains(terms_r, 'href="#sec-3"')
        self.assertContains(terms_r, 'href="#sec-6"')
        self.assertContains(terms_r, 'id="sec-1"')
        self.assertContains(terms_r, 'id="sec-6"')
        self.assertContains(terms_r, "<div class=\"prose-table\"><table>")
        self.assertContains(terms_r, "بدون تاریخ انقضای اشتراک")
        self.assertContains(terms_r, "معادل ۳۰ روز")
        self.assertContains(terms_r, "توقف فروش یک کتاب به خریداران جدید، دسترسی خریداران قبلیِ همان کتاب را لغو نمی‌کند")
        self.assertContains(terms_r, "۷ روز کاری")
        self.assertContains(terms_r, "پیگیری سفارش یا درخواست استرداد")
        self.assertContains(terms_r, "گزارش مشکل حساب یا دسترسی")
        api_terms = Client().get("/api/v1/app/pages/terms/")
        self.assertEqual(api_terms.status_code, 200)
        self.assertEqual(api_terms.json()["title"], "شرایط استفاده و خرید در لیموخوان")
        self.assertIsNotNone(api_terms.json()["important_at"])

        table_html = simple_text("| <b>الف</b> | ب |\n|---|---|\n| <script>x</script> | ۲ |")
        self.assertIn("<table><thead><tr><th>&lt;b&gt;الف&lt;/b&gt;</th><th>ب</th></tr></thead>", table_html)
        self.assertIn("<td>&lt;script&gt;x&lt;/script&gt;</td><td>۲</td>", table_html)

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

        html = r.content.decode("utf-8")
        self.assertRegex(html, r'<div class="book-tab-panel" role="tabpanel" data-tab-panel="book">')
        self.assertRegex(html, r'<div class="book-tab-panel" role="tabpanel" data-tab-panel="author" hidden>')
        self.assertRegex(html, r'<div class="book-tab-panel" role="tabpanel" data-tab-panel="reviews" hidden>')

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

    def test_cover_ribbon_and_two_layer_release_notes_across_site_and_api(self):
        from apps.accounts.models import User
        from apps.catalog.models import ContentNode, Major
        from .models import SiteSettings

        major = Major.objects.create(slug="ribbon-major", name="رشته تست")
        preparing_default = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب برنامه‌ریزی ۱", slug="prep-default",
            is_published=True, is_coming_soon=False, release_estimate="دی ۱۴۰۵",
        )
        preparing_custom = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب برنامه‌ریزی ۲", slug="prep-custom",
            is_published=True, is_coming_soon=False, release_estimate="بهمن ۱۴۰۵",
            release_note="توضیح اختصاصی همین کتاب برای برنامه‌ریزی.",
        )
        coming_soon_book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب به‌زودی", slug="soon-book",
            is_published=True, is_coming_soon=True, release_estimate="اسفند ۱۴۰۵",
        )
        paid_locked = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب پولی بدون نمونه", slug="paid-locked",
            is_published=True, price=250_000,
        )
        paid_locked.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل پولی", slug="paid-ch1", is_published=True, is_free=False)
        for b in (preparing_default, preparing_custom, coming_soon_book, paid_locked):
            b.majors.add(major)

        # Layer 1: editing global defaults in SiteSettings applies across website cards, book detail, and app API.
        s = SiteSettings.get()
        s.preparing_hover_note = "متن کوتاه سراسری از پنل."
        s.preparing_note = "متن کامل سراسری برنامه‌ریزی از پنل."
        s.coming_soon_note = "متن کامل سراسری به‌زودی از پنل."
        s.save()

        c = Client()
        home_html = c.get("/site/").content.decode("utf-8")
        books_html = c.get("/site/books/").content.decode("utf-8")
        for html in (home_html, books_html):
            self.assertIn("bk-ribbon-planning", html)
            self.assertIn("bk-ribbon-soon", html)
            self.assertIn("bk-ribbon-locked", html)
            self.assertIn("نسخه‌ی کامل", html)
            self.assertIn("متن کوتاه سراسری از پنل.", html)
            self.assertIn("توضیح اختصاصی همین کتاب برای برنامه‌ریزی.", html)
            self.assertNotIn("متن کامل سراسری برنامه‌ریزی از پنل.", html)

        # Book detail pages mirror cover ribbons and resolve Layer 2 override vs Layer 1 defaults.
        r_default = c.get(f"/site/books/{preparing_default.slug}/")
        self.assertContains(r_default, "bk-ribbon-planning")
        self.assertContains(r_default, "متن کامل سراسری برنامه‌ریزی از پنل.")
        r_custom = c.get(f"/site/books/{preparing_custom.slug}/")
        self.assertContains(r_custom, "bk-ribbon-planning")
        self.assertContains(r_custom, "توضیح اختصاصی همین کتاب برای برنامه‌ریزی.")
        self.assertNotContains(r_custom, "متن کامل سراسری برنامه‌ریزی از پنل.")
        r_soon = c.get(f"/site/books/{coming_soon_book.slug}/")
        self.assertContains(r_soon, "bk-ribbon-soon")
        self.assertContains(r_soon, "متن کامل سراسری به‌زودی از پنل.")
        r_locked = c.get(f"/site/books/{paid_locked.slug}/")
        self.assertContains(r_locked, "bk-ribbon-locked")
        self.assertContains(r_locked, "نسخه‌ی کامل")

        # App/web-app API exposes resolved release_note on both list and detail endpoints.
        api_list = {row["slug"]: row for row in c.get("/api/v1/books/").json()}
        self.assertEqual(api_list[preparing_default.slug]["release_note"], "متن کامل سراسری برنامه‌ریزی از پنل.")
        self.assertEqual(api_list[preparing_custom.slug]["release_note"], "توضیح اختصاصی همین کتاب برای برنامه‌ریزی.")
        self.assertEqual(api_list[coming_soon_book.slug]["release_note"], "متن کامل سراسری به‌زودی از پنل.")
        self.assertEqual(c.get(f"/api/v1/books/{preparing_custom.slug}/").json()["release_note"], "توضیح اختصاصی همین کتاب برای برنامه‌ریزی.")

        # Both layers are visibly exposed in the Django Admin panel.
        admin_user = User.objects.create_superuser("09120009988")
        c.force_login(admin_user)
        site_admin = c.get(f"/admin/website/sitesettings/{s.pk}/change/")
        self.assertEqual(site_admin.status_code, 200)
        for field_name in ("id_preparing_hover_note", "id_preparing_note", "id_coming_soon_note"):
            self.assertContains(site_admin, field_name)
        book_admin = c.get(f"/admin/catalog/book/{preparing_default.pk}/change/")
        self.assertEqual(book_admin.status_code, 200)
        self.assertContains(book_admin, "id_release_note")

    def test_cover_ribbon_matches_app_across_guest_purchase_subscription_editor_and_staff(self):
        from django.contrib.auth.models import Group, Permission
        from rest_framework.test import APIClient
        from apps.accounts.models import User
        from apps.catalog.access import BOOK_EDITOR_GROUP
        from apps.catalog.models import BookEditor, ContentNode, Major
        from apps.commerce.models import Entitlement

        major = Major.objects.create(slug="parity-major", name="رشته همسانی")
        paid_book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب پولی با نمونه", slug="parity-paid",
            is_published=True, price=200_000,
        )
        paid_book.majors.add(major)
        paid_book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل اول", slug="p-ch1", is_published=True, is_free=True)
        paid_book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل دوم", slug="p-ch2", is_published=True, is_free=False)

        free_book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب کاملاً رایگان", slug="parity-free",
            is_published=True, is_free=True,
        )
        free_book.majors.add(major)
        free_book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل اول", slug="f-ch1", is_published=True, is_free=True)

        preparing_book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK, title="کتاب در حال برنامه‌ریزی", slug="parity-preparing",
            is_published=True, is_coming_soon=False,
        )
        preparing_book.majors.add(major)

        def assert_book_ribbon(client: Client, slug: str, expected_text: str, expected_kind: str):
            home_card = next(c for c in client.get("/site/").context["books"] if c["book"].slug == slug)
            list_card = next(c for c in client.get("/site/books/").context["books"] if c["book"].slug == slug)
            detail_r = client.get(f"/site/books/{slug}/")
            for ribbon in (home_card["cover_ribbon"], list_card["cover_ribbon"], detail_r.context["cover_ribbon"]):
                self.assertEqual(ribbon["text"], expected_text)
                self.assertEqual(ribbon["kind"], expected_kind)
            self.assertContains(detail_r, expected_text)
            if expected_kind != "free":
                self.assertContains(detail_r, f"bk-ribbon-{expected_kind}")

        def api_for(user=None):
            ac = APIClient()
            if user is not None:
                ac.force_authenticate(user=user)
            return ac

        # 1. Guest: paid+sample shows sample ribbon; whole-free shows کل کتاب رایگان; preparing shows در حال برنامه‌ریزی.
        guest = Client()
        assert_book_ribbon(guest, paid_book.slug, "فصل اول رایگان", "free")
        assert_book_ribbon(guest, free_book.slug, "کل کتاب رایگان", "free")
        assert_book_ribbon(guest, preparing_book.slug, "در حال برنامه‌ریزی", "planning")
        api_guest = api_for().get(f"/api/v1/books/{paid_book.slug}/").json()
        self.assertFalse(api_guest["owned"])
        self.assertIsNone(api_guest["access"])

        # 2. Buyer (purchase): paid+sample switches to خریداری شده; whole-free stays کل کتاب رایگان.
        buyer = User.objects.create_user("09128880001")
        Entitlement.objects.create(user=buyer, book=paid_book, ends_at=None)
        buyer_client = Client()
        buyer_client.force_login(buyer)
        assert_book_ribbon(buyer_client, paid_book.slug, "خریداری شده", "access")
        assert_book_ribbon(buyer_client, free_book.slug, "کل کتاب رایگان", "free")
        api_buyer = api_for(buyer).get(f"/api/v1/books/{paid_book.slug}/").json()
        self.assertTrue(api_buyer["owned"])
        self.assertEqual(api_buyer["access"], "purchase")

        # 3. Subscriber (active major subscription): paid+sample switches to با اشتراک; whole-free stays کل کتاب رایگان.
        subscriber = User.objects.create_user("09128880002")
        Entitlement.objects.create(user=subscriber, major=major, ends_at=timezone.now() + timedelta(days=30))
        sub_client = Client()
        sub_client.force_login(subscriber)
        assert_book_ribbon(sub_client, paid_book.slug, "با اشتراک", "access")
        assert_book_ribbon(sub_client, free_book.slug, "کل کتاب رایگان", "free")
        api_sub = api_for(subscriber).get(f"/api/v1/books/{paid_book.slug}/").json()
        self.assertTrue(api_sub["owned"])
        self.assertEqual(api_sub["access"], "subscription")

        # 4. Book editor on their assigned books: paid+sample shows دسترسی تألیف; whole-free stays کل کتاب رایگان; preparing stays در حال برنامه‌ریزی.
        editor = User.objects.create_user("09128880003", is_staff=True)
        group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        editor.groups.add(group)
        perm = Permission.objects.get(codename="change_contentnode", content_type__app_label="catalog")
        editor.user_permissions.add(perm)
        for b in (paid_book, free_book, preparing_book):
            BookEditor.objects.create(user=editor, book=b, can_edit_content=True)
        ed_client = Client()
        ed_client.force_login(editor)
        assert_book_ribbon(ed_client, paid_book.slug, "دسترسی تألیف", "access")
        assert_book_ribbon(ed_client, free_book.slug, "کل کتاب رایگان", "free")
        assert_book_ribbon(ed_client, preparing_book.slug, "در حال برنامه‌ریزی", "planning")
        api_ed = api_for(editor).get(f"/api/v1/books/{paid_book.slug}/").json()
        self.assertEqual(api_ed["access"], "editor")

        # 5. Superuser/staff: paid+sample shows دسترسی مدیر; whole-free stays کل کتاب رایگان; preparing stays در حال برنامه‌ریزی.
        staff = User.objects.create_superuser("09128880004")
        staff_client = Client()
        staff_client.force_login(staff)
        assert_book_ribbon(staff_client, paid_book.slug, "دسترسی مدیر", "access")
        assert_book_ribbon(staff_client, free_book.slug, "کل کتاب رایگان", "free")
        assert_book_ribbon(staff_client, preparing_book.slug, "در حال برنامه‌ریزی", "planning")
        api_staff = api_for(staff).get(f"/api/v1/books/{paid_book.slug}/").json()
        self.assertTrue(api_staff["owned"])
        self.assertEqual(api_staff["access"], "staff")

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

    def test_about_page_and_justified_legal_tables(self):
        c = Client()
        r_about = c.get("/site/p/about/")
        self.assertEqual(r_about.status_code, 200)
        self.assertContains(r_about, "درباره ما")
        self.assertNotContains(r_about, "این متن نمونه است")
        self.assertContains(r_about, 'href="/site/p/about/"')
        self.assertContains(r_about, "مشاهدهٔ کتاب‌ها")

        r_api = c.get("/api/v1/app/pages/about/")
        self.assertEqual(r_api.status_code, 200)
        self.assertEqual(r_api.json()["slug"], "about")
        list_slugs = [p["slug"] for p in c.get("/api/v1/app/pages/").json()["pages"]]
        self.assertIn("about", list_slugs)

        r_terms = c.get("/site/p/terms/")
        self.assertEqual(r_terms.status_code, 200)
        self.assertContains(r_terms, '<div class="prose-table"><table>')

        from pathlib import Path
        css = (Path(__file__).resolve().parent / "static/website/site.css").read_text(encoding="utf-8")
        self.assertIn(".prose td { text-align: justify;", css)
        self.assertIn(".prose p, .prose li { font-size: 16px; line-height: 2.15; text-align: justify;", css)


class AppPagesTests(TestCase):
    """«راهنما» and «قوانین» in the app."""

    def setUp(self):
        from .models import HelpPage, SitePage

        self.terms, _ = SitePage.objects.update_or_create(
            slug="terms",
            defaults={"title": "قوانین", "body": "## یک\n\nمتن", "show_in_app": True, "important_at": None},
        )
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

        # Linked from checkout/receipts («پیگیری سفارش»): opens even when not listed and exposes SiteSettings contact info.
        from .models import SiteSettings

        settings_row = SiteSettings.get()
        settings_row.email = "support@limookhan.ir"
        settings_row.phone = "021-88000000"
        settings_row.save()
        contact_res = self.client.get("/api/v1/app/pages/contact/")
        self.assertEqual(contact_res.status_code, 200)
        self.assertIn("support@limookhan.ir", contact_res.json()["body"])
        self.assertIn("021-88000000", contact_res.json()["body"])

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
        self.assertContains(r, reverse("teacher-login"))

    def test_top_nav_contains_legal_and_support_dropdown_with_all_four_pages(self):
        r = Client().get("/site/p/privacy/")
        self.assertEqual(r.status_code, 200)
        nav_items = r.context["nav_items"]
        legal = next((item for item in nav_items if item["title"] == "قوانین و پشتیبانی"), None)
        self.assertIsNotNone(legal)
        self.assertTrue(legal["active"])
        self.assertEqual(
            [(sub["title"], sub["href"], sub["active"]) for sub in legal["children"]],
            [
                ("شرایط استفاده و خرید", "/site/p/terms/", False),
                ("حریم خصوصی", "/site/p/privacy/", True),
                ("حفاظت از محتوا", "/site/p/protection/", False),
                ("تماس با ما", "/site/p/contact/", False),
            ],
        )
        self.assertContains(r, 'class="nav-dd"')
        self.assertContains(r, "قوانین و پشتیبانی")
        self.assertContains(r, 'href="/site/p/terms/"')
        self.assertContains(r, 'href="/site/p/privacy/"')
        self.assertContains(r, 'href="/site/p/protection/"')
        self.assertContains(r, 'href="/site/p/contact/"')

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

    def test_prerelease_books_have_dimmed_cover_class(self):
        from apps.catalog.models import ContentNode, Major

        major = Major.objects.create(slug="pre-dim", name="رشته", order=1)
        soon = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="soon-dim", title="کتاب به‌زودی", is_published=True, is_coming_soon=True)
        soon.majors.add(major)
        prep = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="prep-dim", title="کتاب برنامه‌ریزی", is_published=True, price=0)
        prep.majors.add(major)
        ready = ContentNode.add_root(kind=ContentNode.Kind.BOOK, slug="ready-dim", title="کتاب آماده", is_published=True, is_free=True)
        ready.majors.add(major)
        ready.add_child(kind=ContentNode.Kind.CHAPTER, slug="ready-ch", title="فصل", is_published=True)

        r = Client().get("/site/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode("utf-8")
        self.assertIn('class="bk bk-prerelease" href="/site/books/soon-dim/"', html)
        self.assertIn('class="bk bk-prerelease" href="/site/books/prep-dim/"', html)
        self.assertIn('class="bk" href="/site/books/ready-dim/"', html)


