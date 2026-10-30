import io
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, User
from apps.catalog.models import ContentNode, Major

from .models import Entitlement, Order, Plan


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

    def test_major_subscription_opens_books_of_that_major_and_renewal_extends(self):
        plan = Plan.objects.get(scope="major", months=1)
        for track in ("S1", "S2"):
            with mock.patch("apps.commerce.zibal.request_payment", return_value=track):
                r = self.client.post("/api/v1/orders/", {"plan": plan.id, "major": "economics"}, format="json")
            self._callback(track, {"result": 100, "amount": plan.price * 10})
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 200)
        ends = sorted(Entitlement.objects.values_list("ends_at", flat=True))
        self.assertGreater(ends[1] - ends[0], timedelta(days=29))

    def test_subscription_to_other_major_does_not_open_book(self):
        other = Major.objects.create(name="آزمایشی", slug="other")
        Entitlement.objects.create(user=self.user, major=other, ends_at=timezone.now() + timedelta(days=30))
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 403)

    def test_expired_or_archived_entitlement_does_not_open(self):
        Entitlement.objects.create(user=self.user, all_majors=True, ends_at=timezone.now() - timedelta(days=1))
        Entitlement.objects.create(user=self.user, book=self.book, is_archived=True)
        self.assertEqual(self.client.get(f"/api/v1/nodes/{self.paid_section.id}/").status_code, 403)

    def test_major_plan_needs_major(self):
        plan = Plan.objects.get(scope="major", months=1)
        r = self.client.post("/api/v1/orders/", {"plan": plan.id}, format="json")
        self.assertEqual(r.data["code"], "major_required")

    def test_orders_are_private(self):
        order = self._order_book()
        other = User.objects.create_user("09120000002")
        _, token = DeviceSession.start(other, "x")
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(c.get(f"/api/v1/orders/{order.id}/").status_code, 404)

    def test_guest_cannot_order(self):
        self.assertEqual(APIClient().post("/api/v1/orders/", {"book": "math-1"}, format="json").status_code, 401)
