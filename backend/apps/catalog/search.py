"""
Persian search across what the learner may read: lesson text (notes and summary), questions, flashcards and their own
notes. Matching ignores the usual Persian typing differences: «ي/ی»، «ك/ک»، «ة/ه»، «أإآ/ا»، the zero-width non-joiner
and spaces between letters, tatweel and short vowels, and Persian/Arabic digits. Only content the learner can read is
searched, so paid text never leaks through results.
"""

from __future__ import annotations

import re

from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.response import Response

from .access import AccessMap
from .models import ContentNode

MAX_RESULTS = 60
MIN_QUERY = 2

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_VARIANTS = {"ی": "یيىئ", "ک": "کك", "ه": "هةۀ", "ا": "اأإآٱ", "و": "وؤ"}
_SKIP = r"[\s‌‍ـً-ٰٟ]*"


def normalize(text: str) -> str:
    text = (text or "").translate(_DIGITS)
    for base, alts in _VARIANTS.items():
        for a in alts[1:]:
            text = text.replace(a, base)
    text = re.sub(r"[ـً-ٰٟ]", "", text)
    return re.sub(r"[\s‌‍]+", " ", text).strip().lower()


def pattern(query: str) -> re.Pattern | None:
    """A regex that finds the query in original text whatever the spacing, half-spaces and letter variants."""
    q = normalize(query).replace(" ", "")
    if len(q) < MIN_QUERY:
        return None
    parts = []
    for ch in q:
        alts = _VARIANTS.get(ch)
        if alts:
            parts.append("[" + alts + "]")
        elif ch in "0123456789":
            i = int(ch)
            parts.append("[" + ch + "۰۱۲۳۴۵۶۷۸۹"[i] + "٠١٢٣٤٥٦٧٨٩"[i] + "]")
        else:
            parts.append(re.escape(ch))
    return re.compile(_SKIP.join(parts), re.IGNORECASE)


def _clean(text: str) -> str:
    """Markdown and LaTeX markup out, for a readable snippet."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"==(?:قرمز|آبی|سبز|red|blue|green):", "", text)  # coloured text «==قرمز:…==»
    text = text.replace("==", "")
    text = re.sub(r"\{#[^}]*\}|:::[^\n]*|<[^>]+>", " ", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)
    text = re.sub(r"[*_`#>$|{}^\\]", "", text)
    return " ".join(text.split())


def _snippet(text: str, rx: re.Pattern, width=60) -> tuple[str, str] | None:
    """(snippet around the first match, the matched words as they are written) or None."""
    plain = _clean(text)
    m = rx.search(plain)
    if not m:
        return None
    start, end = max(0, m.start() - width), min(len(plain), m.end() + width)
    snip = ("…" if start else "") + plain[start:end].strip() + ("…" if end < len(plain) else "")
    return snip, m.group(0)


class SearchThrottle(SimpleRateThrottle):
    """Search reads the whole catalogue: 30 a minute per account, 15 per address for guests."""

    scope = "search"

    def get_rate(self):
        return "30/min"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            return f"throttle_search_user_{request.user.pk}"
        from apps.accounts.views import _client_ip

        self.num_requests = 15
        return f"throttle_search_ip_{_client_ip(request)}"


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([SearchThrottle])
def search(request):
    from apps.learning.models import Flashcard, Question

    query = str(request.query_params.get("q") or "")[:80]
    rx = pattern(query)
    if rx is None:
        return Response({"query": query, "results": [], "too_short": True})
    books = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_published=True, is_archived=False)
    slug = request.query_params.get("book") or ""
    if slug:
        books = books.filter(slug=slug)

    results: list[dict] = []
    for book in books.order_by("position", "title"):
        access = AccessMap(request.user, book)
        if not access.visible(book.id):
            continue
        nodes = {n.id: n for n in access.nodes.values() if access.visible(n.id)}
        readable = [n for n in nodes.values() if access.readable(n.id) and n.kind in (ContentNode.Kind.SECTION, ContentNode.Kind.CHAPTER)]
        for n in sorted(readable, key=lambda n: n.path):
            title_hit = rx.search(_clean(n.title))
            for mode, body in (("full", n.full_body), ("summary", n.summary_body)):
                hit = _snippet(body, rx)
                if hit or (title_hit and mode == "full"):
                    snip, match = hit or (_clean(body)[:120], "")
                    results.append({"kind": "section", "id": n.id, "node_id": n.id, "title": n.title, "book_title": book.title,
                                    "book_slug": book.slug, "mode": mode, "snippet": snip, "match": match})
                    break
        usable = lambda item: item.node_id in nodes and (item.is_free or access.readable(item.node_id))  # noqa: E731
        for q in Question.objects.filter(node_id__in=list(nodes), is_archived=False).only("id", "node_id", "stem", "is_free"):
            if usable(q):
                hit = _snippet(q.stem, rx)
                if hit:
                    results.append({"kind": "question", "id": q.id, "node_id": q.node_id, "title": nodes[q.node_id].title,
                                    "book_title": book.title, "book_slug": book.slug, "snippet": hit[0], "match": hit[1]})
        for f in Flashcard.objects.filter(node_id__in=list(nodes), is_archived=False).only("id", "node_id", "title", "point", "is_free"):
            if usable(f):
                hit = _snippet(f.title + " — " + f.point, rx)
                if hit:
                    results.append({"kind": "flashcard", "id": f.id, "node_id": f.node_id, "title": f.title,
                                    "book_title": book.title, "book_slug": book.slug, "snippet": hit[0], "match": hit[1]})
        if len(results) >= MAX_RESULTS * 2:
            break

    if request.user.is_authenticated:
        from apps.study.models import Note

        paths = [b.path for b in books] if slug else None
        for note in Note.objects.filter(user=request.user, is_archived=False).select_related("node").order_by("-updated_at")[:500]:
            hit = _snippet(note.body, rx) or _snippet(note.quote, rx)
            if hit and (paths is None or any(note.node.path.startswith(p) for p in paths)):
                results.append({"kind": "note", "id": note.id, "node_id": note.node_id, "title": note.node.title, "book_title": "",
                                "book_slug": "", "snippet": hit[0], "match": _clean(note.quote)[:200] or hit[1], "mode": note.mode})

    order = {"section": 0, "note": 1, "flashcard": 2, "question": 3}
    results.sort(key=lambda r: order[r["kind"]])
    return Response({"query": query, "results": results[:MAX_RESULTS], "more": len(results) > MAX_RESULTS})
