"""The public website: home, books, a page per book (with sample tests), download, prices, FAQ and the fixed pages.

Plain HTML from Django templates (fast, and readable by search engines); covers and formulas are drawn in the browser
by the app's own code (catalog/limo-preview.js), so they look exactly as in the app. Links to the app go to
settings.APP_URL (the web app's address; the same server by default).
"""
from __future__ import annotations

import json

from django.conf import settings
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from apps.catalog.access import AccessMap
from apps.catalog.drawing import loads as loads_drawing
from apps.catalog.fresh import formula_macros
from apps.catalog.models import ContentNode, Major

from .models import FaqItem, SitePage, SiteSettings

FA = "۰۱۲۳۴۵۶۷۸۹"


def fa(n) -> str:
    return "".join(FA[int(c)] if c.isdigit() else c for c in str(n))


def toman(price: int | None) -> str:
    """«۲۴۹ هزار تومان»."""
    if not price:
        return "رایگان"
    if price >= 1000 and price % 1000 == 0:
        return f"{fa(f'{price // 1000:,}'.replace(',', '٬'))} هزار تومان"
    return f"{fa(f'{price:,}'.replace(',', '٬'))} تومان"


def app_url(path: str = "") -> str:
    base = getattr(settings, "APP_URL", "/").rstrip("/")
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
    data = {
        "title": book.title, "title_en": book.title_en, "author": book.author, "edition": book.edition,
        "motif": book.cover_motif, "drawing": loads_drawing(book.cover_drawing),
        "major": major.name if major else "", "strip": major.color if major else "",
        "image": request.build_absolute_uri(book.cover.url) if book.cover else "",
    }
    return json.dumps(data, ensure_ascii=False)


def _card(request, book) -> dict:
    """A book on a shelf of the site: cover, link, and the one label under it (option «ب» of the app)."""
    access = AccessMap(request.user, book)
    chapters = access.children(book)
    free = sum(1 for c in chapters if c.is_free)
    if book.is_coming_soon:
        label = {"kind": "soon", "icon": "bell", "text": "به‌زودی"}
    elif not book.price or (chapters and free == len(chapters)) or book.is_free:
        label = {"kind": "free", "icon": "gift", "text": "رایگان"}
    else:
        label = {"kind": "paid", "icon": "tag", "text": toman(book.price)}
    return {"book": book, "cover": _cover(request, book), "label": label,
            "url": reverse("website:book", args=[book.slug]), "majors": [m.slug for m in book.majors.all()]}


def _base(request, **extra) -> dict:
    s = SiteSettings.get()
    return {
        "s": s,
        "app_url": app_url(),
        "apk": _apk(s),
        "pages": {p.slug: p for p in SitePage.objects.all()},
        "canonical": request.build_absolute_uri(request.path),
        # «دستورهای فرمول» for the formulas the browser draws.
        "macros": formula_macros(),
        **extra,
    }


def _apk(s: SiteSettings) -> dict | None:
    if s.apk_url:
        return {"url": s.apk_url, "version": "", "date": None}
    from apps.releases.models import AppRelease

    r = AppRelease.objects.filter(is_published=True).order_by("-build").first()
    return {"url": r.download_url, "version": r.version_name or fa(r.build), "date": r.created_at} if r else None


def _plans():
    from apps.commerce.views import _plans_on_sale

    return [{"title": p.title, "price": toman(p.price), "months": fa(p.months)} for p in _plans_on_sale().order_by("order", "price")]


def home(request):
    books = [_card(request, b) for b in _published()]
    majors = Major.objects.filter(books__in=[c["book"] for c in books]).distinct().order_by("order", "name")
    paid = [c["book"].price for c in books if c["book"].price and not c["book"].is_coming_soon]
    return render(request, "website/home.html", _base(
        request, books=books[:12], more=len(books) > 12, majors=majors, plans=_plans(),
        min_price=toman(min(paid)) if paid else None,
    ))


def books(request):
    cards = [_card(request, b) for b in _published()]
    majors = Major.objects.filter(books__in=[c["book"] for c in cards]).distinct().order_by("order", "name")
    return render(request, "website/books.html", _base(request, books=cards, majors=majors))


def book(request, slug):
    b = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, depth=1, slug=slug, is_published=True, is_archived=False, is_inbox=False)
    access = AccessMap(request.user, b)
    if not access.visible(b.id):
        raise Http404
    from apps.learning.models import Flashcard, Question
    from apps.learning.views import _usable

    visible = access.visible_ids_under(b)
    questions = Question.objects.filter(node_id__in=visible, is_archived=False)
    chapters = []
    for c in access.children(b):
        sections = access.children(c)
        ids = [c.id, *[s.id for s in sections]]
        chapters.append({
            "title": c.title, "number": fa(c.position or len(chapters) + 1), "sections": fa(len(sections)),
            "tests": fa(questions.filter(node_id__in=ids).count()), "free": access.readable(c.id),
        })
    first_free = next((ch for ch in chapters if ch["free"]), None)
    samples = (
        questions.filter(is_sample=True).select_related("node").prefetch_related("choices", "questionsource_set__source")
        .order_by("node__path", "order", "id")
    )
    sample_list = []
    for q in samples:
        if not _usable(access, q):
            continue
        src = next(iter(q.questionsource_set.all()), None)
        sample_list.append({
            "id": q.id, "stem": q.stem, "choices": [{"id": c.id, "text": c.text} for c in q.choices.all()],
            "source": (f"{src.source.name} {fa(src.source.year)}" if src.source.year else src.source.name) if src else "",
        })
        if len(sample_list) >= 3:
            break
    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)]
    stats = [
        (fa(len(chapters)), "فصل"), (fa(len(sections)), "بخش"), (fa(questions.count()), "تست"),
        (fa(Flashcard.objects.filter(node_id__in=visible, is_archived=False).count()), "فلش‌کارت"),
    ]
    return render(request, "website/book.html", _base(
        request, b=b, cover=_cover(request, b), majors=list(b.majors.all()), chapters=chapters, stats=[s for s in stats if s[0] != "۰"],
        samples=sample_list, samples_json=json.dumps(sample_list, ensure_ascii=False), first_free=first_free,
        price=toman(b.price) if b.price else None, open_url=app_url(f"book/{b.slug}"), buy_url=app_url(f"buy/{b.slug}"),
        about=b.about,
    ))


def download(request):
    return render(request, "website/download.html", _base(request))


def pricing(request):
    paid = [b.price for b in _published() if b.price and not b.is_coming_soon]
    return render(request, "website/pricing.html", _base(
        request, plans=_plans(), min_price=toman(min(paid)) if paid else None, faq=FaqItem.objects.filter(is_hidden=False)[:6],
    ))


def faq(request):
    return render(request, "website/faq.html", _base(request, faq=FaqItem.objects.filter(is_hidden=False)))


def page(request, slug):
    p = SitePage.objects.filter(slug=slug).first()
    if not p:
        raise Http404
    return render(request, "website/page.html", _base(request, page=p, body=simple_text(p.body)))


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
