from __future__ import annotations

import hashlib
import hmac
import re
from pathlib import Path

from django.conf import settings

# Strict allowlist for event context keys so no PII, note text, question content, or signed URLs ever persist.
ALLOWED_CONTEXT_KEYS = frozenset({
    "book_slug",
    "node_id",
    "media_id",
    "media_ref",
    "session_id",
    "order_id",
    "entitlement_id",
    "attempt_id",
    "status_code",
    "error_name",
    "error_message",
    "stack",
    "component_stack",
    "previous_intact",
    "missing_count",
    "total_count",
    "stage",
    "answered_count",
    "correct_count",
    "served_count",
    "expected_score",
    "recorded_score",
    "expected_months",
    "recorded_days",
    "expected_book_id",
    "recorded_book_id",
    "expected_scope",
    "recorded_scope",
    "owner_mismatch",
    "source",
    "method",
    "exception_type",
    "location",
    "pending_with_track",
    "offline_missing_24h",
    "offline_corrupt_24h",
    "offline_media_24h",
    "offline_update_failed_24h",
    "unknowns",
    "offline_reason",
})

ALLOWED_BREADCRUMB_KEYS = frozenset({"at", "type", "name", "detail"})

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?98|0)9\d{9}")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{6,}\b")
_QUERY_ALL_RE = re.compile(r"\?[^\s\"'<>#]+")
_QUERY_SECRET_RE = re.compile(r"([?&](?:sig|signature|token|code|exp|expires|password|key|q|query|search)=)[^&\s]+", re.IGNORECASE)
_PERSIAN_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+(?:[\s\u200c\u200d،؛؟!«»\-–—.\d]+[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+)*")
_QUOTED_SENSITIVE_RE = re.compile(r"([\"'«])(?:(?=(\\?))\2.)*?\1")
_STACK_FRAME_LINE_RE = re.compile(r"^\s*(?:at\s+.+|File\s+\"[^\"]+\",\s+line\s+\d+.*|[^\s:]+(?:Error|Exception)(?::.*)?)$")
_UUID_OR_HEX_RE = re.compile(r"/[0-9a-fA-F]{16,}(?=/|$)")
_INT_SEGMENT_RE = re.compile(r"/\d+(?=/|$)")
_BOOK_SLUG_SEGMENT_RE = re.compile(r"^(/api/v1/books/|/book/)([^/]+)")

_WEB_COMMIT_CACHE: dict[str, str] = {}


def server_web_commit() -> str:
    """Reads the deployed web build commit hash from WEBAPP_DIR/build-commit.txt (cached per path)."""
    webapp_dir = getattr(settings, "WEBAPP_DIR", None)
    if not webapp_dir:
        return ""
    commit_file = Path(webapp_dir) / "build-commit.txt"
    key = str(commit_file)
    if key in _WEB_COMMIT_CACHE and not getattr(settings, "TESTING", False):
        return _WEB_COMMIT_CACHE[key]
    try:
        value = commit_file.read_text(encoding="utf-8").strip()[:40] if commit_file.is_file() else ""
    except OSError:
        value = ""
    _WEB_COMMIT_CACHE[key] = value
    return value


def user_ref_for(user_id: int | None) -> str:
    """Indirect pseudonymous identifier derived from user pk via HASH_KEY (never phone or raw PII)."""
    if not user_id:
        return ""
    digest = hmac.new(
        str(settings.HASH_KEY).encode("utf-8"),
        f"diag-user:{user_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:12]
    return f"u-{digest}"


def scrub_text(raw: object, max_len: int = 1000) -> str:
    if raw is None:
        return ""
    text = str(raw)
    for secret in (
        getattr(settings, "SECRET_KEY", ""),
        getattr(settings, "HASH_KEY", ""),
        getattr(settings, "BALE_BOT_TOKEN", ""),
        getattr(settings, "BACKUP_S3_SECRET_KEY", ""),
        getattr(settings, "BACKUP_S3_ACCESS_KEY", ""),
        getattr(settings, "RELEASE_WEBHOOK_SECRET", ""),
    ):
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED]", text)
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    text = _QUERY_SECRET_RE.sub(r"\1[REDACTED]", text)
    text = _QUERY_ALL_RE.sub("?[REDACTED]", text)
    return text.strip()[:max_len]


def _redact_quote(match: re.Match) -> str:
    body = match.group(0)
    if len(body) > 22 or _PERSIAN_ARABIC_RE.search(body) or " " in body:
        return '"[REDACTED]"'
    return body


def scrub_untrusted_error(raw: object, max_len: int = 400) -> str:
    """Scrubs untrusted exception/error text so emails, search queries, and lesson/user Persian text never leak."""
    text = scrub_text(raw, max_len=max_len * 2)
    if not text:
        return ""
    text = _PERSIAN_ARABIC_RE.sub("[TEXT]", text)
    text = _QUOTED_SENSITIVE_RE.sub(_redact_quote, text)
    text = re.sub(r"(?:\[TEXT\]\s*){2,}", "[TEXT] ", text)
    return text.strip()[:max_len]


def scrub_stack(raw: object, max_len: int = 1600) -> str:
    if not raw:
        return ""
    lines: list[str] = []
    for line in str(raw).splitlines()[-14:]:
        stripped = line.rstrip()
        if not stripped:
            continue
        if re.match(r"^\s*(?:at\s+|File\s+\")", stripped):
            lines.append(scrub_text(stripped, max_len=240))
        else:
            lines.append(scrub_untrusted_error(stripped, max_len=240))
    return "\n".join(lines)[:max_len]


def normalize_route(raw: object) -> str:
    if not raw:
        return ""
    path = str(raw).split("?", 1)[0].split("#", 1)[0].strip()
    path = _UUID_OR_HEX_RE.sub("/<hex>", path)
    path = _INT_SEGMENT_RE.sub("/<id>", path)
    path = _BOOK_SLUG_SEGMENT_RE.sub(r"\1<slug>", path)
    return scrub_text(path, 200)


def sanitize_scalar(value: object, max_len: int = 500):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [sanitize_scalar(item, max_len=200) for item in list(value)[:10]]
    return scrub_text(value, max_len=max_len)


def sanitize_context(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, object] = {}
    for key, val in raw.items():
        if key not in ALLOWED_CONTEXT_KEYS:
            continue
        if key in ("stack", "component_stack"):
            cleaned = scrub_stack(val, max_len=1600)
        elif key == "error_message":
            cleaned = scrub_untrusted_error(val, max_len=400)
        else:
            cleaned = sanitize_scalar(val, max_len=400)
        if cleaned not in ("", None, []):
            out[key] = cleaned
    return out


def sanitize_breadcrumbs(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[-15:]:
        if not isinstance(item, dict):
            continue
        entry: dict[str, object] = {}
        for key in ALLOWED_BREADCRUMB_KEYS:
            if key in item and item[key] is not None:
                if key == "detail":
                    entry[key] = scrub_untrusted_error(item[key], max_len=160)
                else:
                    entry[key] = sanitize_scalar(item[key], max_len=160)
        if entry:
            out.append(entry)
    return out


def format_build_label(platform: str, channel: str, app_build: str) -> str:
    p = (platform or "").strip().lower()
    c = (channel or "").strip().lower()
    b = (app_build or "").strip()
    parts = [x for x in (p, c, b[:12] if b else "") if x]
    return ":".join(parts)[:80]


def make_fingerprint(source: str, kind: str, code: str, route: str, title: str) -> str:
    basis = "|".join([
        (source or "").strip().lower(),
        (kind or "").strip().lower(),
        (code or "").strip().lower(),
        normalize_route(route),
        scrub_text(title, 120).lower() if code in ("unhandled_exception", "client_error", "react_render", "js_error") else "",
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:40]
