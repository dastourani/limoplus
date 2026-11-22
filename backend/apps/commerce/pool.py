from decimal import Decimal
import logging
from django.db import models, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.catalog.models import BookEditor, ContentNode
from apps.learning.models import Question
from apps.study.models import StudyTime
from .models import (
    BookRoyaltyRule,
    Order,
    PoolBookShare,
    SubscriptionPoolPeriod,
    TeacherWallet,
    WalletTransaction,
)

log = logging.getLogger(__name__)


def simulate_subscription_pool(period: SubscriptionPoolPeriod) -> dict:
    """
    محاسبه و شبیه‌سازی شفاف سهم هر کتاب و استادان آن از استخر اشتراک یک دوره ماهانه.
    اعمال دقیق فیلترهای ضدتقلب:
    ۱. سقف مطالعه روزانه هر کاربر (daily_user_cap_hours)
    ۲. حذف فصول رایگان (در صورت فعال بودن exclude_free_chapters)
    ۳. حداقل شرط محتوایی (حداقل فصل و تست فعال برای جلوگیری از کتاب‌های دکوری)
    ۴. محاسبه درآمد استخر از اشتراک‌های فروخته‌شده در بازه
    """
    starts_at = period.starts_at
    ends_at = period.ends_at

    # ۱. محاسبه جمع کل مبالغ فروش اشتراک و سهم استخر اساتید
    # خواندن تمام سفارشات پرداخت‌شده اشتراک در این بازه زمانی
    plan_orders = Order.objects.filter(
        plan__isnull=False,
        status=Order.Status.PAID,
        paid_at__gte=starts_at,
        paid_at__lte=ends_at,
    ).select_related("plan")

    total_sales = 0
    total_pool = 0

    for ord in plan_orders:
        total_sales += ord.amount
        plan_share = ord.plan.pool_share_percent if getattr(ord.plan, "pool_share_percent", None) else 50
        total_pool += int(round(float(ord.amount) * float(plan_share) / 100.0))

    # ذخیره مبالغ محاسبه‌شده در دوره
    period.total_subscription_sales = total_sales
    period.total_pool_amount = total_pool

    if total_pool <= 0:
        res = {
            "total_sales": total_sales,
            "total_pool": 0,
            "books": [],
            "teachers": [],
            "summary": "هیچ فروش اشتراکی در این بازه برای تشکیل استخر وجود ندارد.",
        }
        period.simulation_results = res
        period.save()
        return res

    # ۲. فیلتر کردن کتاب‌های واجد شرایط (ضد کتاب‌های دکوری و آزمایشی)
    # کتاب باید منتشرشده باشد، حداقل تعداد فصل و تست فعال داشته باشد
    eligible_books = []
    all_books = ContentNode.objects.filter(
        kind=ContentNode.Kind.BOOK,
        depth=1,
        is_published=True,
        is_archived=False,
    )

    for b in all_books:
        # شمارش فصل‌های منتشرشده
        chapters_count = ContentNode.objects.filter(
            path__startswith=b.path,
            depth=2,
            is_published=True,
        ).count()

        # شمارش تست‌های فعال
        questions_count = Question.objects.filter(
            node__path__startswith=b.path,
        ).count()

        if chapters_count >= period.min_published_chapters and questions_count >= period.min_active_questions:
            eligible_books.append(b)

    if not eligible_books:
        res = {
            "total_sales": total_sales,
            "total_pool": total_pool,
            "books": [],
            "teachers": [],
            "summary": "هیچ کتابی به حداقل استانداردهای محتوایی (فصل و تست) برای ورود به استخر نرسیده است.",
        }
        period.simulation_results = res
        period.save()
        return res

    eligible_book_pks = [b.pk for b in eligible_books]

    # ۳. فیلتر زمان مطالعه با اعمال سقف ضدتقلب روزانه و تفکیک فصول رایگان
    # کوئری مبنا روی StudyTime در بازه دوره
    start_date = starts_at.date()
    end_date = ends_at.date()
    study_qs = StudyTime.objects.filter(
        book_id__in=eligible_book_pks,
        day__gte=start_date,
        day__lte=end_date,
    )

    if period.exclude_free_chapters:
        # فصل رایگان است اگر پرچم is_free آن یا کتاب روشن باشد
        study_qs = study_qs.filter(node__is_free=False, book__is_free=False)

    # سقف روزانه به ثانیه
    cap_seconds = period.daily_user_cap_hours * 3600

    # تجمیع مصرف هر کاربر در هر روز روی هر کتاب
    # values('book', 'user', 'day') -> annotate(s=Sum('seconds'))
    user_day_stats = study_qs.values("book_id", "user_id", "day").annotate(daily_sec=Sum("seconds"))

    book_valid_seconds: dict[int, int] = {b.pk: 0 for b in eligible_books}
    book_users: dict[int, set[int]] = {b.pk: set() for b in eligible_books}

    for row in user_day_stats:
        b_id = row["book_id"]
        sec = min(row["daily_sec"] or 0, cap_seconds)  # اعمال سقف ضدتقلب
        book_valid_seconds[b_id] = book_valid_seconds.get(b_id, 0) + sec
        book_users[b_id].add(row["user_id"])

    # تجمیع تست‌های پاسخ‌داده‌شده در دوره
    quiz_qs = study_qs.filter(kind=StudyTime.Kind.QUIZ).values("book_id").annotate(q_count=Count("id"))
    book_quizzes = {r["book_id"]: r["q_count"] for r in quiz_qs}

    # ۴. محاسبه امتیاز هر کتاب بر اساس مدل انتخابی مدیر کل
    # امتیازدهی:
    # حالت STUDY_TIME: فقط زمان مطالعه موثر
    # حالت HYBRID: زمان مطالعه (وزن ۷۰٪) + فعالیت تستی/تعامل (وزن ۳۰٪) با ضریب نرمالیزه
    book_scores = {}
    for b in eligible_books:
        sec = book_valid_seconds.get(b.pk, 0)
        q_cnt = book_quizzes.get(b.pk, 0)
        unique_u = len(book_users.get(b.pk, set()))

        if period.sharing_model == SubscriptionPoolPeriod.ModelChoice.STUDY_TIME:
            score = Decimal(sec)
        else:
            # مدل ترکیبی: هر تست معادل ۶۰ ثانیه مطالعه موثر وزن می‌گیرد
            score = Decimal(sec) + Decimal(q_cnt * 60)

        # ضریب تنوع کاربران یکتا (User Diversity Factor): افزایش اندک برای اقبال گسترده
        if unique_u > 0:
            score = score * (Decimal("1.0") + min(Decimal("0.2"), Decimal(unique_u) * Decimal("0.01")))

        book_scores[b.pk] = score

    total_score = sum(book_scores.values())

    books_result = []
    teachers_payout: dict[int, dict] = {}

    for b in eligible_books:
        score = book_scores[b.pk]
        sec = book_valid_seconds.get(b.pk, 0)
        q_cnt = book_quizzes.get(b.pk, 0)
        u_cnt = len(book_users.get(b.pk, set()))

        if total_score > 0:
            share_pct = (score / total_score) * Decimal(100)
            b_amount = int(round(float(total_pool) * float(share_pct) / 100.0))
        else:
            share_pct = Decimal(0)
            b_amount = 0

        books_result.append({
            "book_id": b.pk,
            "book_title": b.title,
            "valid_seconds": sec,
            "valid_minutes": round(sec / 60),
            "quizzes_count": q_cnt,
            "unique_users": u_cnt,
            "score": float(score),
            "share_percent": float(round(share_pct, 3)),
            "amount": b_amount,
        })

        # محاسبه سهم اساتید این کتاب بر اساس قراردادهای فاز ۱
        if b_amount > 0:
            rule = BookRoyaltyRule.objects.filter(book=b).first()
            author_shares = list(rule.author_shares.filter(is_active=True).select_related("author")) if rule else []

            if author_shares:
                defined_sum = sum(s.share_percent for s in author_shares)
                for s in author_shares:
                    t_amt = int(round(float(b_amount) * float(s.share_percent / defined_sum)))
                    t_id = s.author_id
                    if t_id not in teachers_payout:
                        teachers_payout[t_id] = {
                            "teacher_id": t_id,
                            "phone": s.author.phone,
                            "amount": 0,
                            "books": [],
                        }
                    teachers_payout[t_id]["amount"] += t_amt
                    teachers_payout[t_id]["books"].append({"title": b.title, "amount": t_amt})
            else:
                editors = list(BookEditor.objects.filter(book=b).select_related("user"))
                if editors:
                    split_amt = int(round(float(b_amount) / len(editors)))
                    for ed in editors:
                        t_id = ed.user_id
                        if t_id not in teachers_payout:
                            teachers_payout[t_id] = {
                                "teacher_id": t_id,
                                "phone": ed.user.phone,
                                "amount": 0,
                                "books": [],
                            }
                        teachers_payout[t_id]["amount"] += split_amt
                        teachers_payout[t_id]["books"].append({"title": b.title, "amount": split_amt})

    # مرتب‌سازی بر اساس بیشترین سهم
    books_result.sort(key=lambda x: x["amount"], reverse=True)

    simulation_data = {
        "period_id": period.id,
        "title": period.title,
        "total_sales": total_sales,
        "total_pool": total_pool,
        "eligible_books_count": len(eligible_books),
        "books": books_result,
        "teachers": list(teachers_payout.values()),
        "computed_at": timezone.now().isoformat(),
    }

    period.simulation_results = simulation_data
    period.save()
    return simulation_data


def finalize_subscription_pool(period: SubscriptionPoolPeriod, manager_user=None) -> int:
    """
    نهایی‌سازی قطعی استخر ماهانه و واریز مستقیم سهم هر استاد به کیف پول در یک ترنزکشن اتمیک.
    سهم استخر به صورت تسویه فوری (مستقیماً در available_balance با رویداد SUBSCRIPTION_POOL) منظور می‌شود.
    """
    from django.core.exceptions import ValidationError
    if period.status == SubscriptionPoolPeriod.Status.FINALIZED:
        raise ValidationError("این دوره قبلاً نهایی شده و مبالغ آن به کیف پول‌ها واریز گردیده است.")

    # اجرای شبیه‌سازی برای اطمینان از برآوردهای دقیق
    sim = simulate_subscription_pool(period)
    teachers_data = sim.get("teachers", [])

    if not teachers_data:
        raise ValidationError("مبلغی برای واریز به اساتید در این دوره وجود ندارد.")

    credited_count = 0

    with transaction.atomic():
        period_locked = SubscriptionPoolPeriod.objects.select_for_update().get(pk=period.pk)
        if period_locked.status == SubscriptionPoolPeriod.Status.FINALIZED:
            return 0

        # ثبت سهم هر کتاب در PoolBookShare
        for b_data in sim.get("books", []):
            PoolBookShare.objects.update_or_create(
                period=period_locked,
                book_id=b_data["book_id"],
                defaults={
                    "valid_seconds": b_data["valid_seconds"],
                    "valid_quizzes": b_data["quizzes_count"],
                    "unique_active_users": b_data["unique_users"],
                    "computed_score": Decimal(str(b_data["score"])),
                    "share_percent": Decimal(str(b_data["share_percent"])),
                    "total_amount": b_data["amount"],
                },
            )

        # واریز مستقیم به کیف پول اساتید
        for t_info in teachers_data:
            amount = t_info["amount"]
            if amount <= 0:
                continue

            wallet = TeacherWallet.objects.select_for_update().get_or_create(teacher_id=t_info["teacher_id"])[0]

            wallet.total_earned += amount

            # در صورت وجود بدهی قبلی، تسویه بدهی
            if wallet.debt_balance > 0:
                debt_deduct = min(wallet.debt_balance, amount)
                wallet.debt_balance -= debt_deduct
                amount_credited = amount - debt_deduct
            else:
                amount_credited = amount

            wallet.available_balance += amount_credited
            wallet.save()

            idempotency_key = f"pool-{period_locked.id}-teacher-{t_info['teacher_id']}"
            WalletTransaction.objects.create(
                wallet=wallet,
                event_type=WalletTransaction.EventType.SUBSCRIPTION_POOL,
                amount=amount,
                available_balance_after=wallet.available_balance,
                pending_balance_after=wallet.pending_balance,
                locked_balance_after=wallet.locked_balance,
                debt_balance_after=wallet.debt_balance,
                idempotency_key=idempotency_key,
                description=f"سهم از استخر ماهانه اشتراک «{period_locked.title}»",
            )
            credited_count += 1

        period_locked.status = SubscriptionPoolPeriod.Status.FINALIZED
        period_locked.finalized_at = timezone.now()
        period_locked.save()

        try:
            from apps.catalog.backups import notify_bale
            from apps.catalog.panel_display import fa_number
            msg = (
                f"🎉 دوره استخر اشتراک نهایی و واریز شد\n"
                f"دوره: {period_locked.title}\n"
                f"کل استخر: {fa_number(period_locked.total_pool_amount)} تومان\n"
                f"تعداد اساتید واریزشده: {credited_count}"
            )
            notify_bale(msg)
        except Exception:
            pass

    log.info("Subscription pool period #%s finalized: %s teachers credited.", period.id, credited_count)
    return credited_count
