from decimal import Decimal
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import BookEditor, ContentNode
from apps.commerce.models import (
    BookAuthorShare,
    BookRoyaltyRule,
    Order,
    OrderAuthorRevenue,
    OrderRevenueSnapshot,
    RevenuePlan,
)
from apps.commerce.royalty import calculate_and_save_order_royalty, get_active_plan_for_book


class BookRoyaltyAndSplitTests(TestCase):
    def setUp(self):
        self.teacher1 = User.objects.create_user(phone="09121111111", first_name="استاد", last_name="یک")
        self.teacher2 = User.objects.create_user(phone="09122222222", first_name="استاد", last_name="دو")
        self.buyer = User.objects.create_user(phone="09123333333", first_name="دانشجو", last_name="خریدار")

        self.book = ContentNode.add_root(
            kind=ContentNode.Kind.BOOK,
            title="فیزیک کوانتومی پیشرفته",
            price=200_000,
            is_published=True,
        )

        # Default system plan: 70% author, 30% platform
        self.default_plan = RevenuePlan.objects.create(
            title="طرح استاندارد سامانه",
            code="standard",
            author_share_percent=70,
            platform_share_percent=30,
            is_default=True,
            is_active=True,
        )

    def test_default_plan_applies_when_no_custom_rule(self):
        plan, author_pct, platform_pct = get_active_plan_for_book(self.book)
        self.assertEqual(plan, self.default_plan)
        self.assertEqual(author_pct, Decimal("70"))
        self.assertEqual(platform_pct, Decimal("30"))

    def test_early_adopter_plan_with_sales_cap(self):
        early_plan = RevenuePlan.objects.create(
            title="طرح ۳۰ استاد اول",
            code="early-30",
            author_share_percent=85,
            platform_share_percent=15,
            max_sales_count=2,  # valid only for 2 sales
            is_active=True,
        )

        rule = BookRoyaltyRule.objects.create(
            book=self.book,
            revenue_plan=early_plan,
        )

        # 1st sale: applies early plan (85%)
        order1 = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=200_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        snap1 = calculate_and_save_order_royalty(order1)
        self.assertEqual(snap1.platform_share_amount, 30_000)  # 15%
        self.assertEqual(snap1.total_authors_amount, 170_000)  # 85%

        # 2nd sale: still under cap (85%)
        order2 = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=200_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        snap2 = calculate_and_save_order_royalty(order2)
        self.assertEqual(snap2.total_authors_amount, 170_000)

        # 3rd sale: cap of 2 reached -> falls back to default plan (70%)
        order3 = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=200_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )
        snap3 = calculate_and_save_order_royalty(order3)
        self.assertEqual(snap3.platform_share_amount, 60_000)  # 30% of default
        self.assertEqual(snap3.total_authors_amount, 140_000)  # 70% of default

    def test_multi_author_split_and_rounding(self):
        rule = BookRoyaltyRule.objects.create(
            book=self.book,
            revenue_plan=self.default_plan,
        )

        # Author 1: 40% of sales, Author 2: 30% of sales (Total authors 70%)
        BookAuthorShare.objects.create(
            royalty_rule=rule,
            author=self.teacher1,
            share_percent=Decimal("40.00"),
            role_title="مؤلف اصلی",
        )
        BookAuthorShare.objects.create(
            royalty_rule=rule,
            author=self.teacher2,
            share_percent=Decimal("30.00"),
            role_title="همکار تألیف",
        )

        order = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=155_555,  # Odd amount to test exact integer rounding without loss
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

        snap = calculate_and_save_order_royalty(order)
        self.assertIsNotNone(snap)

        # Exact sum guarantee: platform + authors == order.amount
        self.assertEqual(snap.platform_share_amount + snap.total_authors_amount, order.amount)

        # Verify individual author records
        rev1 = OrderAuthorRevenue.objects.get(snapshot=snap, author=self.teacher1)
        rev2 = OrderAuthorRevenue.objects.get(snapshot=snap, author=self.teacher2)

        self.assertEqual(rev1.amount + rev2.amount, snap.total_authors_amount)
        self.assertGreater(rev1.amount, rev2.amount)
        self.assertFalse(rev1.is_settled)

    def test_custom_book_override_percent(self):
        # Override platform to 20% directly on book (authors get 80%)
        BookRoyaltyRule.objects.create(
            book=self.book,
            is_custom_split=True,
            custom_platform_share_percent=20,
        )

        BookEditor.objects.create(book=self.book, user=self.teacher1)

        order = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=100_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

        snap = calculate_and_save_order_royalty(order)
        self.assertEqual(snap.platform_share_amount, 20_000)
        self.assertEqual(snap.total_authors_amount, 80_000)

        author_rev = OrderAuthorRevenue.objects.get(snapshot=snap, author=self.teacher1)
        self.assertEqual(author_rev.amount, 80_000)

    def test_teacher_wallet_pending_credit_and_release(self):
        from apps.commerce.models import TeacherWallet, WalletTransaction
        from apps.commerce.wallet import release_pending_balances, audit_teacher_wallet
        from datetime import timedelta

        BookEditor.objects.create(book=self.book, user=self.teacher1)

        # Purchase with default plan (7-day hold)
        order = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=100_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

        snap = calculate_and_save_order_royalty(order)
        author_rev = OrderAuthorRevenue.objects.get(snapshot=snap, author=self.teacher1)

        # Check wallet immediately after sale: 70,000 in pending, 0 in available
        wallet = TeacherWallet.objects.get(teacher=self.teacher1)
        self.assertEqual(wallet.pending_balance, 70_000)
        self.assertEqual(wallet.available_balance, 0)
        self.assertEqual(wallet.total_earned, 70_000)
        self.assertEqual(wallet.debt_balance, 0)

        tx_earn = WalletTransaction.objects.get(wallet=wallet, event_type=WalletTransaction.EventType.EARN_PENDING)
        self.assertEqual(tx_earn.amount, 70_000)

        # Before 7 days: release does nothing
        released = release_pending_balances(now=timezone.now() + timedelta(days=3))
        self.assertEqual(released, 0)
        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 0)

        # After 7 days: release moves funds from pending to available
        released = release_pending_balances(now=timezone.now() + timedelta(days=8))
        self.assertEqual(released, 1)

        wallet.refresh_from_db()
        self.assertEqual(wallet.pending_balance, 0)
        self.assertEqual(wallet.available_balance, 70_000)

        # Audit check verifies zero discrepancy
        audit = audit_teacher_wallet(wallet)
        self.assertTrue(audit["is_healthy"])

    def test_order_refund_after_available_creates_debt_balance(self):
        from apps.commerce.models import TeacherWallet
        from apps.commerce.wallet import release_pending_balances, process_order_refund
        from datetime import timedelta

        BookEditor.objects.create(book=self.book, user=self.teacher1)

        order = Order.objects.create(
            user=self.buyer,
            book=self.book,
            title=f"خرید {self.book.title}",
            amount=100_000,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
        )

        calculate_and_save_order_royalty(order)
        # Release funds to available
        release_pending_balances(now=timezone.now() + timedelta(days=8))

        wallet = TeacherWallet.objects.get(teacher=self.teacher1)
        self.assertEqual(wallet.available_balance, 70_000)

        # Simulate withdrawal of 50,000 (remaining available: 20,000)
        wallet.available_balance = 20_000
        wallet.total_withdrawn = 50_000
        wallet.save()

        # Now full refund of the 70,000 order occurs:
        # Available is only 20,000 -> 20,000 deducted, remaining 50,000 recorded as debt_balance
        adjusted = process_order_refund(order, reason="استرداد پس از تسویه")
        self.assertEqual(adjusted, 1)

        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 0)
        self.assertEqual(wallet.debt_balance, 50_000)
        self.assertEqual(wallet.net_withdrawable_amount, 0)

