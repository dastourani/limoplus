"""One source of truth for live, time-bounded prices across checkout, the app, the site and campaign banners."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Subquery
from django.db.models.functions import Substr
from django.utils import timezone

from apps.catalog.models import ContentNode
from .models import Plan, SaleCampaign


class ProductStatus:
    """One server-owned classification for book availability and price presentation."""

    UNAVAILABLE = "unavailable"
    COMING_SOON = "coming_soon"
    FREE = "free"
    PREPARING = "preparing"
    UNPRICED = "unpriced"
    PAID = "paid"


@dataclass(frozen=True)
class PriceQuote:
    regular_price: int | None
    price: int | None
    discount_amount: int = 0
    discount_percent: int | float = 0
    campaign: SaleCampaign | None = None
    product_status: str = ProductStatus.UNAVAILABLE
    has_free_sample: bool = False

    @property
    def is_discounted(self) -> bool:
        return self.discount_amount > 0 and self.campaign is not None

    @property
    def product_status_payload(self) -> dict:
        """A complete product presentation contract; clients never infer states from null prices or chapter flags."""
        return {
            "state": self.product_status,
            "preview": (
                "sample"
                if self.product_status in (ProductStatus.PAID, ProductStatus.UNPRICED) and self.has_free_sample
                else "none"
            ),
            "promotion": "discount" if self.product_status == ProductStatus.PAID and self.is_discounted else "none",
        }

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
        return {
            "price": self.price,
            "regular_price": self.regular_price,
            "discount": discount,
            "product_status": self.product_status_payload,
        }


def _percentage(saving: int, regular: int) -> int | float:
    """Round to one decimal, half up, never reporting 100% when the buyer still pays a non-zero price."""
    if saving <= 0 or regular <= 0:
        return 0
    if saving >= regular:
        return 100
    value = (Decimal(saving * 100) / Decimal(regular)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if value >= Decimal("100"):
        return 99
    if value <= Decimal("0"):
        return 0.1
    return int(value) if value == value.to_integral_value() else float(value)


def book_product_status(book: ContentNode, has_public_chapter: bool | None = None) -> str:
    """Classify a book without interpreting a missing price or a free chapter as a free product.

    `ContentNode.is_free` on the book itself is the only whole-book free switch. A free chapter is a preview,
    even when it is the first or only chapter currently published.
    """
    if (
        book.kind != ContentNode.Kind.BOOK
        or book.depth != 1
        or not book.is_published
        or book.is_archived
        or book.is_inbox
    ):
        return ProductStatus.UNAVAILABLE
    if book.is_coming_soon:
        return ProductStatus.COMING_SOON
    if book.is_free:
        return ProductStatus.FREE
    if has_public_chapter is None:
        has_public_chapter = ContentNode.objects.filter(
            path__startswith=book.path,
            kind=ContentNode.Kind.CHAPTER,
            depth=2,
            is_published=True,
            is_archived=False,
            is_inbox=False,
        ).exists()
    if not has_public_chapter:
        return ProductStatus.PREPARING
    if book.price is None or book.price <= 0:
        return ProductStatus.UNPRICED
    return ProductStatus.PAID


def campaign_book_queryset(queryset=None):
    """Books a new sale campaign may target; keep the picker aligned with pricing and validation."""
    queryset = queryset if queryset is not None else ContentNode.objects.all()
    chapter_roots = (
        ContentNode.objects.filter(
            kind=ContentNode.Kind.CHAPTER,
            depth=2,
            is_published=True,
            is_archived=False,
            is_inbox=False,
        )
        .order_by()
        .annotate(book_path=Substr("path", 1, ContentNode.steplen))
        .values("book_path")
    )
    return queryset.filter(
        kind=ContentNode.Kind.BOOK,
        depth=1,
        is_published=True,
        is_archived=False,
        is_inbox=False,
        is_free=False,
        is_coming_soon=False,
        price__gt=0,
        path__in=Subquery(chapter_roots),
    ).order_by("title", "pk")


def _plan_can_be_sold(plan: Plan) -> bool:
    return plan.is_active and plan.scope == Plan.Scope.ALL


def _quote(
    regular_price: int | None,
    campaign: SaleCampaign | None = None,
    product_status: str = ProductStatus.PAID,
    has_free_sample: bool = False,
) -> PriceQuote:
    if regular_price is None:
        return PriceQuote(regular_price=None, price=None, product_status=product_status, has_free_sample=has_free_sample)
    if regular_price <= 0 or campaign is None or campaign.discounted_price <= 0 or campaign.discounted_price >= regular_price:
        return PriceQuote(
            regular_price=regular_price,
            price=regular_price,
            product_status=product_status,
            has_free_sample=has_free_sample,
        )
    saving = regular_price - campaign.discounted_price
    return PriceQuote(
        regular_price=regular_price,
        price=campaign.discounted_price,
        discount_amount=saving,
        discount_percent=_percentage(saving, regular_price),
        campaign=campaign,
        product_status=product_status,
        has_free_sample=has_free_sample,
    )


def book_price_quotes(books, now=None) -> dict[int, PriceQuote]:
    """Resolve book states and campaign prices in batches for shelves and the catalogue."""
    books = list(books)
    if not books:
        return {}
    now = now or timezone.now()
    by_id = {book.pk: book for book in books}
    by_path = {book.path[: ContentNode.steplen]: book.pk for book in books if book.path}
    chapter_roots = set()
    sample_roots = set()
    public_paths = {
        book.path[: ContentNode.steplen]
        for book in books
        if book.path and book.is_published and not book.is_archived and not book.is_inbox
    }
    descendants = []
    if by_path:
        descendants = list(
            ContentNode.objects.filter(kind__in=(ContentNode.Kind.CHAPTER, ContentNode.Kind.SECTION), depth__gte=2)
            .order_by()
            .annotate(book_path=Substr("path", 1, ContentNode.steplen))
            .filter(book_path__in=by_path)
            .values_list("book_path", "path", "kind", "is_free", "is_published", "is_archived", "is_inbox")
        )
        public_paths.update(
            path for _, path, _, _, published, archived, inbox in descendants
            if published and not archived and not inbox
        )
        for book_path, path, kind, is_free, published, archived, inbox in descendants:
            if not published or archived or inbox:
                continue
            depth = len(path) // ContentNode.steplen
            if not all(path[: ContentNode.steplen * level] in public_paths for level in range(1, depth + 1)):
                continue
            if kind == ContentNode.Kind.CHAPTER:
                chapter_roots.add(book_path)
            if is_free:
                sample_roots.add(book_path)
    has_chapter = {pk: path in chapter_roots for path, pk in by_path.items()}
    has_sample = {pk: path in sample_roots for path, pk in by_path.items()}
    statuses = {
        book.pk: book_product_status(book, has_chapter.get(book.pk, False))
        for book in books
    }
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
            book__price__gt=0,
        )
        .select_related("book")
        # If a bad/legacy overlap exists, pick one deterministically; never apply two campaigns together.
        .order_by("book_id", "-starts_at", "-pk")
    )
    campaign_by_id = {}
    for campaign in campaigns:
        book = by_id.get(campaign.book_id)
        if (
            book
            and statuses.get(book.pk) == ProductStatus.PAID
            and campaign.discounted_price < book.price
        ):
            campaign_by_id.setdefault(book.pk, campaign)
    return {
        book.pk: (
            _quote(book.price, campaign_by_id.get(book.pk), statuses[book.pk], has_sample.get(book.pk, False))
            if statuses[book.pk] == ProductStatus.PAID
            else PriceQuote(None, None, product_status=statuses[book.pk], has_free_sample=has_sample.get(book.pk, False))
        )
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
    """A book campaign opens that book's checkout; a plan campaign opens the dedicated subscription screen."""
    if campaign.book_id:
        return f"buy/{campaign.book.slug}"
    if campaign.plan_id:
        return "subscribe"
    return ""


def campaign_banner_links(campaigns) -> dict[int, str]:
    """Resolve links for a banner batch without querying extra books for subscription campaigns."""
    return {campaign.pk: campaign_banner_link(campaign) for campaign in campaigns}


def _campaign_banner_payload(campaign: SaleCampaign, quote: PriceQuote | None, now) -> dict | None:
    """Build a sale-banner payload only from the quote the checkout currently selects."""
    if not campaign.is_active or campaign.starts_at > now or campaign.ends_at <= now or quote is None:
        return None
    if campaign.book_id:
        product = campaign.book
        if quote.product_status != ProductStatus.PAID:
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
        quote = book_price_quote(campaign.book, now=now)
        if quote.product_status != ProductStatus.PAID:
            return None
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
