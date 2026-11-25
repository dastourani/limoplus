from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.commerce.models import Order
from apps.learning.models import QuizAnswer
from apps.study.models import ReviewSession

from .models import ErrorEvent, ErrorGroup, HealthCheckRun
from .service import record_event

log = logging.getLogger(__name__)

PENDING_GRACE = timedelta(minutes=15)
SECONDS_PER_MONTH = 30 * 86400


def verify_settled_order(order_id: int) -> bool:
    """Lightweight post-commit sanity check right after an order transitions to PAID."""
    try:
        return _verify_settled_order_impl(order_id)
    except Exception:  # noqa: BLE001 — post-commit verification must never break a payment callback
        log.exception("verify_settled_order failed for order %s", order_id)
        return True


def _verify_settled_order_impl(order_id: int) -> bool:
    order = Order.objects.select_related("plan", "book", "entitlement").filter(pk=order_id).first()
    if order is None or order.status != Order.Status.PAID:
        return True
    day_key = timezone.localdate().isoformat()
    ent = getattr(order, "entitlement", None)
    if ent is None:
        record_event(
            source=ErrorGroup.Source.HEALTH,
            kind=ErrorGroup.Kind.INVARIANT,
            code="paid_order_missing_entitlement",
            title="سفارش پرداخت‌شده بدون دسترسی متناظر",
            event_id=f"health:pay:missing:{order.id}:{day_key}",
            user_id=order.user_id,
            platform=order.return_channel or "server",
            route="/api/v1/payments/zibal/callback/",
            operation="settle_order",
            expected="هر سفارش PAID باید دقیقاً یک رکورد دسترسی (Entitlement) متصل داشته باشد.",
            observed=f"سفارش #{order.id} وضعیت PAID دارد اما دسترسی متصل ندارد.",
            severity=ErrorGroup.Severity.CRITICAL,
            context={"order_id": order.id, "book_slug": order.book.slug if order.book_id else ""},
        )
        return False

    mismatch_msg = _entitlement_mismatch(order, ent)
    if mismatch_msg:
        record_event(
            source=ErrorGroup.Source.HEALTH,
            kind=ErrorGroup.Kind.INVARIANT,
            code="paid_order_wrong_entitlement",
            title="دسترسی سفارش پرداخت‌شده با مشخصات سفارش تطابق ندارد",
            event_id=f"health:pay:wrong:{order.id}:{day_key}",
            user_id=order.user_id,
            platform=order.return_channel or "server",
            route="/api/v1/payments/zibal/callback/",
            operation="settle_order",
            expected="کتاب یا مدت اشتراک دسترسی متصل باید دقیقاً با سفارش پرداخت‌شده منطبق باشد.",
            observed=mismatch_msg,
            severity=ErrorGroup.Severity.CRITICAL,
            context=_order_context(order, ent),
        )
        return False
    return True


def _order_context(order: Order, ent) -> dict:
    ctx: dict[str, object] = {"order_id": order.id, "entitlement_id": ent.id}
    if order.book_id:
        ctx["expected_book_id"] = order.book_id
        ctx["recorded_book_id"] = ent.book_id
        if order.book:
            ctx["book_slug"] = order.book.slug
    else:
        months = order.plan_months or (order.plan.months if order.plan_id else 0)
        ctx["expected_months"] = months
        if ent.starts_at and ent.ends_at:
            ctx["recorded_days"] = round((ent.ends_at - ent.starts_at).total_seconds() / 86400, 2)
    return ctx


def _entitlement_mismatch(order: Order, ent) -> str | None:
    if order.book_id:
        if ent.book_id != order.book_id:
            return f"سفارش #{order.id} برای کتاب {order.book_id} است، اما دسترسی متصل به کتاب {ent.book_id} اشاره دارد."
        if ent.ends_at is not None:
            return f"سفارش کتاب #{order.id} باید دسترسی دائمی بسازد، اما ends_at پر است."
        return None

    expected_months = order.plan_months or (order.plan.months if order.plan_id else None)
    if expected_months is None:
        return None
    if ent.book_id is not None:
        return f"سفارش اشتراک #{order.id} به‌اشتباه دسترسی کتاب ثبت کرده است."
    if ent.starts_at is None or ent.ends_at is None:
        return f"سفارش اشتراک #{order.id} ({expected_months} ماه) تاریخ شروع یا پایان ندارد."
    expected_seconds = expected_months * SECONDS_PER_MONTH
    actual_seconds = (ent.ends_at - ent.starts_at).total_seconds()
    # Allow <= 60s tolerance for DST/leap edge, while exact 30*months days are produced by _grant().
    if abs(actual_seconds - expected_seconds) > 60:
        actual_days = round(actual_seconds / 86400, 2)
        return f"مدت دسترسی سفارش #{order.id} برابر با {actual_days} روز است، اما باید {expected_months * 30} روز ({expected_months} ماه) باشد."
    return None


def check_payments_and_entitlements(now=None) -> HealthCheckRun:
    """
    Audits PAID orders against their OneToOne Entitlement effect at settlement time:
    - Stacked renewals pass because `ends_at - starts_at` equals `30 * months` days even when `starts_at` shifts forward.
    - Later cancelled (`is_archived=True`) or naturally expired entitlements pass because the entitlement exists with valid terms.
    - REFUNDED orders are excluded; PENDING orders with `track_id` are counted separately as pending, not invariant failures.
    """
    t0 = time.monotonic()
    now = now or timezone.now()
    day_key = timezone.localdate(now).isoformat()
    checked = 0
    issues = 0
    missing_ids: list[int] = []
    wrong_ids: list[int] = []

    paid_orders = Order.objects.filter(status=Order.Status.PAID).select_related("plan", "book", "entitlement").order_by("id")
    for order in paid_orders.iterator(chunk_size=500):
        checked += 1
        ent = getattr(order, "entitlement", None)
        if ent is None:
            issues += 1
            missing_ids.append(order.id)
            record_event(
                source=ErrorGroup.Source.HEALTH,
                kind=ErrorGroup.Kind.INVARIANT,
                code="paid_order_missing_entitlement",
                title="سفارش پرداخت‌شده بدون دسترسی متناظر",
                event_id=f"health:pay:missing:{order.id}:{day_key}",
                user_id=order.user_id,
                platform=order.return_channel or "server",
                route="/api/v1/payments/zibal/callback/",
                operation="health_check_payments",
                expected="هر سفارش PAID باید یک Entitlement متصل با مدت/کتاب منطبق داشته باشد (حتی اگر بعداً منقضی یا لغو شده باشد).",
                observed=f"سفارش #{order.id} در وضعیت PAID است اما هیچ رکورد Entitlement به آن متصل نیست.",
                severity=ErrorGroup.Severity.CRITICAL,
                context={"order_id": order.id, "book_slug": order.book.slug if order.book_id else ""},
            )
            continue

        mismatch = _entitlement_mismatch(order, ent)
        if mismatch:
            issues += 1
            wrong_ids.append(order.id)
            record_event(
                source=ErrorGroup.Source.HEALTH,
                kind=ErrorGroup.Kind.INVARIANT,
                code="paid_order_wrong_entitlement",
                title="دسترسی سفارش پرداخت‌شده با مشخصات سفارش تطابق ندارد",
                event_id=f"health:pay:wrong:{order.id}:{day_key}",
                user_id=order.user_id,
                platform=order.return_channel or "server",
                route="/api/v1/payments/zibal/callback/",
                operation="health_check_payments",
                expected="کتاب یا مدت اشتراک دسترسی متصل باید دقیقاً با سفارش پرداخت‌شده منطبق باشد.",
                observed=mismatch,
                severity=ErrorGroup.Severity.CRITICAL,
                context=_order_context(order, ent),
            )

    pending_with_track = Order.objects.filter(
        status=Order.Status.PENDING,
        track_id__isnull=False,
        created_at__lt=now - PENDING_GRACE,
    ).count()

    summary = f"{checked} سفارش پرداخت‌شده بررسی شد؛ {issues} مغایرت قطعی؛ {pending_with_track} سفارش در انتظار تعیین وضعیت."
    return HealthCheckRun.objects.create(
        check_key=HealthCheckRun.CheckKey.PAYMENTS,
        completed=True,
        checked_count=checked,
        issues_found=issues,
        pending_count=pending_with_track,
        summary=summary,
        details={"missing_order_ids": missing_ids[:20], "wrong_order_ids": wrong_ids[:20], "pending_with_track": pending_with_track},
        duration_ms=int((time.monotonic() - t0) * 1000),
        ran_at=now,
    )


def check_review_sessions(now=None) -> HealthCheckRun:
    """
    Audits finalized non-exam ReviewSessions (`finished_at__isnull=False, score__isnull=False, exam__isnull=True`):
    - Excludes legacy sessions closed without a score by migration 0016.
    - Uses `QuizAnswer.was_correct` recorded at answer time (immune to later answer-key edits).
    - Compares session answers against `session.served` and `session.score`.
    """
    t0 = time.monotonic()
    now = now or timezone.now()
    day_key = timezone.localdate(now).isoformat()

    sessions = list(
        ReviewSession.objects.filter(finished_at__isnull=False, score__isnull=False, exam__isnull=True)
        .order_by("id")
        .only("id", "user_id", "served", "score", "minimum", "stage")
    )
    checked = len(sessions)
    issues = 0
    mismatched_ids: list[int] = []

    if sessions:
        session_ids = [s.id for s in sessions]
        answers_by_session: dict[int, list[tuple[int, bool]]] = {sid: [] for sid in session_ids}
        for sid, qid, ok in (
            QuizAnswer.objects.filter(review_session_id__in=session_ids)
            .order_by("answered_at", "id")
            .values_list("review_session_id", "question_id", "was_correct")
        ):
            answers_by_session[sid].append((qid, bool(ok)))

        for s in sessions:
            served_ids = list(s.served or [])
            served_set = set(served_ids)
            rows = answers_by_session.get(s.id, [])

            first_per_q: dict[int, bool] = {}
            orphan_qids: list[int] = []
            for qid, ok in rows:
                if qid not in served_set:
                    orphan_qids.append(qid)
                elif qid not in first_per_q:
                    first_per_q[qid] = ok

            if orphan_qids:
                issues += 1
                mismatched_ids.append(s.id)
                record_event(
                    source=ErrorGroup.Source.HEALTH,
                    kind=ErrorGroup.Kind.INVARIANT,
                    code="review_orphan_answers",
                    title="پاسخ‌های ثبت‌شده در جلسهٔ مرور در فهرست سؤال‌های ارائه‌شده نیستند",
                    event_id=f"health:rev:orphan:{s.id}:{day_key}",
                    user_id=s.user_id,
                    platform="server",
                    route="/api/v1/me/reviews/<id>/finish/",
                    operation="health_check_reviews",
                    expected=f"همهٔ پاسخ‌های جلسهٔ #{s.id} باید عضو served ({len(served_ids)} سؤال) باشند.",
                    observed=f"در جلسهٔ #{s.id} تعداد {len(orphan_qids)} پاسخ خارج از فهرست served ثبت شده است.",
                    severity=ErrorGroup.Severity.ERROR,
                    context={
                        "session_id": s.id,
                        "served_count": len(served_ids),
                        "answered_count": len(first_per_q),
                        "missing_count": len(orphan_qids),
                    },
                )
                continue

            if not first_per_q:
                issues += 1
                mismatched_ids.append(s.id)
                record_event(
                    source=ErrorGroup.Source.HEALTH,
                    kind=ErrorGroup.Kind.INVARIANT,
                    code="review_score_without_answers",
                    title="جلسهٔ مرور با نمره بسته شده اما پاسخی در جلسه ثبت نشده است",
                    event_id=f"health:rev:empty:{s.id}:{day_key}",
                    user_id=s.user_id,
                    platform="server",
                    route="/api/v1/me/reviews/<id>/finish/",
                    operation="health_check_reviews",
                    expected="جلسهٔ نهایی‌شده و امتیازدار باید دست‌کم یک QuizAnswer متصل به همین جلسه داشته باشد.",
                    observed=f"جلسهٔ #{s.id} دارای score={round(s.score, 4)} است اما ۰ پاسخ متصل دارد.",
                    severity=ErrorGroup.Severity.ERROR,
                    context={
                        "session_id": s.id,
                        "served_count": len(served_ids),
                        "answered_count": 0,
                        "recorded_score": round(s.score, 4),
                    },
                )
                continue

            correct_count = sum(1 for ok in first_per_q.values() if ok)
            expected_score = correct_count / len(first_per_q)
            if abs(float(s.score) - expected_score) > 1e-6:
                issues += 1
                mismatched_ids.append(s.id)
                record_event(
                    source=ErrorGroup.Source.HEALTH,
                    kind=ErrorGroup.Kind.INVARIANT,
                    code="review_score_mismatch",
                    title="نمرهٔ ثبت‌شدهٔ جلسهٔ مرور با پاسخ‌های همان جلسه نمی‌خواند",
                    event_id=f"health:rev:score:{s.id}:{day_key}",
                    user_id=s.user_id,
                    platform="server",
                    route="/api/v1/me/reviews/<id>/finish/",
                    operation="health_check_reviews",
                    expected=f"نمرهٔ محاسبه‌شده از {len(first_per_q)} پاسخ جلسهٔ #{s.id} ({correct_count} درست) برابر {round(expected_score, 4)} باشد.",
                    observed=f"نمرهٔ ذخیره‌شده روی ReviewSession #{s.id} برابر {round(float(s.score), 4)} است درحالی‌که از پاسخ‌های ثبت‌شده {round(expected_score, 4)} به دست می‌آید.",
                    severity=ErrorGroup.Severity.ERROR,
                    context={
                        "session_id": s.id,
                        "stage": s.stage,
                        "served_count": len(served_ids),
                        "answered_count": len(first_per_q),
                        "correct_count": correct_count,
                        "expected_score": round(expected_score, 4),
                        "recorded_score": round(float(s.score), 4),
                    },
                )

    summary = f"{checked} جلسهٔ مرور نهایی‌شده بررسی شد؛ {issues} مغایرت یافت شد."
    return HealthCheckRun.objects.create(
        check_key=HealthCheckRun.CheckKey.REVIEWS,
        completed=True,
        checked_count=checked,
        issues_found=issues,
        pending_count=0,
        summary=summary,
        details={"mismatched_session_ids": mismatched_ids[:20]},
        duration_ms=int((time.monotonic() - t0) * 1000),
        ran_at=now,
    )


def check_offline_health(now=None) -> HealthCheckRun:
    """Summarizes client-reported offline bundle failures over the last 24 hours."""
    t0 = time.monotonic()
    now = now or timezone.now()
    since = now - timedelta(hours=24)

    counts = {
        "offline_missing": 0,
        "offline_corrupt": 0,
        "offline_media_missing": 0,
        "offline_update_failed_prev_intact": 0,
    }
    for code, cnt in (
        ErrorEvent.objects.filter(group__kind=ErrorGroup.Kind.OFFLINE, created_at__gte=since)
        .values_list("group__code")
        .annotate(c=Count("id"))
    ):
        if code in counts:
            counts[code] = cnt

    total = sum(counts.values())
    broken_open = counts["offline_corrupt"] + counts["offline_media_missing"]
    summary = (
        f"۲۴ ساعت اخیر: {counts['offline_missing']} فایل پیدا نشد، "
        f"{broken_open} بازنشد/عکس ناقص، "
        f"{counts['offline_update_failed_prev_intact']} خطای آپدیت با حفظ نسخهٔ قبلی."
    )
    return HealthCheckRun.objects.create(
        check_key=HealthCheckRun.CheckKey.OFFLINE,
        completed=True,
        checked_count=total,
        issues_found=counts["offline_missing"] + counts["offline_corrupt"] + counts["offline_media_missing"],
        pending_count=counts["offline_update_failed_prev_intact"],
        summary=summary,
        details=counts,
        duration_ms=int((time.monotonic() - t0) * 1000),
        ran_at=now,
    )


def run_all_health_checks_if_due(now=None, force: bool = False) -> list[HealthCheckRun]:
    """Runs all health checks if forced or not completed in the last 55 minutes (for hourly `run_due`)."""
    now = now or timezone.now()
    if not force and HealthCheckRun.objects.filter(completed=True, ran_at__gte=now - timedelta(minutes=55)).exists():
        return []
    return run_all_health_checks(now=now)


def run_all_health_checks(now=None) -> list[HealthCheckRun]:
    now = now or timezone.now()
    runs: list[HealthCheckRun] = []
    for key, fn in (
        (HealthCheckRun.CheckKey.PAYMENTS, check_payments_and_entitlements),
        (HealthCheckRun.CheckKey.REVIEWS, check_review_sessions),
        (HealthCheckRun.CheckKey.OFFLINE, check_offline_health),
    ):
        try:
            runs.append(fn(now=now))
        except Exception as exc:  # noqa: BLE001 — record failed check run explicitly so silence != health
            log.exception("Health check %s failed", key)
            runs.append(
                HealthCheckRun.objects.create(
                    check_key=key,
                    completed=False,
                    summary=f"اجرا با خطا متوقف شد: {type(exc).__name__}",
                    ran_at=now,
                )
            )
    return runs
