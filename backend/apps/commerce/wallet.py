from datetime import timedelta
import logging
from django.db import transaction
from django.utils import timezone

from .models import (
    Order,
    OrderAuthorRevenue,
    PayoutRequest,
    TeacherBankAccount,
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
    مقایسه ریز تراکنش‌های دفترکل با موجودی‌های اسمی کیف پول جهت کشف هرگونه مغایرت ۶ سطحی:
    (total_earned, total_withdrawn, available_balance, pending_balance, locked_balance, debt_balance)
    """
    txs = list(wallet.transactions.all().order_by("created_at", "id"))

    calc_earned = 0
    calc_withdrawn = 0
    calc_pending = 0
    calc_available = 0
    calc_locked = 0
    calc_debt = 0

    for tx in txs:
        if tx.event_type == WalletTransaction.EventType.EARN_PENDING:
            calc_earned += tx.amount
            calc_pending += tx.amount
        elif tx.event_type == WalletTransaction.EventType.SUBSCRIPTION_POOL:
            calc_earned += tx.amount
            if calc_debt > 0:
                debt_pay = min(calc_debt, tx.amount)
                calc_debt -= debt_pay
                calc_available += (tx.amount - debt_pay)
            else:
                calc_available += tx.amount
        elif tx.event_type == WalletTransaction.EventType.RELEASE_AVAILABLE:
            calc_pending = max(0, calc_pending - tx.amount)
            # اگر بدهی وجود دارد، ابتدا بدهی صاف می‌شود
            if calc_debt > 0:
                debt_pay = min(calc_debt, tx.amount)
                calc_debt -= debt_pay
                calc_available += (tx.amount - debt_pay)
            else:
                calc_available += tx.amount
        elif tx.event_type == WalletTransaction.EventType.WITHDRAW_HOLD:
            calc_available = max(0, calc_available - tx.amount)
            calc_locked += tx.amount
        elif tx.event_type == WalletTransaction.EventType.WITHDRAW_PAID:
            calc_locked = max(0, calc_locked - tx.amount)
            calc_withdrawn += tx.amount
        elif tx.event_type == WalletTransaction.EventType.WITHDRAW_REJECTED:
            calc_locked = max(0, calc_locked - tx.amount)
            calc_available += tx.amount
        elif tx.event_type == WalletTransaction.EventType.REFUND_ADJUSTMENT:
            calc_earned = max(0, calc_earned - tx.amount)
            if tx.author_revenue and tx.author_revenue.release_status == OrderAuthorRevenue.ReleaseStatus.PENDING:
                calc_pending = max(0, calc_pending - tx.amount)
            else:
                if calc_available >= tx.amount:
                    calc_available -= tx.amount
                else:
                    calc_debt += (tx.amount - calc_available)
                    calc_available = 0

    is_healthy = (
        wallet.total_earned == calc_earned and
        wallet.total_withdrawn == calc_withdrawn and
        wallet.available_balance == calc_available and
        wallet.pending_balance == calc_pending and
        wallet.locked_balance == calc_locked and
        wallet.debt_balance == calc_debt and
        wallet.available_balance >= 0 and
        wallet.pending_balance >= 0 and
        wallet.locked_balance >= 0 and
        wallet.debt_balance >= 0
    )

    return {
        "wallet_id": wallet.id,
        "teacher_phone": wallet.teacher.phone,
        "is_healthy": is_healthy,
        "available_balance": wallet.available_balance,
        "calculated_available": calc_available,
        "pending_balance": wallet.pending_balance,
        "calculated_pending": calc_pending,
        "locked_balance": wallet.locked_balance,
        "calculated_locked": calc_locked,
        "debt_balance": wallet.debt_balance,
        "calculated_debt": calc_debt,
        "net_withdrawable": wallet.net_withdrawable_amount,
        "total_earned": wallet.total_earned,
        "calculated_earned": calc_earned,
        "total_withdrawn": wallet.total_withdrawn,
        "calculated_withdrawn": calc_withdrawn,
        "transactions_count": len(txs),
    }


MIN_WITHDRAWAL_AMOUNT = 200_000  # حداقل سقف برداشت به تومان


def request_teacher_payout(teacher, amount: int) -> PayoutRequest:
    """
    ثبت درخواست تسویه حساب توسط استاد با مسدودسازی اتمیک مبلغ و ثبت در دفترکل.
    """
    from django.core.exceptions import ValidationError

    if amount < MIN_WITHDRAWAL_AMOUNT:
        raise ValidationError(f"حداقل مبلغ قابل درخواست تسویه {MIN_WITHDRAWAL_AMOUNT:,} تومان است.")

    bank_account = getattr(teacher, "bank_account", None)
    if not bank_account or not bank_account.is_verified:
        raise ValidationError("شماره شبای بانکی شما هنوز ثبت یا توسط مدیریت تایید نشده است.")

    with transaction.atomic():
        # بررسی عدم وجود درخواست تسویه باز
        has_open_request = PayoutRequest.objects.filter(
            teacher=teacher,
            status__in=[PayoutRequest.Status.PENDING, PayoutRequest.Status.PROCESSING],
        ).exists()
        if has_open_request:
            raise ValidationError("شما در حال حاضر یک درخواست تسویه حساب در جریان دارید. پس از تعیین تکلیف آن درخواست جدید ثبت کنید.")

        wallet = TeacherWallet.objects.select_for_update().get_or_create(teacher=teacher)[0]
        net_available = wallet.net_withdrawable_amount

        if amount > net_available:
            raise ValidationError(f"مبلغ درخواستی ({amount:,} تومان) از موجودی قابل برداشت خالص شما ({net_available:,} تومان) بیشتر است.")

        # مسدودسازی مبلغ: انتقال از available به locked
        wallet.available_balance -= amount
        wallet.locked_balance += amount
        wallet.save()

        payout = PayoutRequest.objects.create(
            teacher=teacher,
            amount=amount,
            status=PayoutRequest.Status.PENDING,
            account_holder_snapshot=bank_account.account_holder_name,
            iban_snapshot=bank_account.iban,
            bank_name_snapshot=bank_account.bank_name,
        )

        idempotency_key = f"payout-{payout.id}-hold"
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.WITHDRAW_HOLD,
            amount=amount,
            available_balance_after=wallet.available_balance,
            pending_balance_after=wallet.pending_balance,
            locked_balance_after=wallet.locked_balance,
            debt_balance_after=wallet.debt_balance,
            idempotency_key=idempotency_key,
            description=f"مسدودسازی جهت تسویه حساب #{payout.id} (شبا: {bank_account.iban})",
        )

        from apps.catalog.backups import notify_bale_after_commit
        from apps.catalog.panel_display import fa_number
        msg = (
            f"🏦 درخواست تسویه حساب جدید\n"
            f"استاد: {teacher.phone} ({teacher.full_name or ''})\n"
            f"مبلغ: {fa_number(amount)} تومان\n"
            f"شبا: {bank_account.iban}\n"
            f"صاحب حساب: {bank_account.account_holder_name}"
        )
        notify_bale_after_commit(msg, log_label=f"Bale payout request alert for #{payout.id}")

    return payout


def mark_payout_as_processing(payout: PayoutRequest, manager_user=None) -> PayoutRequest:
    """انتقال وضعیت درخواست تسویه به در حال پرداخت بانکی."""
    from django.core.exceptions import ValidationError
    if payout.status != PayoutRequest.Status.PENDING:
        raise ValidationError("فقط درخواست‌های در انتظار قابل انتقال به وضعیت در حال پرداخت هستند.")

    payout.status = PayoutRequest.Status.PROCESSING
    if manager_user:
        payout.processed_by = manager_user
    payout.save(update_fields=["status", "processed_by"])
    return payout


def finalize_payout_paid(payout: PayoutRequest, tracking_code: str, receipt_note: str = "", manager_user=None) -> PayoutRequest:
    """
    نهایی‌سازی پرداخت قطعی بانکی با ثبت کد رهگیری پایا/ساتنا و بروزرسانی کیف پول و دفترکل.
    """
    from django.core.exceptions import ValidationError
    if not tracking_code:
        raise ValidationError("ثبت کد رهگیری بانکی (پایا/ساتنا) برای تسویه قطعی الزامی است.")
    if payout.status not in (PayoutRequest.Status.PENDING, PayoutRequest.Status.PROCESSING):
        raise ValidationError("این درخواست قبلاً تعیین تکلیف شده است.")

    with transaction.atomic():
        payout_locked = PayoutRequest.objects.select_for_update().get(pk=payout.pk)
        if payout_locked.status == PayoutRequest.Status.PAID:
            return payout_locked

        wallet = TeacherWallet.objects.select_for_update().get(teacher=payout_locked.teacher)

        # کسر از locked_balance و افزایش total_withdrawn
        wallet.locked_balance = max(0, wallet.locked_balance - payout_locked.amount)
        wallet.total_withdrawn += payout_locked.amount
        wallet.save()

        payout_locked.status = PayoutRequest.Status.PAID
        payout_locked.tracking_code = tracking_code
        payout_locked.receipt_note = receipt_note
        payout_locked.paid_at = timezone.now()
        if manager_user:
            payout_locked.processed_by = manager_user
        payout_locked.save()

        idempotency_key = f"payout-{payout_locked.id}-paid"
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.WITHDRAW_PAID,
            amount=payout_locked.amount,
            available_balance_after=wallet.available_balance,
            pending_balance_after=wallet.pending_balance,
            locked_balance_after=wallet.locked_balance,
            debt_balance_after=wallet.debt_balance,
            idempotency_key=idempotency_key,
            description=f"واریز قطعی تسویه حساب #{payout_locked.id} (کد رهگیری: {tracking_code})",
        )

        from apps.catalog.backups import notify_bale_after_commit
        from apps.catalog.panel_display import fa_number
        msg = (
            f"✅ واریز تسویه حساب استاد انجام شد\n"
            f"استاد: {payout_locked.teacher.phone}\n"
            f"مبلغ: {fa_number(payout_locked.amount)} تومان\n"
            f"کد رهگیری: {tracking_code}"
        )
        notify_bale_after_commit(msg, log_label=f"Bale payout paid alert for #{payout_locked.id}")

    return payout_locked


def reject_payout_request(payout: PayoutRequest, reason: str, manager_user=None) -> PayoutRequest:
    """
    رد درخواست تسویه توسط مدیر و بازگشت خودکار مبلغ از locked به available_balance در یک ترنزکشن اتمیک.
    """
    from django.core.exceptions import ValidationError
    if not reason:
        raise ValidationError("ذکر دلیل رد درخواست الزامی است.")
    if payout.status not in (PayoutRequest.Status.PENDING, PayoutRequest.Status.PROCESSING):
        raise ValidationError("این درخواست قبلاً تعیین تکلیف شده است.")

    with transaction.atomic():
        payout_locked = PayoutRequest.objects.select_for_update().get(pk=payout.pk)
        if payout_locked.status == PayoutRequest.Status.REJECTED:
            return payout_locked

        wallet = TeacherWallet.objects.select_for_update().get(teacher=payout_locked.teacher)

        # بازگشت مبلغ مسدودشده به موجودی در دسترس
        wallet.locked_balance = max(0, wallet.locked_balance - payout_locked.amount)
        wallet.available_balance += payout_locked.amount
        wallet.save()

        payout_locked.status = PayoutRequest.Status.REJECTED
        payout_locked.rejection_reason = reason
        if manager_user:
            payout_locked.processed_by = manager_user
        payout_locked.save()

        idempotency_key = f"payout-{payout_locked.id}-rejected"
        WalletTransaction.objects.create(
            wallet=wallet,
            event_type=WalletTransaction.EventType.WITHDRAW_REJECTED,
            amount=payout_locked.amount,
            available_balance_after=wallet.available_balance,
            pending_balance_after=wallet.pending_balance,
            locked_balance_after=wallet.locked_balance,
            debt_balance_after=wallet.debt_balance,
            idempotency_key=idempotency_key,
            description=f"رد تسویه حساب #{payout_locked.id}: {reason}",
        )

    return payout_locked

