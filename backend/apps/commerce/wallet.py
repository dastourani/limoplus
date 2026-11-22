from datetime import timedelta
import logging
from django.db import transaction
from django.utils import timezone

from .models import (
    Order,
    OrderAuthorRevenue,
    TeacherWallet,
    WalletTransaction,
)

log = logging.getLogger(__name__)


def get_or_create_wallet(teacher) -> TeacherWallet:
    """دریافت یا ایجاد امن کیف پول استاد."""
    wallet, _ = TeacherWallet.objects.get_or_create(teacher=teacher)
    return wallet


def credit_teacher_pending_royalty(author_rev: OrderAuthorRevenue) -> WalletTransaction | None:
    """
    شارژ اولیه سهم فروش در کیف پول استاد به صورت «در انتظار» همراه با محاسبه زمان آزادسازی.
    کاملاً امن و Idempotent (عدم ثبت تکراری).
    """
    if author_rev.amount <= 0:
        return None

    idempotency_key = f"rev-{author_rev.id}-earn-pending"
    if WalletTransaction.objects.filter(idempotency_key=idempotency_key).exists():
        return WalletTransaction.objects.get(idempotency_key=idempotency_key)

    with transaction.atomic():
        wallet = TeacherWallet.objects.select_for_update().get_or_create(teacher=author_rev.author)[0]

        # اگر در لحظه ایجاد کیف پول یا شارژ، بدهی معوق وجود دارد، سهم ورودی ابتدا بدهی را تسویه می‌کند
        amount = author_rev.amount
        wallet.total_earned += amount

        # اگر سهم با دوره گارانتی ۰ روزه باشد (تسویه فوری)
        if author_rev.hold_days == 0:
            author_rev.release_status = OrderAuthorRevenue.ReleaseStatus.AVAILABLE
            author_rev.released_at = timezone.now()
            author_rev.available_at = timezone.now()
            author_rev.save(update_fields=["release_status", "released_at", "available_at"])

            # کسر بدهی در صورت وجود
            if wallet.debt_balance > 0:
                debt_deduct = min(wallet.debt_balance, amount)
                wallet.debt_balance -= debt_deduct
                amount_credited = amount - debt_deduct
            else:
                amount_credited = amount

            wallet.available_balance += amount_credited
            wallet.save()

            tx = WalletTransaction.objects.create(
                wallet=wallet,
                event_type=WalletTransaction.EventType.RELEASE_AVAILABLE,
                amount=author_rev.amount,
                available_balance_after=wallet.available_balance,
                pending_balance_after=wallet.pending_balance,
                debt_balance_after=wallet.debt_balance,
                reference_order=author_rev.snapshot.order,
                author_revenue=author_rev,
                idempotency_key=idempotency_key,
                description=f"سهم فروش فوری کتاب {author_rev.snapshot.book.title if author_rev.snapshot.book else ''} (سفارش #{author_rev.snapshot.order_id})",
            )
            return tx

        # حالت معمول: اضافه شدن به موجودی در انتظار تا پایان دوره گارانتی
        wallet.pending_balance += amount
        wallet.save()

        tx = WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.EARN_PENDING,
            amount=amount,
            available_balance_after=wallet.available_balance,
            pending_balance_after=wallet.pending_balance,
            debt_balance_after=wallet.debt_balance,
            reference_order=author_rev.snapshot.order,
            author_revenue=author_rev,
            idempotency_key=idempotency_key,
            description=f"سهم فروش در انتظار کتاب {author_rev.snapshot.book.title if author_rev.snapshot.book else ''} (سفارش #{author_rev.snapshot.order_id})",
        )
        return tx


def release_pending_balances(now=None) -> int:
    """
    بررسی و آزادسازی خودکار تمام سهم‌های در انتظاری که دوره گارانتی آن‌ها منقضی شده است.
    با قفل ردیف و اتمیک جهت جلوگیری مطلق از دوبل‌شمارش.
    خروجی: تعداد سهم‌های آزادشده.
    """
    now = now or timezone.now()
    due_revenues = OrderAuthorRevenue.objects.filter(
        release_status=OrderAuthorRevenue.ReleaseStatus.PENDING,
        available_at__lte=now,
    ).select_related("snapshot__order", "snapshot__book", "author")

    released_count = 0

    for rev in due_revenues:
        with transaction.atomic():
            # قفل مجدد رکورد برای اطمینان از عدم دستکاری هم‌زمان
            rev_locked = OrderAuthorRevenue.objects.select_for_update().filter(
                id=rev.id, release_status=OrderAuthorRevenue.ReleaseStatus.PENDING
            ).first()

            if not rev_locked:
                continue

            wallet = TeacherWallet.objects.select_for_update().get_or_create(teacher=rev_locked.author)[0]
            amount = rev_locked.amount

            # کسر از موجودی در انتظار کیف پول
            wallet.pending_balance = max(0, wallet.pending_balance - amount)

            # اگر استاد از قبل بدهی معوق (ناشی از استردادهای قبلی) دارد، ابتدا بدهی صاف می‌شود
            if wallet.debt_balance > 0:
                debt_deduct = min(wallet.debt_balance, amount)
                wallet.debt_balance -= debt_deduct
                amount_to_available = amount - debt_deduct
            else:
                amount_to_available = amount

            wallet.available_balance += amount_to_available
            wallet.save()

            rev_locked.release_status = OrderAuthorRevenue.ReleaseStatus.AVAILABLE
            rev_locked.released_at = now
            rev_locked.save(update_fields=["release_status", "released_at"])

            idempotency_key = f"rev-{rev_locked.id}-release"
            WalletTransaction.objects.create(
                wallet=wallet,
                event_type=WalletTransaction.EventType.RELEASE_AVAILABLE,
                amount=amount,
                available_balance_after=wallet.available_balance,
                pending_balance_after=wallet.pending_balance,
                debt_balance_after=wallet.debt_balance,
                reference_order=rev_locked.snapshot.order,
                author_revenue=rev_locked,
                idempotency_key=idempotency_key,
                description=f"پایان دوره گارانتی و آزادسازی سهم فروش سفارش #{rev_locked.snapshot.order_id}",
            )
            released_count += 1

    return released_count


def process_order_refund(order: Order, reason: str = "استرداد وجه سفارش") -> int:
    """
    پردازش مالی استرداد یا لغو سفارش و اصلاح دقیق کیف پول تمام مؤلفان آن سفارش.
    اگر سهم در انتظار باشد از pending کسر می‌شود.
    اگر آزاد شده باشد، از available کسر شده و در صورت کسری موجودی، به debt_balance منتقل می‌شود.
    """
    if order.status == Order.Status.REFUNDED:
        return 0

    snapshot = getattr(order, "revenue_snapshot", None)
    if not snapshot:
        order.status = Order.Status.REFUNDED
        order.save(update_fields=["status"])
        return 0

    author_revs = OrderAuthorRevenue.objects.filter(snapshot=snapshot)
    adjusted_count = 0

    with transaction.atomic():
        for rev in author_revs:
            if rev.release_status == OrderAuthorRevenue.ReleaseStatus.REFUNDED:
                continue

            wallet = TeacherWallet.objects.select_for_update().get_or_create(teacher=rev.author)[0]
            amount = rev.amount

            if rev.release_status == OrderAuthorRevenue.ReleaseStatus.PENDING:
                # هنوز در دوره گارانتی بوده: به سادگی از pending کم می‌شود
                wallet.pending_balance = max(0, wallet.pending_balance - amount)
            elif rev.release_status == OrderAuthorRevenue.ReleaseStatus.AVAILABLE:
                # قبلاً آزاد شده بوده: از available کم می‌شود
                if wallet.available_balance >= amount:
                    wallet.available_balance -= amount
                else:
                    # کسری موجودی به عنوان بدهی معوق نگهداری می‌شود
                    shortage = amount - wallet.available_balance
                    wallet.available_balance = 0
                    wallet.debt_balance += shortage

            wallet.total_earned = max(0, wallet.total_earned - amount)
            wallet.save()

            rev.release_status = OrderAuthorRevenue.ReleaseStatus.REFUNDED
            rev.save(update_fields=["release_status"])

            idempotency_key = f"rev-{rev.id}-refund"
            WalletTransaction.objects.create(
                wallet=wallet,
                event_type=WalletTransaction.EventType.REFUND_ADJUSTMENT,
                amount=amount,
                available_balance_after=wallet.available_balance,
                pending_balance_after=wallet.pending_balance,
                debt_balance_after=wallet.debt_balance,
                reference_order=order,
                author_revenue=rev,
                idempotency_key=idempotency_key,
                description=f"{reason} (سفارش #{order.id})",
            )
            adjusted_count += 1

        order.status = Order.Status.REFUNDED
        order.save(update_fields=["status"])

    return adjusted_count


def audit_teacher_wallet(wallet: TeacherWallet) -> dict:
    """
    چک‌لیست سلامت حسابداری برای مدیر کل:
    مقایسه ریز تراکنش‌های دفترکل با موجودی‌های اسمی کیف پول جهت کشف هرگونه مغایرت.
    """
    txs = wallet.transactions.all()

    # محاسبه تراز نظری از روی تراکنش‌ها
    calc_earned = 0
    calc_withdrawn = 0

    for tx in txs:
        if tx.event_type in (WalletTransaction.EventType.EARN_PENDING, WalletTransaction.EventType.SUBSCRIPTION_POOL):
            calc_earned += tx.amount
        elif tx.event_type == WalletTransaction.EventType.WITHDRAW_PAID:
            calc_withdrawn += tx.amount
        elif tx.event_type == WalletTransaction.EventType.REFUND_ADJUSTMENT:
            calc_earned = max(0, calc_earned - tx.amount)

    is_healthy = (
        wallet.total_earned == calc_earned and
        wallet.total_withdrawn == calc_withdrawn and
        wallet.available_balance >= 0 and
        wallet.pending_balance >= 0 and
        wallet.debt_balance >= 0
    )

    return {
        "wallet_id": wallet.id,
        "teacher_phone": wallet.teacher.phone,
        "is_healthy": is_healthy,
        "available_balance": wallet.available_balance,
        "pending_balance": wallet.pending_balance,
        "debt_balance": wallet.debt_balance,
        "net_withdrawable": wallet.net_withdrawable_amount,
        "total_earned": wallet.total_earned,
        "calculated_earned": calc_earned,
        "total_withdrawn": wallet.total_withdrawn,
        "calculated_withdrawn": calc_withdrawn,
        "transactions_count": txs.count(),
    }
