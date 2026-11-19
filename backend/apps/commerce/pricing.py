"""One source of truth for live, time-bounded prices across checkout, the app, the site and campaign banners."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from apps.catalog.models import ContentNode
from .models import Plan, SaleCampaign


@dataclass(frozen=True)
class PriceQuote:
    regular_price: int | None
    price: int | None
    discount_amount: int = 0
    discount_percent: int | float = 0
    campaign: SaleCampaign | None = None

    @property
    def is_discounted(self) -> bool:
        return self.discount_amount > 0 and self.campaign is not None

    def payload(self) -> dict:
        discount = None
        if self.is_discounted:
            discount = {
                "amount": self.discount_amount,
                "percent": self.discount_percent,
                "starts_at": self.campaign.starts_at,
                "ends_at": self.campaign.ends_at,
                "campaign_title": self.campaign.title,
            }
        return {"price": self.price, "regular_price": self.regular_price, "discount": discount}


def _percentage(saving: int, regular: int) -> int | float:
    """Round to one decimal, half up (not Python's banker rounding), without inventing a whole percent."""
    value = (Decimal(saving * 100) / Decimal(regular)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return int(value) if value == value.to_integral_value() else float(value)


def _book_can_be_sold(book: ContentNode) -> bool:
    return (
        book.kind == ContentNode.Kind.BOOK
        and book.depth == 1
        and book.is_published
        and not book.is_archived
        and not book.is_free
        and not book.is_inbox
        and not book.is_coming_soon
    )


def _plan_can_be_sold(plan: Plan) -> bool:
    return plan.is_active and plan.scope == Plan.Scope.ALL


def _quote(regular_price: int | None, campaign: SaleCampaign | None = None) -> PriceQuote:
    if regular_price is None:
        return PriceQuote(regular_price=None, price=None)
    if regular_price <= 0 or campaign is None or campaign.discounted_price <= 0 or campaign.discounted_price >= regular_price:
        return PriceQuote(regular_price=regular_price, price=regular_price)
    saving = regular_price - campaign.discounted_price
    return PriceQuote(
        regular_price=regular_price,
        price=campaign.discounted_price,
        discount_amount=saving,
        discount_percent=_percentage(saving, regular_price),
        campaign=campaign,
    )


def book_price_quotes(books, now=None) -> dict[int, PriceQuote]:
    """Resolve many books in one campaign query; safe for shelves and the catalogue (no per-book query)."""
    books = list(books)
    if not books:
        return {}
    now = now or timezone.now()
    by_id = {book.pk: book for book in books}
    campaigns = (
        SaleCampaign.objects.filter(
            book_id__in=by_id,
            is_active=True,
            starts_at__lte=now,
            ends_at__gt=now,
            book__kind=ContentNode.Kind.BOOK,
            book__depth=1,
            book__is_published=True,
            book__is_archived=False,
            book__is_free=False,
            book__is_inbox=False,
            book__is_coming_soon=False,
        )
        .select_related("book")
        # If a bad/legacy overlap exists, pick one deterministically; never apply two campaigns together.
        .order_by("book_id", "-starts_at", "-pk")
    )
    campaign_by_id = {}
    for campaign in campaigns:
        book = by_id.get(campaign.book_id)
        if book and _book_can_be_sold(book) and book.price and campaign.discounted_price < book.price:
            campaign_by_id.setdefault(book.pk, campaign)
    return {
        book.pk: (_quote(book.price, campaign_by_id.get(book.pk)) if _book_can_be_sold(book) else PriceQuote(None, None))
        for book in books
    }


def plan_price_quotes(plans, now=None) -> dict[int, PriceQuote]:
    """Resolve active all-books plans in one query, keeping the whole plan term as the quoted amount."""
    plans = list(plans)
    if not plans:
        return {}
    now = now or timezone.now()
    by_id = {plan.pk: plan for plan in plans}
    campaigns = (
        SaleCampaign.objects.filter(
            plan_id__in=by_id,
            is_active=True,
            starts_at__lte=now,
            ends_at__gt=now,
            plan__scope=Plan.Scope.ALL,
            plan__is_active=True,
        )
        .select_related("plan")
        .order_by("plan_id", "-starts_at", "-pk")
    )
    campaign_by_id = {}
    for campaign in campaigns:
        plan = by_id.get(campaign.plan_id)
        if plan and _plan_can_be_sold(plan) and plan.price and campaign.discounted_price < plan.price:
            campaign_by_id.setdefault(plan.pk, campaign)
    return {plan.pk: _quote(plan.price, campaign_by_id.get(plan.pk)) for plan in plans}


def book_price_quote(book: ContentNode, now=None) -> PriceQuote:
    return book_price_quotes([book], now=now)[book.pk]


def plan_price_quote(plan: Plan, now=None) -> PriceQuote:
    return plan_price_quotes([plan], now=now)[plan.pk]


def campaign_banner_link(campaign: SaleCampaign) -> str:
    """A book campaign opens that book's checkout; a plan campaign opens an active book's shared offer screen."""
    if campaign.book_id:
        return f"buy/{campaign.book.slug}"
    if campaign.plan_id:
        slug = (
            ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK,
                depth=1,
                is_published=True,
                is_archived=False,
                is_inbox=False,
                is_coming_soon=False,
            )
            .order_by("position", "title", "pk")
            .values_list("slug", flat=True)
            .first()
        )
        return f"buy/{slug}" if slug else ""
    return ""


def campaign_banner_links(campaigns) -> dict[int, str]:
    """Resolve links for a banner batch, querying the shared plan destination only once."""
    campaigns = list(campaigns)
    plan_campaign = next((campaign for campaign in campaigns if campaign.plan_id), None)
    shared_plan_link = campaign_banner_link(plan_campaign) if plan_campaign else ""
    links = {}
    for campaign in campaigns:
        if campaign.book_id:
            links[campaign.pk] = campaign_banner_link(campaign)
        elif campaign.plan_id:
            links[campaign.pk] = shared_plan_link
        else:
            links[campaign.pk] = ""
    return links


def _campaign_banner_payload(campaign: SaleCampaign, quote: PriceQuote | None, now) -> dict | None:
    """Build a sale-banner payload only from the quote the checkout currently selects."""
    if not campaign.is_active or campaign.starts_at > now or campaign.ends_at <= now or quote is None:
        return None
    if campaign.book_id:
        product = campaign.book
        if not _book_can_be_sold(product):
            return None
        kind = "book"
        title = product.title
        months = None
    elif campaign.plan_id:
        product = campaign.plan
        if not _plan_can_be_sold(product):
            return None
        kind = "plan"
        title = product.title
        months = product.months
    else:
        return None
    if not quote.is_discounted or quote.campaign.pk != campaign.pk:
        # If a legacy race or direct ORM write created an overlap, a banner must show only the exact campaign
        # checkout has selected. A stale overlapping banner must never advertise a different payable amount.
        return None
    return {
        "kind": kind,
        "product_title": title,
        "months": months,
        "regular_price": quote.regular_price,
        "price": quote.price,
        "amount": quote.discount_amount,
        "percent": quote.discount_percent,
        "campaign_title": campaign.title,
        "starts_at": campaign.starts_at,
        "ends_at": campaign.ends_at,
    }


def campaign_banner_payload(campaign: SaleCampaign, now=None) -> dict | None:
    """Compact product and price details for a banner attached to the same sale campaign."""
    now = now or timezone.now()
    if not campaign.is_active or campaign.starts_at > now or campaign.ends_at <= now:
        return None
    if campaign.book_id:
        if not _book_can_be_sold(campaign.book):
            return None
        quote = book_price_quote(campaign.book, now=now)
    elif campaign.plan_id:
        if not _plan_can_be_sold(campaign.plan):
            return None
        quote = plan_price_quote(campaign.plan, now=now)
    else:
        return None
    return _campaign_banner_payload(campaign, quote, now)


def campaign_banner_payloads(campaigns, now=None) -> dict[int, dict]:
    """Resolve many sale banners in two quote queries instead of one checkout-price query per banner."""
    now = now or timezone.now()
    campaigns = list(campaigns)
    if not campaigns:
        return {}

    books = {campaign.book_id: campaign.book for campaign in campaigns if campaign.book_id}
    plans = {campaign.plan_id: campaign.plan for campaign in campaigns if campaign.plan_id}
    book_quotes = book_price_quotes(books.values(), now=now)
    plan_quotes = plan_price_quotes(plans.values(), now=now)

    payloads = {}
    for campaign in campaigns:
        quote = book_quotes.get(campaign.book_id) if campaign.book_id else plan_quotes.get(campaign.plan_id)
        payload = _campaign_banner_payload(campaign, quote, now)
        if payload:
            payloads[campaign.pk] = payload
    return payloads
