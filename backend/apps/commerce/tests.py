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

        self.assertEqual(len(queries), 1)
        self.assertEqual(links[campaigns[0].pk], links[campaigns[1].pk])
        self.assertTrue(links[campaigns[0].pk].startswith("buy/"))

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
