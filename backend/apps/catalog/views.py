from django.conf import settings
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .access import AccessMap
from .drawing import loads as loads_drawing
from .importer import MEDIA_PREFIX
from .labels import all_labels
from .numbering import numbering_for
from .models import Banner, ContentNode, Major, ShareSettings

NOT_FOUND = {"code": "not_found", "message": "پیدا نشد."}


def media_urls(request, text: str) -> str:
    """Turn stored image references (media:content/…) into full URLs for this server."""
    if not text or MEDIA_PREFIX not in text:
        return text
    base = request.build_absolute_uri("/" + settings.MEDIA_URL.lstrip("/"))
    return text.replace(f"]({MEDIA_PREFIX}", f"]({base}")


def locked_response(book):
    return Response(
        {
            "code": "locked",
            "message": "این بخش در نسخه‌ی کامل کتاب است.",
            "book": {"slug": book.slug, "title": book.title, "price": book.price},
        },
        status=status.HTTP_403_FORBIDDEN,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def majors(request):
    return Response(
        [{"slug": m.slug, "name": m.name, "color": m.color, "is_coming_soon": m.is_coming_soon} for m in Major.objects.all()]
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def major_books(request, slug):
    major = get_object_or_404(Major, slug=slug)
    books = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, majors=major, is_published=True, is_archived=False)
    payload = []
    for book in books.order_by("is_coming_soon", F("position").asc(nulls_last=True), "title"):
        access = AccessMap(request.user, book)
        payload.append(book_card(request, book, access))
    return Response(payload)


@api_view(["GET"])
@permission_classes([AllowAny])
def all_books(request):
    """Every book, for a learner who hasn't picked a major yet. Each carries its first major (for the cover)."""
    books = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_published=True, is_archived=False, majors__isnull=False).distinct()
    payload = []
    for book in books.order_by("is_coming_soon", F("position").asc(nulls_last=True), "title"):
        major = book.majors.order_by("order", "name").first()
        card = book_card(request, book, AccessMap(request.user, book))
        card["major"] = {"slug": major.slug, "name": major.name, "color": major.color} if major else None
        payload.append(card)
    return Response(payload)


@api_view(["GET"])
@permission_classes([AllowAny])
def shelves(request):
    """The home page: one row per active shelf (set in the panel), then the published books on no shelf, so none is hidden."""
    from .models import Shelf, ShelfBook

    from .access import access_kind_from, active_rows

    published = {
        b.id: b
        for b in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_published=True, is_archived=False).prefetch_related("majors")
    }
    # Read once for all the books: the learner's entitlements, finished sections and «خبرم کن» rows.
    entitlements = active_rows(request.user)
    _prefetch_user_rows(request)
    cards: dict[int, dict] = {}

    def card(book):
        if book.id not in cards:
            kind = access_kind_from(entitlements, request.user, book.id, {m.id for m in book.majors.all()})
            cards[book.id] = book_card(request, book, AccessMap(request.user, book, light=True, kind=kind))
        return cards[book.id]

    rows, placed = [], set()
    for shelf in Shelf.objects.filter(is_active=True).order_by("order", "id"):
        ids = [i.book_id for i in ShelfBook.objects.filter(shelf=shelf).order_by("order", "id") if i.book_id in published]
        if ids:
            rows.append({"id": shelf.id, "title": shelf.title, "books": [card(published[i]) for i in ids]})
            placed.update(ids)
    rest = sorted((b for i, b in published.items() if i not in placed), key=lambda b: (b.is_coming_soon, b.position or 9999, b.title))
    if rest:
        rows.append({"id": None, "title": "کتاب‌های دیگر" if rows else "همه‌ی کتاب‌ها", "books": [card(b) for b in rest]})
    return Response(rows)


def book_card(request, book, access) -> dict:
    """What a shelf needs to draw a book: its cover, its free part, the reader's progress and «خبرم کن»."""
    chapters = access.children(book)
    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION and access.visible(n.id)]
    # «تمام شد» sections (read, and enough of their questions answered) make the progress.
    from apps.study.progress import section_states

    done = section_states(request.user, access, request)[1] & {s.id for s in sections}
    free_chapter = next((i for i, c in enumerate(chapters, start=1) if c.is_free), None)
    free_chapters = len(chapters) if book.is_free else sum(1 for c in chapters if c.is_free)
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
        "price": book.price,
        "chapter_count": len(chapters),
        "section_count": len(sections),
        "has_free_part": any(n.is_free for n in access.nodes.values() if access.visible(n.id)),
        "free_chapter": free_chapter,
        # For the one label on the shelf: the whole book, n chapters, or only some sections are free.
        "free_chapters": free_chapters,
        "all_free": bool(chapters) and free_chapters == len(chapters),
        "owned": access.owned,
        "access": access.access,
        "progress": round(len(done) / len(sections), 3) if done and sections else None,
        **_notify(request.user, book, request),
    }


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


@api_view(["GET"])
@permission_classes([AllowAny])
def book_detail(request, slug):
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)
    from apps.study.progress import section_states

    _states = section_states(request.user, access, request)

    sections = [n for n in access.nodes.values() if n.kind == ContentNode.Kind.SECTION]
    counts = {}
    from apps.learning.models import Flashcard, Question

    for model, key in ((Question, "question_count"), (Flashcard, "flashcard_count")):
        rows = model.objects.filter(node_id__in=[s.id for s in sections], is_archived=False).values("node_id").annotate(n=Count("id"))
        for row in rows:
            counts.setdefault(row["node_id"], {})[key] = row["n"]

    def summary(node):
        data = {"id": node.id, "slug": node.slug, "kind": node.kind, "title": node.title, "is_locked": not access.readable(node.id)}
        if node.kind == ContentNode.Kind.SECTION:
            data["has_summary"] = bool(node.summary_body)
            data["group"] = node.group
            data["question_count"] = counts.get(node.id, {}).get("question_count", 0)
            data["flashcard_count"] = counts.get(node.id, {}).get("flashcard_count", 0)
        return data

    chapters = []
    for chapter in access.children(book):
        item = summary(chapter)
        item["has_overview"] = bool(chapter.full_body or chapter.summary_body) and not item["is_locked"]
        item["sections"] = [summary(s) for s in access.children(chapter)]
        item["term_count"] = _term_count(access, chapter)
        chapters.append(item)
    return Response(
        {
            **book_card(request, book, access),
            "about": media_urls(request, book.about),
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
        }
    )


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
        if access.visible(q.node_id) and (q.is_free or access.readable(q.node_id))
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
    siblings = [n.id for n in access.children(parent)] if parent else [node.id]
    index = siblings.index(node.id)
    return Response(
        {
            "id": node.id,
            "kind": node.kind,
            "title": node.title,
            # A chapter's number is its place in the book (kept in step when chapters are reordered in the panel).
            "breadcrumb": [{"id": a.id, "kind": a.kind, "slug": a.slug, "title": a.title, "number": a.position} for a in ancestors],
            "summary": media_urls(request, node.summary_body),
            "full": media_urls(request, node.full_body),
            # The panel's labels: boxes in the notes and parts of the summary (app/src/lib/labels.ts).
            "labels": all_labels(),
            # «مثال ۳-۵»: where this section's numbered boxes start, and the book's [[#names]] (apps/catalog/numbering.py).
            "numbering": numbering_for(access, node),
            "previous_id": siblings[index - 1] if index > 0 else None,
            "next_id": siblings[index + 1] if index + 1 < len(siblings) else None,
            # Titles of the neighbours, for the page drawn while turning to them.
            "previous_title": access.nodes[siblings[index - 1]].title if index > 0 else None,
            "next_title": access.nodes[siblings[index + 1]].title if index + 1 < len(siblings) else None,
            "updated_at": node.updated_at,
            "chapter_end": _chapter_end(access, node, parent, request) if index + 1 == len(siblings) else None,
            "status": _section_status(request.user, access, node),
        }
    )


def _chapter_end(access, node, chapter, request=None):
    """The last section of a chapter: no dead end. The chapter's summary exam, and the next chapter (or the book's end)."""
    if node.kind != ContentNode.Kind.SECTION or chapter is None or chapter.kind != ContentNode.Kind.CHAPTER:
        return None
    chapters = [c.id for c in access.children(access.book)]
    i = chapters.index(chapter.id) if chapter.id in chapters else -1
    nxt = None
    if 0 <= i < len(chapters) - 1:
        c = access.nodes[chapters[i + 1]]
        sections = access.children(c)
        first = sections[0] if sections else c
        nxt = {"id": first.id, "chapter_title": c.title, "title": first.title, "locked": not access.readable(first.id)}
    # The summary exam it suggests: 10 questions (fewer if the chapter has fewer), with its time from their own estimates.
    from apps.learning.models import Question

    pool = [q for q in Question.objects.filter(node_id__in=access.visible_ids_under(chapter), is_archived=False).only("id", "node_id", "is_free", "estimated_seconds")
            if access.visible(q.node_id) and (q.is_free or access.readable(q.node_id))]
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
              if access.visible(q.node_id) and (q.is_free or access.readable(q.node_id))]
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


@api_view(["GET"])
@permission_classes([AllowAny])
def banners(request):
    now = timezone.now()
    items = Banner.objects.filter(is_active=True).filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now)).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gte=now)
    )
    # A banner for the readers of one book is shown only to them; the rest go to everyone.
    reading = set()
    if request.user.is_authenticated:
        from apps.study.models import SectionProgress

        reading = set(SectionProgress.objects.filter(user=request.user).values_list("book_id", flat=True))
    items = [b for b in items if b.audience_book_id is None or b.audience_book_id in reading][:10]
    Banner.objects.filter(pk__in=[b.pk for b in items]).update(impressions=F("impressions") + 1)
    return Response(
        [
            {
                "id": b.id,
                "title": b.title,
                "subtitle": b.subtitle,
                "image": request.build_absolute_uri(b.image.url) if b.image else None,
                "link": b.resolved_link(),
                "template": b.template,
                "button": b.button,
                "motif": b.motif,
                # The countdown runs on the server's clock, so a phone with the wrong time still counts right.
                "ends_at": b.ends_at if b.countdown else None,
                "server_now": now,
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
