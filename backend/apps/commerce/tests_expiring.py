from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Major
from apps.commerce.management.commands.check_expiring_entitlements import check_and_notify_expiring_entitlements
from apps.commerce.models import Entitlement

User = get_user_model()


class CheckExpiringEntitlementsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("09121112233")
        self.major = Major.objects.create(name="عمران", slug="civil")

    @patch("apps.commerce.management.commands.check_expiring_entitlements.send_sms")
    @patch("apps.commerce.management.commands.check_expiring_entitlements.notify_bale")
    def test_expiring_entitlement_sends_sms_and_bale(self, mock_bale, mock_sms):
        now = timezone.now()
        # Entitlement ending in 2 days
        ent = Entitlement.objects.create(
            user=self.user,
            major=self.major,
            starts_at=now - timedelta(days=28),
            ends_at=now + timedelta(days=2),
        )

        res = check_and_notify_expiring_entitlements(now=now)
        self.assertEqual(res["notified_count"], 1)
        self.assertEqual(res["skipped_count"], 0)

        # Check SMS sent
        mock_sms.assert_called_once()
        sent_phone, sent_text = mock_sms.call_args[0]
        self.assertEqual(sent_phone, "09121112233")
        self.assertIn("اشتراک رشته عمران", sent_text)
        self.assertIn("۲ روز دیگر", sent_text)

        # Check Bale report
        mock_bale.assert_called_once()
        bale_text = mock_bale.call_args[0][0]
        self.assertIn("گزارش انقضای اشتراک", bale_text)
        self.assertIn("09121112233", bale_text)

        # Verify entitlement model record updated
        ent.refresh_from_db()
        self.assertIsNotNone(ent.expiry_warning_sent_at)

        # Running again today should skip (no duplicate SMS)
        mock_sms.reset_mock()
        mock_bale.reset_mock()
        res_dup = check_and_notify_expiring_entitlements(now=now)
        self.assertEqual(res_dup["notified_count"], 0)
        self.assertEqual(res_dup["skipped_count"], 1)
        mock_sms.assert_not_called()
        mock_bale.assert_not_called()

    @patch("apps.commerce.management.commands.check_expiring_entitlements.send_sms")
    def test_archived_or_far_future_entitlements_are_ignored(self, mock_sms):
        now = timezone.now()
        # Ending in 10 days (not within 3 days)
        Entitlement.objects.create(
            user=self.user,
            major=self.major,
            starts_at=now,
            ends_at=now + timedelta(days=10),
        )
        # Already archived
        Entitlement.objects.create(
            user=self.user,
            major=self.major,
            starts_at=now - timedelta(days=30),
            ends_at=now + timedelta(days=1),
            is_archived=True,
        )
        res = check_and_notify_expiring_entitlements(now=now)
        self.assertEqual(res["notified_count"], 0)
        mock_sms.assert_not_called()
