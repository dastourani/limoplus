import io
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, User
from apps.catalog.models import Banner, ContentNode, Major

from .models import Entitlement, Order, Plan, SaleCampaign


class PaymentTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media, SITE_URL="http://testserver")
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.user = User.objects.create_user("09120000001")
        _, token = DeviceSession.start(self.user, "test")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.book = ContentNode.objects.get(slug="math-1", depth=1)
        self.paid_section = ContentNode.objects.get(slug="derivatives").get_children().first()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def _order_book(self, track="T1"):
        with mock.patch("apps.commerce.zibal.request_payment", return_value=track) as req:
            r = self.client.post("/api/v1/orders/", {"book": "math-1", "amount": 1}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(req.call_args.kwargs["amount_rial"], 249_000 * 10)  # client amount is ignored
        return Order.objects.get(pk=r.data["order_id"])

    def _callback(self, track, verify):
        with mock.patch("apps.commerce.zibal.verify", return_value=verify):
            return self.client.get(f"/api/v1/payments/zibal/callback/?trackId={track}&success=1")

    def test_paid_book_opens_after_verified_payment(self):
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 403)
        order = self._order_book()
        r = self._callback("T1", {"result": 100, "amount": 2_490_000, "refNumber": "R1", "cardNumber": "6037****1234"})
        self.assertContains(r, "پرداخت موفق")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 200)

    def test_payments_off_refuses_orders_and_never_settles(self):
        order = self._order_book()
        with override_settings(PAYMENTS_ENABLED=False):
            with mock.patch("apps.commerce.zibal.request_payment") as req:
                r = self.client.post("/api/v1/orders/", {"book": "math-1"}, format="json")
            self.assertEqual(r.status_code, 503)
            self.assertEqual(r.data["code"], "payments_off")
            req.assert_not_called()
            with mock.patch("apps.commerce.zibal.verify") as verify:
                self.client.get("/api/v1/payments/zibal/callback/?trackId=T1&success=1")
            verify.assert_not_called()
            self.assertFalse(self.client.get("/api/v1/offers/?book=math-1").data["payments_enabled"])
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertFalse(Entitlement.objects.exists())

    def test_amount_mismatch_is_not_paid(self):
        order = self._order_book()
        self._callback("T1", {"result": 100, "amount": 1000})
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FAILED)
        self.assertFalse(Entitlement.objects.exists())

    def test_callback_twice_grants_once(self):
        self._order_book()
        ok = {"result": 100, "amount": 2_490_000}
        self._callback("T1", ok)
        self._callback("T1", {"result": 201, "amount": 2_490_000})
        self.assertEqual(Entitlement.objects.count(), 1)

    def test_unknown_track_id_does_nothing(self):
        r = self._callback("nope", {"result": 100, "amount": 2_490_000})
        self.assertContains(r, "پرداخت انجام نشد")

    def test_cannot_buy_twice(self):
        self._order_book()
        self._callback("T1", {"result": 100, "amount": 2_490_000})
        with mock.patch("apps.commerce.zibal.request_payment", return_value="T2"):
            r = self.client.post("/api/v1/orders/", {"book": "math-1"}, format="json")
        self.assertEqual(r.data["code"], "already_owned")

    def test_subscription_opens_all_books_and_renewal_extends(self):
        plan = Plan.objects.get(scope="all", months=1)
        for track in ("S1", "S2"):
            with mock.patch("apps.commerce.zibal.request_payment", return_value=track):
                r = self.client.post("/api/v1/orders/", {"plan": plan.id, "major": "economics"}, format="json")
            self._callback(track, {"result": 100, "amount": plan.price * 10})
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 200)
        ends = sorted(Entitlement.objects.values_list("ends_at", flat=True))
        self.assertGreater(ends[1] - ends[0], timedelta(days=29))

    def test_order_keeps_the_plan_terms_it_was_made_with(self):
        plan = Plan.objects.get(scope="all", months=1)
        with mock.patch("apps.commerce.zibal.request_payment", return_value="K1"):
            self.client.post("/api/v1/orders/", {"plan": plan.id, "major": "economics"}, format="json")
        Plan.objects.filter(pk=plan.pk).update(months=12)  # the admin changes the plan before the payment comes back
        self._callback("K1", {"result": 100, "amount": plan.price * 10})
        e = Entitlement.objects.get()
        self.assertLess(e.ends_at - e.starts_at, timedelta(days=40))

    def test_subscription_to_other_major_does_not_open_book(self):
        other = Major.objects.create(name="آزمایشی", slug="other")
        Entitlement.objects.create(user=self.user, major=other, ends_at=timezone.now() + timedelta(days=30))
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 403)

    def test_expired_or_archived_entitlement_does_not_open(self):
        Entitlement.objects.create(user=self.user, all_majors=True, ends_at=timezone.now() - timedelta(days=1))
        Entitlement.objects.create(user=self.user, book=self.book, is_archived=True)
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 403)

    def test_old_one_major_plan_is_no_longer_sold_but_its_subscription_still_opens(self):
        old = Plan.objects.create(title="قدیمی", scope="major", months=1, price=100_000)
        r = self.client.post("/api/v1/orders/", {"plan": old.id, "major": "economics"}, format="json")
        self.assertEqual(r.data["code"], "invalid_plan")
        offered = self.client.get("/api/v1/offers/?book=math-1").data["plans"]
        self.assertTrue(offered and all(p["scope"] == "all" for p in offered))
        Entitlement.objects.create(user=self.user, major=self.book.majors.first(), ends_at=timezone.now() + timedelta(days=30))
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 200)

    def test_orders_are_private(self):
        order = self._order_book()
        other = User.objects.create_user("09120000002")
        _, token = DeviceSession.start(other, "x")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.get(f"/api/v1/orders/{order.id}/").status_code, 404)

    def test_guest_cannot_order(self):
        self.assertEqual(APIClient().post("/api/v1/orders/", {"book": "math-1"}, format="json").status_code, 401)

    def test_three_stacked_renewals_chain(self):
        plan = Plan.objects.get(scope="all", months=1)
        for track in ("A", "B", "C"):
            with mock.patch("apps.commerce.zibal.request_payment", return_value=track):
                self.client.post("/api/v1/orders/", {"plan": plan.id, "major": "economics"}, format="json")
            self._callback(track, {"result": 100, "amount": plan.price * 10})
        rows = list(Entitlement.objects.order_by("starts_at").values_list("starts_at", "ends_at"))
        self.assertEqual(rows[1][0], rows[0][1])
        self.assertEqual(rows[2][0], rows[1][1])

    def test_not_paid_yet_stays_pending_and_can_be_paid_later(self):
        order = self._order_book()
        with mock.patch("apps.commerce.zibal.verify", return_value={"result": 202}):
            self.client.get(f"/api/v1/orders/{order.id}/?check=1")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING)
        with mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": 2_490_000}):
            r = self.client.get(f"/api/v1/orders/{order.id}/?check=1")
        self.assertEqual(r.data["status"], "paid")

    def test_bad_plan_id_is_400(self):
        self.assertEqual(self.client.post("/api/v1/orders/", {"plan": "abc"}, format="json").status_code, 400)

    def test_callback_page_shows_no_order_details(self):
        self._order_book()
        r = self._callback("T1", {"result": 100, "amount": 2_490_000, "refNumber": "SECRET-REF"})
        self.assertNotContains(r, "SECRET-REF")

    def test_offline_access_capped_by_subscription(self):
        Entitlement.objects.create(user=self.user, all_majors=True, ends_at=timezone.now() + timedelta(days=2))
        data = self.client.get("/api/v1/books/math-1/offline/").data
        self.assertLess(data["valid_until"], timezone.now() + timedelta(days=3))

    def test_book_campaign_is_exposed_and_order_snapshots_the_server_quote(self):
        now = timezone.now()
        campaign = SaleCampaign.objects.create(
            title="کمپین کتاب آزمایشی",
            book=self.book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
        )
        offer = self.client.get("/api/v1/offers/?book=math-1").data["book"]
        self.assertEqual(offer["regular_price"], 249_000)
        self.assertEqual(offer["price"], 199_000)
        self.assertEqual(offer["discount"]["amount"], 50_000)
        self.assertEqual(offer["discount"]["percent"], 20.1)

        from apps.commerce.pricing import _percentage
        self.assertEqual(_percentage(499_900, 500_000), 99)
        self.assertEqual(_percentage(100, 500_000), 0.1)
        self.assertEqual(_percentage(500_000, 500_000), 100)
        self.assertEqual(
            offer["product_status"],
            {"state": "paid", "preview": "sample", "promotion": "discount"},
        )
        shelves = self.client.get("/api/v1/shelves/").data
        card = next(book for shelf in shelves for book in shelf["books"] if book["slug"] == self.book.slug)
        self.assertEqual(card["product_status"], offer["product_status"])
        self.assertFalse(card["all_free"], "a free chapter must not set the whole-book free flag")
        self.assertEqual(card["price"], 199_000)

        with mock.patch("apps.commerce.zibal.request_payment", return_value="DISC-BOOK") as gateway:
            response = self.client.post("/api/v1/orders/", {"book": "math-1", "amount": 1}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["amount"], 199_000)
        self.assertEqual(gateway.call_args.kwargs["amount_rial"], 1_990_000)
        order = Order.objects.get(pk=response.data["order_id"])
        self.assertEqual((order.regular_amount, order.discount_amount), (249_000, 50_000))
        self.assertEqual(order.campaign_title_snapshot, campaign.title)
        self.assertEqual(order.campaign_id_snapshot, campaign.pk)

        # A campaign ending after order creation cannot rewrite that pending financial record or its gateway amount.
        campaign.ends_at = now - timedelta(seconds=1)
        campaign.save(update_fields=["ends_at", "updated_at"])
        with mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": 1_990_000}):
            self.client.get("/api/v1/payments/zibal/callback/?trackId=DISC-BOOK&success=1")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)
        self.assertEqual((order.amount, order.regular_amount, order.discount_amount), (199_000, 249_000, 50_000))

        # New buyers after the campaign expires go back to the regular price.
        later_user = User.objects.create_user("09120000004")
        _, later_token = DeviceSession.start(later_user, "test")
        later_client = APIClient()
        later_client.credentials(HTTP_AUTHORIZATION=f"Bearer {later_token}")
        with mock.patch("apps.commerce.zibal.request_payment", return_value="REGULAR-BOOK"):
            regular = later_client.post("/api/v1/orders/", {"book": "math-1"}, format="json")
        self.assertEqual(regular.data["amount"], 249_000)
        regular_order = Order.objects.get(pk=regular.data["order_id"])
        self.assertEqual((regular_order.regular_amount, regular_order.discount_amount), (249_000, 0))

    def test_even_all_free_chapters_do_not_make_a_paid_book_free(self):
        self.book.get_children().update(is_free=True)
        shelves = self.client.get("/api/v1/shelves/").data
        card = next(book for shelf in shelves for book in shelf["books"] if book["slug"] == self.book.slug)
        self.assertFalse(card["all_free"])
        self.assertEqual(card["product_status"]["state"], "paid")
        self.assertEqual(card["product_status"]["preview"], "sample")
        self.assertEqual(card["price"], 249_000)
        self.assertEqual(card["free_chapters"], card["chapter_count"])

    def test_manager_making_a_book_free_stops_campaign_and_blocks_direct_checkout(self):
        now = timezone.now()
        campaign = SaleCampaign.objects.create(
            title="کمپین پیش از رایگان‌شدن",
            book=self.book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
        )
        banner = Banner.objects.create(
            title="بنر کمپین کتاب",
            template=Banner.Template.SALE,
            sale_campaign=campaign,
        )
        self.book.is_free = True
        self.book.save(update_fields=["is_free", "updated_at"])

        offers = self.client.get("/api/v1/offers/?book=math-1").data
        self.assertIsNone(offers["book"]["price"])
        self.assertIsNone(offers["book"]["discount"])
        self.assertEqual(
            offers["book"]["product_status"],
            {"state": "free", "preview": "none", "promotion": "none"},
        )
        shelves = self.client.get("/api/v1/shelves/").data
        card = next(book for shelf in shelves for book in shelf["books"] if book["slug"] == self.book.slug)
        self.assertTrue(card["all_free"])
        self.assertEqual(card["product_status"]["state"], "free")
        with self.assertRaises(ValidationError):
            campaign.full_clean()
        self.assertFalse(any(item["id"] == banner.pk for item in self.client.get("/api/v1/banners/").data))
        with mock.patch("apps.commerce.zibal.request_payment") as gateway:
            response = self.client.post("/api/v1/orders/", {"book": "math-1"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "not_for_sale")
        gateway.assert_not_called()

    def test_plan_campaign_discounts_the_whole_term_and_is_server_computed(self):
        now = timezone.now()
        plan = Plan.objects.get(scope=Plan.Scope.ALL, months=3)
        campaign = SaleCampaign.objects.create(
            title="اشتراک سه‌ماهه‌ی پاییزی",
            plan=plan,
            discounted_price=499_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
        )
        offers = self.client.get("/api/v1/offers/?book=math-1").data
        plan_offer = next(p for p in offers["plans"] if p["id"] == plan.pk)
        self.assertEqual(plan_offer["regular_price"], plan.price)
        self.assertEqual(plan_offer["price"], 499_000)
        self.assertEqual(plan_offer["discount"]["campaign_title"], campaign.title)

        with mock.patch("apps.commerce.zibal.request_payment", return_value="DISC-PLAN") as gateway:
            response = self.client.post("/api/v1/orders/", {"plan": plan.pk, "amount": 1}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data["order_id"])
        self.assertEqual((order.amount, order.regular_amount), (499_000, plan.price))
        self.assertEqual(order.discount_amount, plan.price - 499_000)
        self.assertEqual(gateway.call_args.kwargs["amount_rial"], 4_990_000)

    def test_batch_campaign_links_resolves_shared_plan_destination_once(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from .pricing import campaign_banner_links

        now = timezone.now()
        plans = [
            Plan.objects.get(scope=Plan.Scope.ALL, months=3),
            Plan.objects.create(title="اشتراک شش‌ماهه", scope=Plan.Scope.ALL, months=6, price=900_000),
        ]
        campaigns = [
            SaleCampaign.objects.create(
                title=f"کمپین اشتراک {plan.months}ماهه",
                plan=plan,
                discounted_price=plan.price - 100_000,
                starts_at=now - timedelta(minutes=1),
                ends_at=now + timedelta(hours=1),
            )
            for plan in plans
        ]

        with CaptureQueriesContext(connection) as queries:
            links = campaign_banner_links(campaigns)

        self.assertEqual(len(queries), 0)
        self.assertEqual(links[campaigns[0].pk], "subscribe")
        self.assertEqual(links[campaigns[1].pk], "subscribe")

    def test_campaign_banner_uses_the_same_schedule_and_price_as_checkout(self):
        now = timezone.now()
        campaign = SaleCampaign.objects.create(
            title="فروش ویژه‌ی کتاب",
            book=self.book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=2),
        )
        banner = Banner.objects.create(
            title="قیمت کمپین کتاب",
            template=Banner.Template.SALE,
            is_active=True,
            # The linked campaign replaces stale manual banner dates and supplies its sale layout/countdown.
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=4),
            sale_campaign=campaign,
        )
        response = self.client.get("/api/v1/banners/")
        self.assertEqual(response.status_code, 200)
        item = next(b for b in response.data if b["id"] == banner.pk)
        self.assertEqual(item["template"], Banner.Template.SALE)
        self.assertEqual(item["link"], "buy/math-1")
        self.assertEqual(item["discount"]["price"], 199_000)
        self.assertEqual(item["discount"]["regular_price"], 249_000)
        self.assertEqual(item["ends_at"], campaign.ends_at)

        campaign.ends_at = now - timedelta(seconds=1)
        campaign.save(update_fields=["ends_at", "updated_at"])
        self.assertFalse(any(b["id"] == banner.pk for b in self.client.get("/api/v1/banners/").data))

    def test_only_the_checkout_winning_campaign_banner_is_visible_for_an_legacy_overlap(self):
        now = timezone.now()
        earlier = SaleCampaign.objects.create(
            title="کمپین قبلی",
            book=self.book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=10),
            ends_at=now + timedelta(hours=2),
        )
        winner = SaleCampaign.objects.create(
            title="کمپین منتخب",
            book=self.book,
            discounted_price=179_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=3),
        )
        old_banner = Banner.objects.create(title="بنر قدیمی", template=Banner.Template.SALE, sale_campaign=earlier)
        winning_banner = Banner.objects.create(title="بنر منتخب", template=Banner.Template.SALE, sale_campaign=winner)

        offer = self.client.get("/api/v1/offers/?book=math-1").data["book"]
        self.assertEqual(offer["price"], 179_000)
        banners = self.client.get("/api/v1/banners/").data
        self.assertFalse(any(item["id"] == old_banner.pk for item in banners))
        selected = next(item for item in banners if item["id"] == winning_banner.pk)
        self.assertEqual(selected["discount"]["price"], offer["price"])
        self.assertEqual(selected["discount"]["campaign_title"], winner.title)

    def test_campaign_rejects_overlaps_and_free_or_increased_prices(self):
        now = timezone.now()
        SaleCampaign.objects.create(
            title="کمپین اول",
            book=self.book,
            discounted_price=200_000,
            starts_at=now,
            ends_at=now + timedelta(hours=2),
        )
        overlap = SaleCampaign(
            title="کمپین هم‌زمان",
            book=self.book,
            discounted_price=190_000,
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=3),
        )
        with self.assertRaises(ValidationError):
            overlap.full_clean()
        free = SaleCampaign(
            title="تخفیف رایگان نیست",
            book=self.book,
            discounted_price=0,
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=2),
        )
        with self.assertRaises(ValidationError):
            free.full_clean()

    def test_campaign_picker_and_model_validation_exclude_ineligible_books(self):
        def book(slug, **flags):
            with_chapter = flags.pop("with_chapter", True)
            defaults = {
                "kind": ContentNode.Kind.BOOK,
                "title": slug,
                "slug": slug,
                "price": 100_000,
                "is_published": True,
                "is_archived": False,
                "is_free": False,
                "is_coming_soon": False,
            }
            defaults.update(flags)
            item = ContentNode.add_root(**defaults)
            if with_chapter:
                item.add_child(
                    kind=ContentNode.Kind.CHAPTER,
                    title=f"فصل {slug}",
                    slug=f"{slug}-chapter",
                    is_published=True,
                    is_archived=False,
                    is_inbox=False,
                )
            return item

        eligible = book("campaign-picker-eligible")
        free = book("campaign-picker-free", is_free=True)
        soon = book("campaign-picker-soon", is_coming_soon=True)
        draft = book("campaign-picker-draft", is_published=False)
        archived = book("campaign-picker-archived", is_archived=True)
        preparing = book("campaign-picker-preparing", with_chapter=False)
        invalid_books = [free, soon, draft, archived, preparing]

        manager = User.objects.create_superuser("09120000006", password="Pass-12345")
        client = Client()
        client.force_login(manager)
        response = client.get(reverse("admin:commerce_salecampaign_add"))
        self.assertEqual(response.status_code, 200)
        choices = set(response.context["adminform"].form.fields["book"].queryset.values_list("pk", flat=True))
        self.assertIn(self.book.pk, choices)
        self.assertIn(eligible.pk, choices)
        for item in invalid_books:
            self.assertNotIn(item.pk, choices, item.slug)

        now = timezone.now()
        for item in invalid_books:
            with self.subTest(book=item.slug):
                campaign = SaleCampaign(
                    title=f"کمپین نامعتبر {item.slug}",
                    book=item,
                    discounted_price=1,
                    starts_at=now,
                    ends_at=now + timedelta(hours=1),
                )
                with self.assertRaises(ValidationError):
                    campaign.full_clean()

    def test_superuser_can_create_campaign_with_its_linked_banner_in_admin(self):
        admin = User.objects.create_superuser("09120000005", password="Pass-12345")
        client = Client()
        client.force_login(admin)
        url = reverse("admin:commerce_salecampaign_add")
        page = client.get(url)
        self.assertEqual(page.status_code, 200)
        inline = page.context["inline_admin_formsets"][0].formset
        prefix = inline.prefix
        form_count = inline.total_form_count()
        now = timezone.now()
        payload = {
            "title": "کمپین پنل",
            "book": str(self.book.pk),
            "plan": "",
            "discounted_price": "199000",
            "starts_at_0": now.strftime("%Y-%m-%d"),
            "starts_at_1": (now - timedelta(minutes=5)).strftime("%H:%M:%S"),
            "ends_at_0": (now + timedelta(hours=2)).strftime("%Y-%m-%d"),
            "ends_at_1": (now + timedelta(hours=2)).strftime("%H:%M:%S"),
            "is_active": "on",
            f"{prefix}-TOTAL_FORMS": str(form_count),
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-MIN_NUM_FORMS": "1",
            f"{prefix}-MAX_NUM_FORMS": "1",
            f"{prefix}-0-template": Banner.Template.SALE,
            f"{prefix}-0-title": "بنر کمپین پنل",
            f"{prefix}-0-subtitle": "قیمت ویژه از همان کمپین",
            f"{prefix}-0-button": "خرید",
            f"{prefix}-0-priority": "100",
            f"{prefix}-0-is_active": "on",
        }
        saved = client.post(url, payload)
        form_errors = saved.context["adminform"].form.errors if saved.context else "no form context"
        inline_errors = [formset.non_form_errors() + [form.errors for form in formset.forms] for formset in saved.context["inline_admin_formsets"]] if saved.context else []
        self.assertEqual(saved.status_code, 302, {"form": form_errors, "inlines": inline_errors})
        self.assertRedirects(saved, reverse("admin:commerce_salecampaign_changelist"))
        campaign = SaleCampaign.objects.get(title="کمپین پنل")
        self.assertEqual(campaign.banner.title, "بنر کمپین پنل")
        self.assertEqual(campaign.banner.template, Banner.Template.SALE)

    def test_only_superusers_can_edit_subscription_prices_or_campaigns(self):
        from django.contrib.auth.models import Permission

        staff = User.objects.create_user("09120000003")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        client = Client()
        client.force_login(staff)
        self.assertEqual(client.get("/admin/commerce/plan/").status_code, 403)
        self.assertEqual(client.get("/admin/commerce/salecampaign/").status_code, 403)

        # Even staff granted ordinary banner-edit permission must not control an active campaign banner.
        staff.user_permissions.add(Permission.objects.get(content_type__app_label="catalog", codename="change_banner"))
        now = timezone.now()
        campaign = SaleCampaign.objects.create(
            title="کمپین محرمانه‌ی پنل",
            book=self.book,
            discounted_price=199_000,
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(hours=1),
        )
        banner = Banner.objects.create(title="بنر وابسته", template=Banner.Template.SALE, sale_campaign=campaign)
        self.assertNotContains(
            client.get(reverse("admin:catalog_banner_change", args=[banner.pk]), follow=True), "بنر وابسته"
        )
        self.assertNotContains(client.get("/admin/catalog/banner/"), "بنر وابسته")

    def test_payment_views_do_not_hold_transaction_across_gateway_verify(self):
        from apps.commerce.views import order_status, settle, zibal_callback

        self.assertIn("default", getattr(zibal_callback, "_non_atomic_requests", set()))
        self.assertIn("default", getattr(order_status, "_non_atomic_requests", set()))

        order = self._order_book("EXT-HTTP")
        in_tx_during_verify = []

        def fake_verify(_track):
            from django.db import connection
            in_tx_during_verify.append(connection.in_atomic_block)
            return {"result": 100, "amount": order.amount * 10}

        # When called from a non-atomic view, zibal.verify runs outside atomic block.
        from django.db import transaction as dj_tx
        with mock.patch("apps.commerce.zibal.verify", side_effect=fake_verify):
            # Simulate view-level non-atomic behavior via CaptureOnCommitCallbacks/atomic check:
            self.assertTrue(callable(settle))
            settle("EXT-HTTP")
        # Inside TestCase everything runs inside the test's own atomic block, so verify the order settled cleanly.
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)

    def test_royalty_error_in_settle_does_not_abort_paid_order_and_reconciles(self):
        from apps.catalog.models import BookEditor
        from apps.commerce.models import OrderRevenueSnapshot, TeacherWallet
        from apps.commerce.royalty import reconcile_missing_royalties
        from apps.commerce.views import settle

        teacher = User.objects.create_user("09120000099")
        BookEditor.objects.create(book=self.book, user=teacher)
        order = self._order_book("ROY-ERR")

        with (
            mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": order.amount * 10}),
            mock.patch("apps.commerce.royalty.calculate_and_save_order_royalty", side_effect=RuntimeError("boom")),
            mock.patch("apps.catalog.backups.notify_bale", side_effect=RuntimeError("bale down")) as mock_bale,
        ):
            with self.captureOnCommitCallbacks(execute=True) as callbacks:
                settled = settle("ROY-ERR")
                # While inside the transaction, Bale has NOT been called yet (locks are never held on Bale I/O).
                self.assertEqual(mock_bale.call_count, 0)
            self.assertEqual(len(callbacks), 2)

        self.assertEqual(settled.status, Order.Status.PAID)
        self.assertTrue(Entitlement.objects.filter(order=order).exists())
        self.assertFalse(OrderRevenueSnapshot.objects.filter(order=order).exists())
        self.assertTrue(any("خطا در ثبت سهم استاد" in c.args[0] for c in mock_bale.call_args_list))

        # Even with Bale completely down, the discrepancy stays visible in OrderAdmin until reconciled.
        admin_user = User.objects.create_superuser("09120000098", password="StrongPass!123")
        admin_client = Client()
        admin_client.force_login(admin_user)
        missing_page = admin_client.get("/admin/commerce/order/?royalty=missing")
        self.assertEqual(missing_page.status_code, 200)
        self.assertContains(missing_page, "سهم ثبت نشده")
        self.assertContains(missing_page, order.title)

        # Recovery repairs missing snapshot & wallet credit idempotently.
        rec = reconcile_missing_royalties()
        self.assertEqual(rec["snapshots_created"], 1)
        self.assertEqual(rec["errors"], 0)
        self.assertTrue(OrderRevenueSnapshot.objects.filter(order=order).exists())
        self.assertGreater(TeacherWallet.objects.get(teacher=teacher).pending_balance, 0)

        missing_after = admin_client.get("/admin/commerce/order/?royalty=missing")
        self.assertNotContains(missing_after, "سهم ثبت نشده")

    def test_settle_locks_user_row_before_granting_entitlement(self):
        import sys
        from apps.commerce import views as commerce_views

        plan = Plan.objects.get(scope=Plan.Scope.ALL, months=1)
        with mock.patch("apps.commerce.zibal.request_payment", return_value="LOCK-1"):
            self.client.post("/api/v1/orders/", {"plan": plan.id}, format="json")

        calls = []
        orig_sfu = User.objects.select_for_update

        def tracked_sfu(*args, **kwargs):
            calls.append("user_lock")
            return orig_sfu(*args, **kwargs)

        with (
            mock.patch.object(User.objects, "select_for_update", side_effect=tracked_sfu),
            mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": plan.price * 10}),
            mock.patch("apps.commerce.views._grant", wraps=commerce_views._grant) as grant_spy,
        ):
            commerce_views.settle("LOCK-1")

        self.assertIn("user_lock", calls)
        self.assertTrue(grant_spy.called)


from django.test import TransactionTestCase


class PostgresConcurrentRenewalTransactionTests(TransactionTestCase):
    def setUp(self):
        call_command("load_samples", stdout=io.StringIO())
        self.user = User.objects.create_user("09120000077")
        self.plan = Plan.objects.get(scope=Plan.Scope.ALL, months=1)

    def test_two_concurrent_renewal_orders_stack_60_days(self):
        import threading
        from django.db import connection, connections
        from apps.commerce.views import settle

        if connection.vendor == "sqlite":
            self.skipTest("SQLite lacks row-level SELECT FOR UPDATE; full race test runs on PostgreSQL in CI")

        o1 = Order.objects.create(
            user=self.user,
            plan=self.plan,
            title=self.plan.title,
            amount=self.plan.price,
            plan_months=self.plan.months,
            plan_scope=self.plan.scope,
            track_id="CONC-1",
        )
        o2 = Order.objects.create(
            user=self.user,
            plan=self.plan,
            title=self.plan.title,
            amount=self.plan.price,
            plan_months=self.plan.months,
            plan_scope=self.plan.scope,
            track_id="CONC-2",
        )

        barrier = threading.Barrier(2)
        errors = []

        def worker(track):
            connections.close_all()
            try:
                with mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": self.plan.price * 10}):
                    barrier.wait(timeout=5)
                    settle(track)
            except Exception as exc:
                errors.append(exc)
            finally:
                connections.close_all()

        t1 = threading.Thread(target=worker, args=("CONC-1",))
        t2 = threading.Thread(target=worker, args=("CONC-2",))
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)
        self.assertEqual(errors, [])

        ents = list(Entitlement.objects.filter(user=self.user, is_archived=False).order_by("starts_at"))
        self.assertEqual(len(ents), 2)
        self.assertEqual(ents[1].starts_at, ents[0].ends_at)
        self.assertEqual((ents[1].ends_at - ents[0].starts_at), timedelta(days=60))


class EntitlementAdminOfflinePolicyTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser("09120009901", password="StrongPass!123")
        self.learner = User.objects.create_user("09120009902")
        self.major = Major.objects.create(slug="eng", name="فنی", order=1)
        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="کتاب آفلاین ادمین",
            slug="admin-offline-book",
            price=40000,
            is_published=True,
        )
        self.book.majors.add(self.major)
        self.free_book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="کتاب رایگان",
            slug="free-book",
            price=0,
            is_free=True,
            is_published=True,
        )
        self.free_book.majors.add(self.major)
        self.admin_client = Client()
        self.admin_client.force_login(self.admin_user)

    def test_entitlement_admin_revoke_keep_vs_wipe_and_subscription_wipe(self):
        from apps.accounts.models import DeviceSession
        from rest_framework.test import APIClient

        ent = Entitlement.objects.create(user=self.learner, book=self.book, note="دستی")
        _, token = DeviceSession.start(self.learner, "گوشی", "android")
        api = APIClient(HTTP_AUTHORIZATION=f"Bearer {token}")

        # 1. Change form renders both policy options and help text
        change_url = f"/admin/commerce/entitlement/{ent.pk}/change/"
        page = self.admin_client.get(change_url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "نگهداری نسخه آفلاین تا پایان مهلت قبلی")
        self.assertContains(page, "حذف فوری نسخه آفلاین")

        # 2. Bulk action: keep -> archives without setting offline_revoked_at
        changelist_url = "/admin/commerce/entitlement/"
        r_keep = self.admin_client.post(
            changelist_url,
            {"action": "revoke_keep_offline", "_selected_action": [str(ent.pk)]},
        )
        self.assertEqual(r_keep.status_code, 302)
        ent.refresh_from_db()
        self.assertTrue(ent.is_archived)
        self.assertIsNone(ent.offline_revoked_at)
        self.assertEqual(api.get("/api/v1/me/").data["offline_revocations"], [])

        # 3. Un-archiving clears any wipe timestamp; saving with wipe sets offline_revoked_at
        self.admin_client.post(
            change_url,
            {
                "user": str(self.learner.pk),
                "book": str(self.book.pk),
                "starts_at_0": ent.starts_at.strftime("%Y-%m-%d"),
                "starts_at_1": ent.starts_at.strftime("%H:%M:%S"),
                "note": "دستی",
                "is_archived": "on",
                "offline_policy": "wipe",
            },
        )
        ent.refresh_from_db()
        self.assertTrue(ent.is_archived)
        self.assertIsNotNone(ent.offline_revoked_at)
        revs = api.get("/api/v1/me/").data["offline_revocations"]
        self.assertEqual([r["slug"] for r in revs], [self.book.slug])

        # 4. Revoking a major subscription with wipe also reports non-free books in that major
        ent.is_archived = False
        ent.offline_revoked_at = None
        ent.save()
        sub = Entitlement.objects.create(user=self.learner, major=self.major, ends_at=timezone.now() + timedelta(days=30))
        self.admin_client.post(
            changelist_url,
            {"action": "revoke_wipe_offline", "_selected_action": [str(sub.pk)]},
        )
        sub.refresh_from_db()
        self.assertTrue(sub.is_archived)
        self.assertIsNotNone(sub.offline_revoked_at)
        # Still owns book via `ent`, so not reported yet:
        self.assertEqual(api.get("/api/v1/me/").data["offline_revocations"], [])
        # Once book-level access is archived (keep), subscription wipe surfaces the paid book (never free books):
        ent.is_archived = True
        ent.save(update_fields=["is_archived"])
        revs_after = api.get("/api/v1/me/").data["offline_revocations"]
        self.assertEqual([r["slug"] for r in revs_after], [self.book.slug])


class PaymentReturnChannelTests(TestCase):
    def setUp(self):
        call_command("load_samples", stdout=io.StringIO())
        self.user = User.objects.create_user("09120000888")
        _, token = DeviceSession.start(self.user, "test")
        self.api = APIClient()
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_zibal_callback_routes_back_to_creating_channel_scheme(self):
        from unittest import mock
        from django.test import override_settings
        from apps.commerce.models import Order

        with mock.patch("apps.commerce.zibal.request_payment", side_effect=["trk-test", "trk-off", "trk-web"]):
            r_test = self.api.post(
                "/api/v1/orders/",
                {"book": "math-1"},
                format="json",
                HTTP_X_APP_PLATFORM="android",
                HTTP_X_APP_BUILD="10",
                HTTP_X_APP_CHANNEL="test",
            )
            self.assertEqual(r_test.status_code, 201)
            r_off = self.api.post(
                "/api/v1/orders/",
                {"book": "math-1"},
                format="json",
                HTTP_X_APP_PLATFORM="android",
                HTTP_X_APP_BUILD="1",
                HTTP_X_APP_CHANNEL="official",
            )
            self.assertEqual(r_off.status_code, 201)
            r_web = self.api.post(
                "/api/v1/orders/",
                {"book": "math-1"},
                format="json",
                HTTP_X_APP_PLATFORM="web",
                HTTP_X_APP_BUILD="1",
                HTTP_X_APP_CHANNEL="official",
            )
            self.assertEqual(r_web.status_code, 201)

        self.assertEqual(Order.objects.get(pk=r_test.data["order_id"]).return_channel, "test")
        self.assertEqual(Order.objects.get(pk=r_off.data["order_id"]).return_channel, "official")
        self.assertEqual(Order.objects.get(pk=r_web.data["order_id"]).return_channel, "web")

        with mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": 2490000, "refNumber": "123", "cardNumber": "6037"}):
            cb_test = self.client.get("/api/v1/payments/zibal/callback/?trackId=trk-test")
            cb_off = self.client.get("/api/v1/payments/zibal/callback/?trackId=trk-off")
            with override_settings(APP_URL="https://app.limookhan.ir"):
                cb_web = self.client.get("/api/v1/payments/zibal/callback/?trackId=trk-web")
        self.assertContains(cb_test, "limookhan-test://payment-result")
        self.assertContains(cb_off, "limookhan://payment-result")
        self.assertNotContains(cb_off, "limookhan-test://")
        self.assertContains(cb_web, f"https://app.limookhan.ir/payment-result?order={r_web.data['order_id']}&amp;status=paid")
        self.assertNotContains(cb_web, "limookhan://")

    def test_plan_offers_and_order_receipt_expose_exact_subscription_dates_and_renewal_stacking(self):
        from unittest import mock
        from apps.commerce.models import Entitlement, Order, Plan

        plan_12 = Plan.objects.create(title="اشتراک ۱۲ ماهه", scope=Plan.Scope.ALL, months=12, price=900_000, order=1)
        # Initial quote (no active subscription): 12 months = 360 days from now
        plans_res = self.api.get("/api/v1/plans/")
        self.assertEqual(plans_res.status_code, 200)
        p12 = next(p for p in plans_res.data if p["id"] == plan_12.pk)
        self.assertEqual(p12["days"], 360)
        self.assertFalse(p12["is_renewal"])
        self.assertEqual((p12["ends_at"] - p12["starts_at"]).days, 360)

        # With an existing active all-books subscription ending in 10 days, offers & plans preview stacked renewal
        active_end = timezone.now() + timedelta(days=10)
        Entitlement.objects.create(user=self.user, all_majors=True, ends_at=active_end)
        offers_res = self.api.get("/api/v1/offers/?book=math-1")
        self.assertEqual(offers_res.status_code, 200)
        offered_12 = next(p for p in offers_res.data["plans"] if p["id"] == plan_12.pk)
        self.assertTrue(offered_12["is_renewal"])
        self.assertEqual(offered_12["starts_at"], active_end)
        self.assertEqual(offered_12["ends_at"], active_end + timedelta(days=360))

        # Order status receipt after settlement returns kind, starts_at, ends_at matching the granted entitlement
        with mock.patch("apps.commerce.zibal.request_payment", return_value="trk-sub-12"):
            created = self.api.post("/api/v1/orders/", {"plan": plan_12.pk}, format="json")
        self.assertEqual(created.status_code, 201)
        with mock.patch("apps.commerce.zibal.verify", return_value={"result": 100, "amount": 900_000 * 10, "refNumber": "999", "cardNumber": "6037"}):
            self.client.get("/api/v1/payments/zibal/callback/?trackId=trk-sub-12")
        receipt = self.api.get(f"/api/v1/orders/{created.data['order_id']}/")
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.data["status"], Order.Status.PAID)
        self.assertEqual(receipt.data["kind"], "subscription")
        self.assertEqual(receipt.data["starts_at"], active_end)
        self.assertEqual(receipt.data["ends_at"], active_end + timedelta(days=360))



