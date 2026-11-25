import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.models import ContentNode, Major

from . import zibal
from .models import Entitlement, Order, Plan
from .pricing import ProductStatus, book_price_quote, plan_price_quotes, plan_price_quote

log = logging.getLogger(__name__)
DAYS_PER_MONTH = 30


def _err(message, code, http=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code, "message": message}, status=http)


def _book(slug):
    return ContentNode.objects.filter(
        kind=ContentNode.Kind.BOOK,
        depth=1,
        slug=slug,
        is_published=True,
        is_archived=False,
        is_inbox=False,
    ).first()


def _plan_payload(plan, quote=None):
    quote = quote or plan_price_quote(plan)
    return {"id": plan.id, "title": plan.title, "scope": plan.scope, "months": plan.months, **quote.payload()}


def _entitlement_payload(e):
    return {
        "id": e.id,
        "kind": "book" if e.book_id else "subscription",
        "title": e.book.title if e.book_id else (f"اشتراک {e.major.name}" if e.major_id else "اشتراک همه‌ی رشته‌ها"),
        "book_slug": e.book.slug if e.book_id else None,
        "major_slug": e.major.slug if e.major_id else None,
        "starts_at": e.starts_at,
        "ends_at": e.ends_at,
    }


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def offers(request):
    """What can be bought to open a book: the book itself and the subscription plans (every plan covers all books)."""
    book = _book(request.query_params.get("book", ""))
    if book is None:
        return _err("کتاب پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
    sale_plans = list(_plans_on_sale())
    prices = plan_price_quotes(sale_plans)
    return Response(
        {
            "book": {"slug": book.slug, "title": book.title, **book_price_quote(book).payload()},
            "majors": [],
            "plans": [_plan_payload(plan, prices[plan.pk]) for plan in sale_plans],
            "payments_enabled": settings.PAYMENTS_ENABLED,
        }
    )


def _plans_on_sale():
    """Only all-books plans are sold. Old one-major plans stay for the record (and their subscriptions keep working)."""
    return Plan.objects.filter(is_active=True, scope=Plan.Scope.ALL)


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def plans(request):
    sale_plans = list(_plans_on_sale())
    prices = plan_price_quotes(sale_plans)
    return Response([_plan_payload(plan, prices[plan.pk]) for plan in sale_plans])


@api_view(["POST"])
def create_order(request):
    """Creates an order with a server-computed amount and returns the gateway URL. The client never sends prices."""
    if not settings.PAYMENTS_ENABLED:
        return _err("خرید هنوز فعال نشده است؛ به‌زودی باز می‌شود.", "payments_off", status.HTTP_503_SERVICE_UNAVAILABLE)
    user = request.user
    book_slug, plan_id = request.data.get("book"), request.data.get("plan")
    from apps.releases.service import normalize_channel
    platform = (request.headers.get("X-App-Platform") or "").strip().lower()
    if platform == "web":
        return_channel = "web"
    elif platform:
        return_channel = normalize_channel(request.headers.get("X-App-Channel"))
    else:
        return_channel = ""
    if book_slug and not plan_id:
        book = _book(book_slug)
        if book is None:
            return _err("این کتاب برای خرید پیدا نشد.", "not_for_sale")
        # Serialize concurrent book checkout attempts for the same buyer before checking permanent ownership.
        type(user).objects.select_for_update().only("pk").get(pk=user.pk)
        # A timed gift doesn't stop buying the book for good. The live campaign, if any, is re-read here;
        # a client-sent amount is never accepted and the quote is frozen into the order.
        if Entitlement.active_for(user).filter(book=book, ends_at__isnull=True).exists():
            return _err("این کتاب را قبلاً خریده‌اید.", "already_owned")
        quote = book_price_quote(book)
        if quote.product_status != ProductStatus.PAID or quote.price is None:
            return _err("این کتاب برای فروش آماده نیست یا قیمت مشخصی ندارد.", "not_for_sale")
        order = Order.objects.create(
            user=user,
            book=book,
            title=f"خرید کتاب {book.title}",
            amount=quote.price,
            regular_amount=quote.regular_price,
            discount_amount=quote.discount_amount,
            campaign_title_snapshot=quote.campaign.title if quote.campaign else "",
            campaign_id_snapshot=quote.campaign.pk if quote.campaign else None,
            return_channel=return_channel,
        )
    elif plan_id and not book_slug:
        try:
            plan = _plans_on_sale().filter(pk=int(plan_id)).first()
        except (TypeError, ValueError):
            plan = None
        if plan is None:
            return _err("این طرح فعال نیست.", "invalid_plan")
        major = None
        title = plan.title
        quote = plan_price_quote(plan)
        order = Order.objects.create(
            user=user,
            plan=plan,
            major=major,
            title=title,
            amount=quote.price,
            regular_amount=quote.regular_price,
            discount_amount=quote.discount_amount,
            campaign_title_snapshot=quote.campaign.title if quote.campaign else "",
            campaign_id_snapshot=quote.campaign.pk if quote.campaign else None,
            plan_months=plan.months,
            plan_scope=plan.scope,
            return_channel=return_channel,
        )
    else:
        return _err("کتاب یا طرح اشتراک را انتخاب کنید.", "invalid_request")

    callback = f"{settings.SITE_URL}/api/v1/payments/zibal/callback/"
    try:
        track_id = zibal.request_payment(
            amount_rial=order.amount * 10, order_id=order.id, callback_url=callback, mobile=user.phone, description=order.title
        )
    except zibal.GatewayError:
        log.exception("Zibal request failed for order %s", order.id)
        order.status = Order.Status.FAILED
        order.save(update_fields=["status"])
        return _err("اتصال به درگاه پرداخت ممکن نشد. کمی بعد دوباره تلاش کنید.", "gateway_error", status.HTTP_502_BAD_GATEWAY)
    order.track_id = track_id
    order.save(update_fields=["track_id"])
    return Response({"order_id": order.id, "amount": order.amount, "pay_url": zibal.start_url(track_id)}, status=status.HTTP_201_CREATED)


def _grant(order: Order):
    """Creates the access an order pays for. Called inside the transaction with the user row locked."""
    if order.book_id:
        if Entitlement.active_for(order.user).filter(book_id=order.book_id, ends_at__isnull=True).exists():
            log.warning("Duplicate permanent book payment settled for user=%s book=%s order=%s", order.user_id, order.book_id, order.id)
        return Entitlement.objects.create(user=order.user, book=order.book, order=order)
    now = timezone.now()
    # What was bought, as it was when the order was made (older orders: the plan as it is now).
    months = order.plan_months or order.plan.months
    all_majors = (order.plan_scope or order.plan.scope) == Plan.Scope.ALL
    # Includes renewals bought earlier that start in the future, so stacked purchases chain end to end.
    same_scope = Entitlement.objects.filter(
        user=order.user, is_archived=False, book__isnull=True, all_majors=all_majors, major=order.major
    ).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
    # A renewal starts when the current subscription ends, so no paid days are lost.
    start = max(now, same_scope.aggregate(end=Max("ends_at"))["end"] or now)
    return Entitlement.objects.create(
        user=order.user,
        major=order.major,
        all_majors=all_majors,
        starts_at=start,
        ends_at=start + timedelta(days=DAYS_PER_MONTH * months),
        order=order,
    )


# Zibal verify results that end an order for good. Anything else (e.g. 202 "not paid yet") leaves it pending,
# so a check made before the user finishes paying cannot lose a later payment.
FINAL_FAILURES = {102, 103, 104, 203}
RECHECK_WINDOW = timedelta(hours=2)


def settle(track_id: str) -> Order | None:
    """Verifies a payment with Zibal and, if the paid amount matches, marks the order paid and grants access once."""
    if not settings.PAYMENTS_ENABLED:
        # Switched off (possibly with Zibal's test merchant set): never verify or grant anything.
        return Order.objects.filter(track_id=track_id).first()
    preview = Order.objects.filter(track_id=track_id).values("id", "user_id", "status").first()
    if preview is None:
        return None
    if preview["status"] == Order.Status.PAID:
        return Order.objects.get(pk=preview["id"])

    # External gateway HTTP call must run outside the DB transaction/locks.
    try:
        result = zibal.verify(track_id)
    except zibal.GatewayError:
        log.exception("Zibal verify failed for order %s", preview["id"])
        return Order.objects.filter(pk=preview["id"]).first()  # stays pending; the user can retry the check

    with transaction.atomic():
        # Lock the buyer BEFORE the order (consistent lock order: User -> Order) so two concurrent renewals for
        # the same learner serialize cleanly and stack end-to-end instead of reading the same Max(ends_at).
        Order._meta.get_field("user").related_model.objects.select_for_update().only("pk").get(pk=preview["user_id"])
        order = Order.objects.select_for_update(of=("self",)).select_related("plan", "book", "major", "user").filter(pk=preview["id"]).first()
        if order is None or order.status == Order.Status.PAID:
            return order
        order.gateway_response = result
        paid = result.get("result") in (100, 201) and int(result.get("amount") or 0) == order.amount * 10
        if result.get("result") in (100, 201) and not paid:
            log.error("Amount mismatch on order %s: %s", order.id, result.get("amount"))
        if paid:
            order.status = Order.Status.PAID
            order.paid_at = timezone.now()
            order.ref_number = str(result.get("refNumber") or "")
            order.card_number = str(result.get("cardNumber") or "")[:20]
            order.save()
            _grant(order)
            try:
                # Isolate royalty errors in an inner savepoint so a failure never aborts the paid order transaction.
                with transaction.atomic():
                    from .royalty import calculate_and_save_order_royalty
                    calculate_and_save_order_royalty(order)
            except Exception:
                log.exception("Failed to calculate royalty snapshot for order %s", order.id)
                from apps.catalog.backups import notify_bale_after_commit
                notify_bale_after_commit(
                    f"⚠️ خطا در ثبت سهم استاد سفارش #{order.id} (مبلغ: {order.amount} ت)؛ نیاز به بررسی/جبران",
                    log_label=f"Bale royalty alert for order {order.id}",
                )
            from apps.catalog.backups import notify_bale_after_commit
            from apps.catalog.panel_display import fa_number
            item_title = order.book.title if order.book else (order.plan.title if order.plan else order.title)
            user_desc = f"{order.user.phone}" + (f" ({order.user.full_name})" if getattr(order.user, 'full_name', None) else "")
            msg = (
                f"💳 خرید جدید در لیموپلاس\n"
                f"مبلغ: {fa_number(order.amount)} تومان\n"
                f"عنوان: {item_title}\n"
                f"کاربر: {user_desc}\n"
                f"شماره پیگیری: {order.ref_number or '—'}"
            )
            notify_bale_after_commit(msg, log_label=f"Bale purchase alert for order {order.id}")
        else:
            verified = result.get("result") in (100, 201)
            # Verified but without an amount to compare: stay pending (re-checkable) instead of failing a real payment.
            amount_mismatch = verified and result.get("amount") not in (None, "")
            if verified and not amount_mismatch:
                log.error("Zibal verify without amount for order %s", order.id)
            if amount_mismatch or result.get("result") in FINAL_FAILURES:
                order.status = Order.Status.FAILED
            order.save(update_fields=["status", "gateway_response"])
        return order


@transaction.non_atomic_requests
@require_GET
def zibal_callback(request):
    """Zibal sends the browser here after payment. We verify on the server, then send the user back to the app."""
    from config.links import app_base_url

    track_id = request.GET.get("trackId", "")
    order = settle(track_id) if track_id else None
    paid = bool(order and order.status == Order.Status.PAID)
    if order and order.return_channel == "web":
        base_return = f"{app_base_url().rstrip('/')}/payment-result"
    elif order and order.return_channel == "test":
        base_return = settings.TEST_APP_RETURN_URL
    else:
        base_return = settings.APP_RETURN_URL
    return_url = f"{base_return}?order={order.id if order else ''}&status={'paid' if paid else 'failed'}"
    # No order details here: anyone holding a trackId could open this page. The app shows details after sign-in.
    return render(request, "commerce/payment_result.html", {"paid": paid, "return_url": return_url})


@transaction.non_atomic_requests
@api_view(["GET"])
def order_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    recent = timezone.now() - order.created_at < RECHECK_WINDOW
    if settings.PAYMENTS_ENABLED and order.status != Order.Status.PAID and order.track_id and recent and request.query_params.get("check"):
        if order.status == Order.Status.FAILED and not order.gateway_response.get("result") in (100, 201):
            Order.objects.filter(pk=order.pk, status=Order.Status.FAILED).update(status=Order.Status.PENDING)
        order = settle(order.track_id) or order
    return Response(
        {
            "id": order.id,
            "title": order.title,
            "amount": order.amount,
            "regular_amount": order.regular_amount if order.regular_amount is not None else order.amount,
            "discount_amount": order.discount_amount,
            "campaign_title": order.campaign_title_snapshot,
            "status": order.status,
            "ref_number": order.ref_number,
            "book_slug": order.book.slug if order.book_id else None,
        }
    )


@api_view(["GET"])
def my_purchases(request):
    entitlements = Entitlement.active_for(request.user).select_related("book", "major")
    orders = Order.objects.filter(user=request.user, status=Order.Status.PAID)[:50]
    return Response(
        {
            "active": [_entitlement_payload(e) for e in entitlements],
            "orders": [
                {
                    "id": o.id,
                    "title": o.title,
                    "amount": o.amount,
                    "regular_amount": o.regular_amount if o.regular_amount is not None else o.amount,
                    "discount_amount": o.discount_amount,
                    "campaign_title": o.campaign_title_snapshot,
                    "paid_at": o.paid_at,
                    "ref_number": o.ref_number,
                }
                for o in orders
            ],
        }
    )
