from django.conf import settings
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .access import AccessMap
from .importer import MEDIA_PREFIX
from .models import Banner, ContentNode, Major

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
    for book in books.order_by("title"):
        access = AccessMap(request.user, book)
        chapters = access.children(book)
        payload.append(
            {
                "slug": book.slug,
                "title": book.title,
                "price": book.price,
                "chapter_count": len(chapters),
                "has_free_part": any(n.is_free for n in access.nodes.values() if access.visible(n.id)),
                "owned": access.owned,
            }
        )
    return Response(payload)


def _done_ids(user, book):
    if not user.is_authenticated:
        return []
    from apps.study.models import SectionProgress

    return list(SectionProgress.objects.filter(user=user, book=book, is_done=True).values_list("node_id", flat=True))


@api_view(["GET"])
@permission_classes([AllowAny])
def book_detail(request, slug):
    book = get_object_or_404(ContentNode, kind=ContentNode.Kind.BOOK, slug=slug, depth=1)
    access = AccessMap(request.user, book)
    if not access.visible(book.id):
        return Response(NOT_FOUND, status=status.HTTP_404_NOT_FOUND)

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
        chapters.append(item)
    return Response(
        {
            "slug": book.slug,
            "title": book.title,
            "price": book.price,
            "majors": list(book.majors.values_list("slug", flat=True)),
            "chapters": chapters,
            "owned": access.owned,
            "done_ids": _done_ids(request.user, book),
        }
    )


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
            "breadcrumb": [{"id": a.id, "kind": a.kind, "slug": a.slug, "title": a.title} for a in ancestors],
            "summary": media_urls(request, node.summary_body),
            "full": media_urls(request, node.full_body),
            "previous_id": siblings[index - 1] if index > 0 else None,
            "next_id": siblings[index + 1] if index + 1 < len(siblings) else None,
            "updated_at": node.updated_at,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def banners(request):
    now = timezone.now()
    items = Banner.objects.filter(is_active=True).filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now)).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gte=now)
    )
    major = request.query_params.get("major")
    if major:
        items = items.filter(Q(majors__isnull=True) | Q(majors__slug=major)).distinct()
    items = list(items[:10])
    Banner.objects.filter(pk__in=[b.pk for b in items]).update(impressions=F("impressions") + 1)
    return Response(
        [
            {
                "id": b.id,
                "title": b.title,
                "subtitle": b.subtitle,
                "image": request.build_absolute_uri(b.image.url) if b.image else None,
                "link": b.resolved_link(),
            }
            for b in items
        ]
    )


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
    seen, terms = set(), []
    for node in sorted(access.nodes.values(), key=lambda n: n.path):
        if node.kind != ContentNode.Kind.SECTION or not access.readable(node.id) or not node.summary_body:
            continue
        for term in parse_terms(node.summary_body):
            key = term["fa"]
            if key in seen:
                continue
            seen.add(key)
            terms.append({**term, "section_id": node.id, "section_title": node.title})
    terms.sort(key=lambda t: t["fa"])
    return Response({"book": book.title, "terms": terms})

