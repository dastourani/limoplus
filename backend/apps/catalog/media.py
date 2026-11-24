"""
Signed, short-lived URLs for protected lesson images (`media/content/...`).

Public catalog assets (`covers/`, `banners/`, `teachers/avatars/`, `apk/`) continue to be served publicly, while
content images under `media/content/` require a valid HMAC signature bound to the exact file path and expiration
timestamp. Signing is performed only after view-level access checks and is scoped to the authorized book (and, for
public intro text like `book.about`, excludes locked chapters).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import posixpath
import re
import time
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, HttpResponseForbidden, HttpResponseNotFound
from django.views.decorators.http import require_http_methods

from .importer import MEDIA_PREFIX

CONTENT_PREFIX = "content/"
DEFAULT_SIGN_BUCKET = 3600
DEFAULT_SIGN_TTL = 7200
_MEDIA_IMAGE_MD = re.compile(r"!\[([^\]]*)\]\(" + re.escape(MEDIA_PREFIX) + r"([^)\s]+)\)")


def _signing_key() -> bytes:
    secret = getattr(settings, "HASH_KEY", "") or settings.SECRET_KEY
    return hashlib.sha256(f"{secret}:media-content".encode("utf-8")).digest()


def normalize_content_path(path: str) -> str | None:
    """Normalize a relative media path and ensure it stays strictly inside `content/`."""
    if not path or "\x00" in path or "\\" in path:
        return None
    cleaned = posixpath.normpath(path.lstrip("/"))
    if cleaned in ("", ".", "..") or cleaned.startswith("../"):
        return None
    if not cleaned.startswith(CONTENT_PREFIX) or len(cleaned) <= len(CONTENT_PREFIX):
        return None
    return cleaned


def _compute_sig(norm_path: str, exp: int) -> str:
    mac = hmac.new(_signing_key(), f"{norm_path}\n{exp}".encode("utf-8"), hashlib.sha256).digest()[:24]
    return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")


def sign_content_path(stored_path: str, *, now: int | None = None) -> tuple[str, int]:
    """Return `(relative_signed_url, exp_unix)` using bucketed expiry so browser/WebView caches work within a window."""
    norm = normalize_content_path(stored_path)
    if norm is None:
        raise ValueError(f"Invalid content media path: {stored_path!r}")
    now_ts = int(time.time()) if now is None else int(now)
    bucket = max(1, int(getattr(settings, "MEDIA_SIGN_BUCKET", DEFAULT_SIGN_BUCKET)))
    ttl = max(bucket, int(getattr(settings, "MEDIA_SIGN_TTL", DEFAULT_SIGN_TTL)))
    exp = ((now_ts // bucket) * bucket) + ttl
    sig = _compute_sig(norm, exp)
    return f"{norm}?exp={exp}&sig={sig}", exp


def verify_content_signature(stored_path: str, exp_raw: str, sig: str, *, now: int | None = None) -> int | None:
    """Validate signature & expiration for `stored_path`; return `exp` if valid, else `None`."""
    norm = normalize_content_path(stored_path)
    if norm is None or not exp_raw or not sig or not exp_raw.isdigit():
        return None
    exp = int(exp_raw)
    now_ts = int(time.time()) if now is None else int(now)
    if exp <= now_ts:
        return None
    expected = _compute_sig(norm, exp)
    if not hmac.compare_digest(sig, expected):
        return None
    return exp


def _is_authorized_ref(
    stored_path: str,
    *,
    book=None,
    book_slug: str | None = None,
    access=None,
    allow_locked_chapters: bool = True,
) -> bool:
    norm = normalize_content_path(stored_path)
    if norm is None:
        return False
    parts = norm[len(CONTENT_PREFIX) :].split("/")
    target_slug = book.slug if book is not None else book_slug
    if not target_slug or parts[0] != target_slug:
        return False
    if not allow_locked_chapters and access is not None and len(parts) >= 2:
        chapter_slug = parts[1]
        for node in access.nodes.values():
            if node.kind == node.Kind.CHAPTER and node.slug == chapter_slug and not access.readable(node.id):
                return False
    return True


def media_urls(
    request,
    text: str,
    *,
    book=None,
    book_slug: str | None = None,
    access=None,
    allow_locked_chapters: bool = True,
) -> str:
    """Turn stored image references (`media:content/…`) into signed URLs scoped to the authorized book."""
    if not text or MEDIA_PREFIX not in text:
        return text

    media_base = "/" + settings.MEDIA_URL.lstrip("/")

    def _replace(match: re.Match[str]) -> str:
        alt, stored = match.group(1), match.group(2)
        if stored.startswith(CONTENT_PREFIX):
            if not _is_authorized_ref(
                stored,
                book=book,
                book_slug=book_slug,
                access=access,
                allow_locked_chapters=allow_locked_chapters,
            ):
                return match.group(0)
            signed_rel, _ = sign_content_path(stored)
            url = request.build_absolute_uri(media_base + signed_rel)
            return f"![{alt}]({url})"
        url = request.build_absolute_uri(media_base + stored.lstrip("/"))
        return f"![{alt}]({url})"

    return _MEDIA_IMAGE_MD.sub(_replace, text)


def filter_authorized_media_refs(
    text: str,
    *,
    book=None,
    book_slug: str | None = None,
    access=None,
    allow_locked_chapters: bool = True,
) -> str:
    """Keep `media:content/...` refs that belong to this book; strip signatures from unauthorized cross-book paths."""
    if not text or MEDIA_PREFIX not in text:
        return text

    def _check(match: re.Match[str]) -> str:
        alt, stored = match.group(1), match.group(2)
        if stored.startswith(CONTENT_PREFIX) and not _is_authorized_ref(
            stored,
            book=book,
            book_slug=book_slug,
            access=access,
            allow_locked_chapters=allow_locked_chapters,
        ):
            return f"![{alt}]()"
        return match.group(0)

    return _MEDIA_IMAGE_MD.sub(_check, text)


def extract_content_media(
    request,
    texts: list[str],
    *,
    book=None,
    book_slug: str | None = None,
    access=None,
    allow_locked_chapters: bool = True,
) -> list[dict]:
    """Return a deduplicated list of `{ref, id, url, mime, expires_at}` for authorized `media:content/...` images."""
    seen: set[str] = set()
    items: list[dict] = []
    media_base = "/" + settings.MEDIA_URL.lstrip("/")
    for text in texts:
        if not text or MEDIA_PREFIX not in text:
            continue
        for match in _MEDIA_IMAGE_MD.finditer(text):
            stored = match.group(2)
            if not stored.startswith(CONTENT_PREFIX):
                continue
            if not _is_authorized_ref(
                stored,
                book=book,
                book_slug=book_slug,
                access=access,
                allow_locked_chapters=allow_locked_chapters,
            ):
                continue
            norm = normalize_content_path(stored)
            if norm is None or norm in seen:
                continue
            seen.add(norm)
            if not default_storage.exists(norm):
                continue
            signed_rel, exp = sign_content_path(norm)
            mime, _ = mimetypes.guess_type(norm)
            items.append(
                {
                    "ref": f"{MEDIA_PREFIX}{norm}",
                    "id": hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24],
                    "url": request.build_absolute_uri(media_base + signed_rel),
                    "mime": mime or "application/octet-stream",
                    "expires_at": exp,
                }
            )
    return items


def _staff_panel_authorized(request, norm_path: str) -> bool:
    """Allow Django panel live-preview (`panel.js`) for active superusers or assigned BookEditors of that book."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated and user.is_active and user.is_staff):
        return False
    if user.is_superuser:
        return True
    parts = norm_path[len(CONTENT_PREFIX) :].split("/")
    book_slug = parts[0] if parts else ""
    if not book_slug:
        return False
    from .models import BookEditor, ContentNode

    book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, slug=book_slug, is_archived=False).first()
    if book is None:
        return False
    return BookEditor.objects.filter(book=book, user=user).exists()


@require_http_methods(["GET", "HEAD"])
def serve_content_media(request, path: str):
    """Serve `media/content/...` only when accompanied by a valid, non-expired HMAC signature (or panel staff session)."""
    norm = normalize_content_path(f"{CONTENT_PREFIX}{path}")
    if norm is None:
        resp = HttpResponseForbidden("مسیر تصویر نامعتبر است.")
        resp["Cache-Control"] = "no-store"
        return resp

    exp_raw = request.GET.get("exp", "")
    sig = request.GET.get("sig", "")
    exp: int | None = None
    staff_preview = False
    if exp_raw or sig:
        exp = verify_content_signature(norm, exp_raw, sig)
    elif _staff_panel_authorized(request, norm):
        staff_preview = True

    if exp is None and not staff_preview:
        resp = HttpResponseForbidden("لینک تصویر نامعتبر یا منقضی شده است.")
        resp["Cache-Control"] = "no-store"
        return resp

    # Extra path containment check when backed by local disk.
    try:
        storage_path = Path(default_storage.path(norm)).resolve()
        content_root = (Path(settings.MEDIA_ROOT) / "content").resolve()
        if content_root not in storage_path.parents:
            resp = HttpResponseForbidden("مسیر تصویر نامعتبر است.")
            resp["Cache-Control"] = "no-store"
            return resp
    except (NotImplementedError, AttributeError):
        pass

    if not default_storage.exists(norm):
        return HttpResponseNotFound("تصویر پیدا نشد.")

    content_type, _ = mimetypes.guess_type(norm)
    fh = default_storage.open(norm, "rb")
    resp = FileResponse(fh, content_type=content_type or "application/octet-stream")
    if staff_preview:
        resp["Cache-Control"] = "private, no-store"
    else:
        remaining = max(0, exp - int(time.time()))
        resp["Cache-Control"] = f"private, max-age={remaining}"
    resp["X-Content-Type-Options"] = "nosniff"
    if norm.lower().endswith(".svg"):
        resp["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp
