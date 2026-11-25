"""Recording copies of lesson text, finding them again, and each account's risk score."""

import hashlib
import zlib
from datetime import datetime, time, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.catalog.models import ChapterRevision, ContentNode

from . import fingerprint
from .models import CopyEvent, TraceHit

DAILY_LIMIT = 30
MAX_CHARS = 400  # the reader allows 200 visible characters; formulas come as LaTeX, a bit longer
SKIP = set("*=#>|`")


# --- Text ---------------------------------------------------------------------------------------------------------

def _project(text: str) -> tuple[str, list[int]]:
    """The text without Markdown marks (formulas kept whole) and with whitespace collapsed, and where each kept
    character came from."""
    out, where, space, line_start, math = [], [], True, True, False
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line_start = True
        if line_start and c not in " \t\n":
            # A list mark at the start of a line: «- », «+ », «۱. » / «1. ».
            j = i
            while j < n and (text[j].isdigit()):
                j += 1
            if j < n and ((j > i and text[j] in ".)") or (j == i and text[j] in "-+")) and j + 1 < n and text[j + 1] == " ":
                i = j + 1
                line_start = False
                continue
            line_start = False
        if c == "$":
            math = not math
        if (c in SKIP and not math) or c in fingerprint.DIGITS or c in (fingerprint.START, fingerprint.STOP):
            i += 1
            continue
        if c.isspace():
            if not space:
                out.append(" ")
                where.append(i)
                space = True
        else:
            out.append(c)
            where.append(i)
            space = False
        i += 1
    return "".join(out), where


def normalize(text: str) -> str:
    return _project(text)[0].strip()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode()).hexdigest()


def locate(source: str, quote: str) -> tuple[int, int] | None:
    q = normalize(quote)
    if not q:
        return None
    flat, where = _project(source)
    at = flat.find(q)
    if at < 0:
        return None
    return where[at], where[at + len(q) - 1] + 1


def chapter_of(node: ContentNode) -> ContentNode | None:
    if node.kind == ContentNode.Kind.CHAPTER:
        return node
    return node.get_ancestors().filter(kind=ContentNode.Kind.CHAPTER).last()


def latest_revision(chapter: ContentNode) -> ChapterRevision:
    from apps.catalog import editing

    revision = chapter.revisions.order_by("-updated_at", "-id").first()
    if revision is None:
        editing.ensure_baseline(chapter)
        revision = chapter.revisions.order_by("-updated_at", "-id").first()
    return revision


def text_of(event: CopyEvent) -> str:
    if event.packed:
        return zlib.decompress(bytes(event.packed)).decode()
    if event.revision_id and event.start is not None:
        return event.revision.text[event.start:event.end]
    return ""


def is_exact(event: CopyEvent) -> bool:
    """The pointer still gives back exactly the copied text."""
    return bool(text_of(event)) and text_hash(text_of(event)) == event.text_hash


# --- Quota --------------------------------------------------------------------------------------------------------

def day_start(now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    return timezone.make_aware(datetime.combine(today, time.min))


def used_today(user, now=None) -> int:
    return CopyEvent.objects.filter(user=user, created_at__gte=day_start(now)).count()


def record(user, node: ContentNode, quote: str, mode: str, platform: str = "") -> tuple[CopyEvent, str]:
    chapter = chapter_of(node)
    revision = latest_revision(chapter) if chapter else None
    digest = text_hash(quote)
    start = end = None
    packed = None
    spot = locate(revision.text, quote) if revision else None
    if spot and text_hash(revision.text[spot[0]:spot[1]]) == digest:
        start, end = spot
    else:
        packed = zlib.compress(quote.encode(), 9)
    code = fingerprint.new_code()
    while CopyEvent.objects.filter(code=code).exists():
        code = fingerprint.new_code()
    event = CopyEvent.objects.create(
        user=user, node=node, revision=revision if start is not None else None, mode=mode, start=start, end=end,
        text_hash=digest, length=len(quote), packed=packed, code=code, platform=platform[:20],
    )
    return event, fingerprint.mark(quote, code)


# --- Finding a pasted text ----------------------------------------------------------------------------------------

def trace(text: str, limit_days: int = 365) -> dict:
    """Fingerprints in the text; without them, recent copies whose text appears in it (or contains it)."""
    codes = fingerprint.decode_all(text)
    marked = list(CopyEvent.objects.filter(code__in=codes).select_related("user", "node", "revision"))
    similar = []
    if not marked:
        flat = normalize(fingerprint.strip(text))
        if len(flat) >= 20:
            since = timezone.now() - timedelta(days=limit_days)
            for event in CopyEvent.objects.filter(created_at__gte=since).select_related("user", "node", "revision")[:5000]:
                own = normalize(text_of(event))
                if len(own) >= 20 and (own in flat or flat in own):
                    similar.append(event)
                    if len(similar) >= 50:
                        break
    return {"codes": codes, "marked": marked, "similar": similar}


# --- Risk ---------------------------------------------------------------------------------------------------------

def risk_parts(copies_7d: int, full_days_30d: int, sections_7d: int, hits: int, new_devices_7d: int) -> dict:
    parts = {
        "copies": min(30, copies_7d),
        "full_days": min(30, full_days_30d * 10),
        "spread": 10 if sections_7d > 10 else 0,
        "hits": min(50, hits * 25),
        "devices": min(20, max(0, new_devices_7d - 2) * 5),
    }
    parts["score"] = min(100, sum(parts.values()))
    parts["level"] = "high" if parts["score"] >= 60 else "mid" if parts["score"] >= 30 else "low"
    return parts


def risk_table(now=None, users=None) -> list[dict]:
    """Every account with a copy or a new device lately, riskiest first."""
    from apps.accounts.models import DeviceSession, User

    now = now or timezone.now()
    week, month = now - timedelta(days=7), now - timedelta(days=30)
    copies = CopyEvent.objects.filter(created_at__gte=month)
    devices = DeviceSession.objects.filter(created_at__gte=week)
    if users is not None:
        copies, devices = copies.filter(user__in=users), devices.filter(user__in=users)
    rows: dict[int, dict] = {}

    def row(uid):
        return rows.setdefault(uid, {"user_id": uid, "copies_7d": 0, "full_days_30d": 0, "sections_7d": 0, "hits": 0, "new_devices_7d": 0})

    for r in copies.filter(created_at__gte=week).values("user_id").annotate(n=Count("id"), s=Count("node_id", distinct=True)):
        row(r["user_id"]).update(copies_7d=r["n"], sections_7d=r["s"])
    per_day = copies.annotate(day=TruncDate("created_at")).values("user_id", "day").annotate(n=Count("id"))
    for r in per_day:
        if r["n"] >= DAILY_LIMIT:
            row(r["user_id"])["full_days_30d"] += 1
    hit_q = TraceHit.objects.all() if users is None else TraceHit.objects.filter(event__user__in=users)
    for r in hit_q.values("event__user_id").annotate(n=Count("event_id", distinct=True)):
        row(r["event__user_id"])["hits"] = r["n"]
    for r in devices.order_by().values("user_id").annotate(n=Count("id")):
        if users is not None or r["n"] > 2:
            row(r["user_id"])["new_devices_7d"] = r["n"]
    people = {u.pk: u for u in User.objects.filter(pk__in=rows)}
    out = []
    for uid, r in rows.items():
        r.update(risk_parts(r["copies_7d"], r["full_days_30d"], r["sections_7d"], r["hits"], r["new_devices_7d"]))
        r["user"] = people.get(uid)
        out.append(r)
    out.sort(key=lambda r: (-r["score"], -r["copies_7d"]))
    return out


def risk_of(user, now=None) -> dict:
    rows = risk_table(now, users=[user.pk])
    return rows[0] if rows else {**risk_parts(0, 0, 0, 0, 0), "user": user}


def new_sessions_7d(user_ids) -> dict[int, int]:
    from apps.accounts.models import DeviceSession

    week = timezone.now() - timedelta(days=7)
    rows = DeviceSession.objects.filter(user_id__in=user_ids, created_at__gte=week).order_by().values("user_id").annotate(n=Count("id"))
    return {r["user_id"]: r["n"] for r in rows}


def device_switches(since) -> list[dict]:
    """Accounts that signed in since then and passed «تعویض زیاد دستگاه» (more than DEVICE_SWITCH_ALERT sign-ins in 7 days)."""
    from django.conf import settings

    from apps.accounts.models import DeviceSession

    recent = set(DeviceSession.objects.filter(created_at__gte=since).values_list("user_id", flat=True))
    return [{"user_id": u, "n": n} for u, n in new_sessions_7d(recent).items() if n > settings.DEVICE_SWITCH_ALERT]


# --- Privacy & Book Scoping ---------------------------------------------------------------------------------------

def mask_phone(phone: str, fallback: str = "کاربر لیموخوان") -> str:
    """Mask user phone for teacher privacy (e.g. 0912***3456); never return short raw phones."""
    raw = (phone or "").strip()
    if len(raw) < 7:
        return fallback
    return raw[:4] + "***" + raw[-4:]


def masked_user_label(user, fallback: str = "کاربر لیموخوان") -> str:
    if not user:
        return fallback
    masked = mask_phone(getattr(user, "phone", ""), fallback=fallback)
    full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    return f"{full_name} ({masked})" if full_name else masked


def traceable_books(user):
    """Books this user may trace or view trace findings on (active, non-archived, non-inbox)."""
    from apps.catalog import access

    if not (user and user.is_authenticated and user.is_active):
        return ContentNode.objects.none()
    if user.is_superuser:
        return ContentNode.objects.filter(
            kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False, is_archived=False
        )
    return access.books_for_editor(user, capability="can_edit_content").filter(is_archived=False)


def book_of_event(event: CopyEvent | None) -> ContentNode | None:
    if not event or not event.node_id or not event.node:
        return None
    return event.node.book()


def can_view_event(user, event: CopyEvent | None) -> bool:
    """True if superuser, or an active book teacher with current edit permission on the event's book."""
    from apps.catalog import access

    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    book = book_of_event(event)
    return bool(book and access.can_edit_book(user, book))


def scope_to_traceable_books(queryset, user, path_field: str = "node__path"):
    """Restrict a CopyEvent/TraceHit queryset in SQL to books the user currently holds trace permission on."""
    from django.db.models import OuterRef, Subquery
    from django.db.models.functions import Substr
    from apps.catalog import access

    if user and user.is_authenticated and user.is_active and user.is_superuser:
        return queryset
    if not access.is_book_teacher(user) or not user.has_perm("catalog.change_contentnode"):
        return queryset.none()
    roots = ContentNode.objects.filter(
        path=Substr(OuterRef(path_field), 1, ContentNode.steplen),
        kind=ContentNode.Kind.BOOK,
        depth=1,
        is_archived=False,
        is_inbox=False,
        pk__in=access.book_editor_ids(user, capability="can_edit_content"),
    ).order_by()
    return queryset.annotate(_lp_trace_book_id=Subquery(roots.values("pk")[:1])).filter(_lp_trace_book_id__isnull=False)


