from django.conf import settings
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .access import AccessMap
from .fresh import book_updated_on, formula_macros, section_badges
from .drawing import loads as loads_drawing
from .importer import MEDIA_PREFIX
from .labels import all_labels
from .media import media_urls
from .numbering import fa, numbering_for
from .models import Banner, ContentNode, Major, ShareSettings

NOT_FOUND = {"code": "not_found", "message": "پیدا نشد."}


def locked_response(book):
    from apps.commerce.pricing import book_price_quote

    return Response(
        {
            "code": "locked",
            "message": "این بخش در نسخه‌ی کامل کتاب است.",
            "book": {
                "slug": book.slug,
                "title": book.title,
                "single_sale_only": bool(getattr(book, "single_sale_only", False)),
                **book_price_quote(book).payload(),
            },
        },
        status=status.HTTP_403_FORBIDDEN,
    )


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def majors(request):
    return Response(
        [{"slug": m.slug, "name": m.name, "color": m.color, "is_coming_soon": m.is_coming_soon} for m in Major.objects.all()]
    )


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def major_books(request, slug):
    from .access import active_rows

    major = get_object_or_404(Major, slug=slug)
    books = list(
        ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, majors=major, is_published=True, is_archived=False)
        .prefetch_related("majors")
        .order_by("is_coming_soon", F("position").asc(nulls_last=True), "title")
    )
    from apps.commerce.pricing import book_price_quotes

    entitlements = active_rows(request.user)
    prices = book_price_quotes(books)
    _prefetch_user_rows(request)
    _prefetch_book_ratings(request, books)
    maps = AccessMap.bulk_for_books(request.user, books, entitlements=entitlements, card_only=True)
    return Response([book_card(request, book, maps[book.pk], prices[book.pk]) for book in books])


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def all_books(request):
    """Every book, for a learner who hasn't picked a major yet. Each carries its first major (for the cover)."""
    from .access import active_rows

    books = list(
        ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_published=True, is_archived=False, majors__isnull=False)
        .prefetch_related("majors")
        .distinct()
        .order_by("is_coming_soon", F("position").asc(nulls_last=True), "title")
    )
    from apps.commerce.pricing import book_price_quotes

    entitlements = active_rows(request.user)
    prices = book_price_quotes(books)
    _prefetch_user_rows(request)
    _prefetch_book_ratings(request, books)
    maps = AccessMap.bulk_for_books(request.user, books, entitlements=entitlements, card_only=True)
    payload = []
    for book in books:
        major = min(book.majors.all(), key=lambda m: (m.order, m.name), default=None)
        card = book_card(request, book, maps[book.pk], prices[book.pk])
        card["major"] = {"slug": major.slug, "name": major.name, "color": major.color} if major else None
        payload.append(card)
    return Response(payload)


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def shelves(request):
    """The home page: one row per active shelf (set in the panel), then the published books on no shelf, so none is hidden."""
    from .models import Shelf, ShelfBook

    from .access import active_rows

    published = {
        b.id: b
        for b in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_published=True, is_archived=False).prefetch_related("majors")
    }
    # Read once for all the books: the learner's entitlements, finished sections and «خبرم کن» rows.
    entitlements = active_rows(request.user)
    private_books = []
    if request.user.is_authenticated:
        from apps.commerce.models import Entitlement

        private_ids = Entitlement.active_for(request.user).filter(
            group_access_member__status="active",
            book__kind=ContentNode.Kind.BOOK,
            book__depth=1,
            book__is_published=False,
            book__is_archived=False,
            book__is_inbox=False,
        ).values("book_id")
        private_books = list(
            ContentNode.objects.filter(pk__in=private_ids)
            .prefetch_related("majors")
            .order_by("title", "pk")
        )
    all_home_books = [*published.values(), *private_books]
    from apps.commerce.pricing import book_price_quotes

    prices = book_price_quotes(all_home_books)
    _prefetch_user_rows(request)
    _prefetch_book_ratings(request, all_home_books)
    maps = AccessMap.bulk_for_books(request.user, all_home_books, entitlements=entitlements, card_only=True)
    cards: dict[int, dict] = {}

    def card(book):
        if book.id not in cards:
            cards[book.id] = book_card(request, book, maps[book.id], prices[book.pk])
        return cards[book.id]

    active_shelves = list(Shelf.objects.filter(is_active=True).order_by("order", "id"))
    by_shelf: dict[int, list[int]] = {}
    if active_shelves:
        for sb in ShelfBook.objects.filter(shelf_id__in=[s.id for s in active_shelves]).order_by("order", "id"):
            if sb.book_id in published:
                by_shelf.setdefault(sb.shelf_id, []).append(sb.book_id)

    rows, placed = [], set()
    for shelf in active_shelves:
        ids = by_shelf.get(shelf.id, [])
        if ids:
            rows.append({"id": shelf.id, "title": shelf.title, "books": [card(published[i]) for i in ids]})
            placed.update(ids)
    rest = sorted((b for i, b in published.items() if i not in placed), key=lambda b: (b.is_coming_soon, b.position or 9999, b.title))
    if rest:
        rows.append({"id": None, "title": "کتاب‌های دیگر" if rows else "همه‌ی کتاب‌ها", "books": [card(b) for b in rest]})
    if private_books:
        rows.append({"id": -1, "title": "کتاب‌های دسترسی گروهی", "books": [card(b) for b in private_books]})
    return Response(rows)


def free_chapter_summary(book, chapters, access) -> tuple[int | None, int, int | None]:
    """Return `(free_chapter, free_chapters, partial_free_chapter)` using the visible tree in `access`."""
    free_chapter = next((i for i, c in enumerate(chapters, start=1) if c.is_free), None)
    free_chapters = len(chapters) if book.is_free else sum(1 for c in chapters if c.is_free)
    partial_free_chapter = (
        None
        if book.is_free or free_chapter is not None
        else next(
            (i for i, c in enumerate(chapters, start=1) if any(s.is_free for s in access.children(c))),
            None,
        )
    )
    return free_chapter, free_chapters, partial_free_chapter


def _site_settings(request=None):
    if request is not None:
        cached = getattr(request, "_limo_site_settings", None)
        if cached is not None:
            return cached
    from apps.website.models import SiteSettings

    s = SiteSettings.get()
    if request is not None:
        request._limo_site_settings = s
    return s


def resolve_release_notes(book, state: str, request=None, site_settings=None) -> tuple[str, str]:
    """Return `(detail_note, hover_note)` for `preparing` and `coming_soon` books.

    Priority:
    1) Book-level `book.release_note` (if filled in the book's panel form).
    2) Global defaults on `SiteSettings` (`preparing_hover_note`, `preparing_note`, `coming_soon_note`).
    3) Built-in model defaults.
    """
    from apps.commerce.pricing import ProductStatus
    from apps.website.models import SiteSettings

    if state not in (ProductStatus.PREPARING, ProductStatus.COMING_SOON):
        return "", ""
    custom = (getattr(book, "release_note", "") or "").strip()
    if custom:
        first_line = next((line.strip() for line in custom.splitlines() if line.strip()), custom)
        hover = first_line if len(first_line) <= 110 else first_line[:107].rstrip() + "…"
        return custom, hover
    s = site_settings or _site_settings(request)
    if state == ProductStatus.PREPARING:
        detail = (s.preparing_note or "").strip() or SiteSettings.DEFAULT_PREPARING_NOTE
        hover = (s.preparing_hover_note or "").strip() or SiteSettings.DEFAULT_PREPARING_HOVER_NOTE
        return detail, hover
    detail = (s.coming_soon_note or "").strip() or SiteSettings.DEFAULT_COMING_SOON_NOTE
    return detail, detail


def book_card(request, book, access, price_quote=None) -> dict:
    """What a shelf needs to draw a book: its cover, current campaign price and the reader's progress."""
    if price_quote is None:
        from apps.commerce.pricing import book_price_quote

        price_quote = book_price_quote(book)
    chapters = access.children(book)
    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)]
    # «تمام شد» sections (read, and enough of their questions answered) make the progress.
    from apps.study.progress import section_states

    done = section_states(request.user, access, request)[1] & {s.id for s in sections}
    free_chapter, free_chapters, partial_free_chapter = free_chapter_summary(book, chapters, access)
    release_note, _ = resolve_release_notes(book, price_quote.product_status, request=request)
    major = min(book.majors.all(), key=lambda m: (m.order, m.name), default=None)
    return {
        "slug": book.slug,
        "title": book.title,
        "title_en": book.title_en,
        # The cover's small label and colour come from the book's first major (set in the panel).
        "major": {"slug": major.slug, "name": major.name, "color": major.color} if major else None,
        "author": book.author,
        "edition": book.edition,
        "motif": book.cover_motif,
        "drawing": loads_drawing(book.cover_drawing),
        "cover": request.build_absolute_uri(book.cover.url) if book.cover else None,
        "is_coming_soon": book.is_coming_soon,
        "release_estimate": book.release_estimate,
        "release_note": release_note,
        **price_quote.payload(),
        "chapter_count": len(chapters),
        "section_count": len(sections),
        "has_free_part": any(n.is_free for n in access.nodes.values() if access.visible(n.id)),
        "free_chapter": free_chapter,
        # On a paid product these describe free previews only; only the book-level flag means the whole book is free.
        "free_chapters": free_chapters,
        "partial_free_chapter": partial_free_chapter,
        # Kept for older app builds; it now means exactly the explicit whole-book flag, never inferred from chapters.
        "all_free": book.is_free,
        "single_sale_only": bool(getattr(book, "single_sale_only", False)),
        "owned": access.owned,
        "access": access.access,
        "progress": round(len(done) / len(sections), 3) if done and sections else None,
        "rating": (rating := _book_rating(request, book))[0],
        "rating_count": rating[1],
        **_notify(request.user, book, request),
    }


def _prefetch_book_ratings(request, books) -> None:
    """Batch-fetch approved reader rating averages and counts in one query so shelf/list endpoints stay O(1) queries."""
    from django.db.models import Avg

    from .models import BookOpinion

    existing = getattr(request, "_limo_ratings", None)
    ratings: dict[int, tuple[float | None, int]] = dict(existing) if existing is not None else {}
    book_ids = [b.id for b in books if b.id not in ratings]
    if book_ids:
        for book_id in book_ids:
            ratings[book_id] = (None, 0)
        rows = (
            BookOpinion.objects.filter(book_id__in=book_ids, status=BookOpinion.Status.APPROVED)
            .values("book_id")
            .annotate(avg=Avg("rating"), count=Count("id"))
        )
        for row in rows:
            if row["count"] and row["avg"] is not None:
                ratings[row["book_id"]] = (round(float(row["avg"]), 1), row["count"])
    request._limo_ratings = ratings


def _book_rating(request, book) -> tuple[float | None, int]:
    cached = getattr(request, "_limo_ratings", None) if request is not None else None
    if cached is not None:
        return cached.get(book.id, (None, 0))
    from django.db.models import Avg

    from .models import BookOpinion

    agg = BookOpinion.objects.filter(book=book, status=BookOpinion.Status.APPROVED).aggregate(
        avg=Avg("rating"), count=Count("id")
    )
    count = agg["count"] or 0
    if not count or agg["avg"] is None:
        return (None, 0)
    return (round(float(agg["avg"]), 1), count)


def _prefetch_user_rows(request) -> None:
    """For a page of many books: the learner's finished sections and waitlist rows in two queries, not two per book."""
    user = request.user
    if not user.is_authenticated:
        return
    from apps.study.models import SectionProgress

    from .models import BookWaitlist

    done: dict[int, list[int]] = {}
    for book_id, node_id in SectionProgress.objects.filter(user=user, is_done=True).values_list("book_id", "node_id"):
        done.setdefault(book_id, []).append(node_id)
    request._limo_done = done
    request._limo_wait = {w.book_id: w for w in BookWaitlist.objects.filter(user=user)}


def _notify(user, book, request=None) -> dict:
    if not user.is_authenticated:
        return {"notify": False, "notify_can_cancel": False}
    from .models import BookWaitlist

    cached = getattr(request, "_limo_wait", None) if request is not None else None
    wait = cached.get(book.id) if cached is not None else BookWaitlist.objects.filter(user=user, book=book).first()
    return {"notify": bool(wait and wait.is_active), "notify_can_cancel": bool(wait and wait.can_cancel)}


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def book_detail(request, slug):
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book, defer_full_body=True)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    from apps.study.progress import section_states, word_counts

    _states = section_states(request.user, access, request)

    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)]
    counts = {}
    from apps.learning.models import Flashcard, Question

    for model, key in ((Question, "question_count"), (Flashcard, "flashcard_count")):
        rows = model.objects.filter(node_id__in=[s.id for s in sections], is_archived=False).values("node_id").annotate(n=Count("id"))
        for row in rows:
            counts.setdefault(row["node_id"], {})[key] = row["n"]

    badges = section_badges(request.user, sections)

    def summary(node):
        data = {"id": node.id, "slug": node.slug, "kind": node.kind, "title": node.title, "is_locked": not access.readable(node.id)}
        if node.kind == ContentNode.Kind.SECTION:
            data["badge"] = badges.get(node.id)
            data["has_summary"] = bool(node.summary_body)
            data["group"] = node.group
            data["question_count"] = counts.get(node.id, {}).get("question_count", 0)
            data["flashcard_count"] = counts.get(node.id, {}).get("flashcard_count", 0)
        return data

    chapters = []
    for chapter in access.children(book):
        item = summary(chapter)
        # Every chapter opens with its introduction page (its text, if any, its sections and «ادامه»).
        item["has_overview"] = not item["is_locked"]
        item["sections"] = [summary(s) for s in access.children(chapter)]
        # A chapter's practice is its sections': the app shows these as the chapter's «N تست» and decides with them
        # whether to offer «تمرین کل فصل», «آزمون» and «فلش‌کارت». Summed here once, not again in every screen.
        item["question_count"] = sum(s["question_count"] for s in item["sections"])
        item["flashcard_count"] = sum(s["flashcard_count"] for s in item["sections"])
        item["term_count"] = _term_count(access, chapter)
        chapters.append(item)
    community_reviews = _book_reviews_data(book, request.user)
    request._limo_ratings = {
        book.id: (
            (community_reviews["average_rating"], community_reviews["total_count"])
            if community_reviews["total_count"] > 0
            else (None, 0)
        )
    }
    return Response(
        {
            **book_card(request, book, access),
            "about": media_urls(request, book.about, book=book, access=access, allow_locked_chapters=False),
            "majors": list(book.majors.values_list("slug", flat=True)),
            "chapters": chapters,
            # «تمام شد» (green tick) and «خوانده شد» (read, questions still to do).
            "done_ids": sorted(_states[1]),
            "read_ids": sorted(_states[0] - _states[1]),
            "mine": _mine_in_book(request, book),
            "reviews": _reviews_in_book(request, book),
            "sample_count": _sample_count(access, book),
            "share_link": ShareSettings.link_for(book),
            "id": book.id,
            # «مرور فلش‌کارت‌های کتاب»: only cards of finished (green) sections.
            "done_card_count": _done_cards(access, _states[1]).count() if request.user.is_authenticated else 0,
            # «آخرین به‌روزرسانی» and «تغییرات کتاب».
            "updated_on": book_updated_on(book),
            "change_count": book.changes.filter(is_hidden=False).count(),
            # «N از M لغت»: word cards learned (Leitner box 4+), when the book has word cards.
            "words": word_counts(request.user, access, book),
            "author_profile": _teacher_info(book, request),
            "community_reviews": community_reviews,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def book_changes(request, slug):
    """«تغییرات کتاب»: the important updates of a book, newest first."""
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    rows = book.changes.filter(is_hidden=False).select_related("node")[:200]
    return Response({
        "title": book.title,
        "changes": [
            {"id": c.id, "text": c.text, "at": c.created_at,
             "place": c.node.title if c.node and c.node.id != book.id and access.visible(c.node.id) else "",
             "node_id": c.node.id if c.node and c.node.kind == ContentNode.Kind.SECTION and access.visible(c.node.id) else None}
            for c in rows
        ],
    })


@api_view(["GET"])
@permission_classes([AllowAny])
def formula_commands(request):
    """«دستورهای فرمول»: KaTeX macros for every formula (the app keeps them for offline reading)."""
    return Response({"macros": formula_macros()})


def _done_cards(access, done_ids):
    """Flashcards of the sections this learner has finished (green tick), that they may read."""
    from apps.learning.models import Flashcard

    ids = [i for i in done_ids if access.visible(i) and access.readable(i)]
    return Flashcard.objects.filter(node_id__in=ids, is_archived=False)


def _sample_count(access, book) -> int:
    """How many shareable questions of this book the learner can see («تست‌های نمونه»)."""
    from apps.learning.models import Question

    return sum(
        1
        for q in Question.objects.filter(node_id__in=access.visible_ids_under(book), is_sample=True, is_archived=False).only("id", "node_id", "is_free")
        if access.usable(q)
    )


def _reviews_in_book(request, book):
    """Each finished chapter's next review («مرور بعدی: ۶ روز دیگر»), and the book's mixed review."""
    from apps.study.reviews import book_schedule

    return book_schedule(request.user, book) if request.user.is_authenticated else None


def _mine_in_book(request, book):
    """«اشتباه‌هایم در این کتاب» and «آزمون‌هایم از این کتاب»: counts for the book page."""
    if not request.user.is_authenticated:
        return None
    from apps.study.models import ExamAttempt
    from apps.study.views import _notebook_counts

    exams = ExamAttempt.objects.filter(user=request.user, node__path__startswith=book.path, submitted_at__isnull=False).count()
    from apps.study.time import totals

    t = totals(request.user, book)
    # «زمان مطالعه‌ی تو در این کتاب»: exact seconds; the app rounds what it shows.
    return {"mistakes": _notebook_counts(request, book.slug), "exams": exams, "time_seconds": t["seconds"], "chapter_seconds": t["chapters"]}


def _term_count(access, chapter) -> int:
    """How many glossary terms the readable sections of a chapter have («واژه‌های این فصل»)."""
    from .summary import parse_terms

    terms = set()
    for n in access.nodes.values():
        if n.kind == ContentNode.Kind.SECTION and n.path.startswith(chapter.path) and n.summary_body and access.readable(n.id):
            terms.update(t["fa"] for t in parse_terms(n.summary_body))
    return len(terms)


def _practice_counts(access, node) -> dict:
    """«۳ تست، ۰ کارت»: how much there is to practise here, for the buttons that lead to it.

    A section counts its own questions and cards; a chapter counts those of every section under it, because
    «تمرین کل فصل» and «فلش‌کارت» of a chapter gather the whole chapter (learning/views.py does the same with
    `visible_ids_under`). The rule inside is the one `_section_status` uses for «۳ تست باقی است»: only items the
    learner may actually answer. The app hides a button whose count is 0, so a book without tests never offers
    «تست‌ها» and never opens an empty practice screen."""
    from apps.learning.models import Flashcard, Question

    ids = access.visible_ids_under(node)

    def count(model) -> int:
        rows = model.objects.filter(node_id__in=ids, is_archived=False).only("id", "node_id", "is_free")
        return sum(1 for r in rows if access.usable(r))

    return {"question_count": count(Question), "flashcard_count": count(Flashcard)}


@api_view(["GET"])
@permission_classes([AllowAny])
def node_detail(request, node_id):
    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    if not access.readable(node.id):
        return locked_response(access.book)
    ancestors = sorted((n for n in access.nodes.values() if node.path.startswith(n.path) and n.id != node.id), key=lambda n: n.depth)
    parent = ancestors[-1] if ancestors else None
    # The book is read in one line: a chapter's introduction, its sections, then the next chapter's introduction.
    order = reading_order(access)
    if node.id not in order:
        order = [n.id for n in access.children(parent)] if parent else [node.id]
    index = order.index(node.id)
    prev_id = order[index - 1] if index > 0 else None
    next_id = order[index + 1] if index + 1 < len(order) else None
    is_chapter = node.kind == ContentNode.Kind.CHAPTER
    last_in_chapter = (
        node.kind == ContentNode.Kind.SECTION and parent is not None and access.children(parent)[-1:] == [node]
    )
    practice = _practice_counts(access, node)
    return Response(
        {
            "id": node.id,
            "kind": node.kind,
            "title": node.title,
            # A chapter's number is its place in the book (kept in step when chapters are reordered in the panel).
            "breadcrumb": [{"id": a.id, "kind": a.kind, "slug": a.slug, "title": a.title, "number": a.position} for a in ancestors],
            # A chapter's page is its introduction only: no summary of its own.
            "summary": "" if is_chapter else media_urls(request, node.summary_body, book=access.book),
            "full": media_urls(request, node.full_body, book=access.book),
            # The panel's labels: boxes in the notes and parts of the summary (app/src/lib/labels.ts).
            "labels": all_labels(),
            # «مثال ۳-۵»: where this section's numbered boxes start, and the book's [[#names]] (apps/catalog/numbering.py).
            "numbering": numbering_for(access, node),
            "previous_id": prev_id,
            "next_id": next_id,
            # Titles of the neighbours, for the page drawn while turning to them.
            "previous_title": _turn_title(access, prev_id),
            "next_title": _turn_title(access, next_id),
            "updated_at": node.updated_at,
            "chapter_end": _chapter_end(access, node, parent, request) if last_in_chapter else None,
            "status": _section_status(request.user, access, node),
            "intro": _chapter_intro(request, access, node, practice=practice) if is_chapter else None,
            # «به‌روز شده»: the panel marked this text since the learner last read it.
            "badge": section_badges(request.user, [node]).get(node.id),
            "refreshed_at": node.refreshed_at,
            "macros": formula_macros(),
            # The buttons of the bottom bar («تست‌ها», «فلش‌کارت») are hidden when there is nothing to practise.
            **practice,
        }
    )


def reading_order(access) -> list[int]:
    """Every visible chapter and section of the book in reading order: chapter, its sections, next chapter…"""
    order = []
    for chapter in access.children(access.book):
        # A chapter the learner may not open (a paid one with a free section) is not in the way of its free sections.
        if access.readable(chapter.id):
            order.append(chapter.id)
        order.extend(s.id for s in access.children(chapter))
    return order


def _turn_title(access, node_id):
    if node_id is None:
        return None
    n = access.nodes[node_id]
    return f"مقدمه‌ی فصل {n.position}، {n.title}" if n.kind == ContentNode.Kind.CHAPTER and n.position else n.title


def _chapter_intro(request, access, chapter, practice=None):
    """A chapter's introduction page: its number, its sections (each with the learner's state), counts, and where to go on."""
    from apps.study.progress import section_states

    started, done = section_states(request.user, access, request)
    sections = access.children(chapter)
    badges = section_badges(request.user, sections)
    items = [
        {"id": s.id, "title": s.title, "locked": not access.readable(s.id),
         "state": "done" if s.id in done else "read" if s.id in started else "empty", "badge": badges.get(s.id)}
        for s in sections
    ]
    go_on = next((i for i in items if i["state"] != "done" and not i["locked"]), None) or next((i for i in items if not i["locked"]), None)
    counts = practice if practice is not None else _practice_counts(access, chapter)
    return {
        "number": chapter.position,
        "sections": items,
        "questions": counts["question_count"],
        "flashcards": counts["flashcard_count"],
        "continue_id": go_on["id"] if go_on else None,
        "started": any(i["state"] != "empty" for i in items),
    }


def _chapter_end(access, node, chapter, request=None):
    """The last section of a chapter: no dead end. The chapter's summary exam, and the next chapter (or the book's end)."""
    if node.kind != ContentNode.Kind.SECTION or chapter is None or chapter.kind != ContentNode.Kind.CHAPTER:
        return None
    chapters = [c.id for c in access.children(access.book)]
    i = chapters.index(chapter.id) if chapter.id in chapters else -1
    nxt = None
    if 0 <= i < len(chapters) - 1:
        c = access.nodes[chapters[i + 1]]
        # Its introduction comes first (the reading order of the book).
        sections = access.children(c)
        first = c if access.readable(c.id) or not sections else sections[0]
        nxt = {"id": first.id, "chapter_title": c.title, "title": _turn_title(access, first.id), "locked": not access.readable(first.id)}
    # The summary exam it suggests: 10 questions (fewer if the chapter has fewer), with its time from their own estimates.
    from apps.learning.models import Question

    pool = [q for q in Question.objects.filter(node_id__in=access.visible_ids_under(chapter), is_archived=False).only("id", "node_id", "is_free", "estimated_seconds")
            if access.usable(q)]
    count = min(10, len(pool))
    seconds = sum(q.estimated_seconds or 90 for q in sorted(pool, key=lambda q: q.estimated_seconds or 90)[:count])
    from apps.study.progress import chapter_state

    return {"chapter_id": chapter.id, "chapter_title": chapter.title, "chapter_number": chapter.position,
            "book_slug": access.book.slug, "book_title": access.book.title, "next_chapter": nxt,
            "exam_questions": count, "exam_minutes": max(1, round(seconds / 60)) if count else 0,
            # «فصل ۲ را کامل کردی» / «۸ تست مانده» / «به پایان جزوه‌ها رسیدی»; null for a guest.
            "progress": chapter_state(request.user, access, chapter, reading=node.id, request=request) if request is not None else None}


def _section_status(user, access, node):
    """«جزوه خوانده شد؛ ۳ تست باقی است؛ ۲ کارت موعد مرور دارد»: what is left in this section for this learner."""
    if not user.is_authenticated or node.kind != ContentNode.Kind.SECTION:
        return None
    from django.utils import timezone

    from apps.learning.models import Flashcard, Question, QuizAnswer
    from apps.study.models import FlashcardReview, SectionProgress

    from apps.study.progress import core

    usable = [q for q in Question.objects.filter(node=node, is_archived=False).only("id", "node_id", "is_free", "is_extra")
              if access.usable(q)]
    kept = set(core((q.id, q.is_extra) for q in usable))
    questions = [q for q in usable if q.id in kept]
    answered = set(QuizAnswer.objects.filter(user=user, question_id__in=[q.id for q in questions], is_archived=False).values_list("question_id", flat=True))
    cards = list(Flashcard.objects.filter(node=node, is_archived=False).values_list("id", flat=True))
    reviews = dict(FlashcardReview.objects.filter(user=user, flashcard_id__in=cards).values_list("flashcard_id", "due_at"))
    now = timezone.now()
    return {
        "read": SectionProgress.objects.filter(user=user, node=node, is_done=True).exists(),
        "questions": len(questions),
        "questions_left": sum(1 for q in questions if q.id not in answered),
        "cards": len(cards),
        "cards_due": sum(1 for c in cards if c in reviews and reviews[c] <= now),
        "cards_new": sum(1 for c in cards if c not in reviews),
    }


@never_cache
@api_view(["GET"])
@permission_classes([AllowAny])
def banners(request):
    from apps.commerce.pricing import campaign_banner_links, campaign_banner_payloads

    now = timezone.now()
    candidates = list(Banner.visible_at(now))
    # A banner for the readers of one book is shown only to them; the rest go to everyone.
    reading = set()
    if request.user.is_authenticated:
        from apps.study.models import SectionProgress

        reading = set(SectionProgress.objects.filter(user=request.user).values_list("book_id", flat=True))
    eligible = [
        banner for banner in candidates
        if banner.audience_book_id is None or banner.audience_book_id in reading
    ]
    sale_campaigns = [banner.sale_campaign for banner in eligible if banner.sale_campaign_id]
    sale_payloads = campaign_banner_payloads(sale_campaigns, now)
    sale_links = campaign_banner_links(sale_campaigns)
    items = []
    for banner in eligible:
        if banner.sale_campaign_id:
            if not sale_payloads.get(banner.sale_campaign_id) or not sale_links.get(banner.sale_campaign_id):
                continue
        items.append(banner)
        if len(items) == 10:
            break
    Banner.objects.filter(pk__in=[b.pk for b in items]).update(impressions=F("impressions") + 1)
    return Response(
        [
            {
                "id": b.id,
                "title": b.title,
                "subtitle": b.subtitle,
                "image": request.build_absolute_uri(b.image.url) if b.image else None,
                "link": sale_links[b.sale_campaign_id] if b.sale_campaign_id else b.resolved_link(),
                "template": Banner.Template.SALE if b.sale_campaign_id else b.template,
                "button": b.button,
                "motif": b.motif,
                # A linked campaign owns its period; generic banners keep their own optional countdown.
                "ends_at": b.sale_campaign.ends_at if b.sale_campaign_id else (b.ends_at if b.countdown else None),
                "server_now": now,
                "discount": sale_payloads.get(b.sale_campaign_id) if b.sale_campaign_id else None,
                "book": _banner_book(request, b),
            }
            for b in items
        ]
    )


def _banner_book(request, b):
    """The book a «کتاب تازه» banner points at, enough to draw its cover."""
    if b.template != Banner.Template.BOOK or b.target not in (Banner.Target.BOOK, Banner.Target.BUY):
        return None
    book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, slug=b.target_value.strip(), is_published=True, is_archived=False).first()
    if not book:
        return None  # a draft book is never shown, even if a banner points at it
    major = book.majors.order_by("order", "name").first()
    return {
        "title": book.title, "title_en": book.title_en, "author": book.author, "edition": book.edition, "motif": book.cover_motif,
        "drawing": loads_drawing(book.cover_drawing), "cover": request.build_absolute_uri(book.cover.url) if book.cover else None,
        "major": {"name": major.name, "color": major.color} if major else None,
    }


@api_view(["POST"])
@permission_classes([AllowAny])
def banner_click(request, banner_id):
    Banner.objects.filter(pk=banner_id).update(clicks=F("clicks") + 1)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def book_glossary(request, slug):
    """Every term from the review cards of the sections this reader can open, alphabetical, with its section."""
    from .summary import parse_terms

    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    # «واژه‌های این فصل»: ?chapter=<id> keeps the terms of one chapter.
    chapter = access.nodes.get(int(request.query_params["chapter"])) if str(request.query_params.get("chapter", "")).isdigit() else None
    seen, terms = set(), []
    for node in sorted(access.nodes.values(), key=lambda n: n.path):
        if node.kind != ContentNode.Kind.SECTION or not access.readable(node.id) or not node.summary_body:
            continue
        if chapter is not None and not node.path.startswith(chapter.path):
            continue
        for term in parse_terms(node.summary_body):
            key = term["fa"]
            if key in seen:
                continue
            seen.add(key)
            terms.append({**term, "section_id": node.id, "section_title": node.title})
    terms.sort(key=lambda t: t["fa"])
    return Response({"book": book.title, "chapter": chapter.title if chapter else None, "terms": terms})



@api_view(["POST"])
def book_notify(request, slug):
    """«خبرم کن» on or off for a coming-soon book."""
    from .models import BookWaitlist

    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    if not AccessMap(request.user, book).visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    on = bool(request.data.get("on", True))
    wait, created = BookWaitlist.objects.get_or_create(user=request.user, book=book, defaults={"is_active": on})
    if not created and wait.is_active != on:
        if not on and not wait.can_cancel:
            return Response({"notify": True, "can_cancel": False})  # cancelled once already: it stays on
        wait.is_active = on
        if not on:
            wait.cancel_count += 1
        wait.save(update_fields=["is_active", "cancel_count", "updated_at"])
    return Response({"notify": wait.is_active, "can_cancel": wait.can_cancel})


@api_view(["GET"])
@permission_classes([AllowAny])
def node_boxes(request, node_id):
    """«کادرهای کتاب»: every box of one label (all definitions, all traps…) in a book or chapter, in reading order,
    with its number («مثال ۳-۵») and section. Without ?label: the labels used, with counts."""
    from .numbering import numbered_names, section_boxes

    node = get_object_or_404(ContentNode, pk=node_id)
    access = AccessMap(request.user, node)
    if not access.visible(node.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    wanted = request.query_params.get("label", "")
    numbered = numbered_names()
    chapters = [node] if node.kind == ContentNode.Kind.CHAPTER else access.children(node) if node.kind == ContentNode.Kind.BOOK else []
    counts, boxes, locked = {}, [], 0
    for chapter in chapters:
        seen: dict[str, int] = {}
        for part in [chapter, *access.children(chapter)]:
            items = section_boxes(part.full_body)
            readable = access.readable(part.id)
            for b in items:
                label = b["label"]
                seen[label["name"]] = seen.get(label["name"], 0) + 1
                if not readable:
                    locked += label["name"] == wanted
                    continue
                if label.get("role") == "glance":
                    continue
                counts[label["name"]] = counts.get(label["name"], 0) + 1
                if label["name"] != wanted:
                    continue
                n = seen[label["name"]]
                number = (f"{fa(chapter.position)}-{fa(n)}" if chapter.position else fa(n)) if label["name"] in numbered else ""
                boxes.append({"label": label["name"], "title": f"{label['name']} {number}".strip(), "name": b["name"],
                              "body": media_urls(request, b["body"], book=access.book), "section_id": part.id, "section_title": part.title if part.kind == ContentNode.Kind.SECTION else chapter.title,
                              "chapter_number": chapter.position})
    labels = [{"name": l["name"], "style": l["style"], "count": counts[l["name"]]} for l in all_labels() if l["name"] in counts]
    # all_labels and refs: what the app's renderer needs to draw the boxes and their [[#name]] links.
    from .numbering import book_refs
    return Response({"labels": labels, "boxes": boxes, "locked_count": locked, "title": node.title,
                     "all_labels": all_labels(), "refs": book_refs(access) if wanted else {}})

def _teacher_info(book, request=None):
    """اطلاعات نویسنده / استاد کتاب جهت نمایش در تب «درباره نویسنده»"""
    # First check editors
    editor = book.editors.select_related("user__teacher_profile").first()
    if editor and hasattr(editor.user, "teacher_profile"):
        prof = editor.user.teacher_profile
        name = f"{editor.user.first_name} {editor.user.last_name}".strip() or book.author or editor.user.phone
        avatar_url = request.build_absolute_uri(prof.avatar.url) if (request and prof.avatar) else None
        return {
            "name": name,
            "academic_title": prof.academic_title,
            "avatar": avatar_url,
            "bio": prof.bio,
            "contact_email": prof.contact_email,
            "social_links": prof.social_links,
        }
    return {
        "name": book.author or "مؤلف لیموخوان",
        "academic_title": "",
        "avatar": None,
        "bio": "",
        "contact_email": "",
        "social_links": "",
    }


def _book_reviews_data(book, user=None):
    """نظرات تأییدشده کتاب همراه با میانگین و آمار رضایت"""
    reviews_qs = book.opinions.filter(status="approved").select_related("user", "teacher_replied_by")
    total_count = reviews_qs.count()
    if total_count == 0:
        return {
            "average_rating": None,
            "satisfaction_rate": None,
            "serious_readers_rating": None,
            "total_count": 0,
            "reviews": [],
        }

    from django.db.models import Avg
    avg_rating = reviews_qs.aggregate(avg=Avg("rating"))["avg"] or 5.0
    avg_sat = reviews_qs.aggregate(avg=Avg("satisfaction_percent"))["avg"] or 100

    # خوانندگان جدی: کسانی که بالای ۵۰٪ مطالعه کرده‌اند
    serious_qs = reviews_qs.filter(study_percent__gte=50)
    serious_avg = serious_qs.aggregate(avg=Avg("rating"))["avg"] if serious_qs.exists() else avg_rating

    items = []
    for r in reviews_qs[:50]:
        name = f"{r.user.first_name} {r.user.last_name}".strip()
        display_name = name if name else "کاربر لیموخوان"
        items.append({
            "id": r.id,
            "display_name": display_name,
            "rating": r.rating,
            "satisfaction_percent": r.satisfaction_percent,
            "body": r.body,
            "study_percent": r.study_percent,
            "test_percent": r.test_percent,
            "is_pinned": r.is_pinned,
            "teacher_reply": r.teacher_reply,
            "created_at": r.created_at.strftime("%Y-%m-%d"),
        })

    return {
        "average_rating": round(float(avg_rating), 1),
        "satisfaction_rate": round(float(avg_sat)),
        "serious_readers_rating": round(float(serious_avg), 1),
        "total_count": total_count,
        "reviews": items,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_book_review(request, slug):
    """ثبت یا ویرایش نظر و امتیاز کاربر برای کتاب با محاسبه خودکار درصد پیشرفت مطالعه"""
    from django.shortcuts import get_object_or_404
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)

    try:
        raw_rating = request.data.get("rating", 5)
        raw_sat = request.data.get("satisfaction_percent", 100)
        rating = max(1, min(5, int(5 if raw_rating is None else raw_rating)))
        satisfaction = max(0, min(100, int(100 if raw_sat is None else raw_sat)))
    except (TypeError, ValueError):
        return Response({"error": "مقدار امتیاز یا درصد رضایت نامعتبر است."}, status=status.HTTP_400_BAD_REQUEST)
    body = str(request.data.get("body", "")).strip()[:2000]

    if not body:
        return Response({"error": "متن نظر الزامی است."}, status=status.HTTP_400_BAD_REQUEST)

    # محاسبه خودکار درصد مطالعه و تست‌های کاربر
    from apps.study.progress import section_states
    access = AccessMap(request.user, book)
    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)]
    done = section_states(request.user, access, request)[1] & {s.id for s in sections}
    study_pct = round((len(done) / len(sections)) * 100) if sections else 0

    from apps.learning.models import Question
    from apps.study.models import ExamAnswer
    total_q = Question.objects.filter(node_id__in=[s.id for s in sections], is_archived=False).count()
    user_answered_q = ExamAnswer.objects.filter(attempt__user=request.user, question__node_id__in=[s.id for s in sections]).values("question_id").distinct().count()
    test_pct = round((user_answered_q / total_q) * 100) if total_q else 0

    from .models import BookOpinion
    review, created = BookOpinion.objects.update_or_create(
        book=book,
        user=request.user,
        defaults={
            "rating": rating,
            "satisfaction_percent": satisfaction,
            "body": body,
            "study_percent": study_pct,
            "test_percent": test_pct,
            "status": BookOpinion.Status.APPROVED,
        }
    )

    return Response({
        "status": "success",
        "message": "نظر شما با موفقیت ثبت شد.",
        "review_id": review.id,
    })
