import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.catalog.models import ContentNode, Major

from . import zibal
from .models import Entitlement, Order, Plan

log = logging.getLogger(__name__)
DAYS_PER_MONTH = 30


def _err(message, code, http=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code, "message": message}, status=http)


def _book(slug):
    return ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, slug=slug, is_published=True, is_archived=False).first()


def _plan_payload(plan):
    return {"id": plan.id, "title": plan.title, "scope": plan.scope, "months": plan.months, "price": plan.price}


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


@api_view(["GET"])
@permission_classes([AllowAny])
def offers(request):
    """What can be bought to open a book: the book itself and subscription plans for its majors."""
    book = _book(request.query_params.get("book", ""))
    if book is None:
        return _err("کتاب پیدا نشد.", "not_found", status.HTTP_404_NOT_FOUND)
    majors = list(book.majors.filter(is_coming_soon=False))
    plans = Plan.objects.filter(is_active=True)
    return Response(
        {
            "book": {"slug": book.slug, "title": book.title, "price": book.price},
            "majors": [{"slug": m.slug, "name": m.name} for m in majors],
            "plans": [_plan_payload(p) for p in plans if p.scope == Plan.Scope.ALL or majors],
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def plans(request):
    return Response([_plan_payload(p) for p in Plan.objects.filter(is_active=True)])


@api_view(["POST"])
def create_order(request):
    """Creates an order with a server-computed amount and returns the gateway URL. The client never sends prices."""
    user = request.user
    book_slug, plan_id, major_slug = request.data.get("book"), request.data.get("plan"), request.data.get("major")
    if book_slug and not plan_id:
        book = _book(book_slug)
        if book is None or not book.price:
            return _err("این کتاب برای فروش نیست.", "not_for_sale")
        if Entitlement.active_for(user).filter(book=book).exists():
            return _err("این کتاب را قبلاً خریده‌اید.", "already_owned")
        order = Order.objects.create(user=user, book=book, title=f"خرید کتاب {book.title}", amount=book.price)
    elif plan_id and not book_slug:
        try:
            plan = Plan.objects.filter(pk=int(plan_id), is_active=True).first()
        except (TypeError, ValueError):
            plan = None
        if plan is None:
            return _err("این طرح فعال نیست.", "invalid_plan")
        major = None
        if plan.scope == Plan.Scope.MAJOR:
            major = Major.objects.filter(slug=major_slug, is_coming_soon=False).first()
            if major is None:
                return _err("رشته‌ی اشتراک را انتخاب کنید.", "major_required")
        title = f"{plan.title}" + (f" — {major.name}" if major else "")
        order = Order.objects.create(user=user, plan=plan, major=major, title=title, amount=plan.price)
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
    """Creates the access an order pays for. Called inside the transaction that marks the order paid."""
    if order.book_id:
        return Entitlement.objects.create(user=order.user, book=order.book, order=order)
    now = timezone.now()
    # Includes renewals bought earlier that start in the future, so stacked purchases chain end to end.
    same_scope = Entitlement.objects.filter(
        user=order.user, is_archived=False, book__isnull=True, all_majors=order.plan.scope == Plan.Scope.ALL, major=order.major
    ).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
    # A renewal starts when the current subscription ends, so no paid days are lost.
    start = max(now, same_scope.aggregate(end=Max("ends_at"))["end"] or now)
    return Entitlement.objects.create(
        user=order.user,
        major=order.major,
        all_majors=order.plan.scope == Plan.Scope.ALL,
        starts_at=start,
        ends_at=start + timedelta(days=DAYS_PER_MONTH * order.plan.months),
        order=order,
    )


# Zibal verify results that end an order for good. Anything else (e.g. 202 "not paid yet") leaves it pending,
# so a check made before the user finishes paying cannot lose a later payment.
FINAL_FAILURES = {102, 103, 104, 203}
RECHECK_WINDOW = timedelta(hours=2)


def settle(track_id: str) -> Order | None:
    """Verifies a payment with Zibal and, if the paid amount matches, marks the order paid and grants access once."""
    with transaction.atomic():
        order = Order.objects.select_for_update().select_related("plan", "book", "major", "user").filter(track_id=track_id).first()
        if order is None or order.status == Order.Status.PAID:
            return order
        try:
            result = zibal.verify(track_id)
        except zibal.GatewayError:
            log.exception("Zibal verify failed for order %s", order.id)
            return order  # stays pending; the user can retry the check
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
        else:
            amount_mismatch = result.get("result") in (100, 201)
            if amount_mismatch or result.get("result") in FINAL_FAILURES:
                order.status = Order.Status.FAILED
            order.save(update_fields=["status", "gateway_response"])
        return order


@require_GET
def zibal_callback(request):
    """Zibal sends the browser here after payment. We verify on the server, then send the user back to the app."""
    track_id = request.GET.get("trackId", "")
    order = settle(track_id) if track_id else None
    paid = bool(order and order.status == Order.Status.PAID)
    return_url = f"{settings.APP_RETURN_URL}?order={order.id if order else ''}&status={'paid' if paid else 'failed'}"
    # No order details here: anyone holding a trackId could open this page. The app shows details after sign-in.
    return render(request, "commerce/payment_result.html", {"paid": paid, "return_url": return_url})


@api_view(["GET"])
def order_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user)
    recent = timezone.now() - order.created_at < RECHECK_WINDOW
    if order.status != Order.Status.PAID and order.track_id and recent and request.query_params.get("check"):
        if order.status == Order.Status.FAILED and not order.gateway_response.get("result") in (100, 201):
            Order.objects.filter(pk=order.pk, status=Order.Status.FAILED).update(status=Order.Status.PENDING)
        order = settle(order.track_id) or order
    return Response(
        {
            "id": order.id,
            "title": order.title,
            "amount": order.amount,
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
            "orders": [{"id": o.id, "title": o.title, "amount": o.amount, "paid_at": o.paid_at, "ref_number": o.ref_number} for o in orders],
        }
    )
