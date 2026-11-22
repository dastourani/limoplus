from datetime import timedelta
from decimal import Decimal
import logging
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import BookEditor
from .models import (
    BookAuthorShare,
    BookRoyaltyRule,
    Order,
    OrderAuthorRevenue,
    OrderRevenueSnapshot,
    RevenuePlan,
)

log = logging.getLogger(__name__)


def get_active_plan_for_book(book, now=None) -> tuple[RevenuePlan | None, Decimal, Decimal]:
    """
    یافتن طرح درآمدی و درصد سهم مؤلفان و پلتفرم برای یک کتاب.
    خروجی: (plan, author_percent, platform_percent)
    """
    now = now or timezone.now()
    rule = BookRoyaltyRule.objects.filter(book=book).first()

    # ۱. اگر درصد اختصاصی دستی برای این کتاب تنظیم شده باشد
    if rule and rule.is_custom_split and rule.custom_platform_share_percent is not None:
        plat_pct = Decimal(rule.custom_platform_share_percent)
        auth_pct = Decimal(100) - plat_pct
        return None, auth_pct, plat_pct

    # ۲. اگر طرح خاصی به این کتاب وصل شده باشد
    plan = rule.revenue_plan if rule else None
    if plan and plan.is_valid_now(now):
        # بررسی سقف فروش تعدادی
        if plan.max_sales_count:
            current_sales = OrderRevenueSnapshot.objects.filter(book=book, revenue_plan=plan).count()
            if current_sales >= plan.max_sales_count:
                plan = None  # منقضی شد، به طرح پیش‌فرض رجوع می‌شود

    # ۳. اگر طرح پیدا نشد، طرح پیش‌فرض سامانه
    if not plan or not plan.is_valid_now(now):
        plan = RevenuePlan.objects.filter(is_default=True, is_active=True).first()

    if plan and plan.is_valid_now(now):
        return plan, Decimal(plan.author_share_percent), Decimal(plan.platform_share_percent)

    # در صورت عدم وجود هرگونه طرح، پیش‌فرض پایدار ۷۰٪ مؤلف / ۳۰٪ پلتفرم
    return None, Decimal(70), Decimal(30)


def calculate_and_save_order_royalty(order: Order) -> OrderRevenueSnapshot | None:
    """
    محاسبه و ذخیره اسنپ‌شات قطعی سهم پلتفرم و مؤلفان در هنگام پرداخت موفق سفارش کتاب.
    در صورت وجود چند مؤلف، سهم هرکدام را بر اساس درصدهای تعریف‌شده ثبت می‌کند.
    """
    if not order.book_id or order.status != Order.Status.PAID:
        return None

    # جلوگیری از ثبت مکرر
    existing = OrderRevenueSnapshot.objects.filter(order=order).first()
    if existing:
        return existing

    book = order.book
    total_amount = order.amount
    now = order.paid_at or timezone.now()

    plan, total_author_pct, platform_pct = get_active_plan_for_book(book, now=now)

    # تعیین مؤلفان و سهم هرکدام
    rule = BookRoyaltyRule.objects.filter(book=book).first()
    author_shares = list(rule.author_shares.filter(is_active=True).select_related("author")) if rule else []

    shares_to_record = []
    if author_shares:
        # اگر چندمؤلفی به صراحت تعریف شده باشد
        # مقیاس‌بندی نسبت‌ها در صورتی که جمع درصدهای مؤلفان با total_author_pct متفاوت باشد
        defined_author_sum = sum(s.share_percent for s in author_shares)
        for s in author_shares:
            if defined_author_sum > 0:
                effective_pct = (s.share_percent / defined_author_sum) * total_author_pct
            else:
                effective_pct = total_author_pct / len(author_shares)
            shares_to_record.append((s.author, effective_pct))
    else:
        # اگر هنوز سهم اختصاصی ثبت نشده، به تمام استادان ثبت‌شده در BookEditor به نسبت مساوی تعلق می‌گیرد
        editors = list(BookEditor.objects.filter(book=book).select_related("user"))
        if editors:
            split_pct = total_author_pct / Decimal(len(editors))
            for ed in editors:
                shares_to_record.append((ed.user, split_pct))
        elif getattr(book, "author_id", None):
            # در صورتی که فیلد author به User اشاره داشت
            shares_to_record.append((book.author, total_author_pct))

    # محاسبه مبالغ ریالی با گرد کردن استاندارد به نزدیک‌ترین تومان
    total_authors_amount = 0
    author_revenues_data = []

    if shares_to_record:
        for author, pct in shares_to_record:
            amt = int(round(float(total_amount) * float(pct) / 100.0))
            total_authors_amount += amt
            author_revenues_data.append({
                "author": author,
                "share_percent": pct,
                "amount": amt,
            })
        platform_amount = max(0, total_amount - total_authors_amount)
    else:
        # اگر هنوز هیچ استادی تعریف نشده، سهم مؤلفان محاسبه شده و به عنوان طلب ذخیره می‌شود
        authors_theoretical_pct = total_author_pct
        total_authors_amount = int(round(float(total_amount) * float(authors_theoretical_pct) / 100.0))
        platform_amount = max(0, total_amount - total_authors_amount)

    # دوره گارانتی اعمال‌شده از روی طرح یا پیش‌فرض ۷ روز
    hold_days = plan.pending_hold_days if plan else 7
    available_at = now + timedelta(days=hold_days) if hold_days > 0 else now

    with transaction.atomic():
        snapshot = OrderRevenueSnapshot.objects.create(
            order=order,
            book=book,
            plan_name=plan.title if plan else ("درصد سفارشی کتاب" if rule and rule.is_custom_split else "طرح پایه"),
            revenue_plan=plan,
            total_amount=total_amount,
            platform_share_percent=platform_pct,
            platform_share_amount=platform_amount,
            total_authors_amount=total_authors_amount,
            details={
                "plan_code": plan.code if plan else "custom",
                "authors_count": len(author_revenues_data),
                "hold_days": hold_days,
                "recorded_at": now.isoformat(),
            },
        )

        for rev in author_revenues_data:
            order_author_rev = OrderAuthorRevenue.objects.create(
                snapshot=snapshot,
                author=rev["author"],
                share_percent=rev["share_percent"],
                amount=rev["amount"],
                hold_days=hold_days,
                available_at=available_at,
                release_status=OrderAuthorRevenue.ReleaseStatus.PENDING if hold_days > 0 else OrderAuthorRevenue.ReleaseStatus.AVAILABLE,
                released_at=now if hold_days == 0 else None,
            )

            # شارژ خودکار کیف پول استاد در دفترکل
            try:
                from .wallet import credit_teacher_pending_royalty
                credit_teacher_pending_royalty(order_author_rev)
            except Exception:
                log.exception("Failed to credit wallet for OrderAuthorRevenue %s", order_author_rev.id)

    log.info(
        "Order #%s revenue split recorded: Platform %s T, Authors %s T across %s authors",
        order.id, platform_amount, total_authors_amount, len(author_revenues_data)
    )
    return snapshot
