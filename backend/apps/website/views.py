"""The public website: home, books, a page per book (with sample tests), download, prices, FAQ and the fixed pages.

Plain HTML from Django templates (fast, and readable by search engines); covers and formulas are drawn in the browser
by the app's own code (catalog/limo-preview.js), so they look exactly as in the app. Links to the app go to
settings.APP_URL (the web app's address; the same server by default).
"""
from __future__ import annotations

import json
import random

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.catalog.access import AccessMap
from apps.catalog.drawing import loads as loads_drawing
from apps.catalog.fresh import book_updated_on, formula_macros
from apps.catalog.jalali import jalali_date as fa_date
from apps.catalog.labels import all_labels
from apps.catalog.media import media_urls
from apps.catalog.models import ContentNode, Major
from apps.catalog.views import _book_rating, _book_reviews_data, _prefetch_book_ratings, _teacher_info, free_chapter_summary
from config.links import app_base_url

from .models import FaqItem, SiteNavItem, SitePage, SiteSettings

FA = "۰۱۲۳۴۵۶۷۸۹"
BOOKS_PER_PAGE = 12
PAGE_ORDER = {"terms": 0, "privacy": 1, "protection": 2, "about": 3, "contact": 4}
NAMED_URLS = {"home": "website:home", "books": "website:books", "pricing": "website:pricing", "download": "website:download", "faq": "website:faq"}


def fa(n) -> str:
    return "".join(FA[int(c)] if c.isdigit() else c for c in str(n))


def fa_percent(value: int | float) -> str:
    text = str(value)
    if text.endswith(".0"):
        text = text[:-2]
    return fa(text.replace(".", "٫"))


ORDINALS = {
    1: "اول", 2: "دوم", 3: "سوم", 4: "چهارم", 5: "پنجم", 6: "ششم", 7: "هفتم", 8: "هشتم", 9: "نهم", 10: "دهم",
    11: "یازدهم", 12: "دوازدهم", 13: "سیزدهم", 14: "چهاردهم", 15: "پانزدهم", 16: "شانزدهم", 17: "هفدهم",
    18: "هجدهم", 19: "نوزدهم", 20: "بیستم",
}


def fa_ordinal(number: int) -> str:
    """«فصل اول رایگان»: the chapter's number as a word, like the app's shelf label."""
    return ORDINALS.get(int(number), fa(number))


def free_preview_label(free_chapter: int | None, free_chapters: int, partial_free_chapter: int | None = None) -> str:
    """The book's free-preview label, matching the app's `shelfLabel`:
    one free chapter («فصل اول رایگان»), several («۲ فصل رایگان»), or a section inside chapter N («بخشی از فصل ۱ رایگان»).
    """
    if free_chapters == 1 and free_chapter:
        return f"فصل {fa_ordinal(free_chapter)} رایگان"
    if free_chapters > 1:
        return f"{fa(free_chapters)} فصل رایگان"
    if partial_free_chapter:
        return f"بخشی از فصل {fa(partial_free_chapter)} رایگان"
    return "بخشی رایگان"


def _cover_free_label(book, state: str, preview: str, chapters, access: AccessMap) -> str | None:
    """Free cover ribbon text matching the app/web-app `shelfLabel` for whole-free and preview books."""
    from apps.commerce.pricing import ProductStatus

    if state == ProductStatus.FREE:
        return "کل کتاب رایگان"
    if preview == "sample":
        free_chapter, free_chapters, partial_free_chapter = free_chapter_summary(book, chapters, access)
        return free_preview_label(free_chapter, free_chapters, partial_free_chapter)
    return None


def toman(price: int | None) -> str:
    """«۲۴۹ هزار تومان»."""
    if not price:
        return "رایگان"
    if price >= 1000 and price % 1000 == 0:
        return f"{fa(f'{price // 1000:,}'.replace(',', '٬'))} هزار تومان"
    return f"{fa(f'{price:,}'.replace(',', '٬'))} تومان"


def app_url(path: str = "") -> str:
    base = app_base_url()
    return f"{base}/{path.lstrip('/')}" if path else (base or "/")


def _published():
    return (
        ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_published=True, is_archived=False, is_inbox=False)
        .prefetch_related("majors")
        .order_by("is_coming_soon", "position", "title")
    )


def _cover(request, book) -> str:
    """What the browser needs to draw the cover (the same template as the app's)."""
    major = min(book.majors.all(), key=lambda m: (m.order, m.name), default=None)
    rating, rating_count = _book_rating(request, book)
    data = {
        "title": book.title, "title_en": book.title_en, "author": book.author, "edition": book.edition,
        "motif": book.cover_motif, "drawing": loads_drawing(book.cover_drawing),
        "major": major.name if major else "", "strip": major.color if major else "",
        "image": request.build_absolute_uri(book.cover.url) if book.cover else "",
        "rating": rating,
        "rating_count": rating_count,
    }
    return json.dumps(data, ensure_ascii=False)


def _card(request, book, price_quote=None) -> dict:
    """A book on a shelf of the site: one server-owned status, its current price and free-preview details."""
    from apps.commerce.pricing import ProductStatus, book_price_quote

    price_quote = price_quote or book_price_quote(book)
    access = AccessMap(request.user, book)
    chapters = access.children(book)
    product_status = price_quote.product_status_payload
    state = product_status["state"]

    if state == ProductStatus.COMING_SOON:
        text = f"به‌زودی ({book.release_estimate})" if book.release_estimate else "به‌زودی"
        label = {"kind": "soon", "icon": "bell", "text": text}
    elif state == ProductStatus.PREPARING:
        label = {"kind": "preparing", "icon": "calendar", "text": "در حال برنامه‌ریزی"}
    elif state == ProductStatus.FREE:
        label = {"kind": "free", "icon": "gift", "text": "رایگان"}
    elif state == ProductStatus.PAID:
        label = {"kind": "paid", "icon": "tag", "text": toman(price_quote.price)}
    elif state == ProductStatus.UNPRICED:
        label = {"kind": "unpriced", "icon": "tag", "text": "قیمت تعیین نشده"}
    else:
        label = {"kind": "unpriced", "icon": "lock", "text": "در دسترس نیست"}

    sample_label = _cover_free_label(book, state, product_status["preview"], chapters, access)

    discount = None
    if product_status["promotion"] == "discount":
        discount = {
            "percent": fa_percent(price_quote.discount_percent),
            "saving": toman(price_quote.discount_amount),
            "end_date": fa_date(price_quote.campaign.ends_at),
        }
    return {
        "book": book, "cover": _cover(request, book), "label": label,
        "product_status": product_status,
        "sample_label": sample_label,
        "regular_price": toman(price_quote.regular_price) if state == ProductStatus.PAID else None,
        "discount": discount,
        "chapters": fa(len(chapters)) if chapters else "",
        "release_estimate": book.release_estimate,
        "url": reverse("website:book", args=[book.slug]), "majors": [m.slug for m in book.majors.all()],
    }


def _resolve_nav_url(raw: str) -> tuple[str, str]:
    raw = (raw or "").strip()
    if raw in NAMED_URLS:
        return reverse(NAMED_URLS[raw]), raw
    if raw.startswith("page:"):
        slug = raw.split(":", 1)[1].strip()
        return reverse("website:page", args=[slug]), f"page:{slug}"
    if raw.startswith("/p/") and raw.strip("/").count("/") == 1:
        slug = raw.strip("/").split("/", 1)[1]
        return reverse("website:page", args=[slug]), f"page:{slug}"
    return raw, raw


def _base(request, **extra) -> dict:
    s = SiteSettings.get()
    ordered_pages = sorted(SitePage.objects.all(), key=lambda p: (p.order, PAGE_ORDER.get(p.slug, 9), p.slug))
    nav_name = request.resolver_match.url_name if getattr(request, "resolver_match", None) else ""
    cur_page = extra.get("page")
    cur_key = f"page:{cur_page.slug}" if cur_page else ("books" if nav_name == "book" else nav_name)

    nav_items = []
    seen_targets = set()
    all_nav = list(SiteNavItem.objects.filter(is_hidden=False).order_by("order", "id"))
    by_parent: dict[int | None, list[SiteNavItem]] = {}
    for item in all_nav:
        by_parent.setdefault(item.parent_id, []).append(item)

    for item in by_parent.get(None, []):
        href, key = _resolve_nav_url(item.url or "#")
        seen_targets.add(key)
        children = []
        for sub in by_parent.get(item.id, []):
            s_href, s_key = _resolve_nav_url(sub.url or "#")
            seen_targets.add(s_key)
            children.append({"title": sub.title, "href": s_href, "active": s_key == cur_key})
        active = (key == cur_key) or any(c["active"] for c in children)
        nav_items.append({"title": item.title, "href": href or "#", "active": active, "children": children})

    for p in ordered_pages:
        key = f"page:{p.slug}"
        if p.show_in_nav and key not in seen_targets:
            nav_items.append({"title": p.title, "href": reverse("website:page", args=[p.slug]), "active": key == cur_key, "children": []})

    return {
        "s": s,
        "app_url": app_url(),
        "subscribe_url": app_url("subscribe"),
        "apk": _apk(s),
        "pages": {p.slug: p for p in ordered_pages},
        "footer_pages": [p for p in ordered_pages if p.show_in_footer],
        "nav_items": nav_items,
        "canonical": request.build_absolute_uri(request.path),
        "nav": nav_name,
        # «دستورهای فرمول» and «برچسب‌های متن» for the lesson boxes and formulas the browser draws.
        "macros": formula_macros(),
        "labels": all_labels(),
        **extra,
    }


def _apk(s: SiteSettings) -> dict | None:
    from apps.releases.models import AppRelease

    r = AppRelease.objects.filter(channel=AppRelease.CHANNEL_OFFICIAL, is_published=True).order_by("-build").first()
    if not r:
        if s.apk_url:
            return {"url": s.apk_url, "version": "", "date": None, "date_fa": "", "notes": []}
        return None

    notes = [line.strip().lstrip("-• ").strip() for line in (r.notes or "").splitlines() if line.strip()]
    # Prefer uploaded APK or release link; fall back to s.apk_url if configured
    main_url = r.link or r.link_arm64 or r.link_32 or s.apk_url
    github_fallback = r.download_url if (r.apk and r.download_url) or (main_url != r.download_url and r.download_url) else ""

    return {
        "url": main_url,
        "arm64": r.link_arm64,
        "bit32": r.link_32,
        "github_url": github_fallback,
        "version": r.version_name or fa(r.build),
        "date": r.created_at,
        "date_fa": fa_date(r.created_at),
        "notes": notes,
    }


def _plans():
    from apps.commerce.pricing import plan_price_quotes
    from apps.commerce.views import _plans_on_sale

    plans = list(_plans_on_sale().order_by("order", "price"))
    quotes = plan_price_quotes(plans)
    result = []
    for plan in plans:
        quote = quotes[plan.pk]
        discount = None
        if quote.is_discounted:
            discount = {
                "percent": fa_percent(quote.discount_percent),
                "saving": toman(quote.discount_amount),
                "end_date": fa_date(quote.campaign.ends_at),
            }
        result.append({
            "title": plan.title,
            "price": toman(quote.price),
            "regular_price": toman(quote.regular_price),
            "discount": discount,
            "months": fa(plan.months),
        })
    return result


def _format_sample(q, idx: int, book_node=None, majors=None, request=None, access=None) -> dict:
    src = next(iter(q.questionsource_set.all()), None)
    sign_kw = {"book": book_node, "access": access, "allow_locked_chapters": False}
    stem = media_urls(request, q.stem, **sign_kw) if (request is not None and book_node is not None) else q.stem
    choices = [
        {
            "id": c.id,
            "num": fa(i),
            "text": media_urls(request, c.text, **sign_kw) if (request is not None and book_node is not None) else c.text,
        }
        for i, c in enumerate(q.choices.all(), start=1)
    ]
    return {
        "id": q.id, "number": fa(idx), "stem": stem,
        "section": q.node.title if q.node and q.node.kind == ContentNode.Kind.SECTION else "",
        "book_title": book_node.title if book_node else "",
        "book_url": reverse("website:book", args=[book_node.slug]) if book_node else "",
        "majors": majors or ([m.slug for m in book_node.majors.all()] if book_node else []),
        "choices": choices,
        "source": (f"{src.source.name} {fa(src.source.year)}" if src.source.year else src.source.name) if src else "",
    }


def _book_samples(questions, access, limit: int = 3, book_node=None, request=None) -> list[dict]:
    """Up to `limit` interactive sample questions: `is_sample` first, then automatic fallback to readable questions."""
    from django.contrib.auth.models import AnonymousUser
    from apps.learning.views import _usable

    # Must be readable by an anonymous visitor so `POST /api/v1/questions/<id>/answer/` works on the public site.
    anon_access = AccessMap(AnonymousUser(), access.book)
    picked_ids: set[int] = set()
    out: list[dict] = []
    base_qs = questions.select_related("node").prefetch_related("choices", "questionsource_set__source").order_by("node__path", "order", "id")
    for pool in (base_qs.filter(is_sample=True), base_qs.filter(is_extra=False)):
        for q in pool:
            if q.id in picked_ids:
                continue
            if not (_usable(access, q) and _usable(anon_access, q)):
                continue
            picked_ids.add(q.id)
            out.append(_format_sample(q, len(out) + 1, book_node=book_node or access.book, request=request, access=anon_access))
            if len(out) >= limit:
                return out
    return out


def home(request):
    from django.utils import timezone
    from apps.catalog.models import Banner, BookChange
    from apps.learning.models import Flashcard, Question

    from apps.commerce.pricing import ProductStatus, book_price_quotes, campaign_banner_links, campaign_banner_payloads

    pub_books = list(_published())
    _prefetch_book_ratings(request, pub_books)
    price_quotes = book_price_quotes(pub_books)
    books = [_card(request, b, price_quotes[b.pk]) for b in pub_books]
    majors = Major.objects.filter(books__in=pub_books).distinct().order_by("order", "name")
    paid = [
        price_quotes[b.pk].price
        for b in pub_books
        if price_quotes[b.pk].product_status == ProductStatus.PAID
    ]

    # Live content statistics and a randomized pool of interactive sample questions across all published books.
    active_books = [
        b for b in pub_books
        if price_quotes[b.pk].product_status not in (ProductStatus.COMING_SOON, ProductStatus.PREPARING)
    ]
    total_sections = 0
    visible_ids: list[int] = []
    pool_samples: list[dict] = []
    for b in active_books:
        acc = AccessMap(request.user, b)
        v_ids = acc.visible_ids_under(b)
        visible_ids.extend(v_ids)
        total_sections += sum(1 for n in acc.nodes.values() if n.kind == ContentNode.Kind.SECTION and acc.visible(n.id))
        if len(pool_samples) < 12:
            qs = Question.objects.filter(node_id__in=v_ids, is_archived=False)
            pool_samples.extend(_book_samples(qs, acc, limit=3, book_node=b, request=request))

    random.shuffle(pool_samples)
    home_sample = pool_samples[0] if pool_samples else None

    total_questions = Question.objects.filter(node_id__in=visible_ids, is_archived=False).count() if visible_ids else 0
    total_cards = Flashcard.objects.filter(node_id__in=visible_ids, is_archived=False).count() if visible_ids else 0
    site_stats = [
        (fa(len(active_books)), "کتاب درسی تعاملی"),
        (fa(total_sections), "بخش درسنامه و چکیده"),
        (fa(total_questions), "تست با پاسخ تشریحی"),
        (fa(total_cards), "فلش‌کارت مرور هوشمند"),
    ] if active_books else []

    # Keep editorial news and purchase campaigns in separate sections. Campaign quotes are batched so removing the
    # old four-banner display cap does not turn the home page into one price query per offer.
    now = timezone.now()
    site_settings = SiteSettings.get()
    banner_query = Banner.visible_at(now)
    if not site_settings.show_updates:
        banner_query = banner_query.filter(sale_campaign__isnull=False)
    banner_rows = list(banner_query)
    sale_campaigns = [bn.sale_campaign for bn in banner_rows if bn.sale_campaign_id]
    sale_payloads = campaign_banner_payloads(sale_campaigns, now)
    sale_links = campaign_banner_links(sale_campaigns)
    editorial_banners = []
    offers = []
    for bn in banner_rows:
        if bn.sale_campaign_id:
            sale = sale_payloads.get(bn.sale_campaign_id)
            if not sale:
                continue
            raw_link = sale_links.get(bn.sale_campaign_id, "")
            # A deal with no checkout destination is not actionable, so don't advertise it as a buyable offer.
            if not raw_link:
                continue
            href = raw_link if raw_link.startswith(("http://", "https://")) else (app_url(raw_link) if raw_link else app_url())
            offers.append({
                "title": bn.title,
                "subtitle": bn.subtitle,
                "button": bn.button or "خرید با تخفیف",
                "url": href,
                "image": request.build_absolute_uri(bn.image.url) if bn.image else "",
                "discount": {
                    "product_title": sale["product_title"],
                    "price": toman(sale["price"]),
                    "regular_price": toman(sale["regular_price"]),
                    "percent": fa_percent(sale["percent"]),
                    "end_date": fa_date(sale["ends_at"]),
                },
            })
        elif site_settings.show_updates:
            raw_link = bn.resolved_link()
            href = raw_link if raw_link.startswith(("http://", "https://")) else (app_url(raw_link) if raw_link else app_url())
            editorial_banners.append({
                "title": bn.title,
                "subtitle": bn.subtitle,
                "button": bn.button or "مشاهده",
                "url": href,
            })

    updates = []
    if site_settings.show_updates:
        raw_changes = (
            BookChange.objects.filter(is_hidden=False, book__in=pub_books)
            .select_related("book", "node")
            .order_by("-created_at")[:4]
        )
        updates = [
            {
                "book_title": ch.book.title,
                "book_url": reverse("website:book", args=[ch.book.slug]),
                "place": ch.node.title if ch.node and ch.node_id != ch.book_id else "",
                "text": ch.text,
                "date": fa_date(ch.created_at),
            }
            for ch in raw_changes
        ]

    return render(request, "website/home.html", _base(
        request, books=books[:12], more=len(books) > 12, majors=majors, plans=_plans(),
        min_price=toman(min(paid)) if paid else None,
        site_stats=site_stats, editorial_banners=editorial_banners, offers=offers, updates=updates,
        home_sample=home_sample, home_samples=pool_samples,
        faq=FaqItem.objects.filter(is_hidden=False)[:4],
    ))


def books(request):
    from apps.commerce.pricing import book_price_quotes

    published = _published()
    majors = Major.objects.filter(books__in=published).distinct().order_by("order", "name")
    selected_major = request.GET.get("major", "")
    if selected_major not in set(majors.values_list("slug", flat=True)):
        selected_major = ""

    book_list = published
    if selected_major:
        book_list = book_list.filter(majors__slug=selected_major).distinct()
    paginator = Paginator(book_list, BOOKS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))
    books_on_page = list(page_obj.object_list)
    _prefetch_book_ratings(request, books_on_page)
    quotes = book_price_quotes(books_on_page)
    cards = [_card(request, book, quotes[book.pk]) for book in books_on_page]
    page_summary = ""
    if page_obj.paginator.count:
        page_summary = (
            f"نمایش {fa(page_obj.start_index())} تا {fa(page_obj.end_index())} "
            f"از {fa(page_obj.paginator.count)} کتاب"
        )
    return render(request, "website/books.html", _base(
        request, books=cards, majors=majors, page_obj=page_obj, selected_major=selected_major,
        page_summary=page_summary,
    ))


def book(request, slug):
    b = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, depth=1, slug=slug, is_published=True, is_archived=False, is_inbox=False)
    access = AccessMap(request.user, b)
    if not access.visible(b.id):
        raise Http404
    from apps.learning.models import Flashcard, Question
    from apps.learning.views import _usable

    visible = access.visible_ids_under(b)
    questions = Question.objects.filter(node_id__in=visible, is_archived=False)
    flashcards = Flashcard.objects.filter(node_id__in=visible, is_archived=False)
    from django.db.models import Count

    q_by_node = dict(questions.values("node_id").annotate(n=Count("id")).values_list("node_id", "n"))
    f_by_node = dict(flashcards.values("node_id").annotate(n=Count("id")).values_list("node_id", "n"))
    raw_chapters = access.children(b)
    chapters = []
    for ch_idx, c in enumerate(raw_chapters, start=1):
        sections = access.children(c)
        ids = [c.id, *[s.id for s in sections]]
        ch_tests = sum(q_by_node.get(i, 0) for i in ids)
        ch_cards = sum(f_by_node.get(i, 0) for i in ids)
        sec_items = []
        for idx, s in enumerate(sections, start=1):
            sq = q_by_node.get(s.id, 0)
            sf = f_by_node.get(s.id, 0)
            s_free = access.readable(s.id)
            sec_items.append({
                "id": s.id, "title": s.title, "number": fa(idx),
                "has_summary": bool(s.summary_body),
                "tests": fa(sq) if sq else "", "cards": fa(sf) if sf else "",
                "free": s_free, "url": app_url(f"section/{s.id}") if s_free else app_url(f"buy/{b.slug}"),
            })
        chapters.append({
            "id": c.id, "title": c.title, "number": fa(ch_idx),
            "order": ch_idx,
            "section_count": len(sections),
            "sections": fa(len(sections)), "tests": fa(ch_tests) if ch_tests else "", "cards": fa(ch_cards) if ch_cards else "",
            "free": bool(b.is_free or c.is_free),
            "chapter_free": bool(b.is_free or c.is_free),
            "sample_free": bool(b.is_free or c.is_free or any(section.is_free for section in sections)),
            "has_overview": bool(c.full_body.strip()),
            "overview_url": app_url(f"section/{c.id}") if access.readable(c.id) else app_url(f"buy/{b.slug}"),
            "section_list": sec_items,
        })
    first_free = next((ch for ch in chapters if ch["sample_free"]), None)
    sample_list = _book_samples(questions, access, limit=3, book_node=b, request=request)
    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)]
    q_total = questions.count()
    f_total = flashcards.count()
    stats = [
        (fa(len(chapters)), "فصل"), (fa(len(sections)), "بخش"), (fa(q_total), "تست"),
        (fa(f_total), "فلش‌کارت"),
    ]
    about_text = media_urls(request, (b.about or "").strip(), book=b, access=access, allow_locked_chapters=False)
    if not about_text and chapters:
        parts = [f"کتاب **{b.title}** در **{fa(len(chapters))} فصل** و **{fa(len(sections))} بخش** تدوین شده"]
        if q_total:
            parts.append(f"همراه با **{fa(q_total)} تست طبقه‌بندی‌شده با پاسخ تشریحی**")
        if f_total:
            parts.append(f"و **{fa(f_total)} فلش‌کارت مرور هوشمند**")
        about_text = "، ".join(parts) + " است.\n\n" + "\n".join(f"- فصل {ch['number']}: {ch['title']}" for ch in chapters[:8])
    from apps.commerce.pricing import ProductStatus, book_price_quote, book_price_quotes

    price_quote = book_price_quote(b)
    product_status = price_quote.product_status_payload
    state = product_status["state"]
    is_preparing = state in (ProductStatus.COMING_SOON, ProductStatus.PREPARING)
    sample_label = _cover_free_label(b, state, product_status["preview"], raw_chapters, access)
    related_books = []
    if is_preparing:
        other = [x for x in _published() if x.id != b.id and not x.is_coming_soon][:6]
        _prefetch_book_ratings(request, [b, *other])
        other_quotes = book_price_quotes(other)
        related_books = [_card(request, item, other_quotes[item.pk]) for item in other]
    else:
        _prefetch_book_ratings(request, [b])
    author_profile = _teacher_info(b, request)
    raw_reviews = _book_reviews_data(b, request.user)
    community_reviews = {
        "average_rating": raw_reviews["average_rating"],
        "average_rating_fa": fa_percent(raw_reviews["average_rating"]) if raw_reviews["average_rating"] is not None else "",
        "satisfaction_rate": raw_reviews["satisfaction_rate"],
        "satisfaction_rate_fa": fa(raw_reviews["satisfaction_rate"]) if raw_reviews["satisfaction_rate"] is not None else "",
        "serious_readers_rating": raw_reviews["serious_readers_rating"],
        "serious_readers_rating_fa": fa_percent(raw_reviews["serious_readers_rating"]) if raw_reviews["serious_readers_rating"] is not None else "",
        "total_count": raw_reviews["total_count"],
        "total_count_fa": fa(raw_reviews["total_count"]),
        "reviews": [
            {
                **item,
                "study_percent_fa": fa(item["study_percent"]),
                "test_percent_fa": fa(item["test_percent"]),
                "created_at_fa": fa(item["created_at"]),
            }
            for item in raw_reviews["reviews"]
        ],
    }
    book_discount = None
    if product_status["promotion"] == "discount":
        book_discount = {
            "percent": fa_percent(price_quote.discount_percent),
            "saving": toman(price_quote.discount_amount),
            "end_date": fa_date(price_quote.campaign.ends_at),
        }
    upd = book_updated_on(b)
    return render(request, "website/book.html", _base(
        request, b=b, cover=_cover(request, b), majors=list(b.majors.all()), chapters=chapters, stats=[s for s in stats if s[0] != "۰"],
        samples=sample_list, samples_json=json.dumps(sample_list, ensure_ascii=False), first_free=first_free,
        product_status=product_status,
        sample_label=sample_label,
        price=toman(price_quote.price) if state == ProductStatus.PAID else None,
        regular_price=toman(price_quote.regular_price) if state == ProductStatus.PAID else None,
        discount=book_discount,
        open_url=app_url(f"book/{b.slug}"), buy_url=app_url(f"buy/{b.slug}"),
        about=about_text, updated_on=fa_date(upd) if upd else "",
        is_preparing=is_preparing, release_estimate=b.release_estimate, related_books=related_books,
        author_profile=author_profile, community_reviews=community_reviews,
    ))


def download(request):
    return render(request, "website/download.html", _base(request))


def pricing(request):
    from apps.commerce.pricing import ProductStatus, book_price_quotes

    books = list(_published())
    quotes = book_price_quotes(books)
    paid = [quotes[b.pk].price for b in books if quotes[b.pk].product_status == ProductStatus.PAID]
    return render(request, "website/pricing.html", _base(
        request, plans=_plans(), min_price=toman(min(paid)) if paid else None, faq=FaqItem.objects.filter(is_hidden=False)[:6],
    ))


def faq(request):
    return render(request, "website/faq.html", _base(request, faq=FaqItem.objects.filter(is_hidden=False)))


def page(request, slug):
    p = SitePage.objects.filter(slug=slug).first()
    if not p:
        raise Http404
    return render(request, "website/page.html", _base(
        request, page=p, body=simple_text(p.body),
        updated_on=fa_date(p.updated_at),
        important_on=fa_date(p.important_at) if p.important_at else "",
    ))


def simple_text(body: str) -> str:
    """The panel's plain text as HTML: blank lines between paragraphs, «## » headings, «- » lists. Everything escaped."""
    out, items = [], []

    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for block in (body or "").replace("\r", "").split("\n\n"):
        for line in block.split("\n"):
            t = line.strip()
            if not t:
                continue
            if t.startswith("- "):
                items.append(escape(t[2:]))
                continue
            flush()
            out.append(f"<h2>{escape(t[3:])}</h2>" if t.startswith("## ") else f"<p>{escape(t)}</p>")
        flush()
    return mark_safe("".join(out))


def robots(request):
    sitemap = request.build_absolute_uri(reverse("website:sitemap"))
    return HttpResponse(f"User-agent: *\nDisallow: /{settings.ADMIN_URL}\nDisallow: /api/\nSitemap: {sitemap}\n", content_type="text/plain")


def sitemap(request):
    urls = [reverse(f"website:{n}") for n in ("home", "books", "download", "pricing", "faq")]
    urls += [reverse("website:book", args=[b.slug]) for b in _published().filter(~Q(slug=""))]
    urls += [reverse("website:page", args=[p.slug]) for p in SitePage.objects.all()]
    body = "".join(f"<url><loc>{escape(request.build_absolute_uri(u))}</loc></url>" for u in urls)
    return HttpResponse(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
                        content_type="application/xml")
