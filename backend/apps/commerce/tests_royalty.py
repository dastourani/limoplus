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

    def test_release_pending_balances_idempotency_on_repeated_runs(self):
        from apps.commerce.models import TeacherWallet, WalletTransaction
        from apps.commerce.wallet import release_pending_balances
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

        # 1st run of release after hold period: releases 1 record
        future = timezone.now() + timedelta(days=10)
        released_1 = release_pending_balances(now=future)
        self.assertEqual(released_1, 1)

        wallet = TeacherWallet.objects.get(teacher=self.teacher1)
        self.assertEqual(wallet.available_balance, 70_000)
        self.assertEqual(wallet.pending_balance, 0)

        # 2nd run immediately after: MUST release 0 records and NOT duplicate funds
        released_2 = release_pending_balances(now=future)
        self.assertEqual(released_2, 0)

        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 70_000)
        self.assertEqual(wallet.pending_balance, 0)

        # Verify only 1 release transaction was created
        release_txs = WalletTransaction.objects.filter(
            wallet=wallet, event_type=WalletTransaction.EventType.RELEASE_AVAILABLE
        )
        self.assertEqual(release_txs.count(), 1)

    def test_teacher_isolation_cannot_access_other_teacher_wallet_or_transactions(self):
        from django.contrib.auth.models import Group
        from apps.catalog.access import BOOK_EDITOR_GROUP
        from apps.commerce.models import TeacherWallet, WalletTransaction

        group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        self.teacher1.is_staff = True
        self.teacher1.groups.add(group)
        self.teacher1.save()

        self.teacher2.is_staff = True
        self.teacher2.groups.add(group)
        self.teacher2.save()

        wallet1 = TeacherWallet.objects.create(teacher=self.teacher1, available_balance=50_000)
        wallet2 = TeacherWallet.objects.create(teacher=self.teacher2, available_balance=90_000)

        tx2 = WalletTransaction.objects.create(
            wallet=wallet2,
            event_type=WalletTransaction.EventType.EARN_PENDING,
            amount=90_000,
            available_balance_after=0,
            pending_balance_after=90_000,
            debt_balance_after=0,
            idempotency_key="tx2-test",
            description="سهم استاد دو",
        )

        # Teacher 1 logs in
        self.client.force_login(self.teacher1)

        # 1. In wallet changelist, Teacher 1 should only see their own wallet
        res_list = self.client.get("/admin/commerce/teacherwallet/")
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, self.teacher1.phone)
        self.assertNotContains(res_list, self.teacher2.phone)

        # 2. Directly accessing Teacher 2's wallet ID in URL MUST return 302/403/404 (isolated queryset)
        res_detail = self.client.get(f"/admin/commerce/teacherwallet/{wallet2.pk}/change/")
        self.assertIn(res_detail.status_code, (302, 403, 404))

        # 3. Directly accessing Teacher 2's transaction ID in URL MUST return 302/403/404
        res_tx = self.client.get(f"/admin/commerce/wallettransaction/{tx2.pk}/change/")
        self.assertIn(res_tx.status_code, (302, 403, 404))

    def test_payout_workflow_lifecycle_hold_pay_and_audit(self):
        from django.core.exceptions import ValidationError
        from apps.commerce.models import PayoutRequest, TeacherBankAccount, TeacherWallet, WalletTransaction
        from apps.commerce.wallet import (
            audit_teacher_wallet,
            finalize_payout_paid,
            mark_payout_as_processing,
            reject_payout_request,
            request_teacher_payout,
        )

        wallet = TeacherWallet.objects.create(
            teacher=self.teacher1,
            available_balance=0,
            pending_balance=0,
            total_earned=0,
        )

        # Simulate natural earnings: 500k earned + released, and 100k earned pending
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.EARN_PENDING,
            amount=500_000,
            available_balance_after=0,
            pending_balance_after=500_000,
            idempotency_key="seed-earn-500",
            description="سهم فروش اول",
        )
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.RELEASE_AVAILABLE,
            amount=500_000,
            available_balance_after=500_000,
            pending_balance_after=0,
            idempotency_key="seed-release-500",
            description="آزادسازی سهم فروش اول",
        )
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.EARN_PENDING,
            amount=100_000,
            available_balance_after=500_000,
            pending_balance_after=100_000,
            idempotency_key="seed-pending-100",
            description="سهم فروش دوم (در انتظار)",
        )
        wallet.available_balance = 500_000
        wallet.pending_balance = 100_000
        wallet.total_earned = 600_000
        wallet.save()

        # 1. Requesting payout without verified bank account fails
        with self.assertRaises(ValidationError):
            request_teacher_payout(self.teacher1, 250_000)

        # Register and verify bank account
        bank = TeacherBankAccount.objects.create(
            teacher=self.teacher1,
            account_holder_name="استاد یک",
            iban="IR120120000000001234567890",
            bank_name="بانک ملت",
            is_verified=True,
        )

        # 2. Requesting below minimum amount (200,000) fails
        with self.assertRaises(ValidationError):
            request_teacher_payout(self.teacher1, 150_000)

        # 3. Requesting above available balance fails
        with self.assertRaises(ValidationError):
            request_teacher_payout(self.teacher1, 550_000)

        # 4. Valid payout request: 300,000 -> moves from available to locked
        payout = request_teacher_payout(self.teacher1, 300_000)
        self.assertEqual(payout.status, PayoutRequest.Status.PENDING)
        self.assertEqual(payout.iban_snapshot, bank.iban)

        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 200_000)
        self.assertEqual(wallet.locked_balance, 300_000)
        self.assertEqual(wallet.total_withdrawn, 0)

        # Check 6-level audit holds true during locked state
        audit = audit_teacher_wallet(wallet)
        if not audit["is_healthy"]:
            print("AUDIT FAILED:", audit)
        self.assertTrue(audit["is_healthy"])

        # 5. Cannot create a second open request while one is pending
        with self.assertRaises(ValidationError):
            request_teacher_payout(self.teacher1, 200_000)

        # 6. Admin marks processing
        mark_payout_as_processing(payout)
        self.assertEqual(payout.status, PayoutRequest.Status.PROCESSING)

        # 7. Admin finalizes paid with tracking code
        finalize_payout_paid(payout, tracking_code="PAYA-987654321")
        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.PAID)
        self.assertEqual(payout.tracking_code, "PAYA-987654321")

        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 200_000)
        self.assertEqual(wallet.locked_balance, 0)
        self.assertEqual(wallet.total_withdrawn, 300_000)

        # Check 6-level audit holds true after paid
        audit_paid = audit_teacher_wallet(wallet)
        self.assertTrue(audit_paid["is_healthy"])

    def test_payout_rejection_restores_locked_balance(self):
        from apps.commerce.models import PayoutRequest, TeacherBankAccount, TeacherWallet, WalletTransaction
        from apps.commerce.wallet import audit_teacher_wallet, reject_payout_request, request_teacher_payout

        wallet = TeacherWallet.objects.create(
            teacher=self.teacher1,
            available_balance=0,
            total_earned=0,
        )
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.EARN_PENDING,
            amount=400_000,
            available_balance_after=0,
            pending_balance_after=400_000,
            idempotency_key="seed-reject-earn",
            description="فروش اولیه",
        )
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.RELEASE_AVAILABLE,
            amount=400_000,
            available_balance_after=400_000,
            pending_balance_after=0,
            idempotency_key="seed-reject-release",
            description="آزادسازی سهم",
        )
        wallet.available_balance = 400_000
        wallet.total_earned = 400_000
        wallet.save()

        TeacherBankAccount.objects.create(
            teacher=self.teacher1,
            account_holder_name="استاد یک",
            iban="IR120120000000001234567890",
            is_verified=True,
        )

        payout = request_teacher_payout(self.teacher1, 250_000)
        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 150_000)
        self.assertEqual(wallet.locked_balance, 250_000)

        # Reject payout: funds must return to available_balance
        reject_payout_request(payout, reason="مغایرت نام صاحب حساب با کدملی")
        payout.refresh_from_db()
        self.assertEqual(payout.status, PayoutRequest.Status.REJECTED)

        wallet.refresh_from_db()
        audit = audit_teacher_wallet(wallet)
        self.assertTrue(audit["is_healthy"])

    def test_iban_mod97_validator(self):
        from apps.commerce.models import validate_iban_mod97

        # Valid Iranian IBAN according to ISO 7064 Mod-97 (Real check digit)
        base = "0120000000001234567890"
        remainder = int(base + "182700") % 97
        check_digit = 98 - remainder
        valid_iban = f"IR{check_digit:02d}{base}"

        self.assertTrue(validate_iban_mod97(valid_iban))
        # An altered digit must fail
        invalid_iban = f"IR{check_digit:02d}0120000000001234567891"
        self.assertFalse(validate_iban_mod97(invalid_iban))

    def test_subscription_pool_simulation_anti_fraud_and_finalization(self):
        from datetime import timedelta
        from apps.commerce.models import Plan, SubscriptionPoolPeriod, TeacherWallet, WalletTransaction
        from apps.commerce.pool import finalize_subscription_pool, simulate_subscription_pool
        from apps.learning.models import Question
        from apps.study.models import StudyTime

        # 1. Create a 3-month all-books subscription plan with 50% pool share
        plan = Plan.objects.create(
            title="اشتراک ۳ ماهه ویژه",
            scope=Plan.Scope.ALL,
            months=3,
            price=300_000,
            pool_share_percent=50,
            is_active=True,
        )

        now = timezone.now()
        period_start = now - timedelta(days=25)
        period_end = now + timedelta(days=5)

        # 2. Simulate 2 orders for this subscription in the period (Total sales: 600k -> Pool: 300k)
        for i in range(2):
            Order.objects.create(
                user=self.buyer,
                plan=plan,
                title=plan.title,
                amount=300_000,
                status=Order.Status.PAID,
                paid_at=now - timedelta(days=10),
            )

        # Setup 2 published chapters & 25 questions on self.book to meet content standard
        ch1 = ContentNode.add_root(kind=ContentNode.Kind.CHAPTER, title="فصل ۱", is_published=True)
        ch1.move(self.book, pos="last-child")
        ch1.refresh_from_db()

        ch2 = ContentNode.add_root(kind=ContentNode.Kind.CHAPTER, title="فصل ۲", is_published=True)
        ch2.move(self.book, pos="last-child")
        ch2.refresh_from_db()

        for q_idx in range(22):
            Question.objects.create(
                node=ch1,
                slug=f"q-{q_idx}",
                stem=f"سوال شماره {q_idx}",
                explanation="پاسخ",
            )

        # Connect teacher1 as editor of book
        BookEditor.objects.get_or_create(book=self.book, user=self.teacher1)

        # 3. Simulate study time with anti-fraud cap test
        # Daily cap is 4 hours (14,400 sec). User logged 10 hours (36,000 sec) in 1 day
        StudyTime.objects.create(
            user=self.buyer,
            book=self.book,
            node=ch1,
            day=(now - timedelta(days=5)).date(),
            kind=StudyTime.Kind.READ,
            seconds=36_000,  # 10 hours -> should be capped at 4 hours (14,400s)
        )

        # Create period
        period = SubscriptionPoolPeriod.objects.create(
            title="استخر اشتراک فروردین ماه",
            starts_at=period_start,
            ends_at=period_end,
            sharing_model=SubscriptionPoolPeriod.ModelChoice.HYBRID,
            exclude_free_chapters=True,
            daily_user_cap_hours=4,
            min_published_chapters=2,
            min_active_questions=20,
        )

        # 4. Run simulation
        sim = simulate_subscription_pool(period)
        self.assertEqual(sim["total_sales"], 600_000)
        self.assertEqual(sim["total_pool"], 300_000)
        self.assertEqual(len(sim["books"]), 1)

        book_stat = sim["books"][0]
        self.assertEqual(book_stat["book_id"], self.book.pk)
        # Verify anti-fraud cap capped 36,000 to 14,400
        self.assertEqual(book_stat["valid_seconds"], 14_400)
        self.assertEqual(book_stat["amount"], 300_000)

        # 5. Finalize pool: credits teacher wallet directly into available_balance
        credited_count = finalize_subscription_pool(period)
        self.assertEqual(credited_count, 1)

        wallet = TeacherWallet.objects.get(teacher=self.teacher1)
        self.assertEqual(wallet.available_balance, 300_000)
        self.assertEqual(wallet.total_earned, 300_000)

        # Verify transaction logged
        pool_tx = WalletTransaction.objects.get(
            wallet=wallet, event_type=WalletTransaction.EventType.SUBSCRIPTION_POOL
        )
        self.assertEqual(pool_tx.amount, 300_000)

        # Period status is updated
        period.refresh_from_db()
        self.assertEqual(period.status, SubscriptionPoolPeriod.Status.FINALIZED)

        # Audit check: wallet is 100% healthy
        from apps.commerce.wallet import audit_teacher_wallet
        audit = audit_teacher_wallet(wallet)
        self.assertTrue(audit["is_healthy"])
        self.assertEqual(audit["available_balance"], audit["calculated_available"])
        self.assertEqual(audit["total_earned"], audit["calculated_earned"])

        # Calling finalize again should be idempotent or raise validation error, never double credit
        with self.assertRaises(Exception):
            finalize_subscription_pool(period)
        wallet.refresh_from_db()
        self.assertEqual(wallet.available_balance, 300_000)
        self.assertEqual(wallet.total_earned, 300_000)





