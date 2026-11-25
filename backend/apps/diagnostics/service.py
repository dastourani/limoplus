from __future__ import annotations

import logging
import traceback
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog.backups import notify_bale_after_commit
from apps.catalog.jalali import jalali_datetime

from .models import ErrorAffectedActor, ErrorEvent, ErrorGroup
from .sanitize import (
    format_build_label,
    make_fingerprint,
    normalize_route,
    sanitize_breadcrumbs,
    sanitize_context,
    scrub_text,
    server_web_commit,
    user_ref_for,
)

log = logging.getLogger(__name__)

MAX_SAMPLES_PER_GROUP = 50
EVENT_RETENTION_DAYS = 60
BALE_COOLDOWN = timedelta(hours=6)

_SEVERITY_RANK = {
    ErrorGroup.Severity.WARNING: 1,
    ErrorGroup.Severity.ERROR: 2,
    ErrorGroup.Severity.CRITICAL: 3,
}


def _trim_group_samples(group: ErrorGroup) -> None:
    stale_ids = list(
        ErrorEvent.objects.filter(group=group)
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)[MAX_SAMPLES_PER_GROUP:]
    )
    if stale_ids:
        ErrorEvent.objects.filter(id__in=stale_ids).delete()


def record_event(
    *,
    source: str,
    kind: str,
    code: str,
    title: str,
    event_id: str | None = None,
    request_id: str = "",
    op_id: str = "",
    install_id: str = "",
    user_id: int | None = None,
    user_ref: str = "",
    platform: str = "",
    channel: str = "",
    app_build: str = "",
    web_commit: str = "",
    is_offline: bool = False,
    route: str = "",
    operation: str = "",
    expected: str = "",
    observed: str = "",
    severity: str = ErrorGroup.Severity.ERROR,
    context: dict | None = None,
    breadcrumbs: list | None = None,
    created_at=None,
) -> tuple[ErrorEvent, bool]:
    """
    Idempotently records one diagnostic event into an aggregated ErrorGroup.
    Repeated delivery of the same `event_id` returns `(existing_event, False)` without incrementing counters.
    """
    clean_event_id = scrub_text(event_id or uuid.uuid4().hex, 64) or uuid.uuid4().hex
    existing = ErrorEvent.objects.select_related("group").filter(event_id=clean_event_id).first()
    if existing is not None:
        return existing, False

    clean_source = source if source in ErrorGroup.Source.values else ErrorGroup.Source.CLIENT
    clean_kind = kind if kind in ErrorGroup.Kind.values else ErrorGroup.Kind.CLIENT_ERROR
    clean_severity = severity if severity in ErrorGroup.Severity.values else ErrorGroup.Severity.ERROR
    clean_code = scrub_text(code or "unknown", 80) or "unknown"
    clean_title = scrub_text(title or clean_code, 240) or clean_code
    clean_route = normalize_route(route)
    clean_operation = scrub_text(operation, 80)
    clean_expected = scrub_text(expected, 1500)
    clean_observed = scrub_text(observed, 1500)
    clean_platform = scrub_text(platform, 20).lower()
    clean_channel = scrub_text(channel, 20).lower()
    clean_web_commit = scrub_text(web_commit, 40)
    clean_build = scrub_text(app_build or clean_web_commit, 40)
    srv_commit = server_web_commit()
    mismatch = bool(clean_platform == "web" and clean_web_commit and srv_commit and clean_web_commit != srv_commit)
    build_label = format_build_label(clean_platform or clean_source, clean_channel, clean_build)

    clean_install = scrub_text(install_id, 64)
    clean_user_ref = scrub_text(user_ref, 32) or user_ref_for(user_id)
    clean_request_id = scrub_text(request_id, 64)
    clean_op_id = scrub_text(op_id, 64)
    now = created_at or timezone.now()

    evidence: dict[str, object] = {}
    clean_ctx = sanitize_context(context or {})
    if clean_ctx:
        evidence["context"] = clean_ctx
    clean_crumbs = sanitize_breadcrumbs(breadcrumbs or [])
    if clean_crumbs:
        evidence["breadcrumbs"] = clean_crumbs

    fingerprint = make_fingerprint(clean_source, clean_kind, clean_code, clean_route, clean_title)

    with transaction.atomic():
        # Double-check inside atomic transaction in case of concurrent delivery of the same event_id.
        existing = ErrorEvent.objects.select_related("group").filter(event_id=clean_event_id).first()
        if existing is not None:
            return existing, False

        group = ErrorGroup.objects.select_for_update().filter(fingerprint=fingerprint).first()
        if group is None:
            try:
                with transaction.atomic():
                    group = ErrorGroup.objects.create(
                        fingerprint=fingerprint,
                        source=clean_source,
                        kind=clean_kind,
                        code=clean_code,
                        title=clean_title,
                        route=clean_route,
                        expected=clean_expected,
                        observed=clean_observed,
                        severity=clean_severity,
                        first_seen_at=now,
                        last_seen_at=now,
                        first_build=build_label,
                        last_build=build_label,
                    )
            except IntegrityError:
                group = ErrorGroup.objects.select_for_update().get(fingerprint=fingerprint)

        try:
            with transaction.atomic():
                event = ErrorEvent.objects.create(
                    group=group,
                    event_id=clean_event_id,
                    request_id=clean_request_id,
                    op_id=clean_op_id,
                    install_id=clean_install,
                    user_ref=clean_user_ref,
                    platform=clean_platform,
                    channel=clean_channel,
                    app_build=clean_build,
                    server_version=srv_commit,
                    version_mismatch=mismatch,
                    is_offline=bool(is_offline),
                    route=clean_route,
                    operation=clean_operation,
                    expected=clean_expected,
                    observed=clean_observed,
                    evidence=evidence,
                    created_at=now,
                )
        except IntegrityError:
            return ErrorEvent.objects.select_related("group").get(event_id=clean_event_id), False

        group.event_count += 1
        if now >= group.last_seen_at:
            group.last_seen_at = now
        if build_label:
            if not group.first_build:
                group.first_build = build_label
            group.last_build = build_label
        if clean_expected and not group.expected:
            group.expected = clean_expected
        if clean_observed:
            group.observed = clean_observed
        if _SEVERITY_RANK.get(clean_severity, 0) > _SEVERITY_RANK.get(group.severity, 0):
            group.severity = clean_severity
        if group.status == ErrorGroup.Status.RESOLVED:
            group.status = ErrorGroup.Status.OPEN
            group.resolved_at = None

        if clean_install:
            _, actor_created = ErrorAffectedActor.objects.get_or_create(
                group=group,
                actor_key=f"i:{clean_install}",
                defaults={"actor_type": "install"},
            )
            if actor_created:
                group.install_count += 1
        if clean_user_ref:
            _, actor_created = ErrorAffectedActor.objects.get_or_create(
                group=group,
                actor_key=f"u:{clean_user_ref}",
                defaults={"actor_type": "user"},
            )
            if actor_created:
                group.user_count += 1

        should_alert = (
            group.severity == ErrorGroup.Severity.CRITICAL
            and group.status == ErrorGroup.Status.OPEN
            and (group.last_bale_alert_at is None or now - group.last_bale_alert_at >= BALE_COOLDOWN)
        )
        update_fields = [
            "event_count",
            "install_count",
            "user_count",
            "last_seen_at",
            "first_build",
            "last_build",
            "expected",
            "observed",
            "severity",
            "status",
            "resolved_at",
        ]
        if should_alert:
            group.last_bale_alert_at = now
            update_fields.append("last_bale_alert_at")

        group.save(update_fields=update_fields)
        _trim_group_samples(group)

        if should_alert:
            msg = (
                f"🚨 پایش لیموخوان ({group.get_source_display()})\n"
                f"عنوان: {group.title}\n"
                f"کد: {group.code}\n"
                f"مسیر: {group.route or '—'}\n"
                f"نسخه: {group.last_build or '—'}"
            )
            notify_bale_after_commit(msg, log_label=f"Bale diagnostics alert {group.code}")

    return event, True


def record_server_exception(request, exc: Exception) -> ErrorEvent | None:
    """Safely persists an unhandled server exception without ever masking the original 500."""
    tb_tail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-6:])
    user = getattr(request, "user", None)
    user_id = user.pk if getattr(user, "is_authenticated", False) else None
    platform = (request.headers.get("X-App-Platform") or "").strip().lower() or "server"
    channel = (request.headers.get("X-App-Channel") or "").strip().lower()
    app_build = (request.headers.get("X-App-Build") or "").strip()
    web_commit = (request.headers.get("X-App-Web-Commit") or "").strip()
    install_id = (request.headers.get("X-App-Install-Id") or "").strip()
    op_id = (request.headers.get("X-App-Op-Id") or "").strip()
    req_id = getattr(request, "diagnostics_request_id", "") or (request.headers.get("X-Request-Id") or "").strip()

    try:
        event, _ = record_event(
            source=ErrorGroup.Source.SERVER,
            kind=ErrorGroup.Kind.EXCEPTION,
            code="unhandled_exception",
            title=f"{type(exc).__name__}: {scrub_text(exc, 160) or 'خطای پیش‌بینی‌نشده'}",
            request_id=req_id,
            op_id=op_id,
            install_id=install_id,
            user_id=user_id,
            platform=platform,
            channel=channel,
            app_build=app_build,
            web_commit=web_commit,
            route=getattr(request, "path", ""),
            operation=f"{getattr(request, 'method', 'GET')} {normalize_route(getattr(request, 'path', ''))}",
            expected="درخواست بدون خطای پیش‌بینی‌نشده و وضعیت ۵۰۰ پاسخ داده شود.",
            observed=f"استثنای {type(exc).__name__} در سرور رخ داد.",
            severity=ErrorGroup.Severity.CRITICAL,
            context={
                "status_code": 500,
                "method": getattr(request, "method", ""),
                "exception_type": type(exc).__name__,
                "error_message": scrub_text(exc, 300),
                "stack": tb_tail,
            },
        )
        return event
    except Exception:  # noqa: BLE001 — diagnostics must never mask or crash exception handling
        log.exception("Failed to store server exception in diagnostics")
        return None


def prune_old_events(now=None) -> int:
    """Deletes sample ErrorEvents older than EVENT_RETENTION_DAYS while keeping the newest sample per group."""
    now = now or timezone.now()
    cutoff = now - timedelta(days=EVENT_RETENTION_DAYS)
    keep_ids: set[int] = set()
    for gid in ErrorGroup.objects.values_list("id", flat=True):
        latest_id = ErrorEvent.objects.filter(group_id=gid).order_by("-created_at", "-id").values_list("id", flat=True).first()
        if latest_id:
            keep_ids.add(latest_id)
    qs = ErrorEvent.objects.filter(created_at__lt=cutoff)
    if keep_ids:
        qs = qs.exclude(id__in=keep_ids)
    return qs.delete()[0]


def build_ai_report(group: ErrorGroup) -> str:
    """Formats a structured, PII-free Persian/technical case file ready to paste to an AI coding assistant."""
    samples = list(group.events.order_by("-created_at", "-id")[:3])
    latest = samples[0] if samples else None
    mismatch_count = sum(1 for s in samples if s.version_mismatch)
    offline_count = sum(1 for s in samples if s.is_offline)

    scope_parts = [
        f"منبع: {group.get_source_display()} ({group.kind})",
        f"شدت: {group.get_severity_display()}",
        f"کد: {group.code}",
        f"مسیر: {group.route or 'نامشخص'}",
        f"نسخهٔ اول/آخر: {group.first_build or 'نامشخص'} ← {group.last_build or 'نامشخص'}",
        f"آمار: {group.event_count} رخداد، {group.install_count} نصب درگیر، {group.user_count} کاربر درگیر",
    ]
    if latest and latest.server_version:
        scope_parts.append(f"نسخهٔ سرور در نمونهٔ آخر: {latest.server_version}")
    if mismatch_count:
        scope_parts.append(f"سرنخ مهم: در {mismatch_count} از {len(samples)} نمونهٔ اخیر، نسخهٔ وب‌اپ با نسخهٔ سرور متفاوت بوده است (احتمال کش قدیمی).")
    if offline_count:
        scope_parts.append(f"وضعیت اتصال: {offline_count} از {len(samples)} نمونهٔ اخیر در حالت آفلاین ثبت شده است.")

    evidence_lines: list[str] = []
    unknowns: list[str] = []
    if not samples:
        unknowns.append("هیچ نمونهٔ خامی باقی نمانده است.")
    for idx, s in enumerate(samples, 1):
        meta = [
            f"زمان: {jalali_datetime(s.created_at)}",
            f"event_id={s.event_id}",
            f"build={s.app_build or s.platform or 'نامشخص'}",
        ]
        if s.request_id:
            meta.append(f"request_id={s.request_id}")
        if s.op_id:
            meta.append(f"op_id={s.op_id}")
        if s.user_ref:
            meta.append(f"user_ref={s.user_ref}")
        if s.install_id:
            meta.append(f"install={s.install_id[:12]}")
        if s.version_mismatch:
            meta.append("web_version_mismatch=True")
        if s.is_offline:
            meta.append("offline=True")
        evidence_lines.append(f"- نمونه {idx}: " + " | ".join(meta))
        ctx = (s.evidence or {}).get("context") or {}
        if ctx:
            for k, v in ctx.items():
                if k == "unknowns":
                    unknowns.append(str(v))
                elif k in ("stack", "component_stack"):
                    evidence_lines.append(f"  {k}:\n    " + str(v).replace("\n", "\n    "))
                else:
                    evidence_lines.append(f"  {k}: {v}")
        crumbs = (s.evidence or {}).get("breadcrumbs") or []
        if crumbs:
            trail = " ← ".join(f"{c.get('type', '')}:{c.get('name', '')}({c.get('detail', '')})".strip("()") for c in crumbs[-8:])
            evidence_lines.append(f"  مسیر رویدادهای پیش از خطا: {trail}")

    if latest and not latest.request_id and group.source == ErrorGroup.Source.CLIENT:
        unknowns.append("پاسخ سرور در این رخداد دریافت نشده یا درخواست اصلاً به سرور نرسیده است (نامعلوم).")
    if not group.expected:
        unknowns.append("انتظار صریح محصول برای این رخداد ثبت نشده است.")

    sections = [
        f"عنوان: {group.title}",
        "دامنه و نسخه:\n" + "\n".join(f"- {p}" for p in scope_parts),
        f"انتظار محصول:\n{group.expected or 'نامشخص — رفتار طبیعی بدون خطا و سازگار با قواعد محصول.'}",
        f"مشاهدهٔ واقعی:\n{group.observed or (latest.observed if latest else '') or group.title}",
        "شواهد قطعی:\n" + ("\n".join(evidence_lines) if evidence_lines else "- موردی ثبت نشده است."),
        "موارد نامعلوم:\n" + ("\n".join(f"- {u}" for u in dict.fromkeys(unknowns)) if unknowns else "- مورد خاص نامعلومی ثبت نشده است."),
        f"بازه‌ی زمانی: از {jalali_datetime(group.first_seen_at)} تا {jalali_datetime(group.last_seen_at)}",
        "درخواست از هوش مصنوعی:\nشواهد قطعی را از فرضیه جدا کن، مسیر کد مرتبط را در همین نسخه بررسی کن، ریشهٔ مشکل را توضیح بده و یک تست بازتولید پیشنهاد بده.",
    ]
    return "\n\n".join(sections)
