"""
Keeping the server's storage tidy. Only things that are not learners' data are removed:

- temporary data: expired sign-in codes, old rate-limit counters, sessions signed out or expired long ago, and
  half-finished file imports;
- old chapter versions: every version of the last 30 days stays, older ones keep one a week (and the newest always);
- pictures no chapter, question, flashcard, version, cover or banner uses any more, once they are a month old.

Run nightly with `python manage.py nightly_cleanup`; the panel's «فضای سرور» page shows the last runs and can start one.
"""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

TEMP_SESSION_DAYS = 90
KEEP_ALL_REVISIONS_DAYS = 30
ORPHAN_IMAGE_DAYS = 30
PENDING_IMPORT_HOURS = 24


def cleanup_temporary(now=None) -> dict:
    from apps.accounts.models import DeviceSession, OTPCode, PanelLoginCode, RateBucket
    from apps.study.models import FlashcardReviewOp, StudyTimeReport

    now = now or timezone.now()
    codes = OTPCode.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()[0]
    # One-time panel → web app codes live a minute; a day later they are only clutter.
    codes += PanelLoginCode.objects.filter(created_at__lt=now - timedelta(days=1)).delete()[0]
    buckets = RateBucket.objects.filter(window_start__lt=now - timedelta(days=2)).delete()[0]
    old = now - timedelta(days=TEMP_SESSION_DAYS)
    sessions = DeviceSession.objects.filter(revoked_at__lt=old).delete()[0] + DeviceSession.objects.filter(
        revoked_at__isnull=True, expires_at__lt=old
    ).delete()[0]
    pending = 0
    folder = os.path.join(settings.MEDIA_ROOT, "imports", "pending")
    if os.path.isdir(folder):
        limit = (now - timedelta(hours=PENDING_IMPORT_HOURS)).timestamp()
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < limit:
                    os.remove(path)
                    pending += 1
            except FileNotFoundError:
                pass
    ops = FlashcardReviewOp.objects.filter(created_at__lt=now - timedelta(days=30)).delete()[0]
    ops += StudyTimeReport.objects.filter(created_at__lt=now - timedelta(days=35)).delete()[0]
    return {"codes": codes, "rate_counters": buckets, "sessions": sessions, "pending_imports": pending, "review_ids": ops}


def prune_revisions(now=None) -> int:
    """Older than 30 days: keep the newest version of each week of each chapter (and each chapter's newest of all)."""
    from .models import ChapterRevision

    now = now or timezone.now()
    cutoff = now - timedelta(days=KEEP_ALL_REVISIONS_DAYS)
    newest = {}
    for cid, rid in ChapterRevision.objects.order_by("-updated_at", "-id").values_list("chapter_id", "id"):
        newest.setdefault(cid, rid)
    kept_weeks: set[tuple[int, int, int]] = set()
    remove = []
    for rid, cid, at in ChapterRevision.objects.filter(updated_at__lt=cutoff).order_by("-updated_at", "-id").values_list("id", "chapter_id", "updated_at"):
        if newest.get(cid) == rid:
            continue
        year, week, _ = timezone.localtime(at).isocalendar()
        if (cid, year, week) in kept_weeks:
            remove.append(rid)
        else:
            kept_weeks.add((cid, year, week))
    if remove:
        ChapterRevision.objects.filter(pk__in=remove).delete()
    return len(remove)


_REF = re.compile(r"media:([^)\s\"']+)")


def _used_files() -> set[str]:
    from apps.learning.models import Choice, Flashcard, Question

    from .models import Banner, ChapterRevision, ContentNode

    used: set[str] = set()

    def scan(values):
        for text in values:
            if text:
                used.update(_REF.findall(text))

    scan(ContentNode.objects.values_list("full_body", flat=True))
    scan(ContentNode.objects.values_list("summary_body", flat=True))
    scan(ContentNode.objects.values_list("about", flat=True))
    for field in ("stem", "explanation", "quick_solution", "alternative_view"):
        scan(Question.objects.values_list(field, flat=True))
    scan(x.get("body", "") for items in Question.objects.values_list("solutions", flat=True) for x in (items or []))
    scan(Choice.objects.values_list("text", flat=True))
    scan(Flashcard.objects.values_list("point", flat=True))
    scan(ChapterRevision.objects.values_list("text", flat=True).iterator())
    # Past exams keep their own copy of each question (pictures included), so a learner's report card never breaks.
    from apps.study.models import ExamAttempt

    for snap in ExamAttempt.objects.values_list("snapshot", flat=True).iterator():
        if snap:
            used.update(_REF.findall(json.dumps(snap, ensure_ascii=False)))
    used.update(p for p in ContentNode.objects.exclude(cover="").values_list("cover", flat=True))
    used.update(p for p in Banner.objects.exclude(image="").values_list("image", flat=True))
    return used


def orphan_images(now=None, delete=True) -> dict:
    """Pictures under content/, covers/ and banners/ that nothing uses, older than a month."""
    now = now or timezone.now()
    limit = (now - timedelta(days=ORPHAN_IMAGE_DAYS)).timestamp()
    used = _used_files()
    count = size = 0
    for top in ("content", "covers", "banners"):
        root = os.path.join(settings.MEDIA_ROOT, top)
        for folder, _, files in os.walk(root):
            for name in files:
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, settings.MEDIA_ROOT).replace(os.sep, "/")
                if rel in used or os.path.getmtime(path) >= limit:
                    continue
                try:
                    bytes_ = os.path.getsize(path)
                    if delete:
                        os.remove(path)
                except FileNotFoundError:
                    continue
                count += 1
                size += bytes_
    return {"files": count, "bytes": size}


def run_all(run=None) -> dict:
    from django.db import transaction

    from .models import CleanupRun

    now = timezone.now()
    with transaction.atomic():
        summary = {**cleanup_temporary(now), "revisions": prune_revisions(now)}
    images = orphan_images(now)
    summary["images"], summary["image_bytes"] = images["files"], images["bytes"]
    if run is None:
        run = CleanupRun.objects.create(summary=summary)
    else:
        CleanupRun.objects.filter(pk=run.pk).update(summary=summary)
    return summary


def _folder_size(path) -> tuple[int, int]:
    total = files = 0
    for folder, _, names in os.walk(path):
        for n in names:
            try:
                total += os.path.getsize(os.path.join(folder, n))
                files += 1
            except OSError:
                pass
    return total, files


def storage_report() -> dict:
    """What takes room: the database (by table where the database can tell), media folders, chapter versions."""
    from django.apps import apps as django_apps

    from .models import ChapterRevision

    tables = []
    for model in django_apps.get_models():
        table = model._meta.db_table
        try:
            rows = model.objects.count()
        except Exception:  # noqa: BLE001 — a table missing on this database is simply skipped
            continue
        size = None
        if connection.vendor == "postgresql":
            with connection.cursor() as c:
                c.execute("SELECT pg_total_relation_size(%s)", [table])
                size = c.fetchone()[0]
        tables.append({"name": str(model._meta.verbose_name_plural), "table": table, "rows": rows, "bytes": size})
    tables.sort(key=lambda t: (t["bytes"] or 0, t["rows"]), reverse=True)
    db_bytes = None
    if connection.vendor == "sqlite":
        name = connection.settings_dict.get("NAME")
        db_bytes = os.path.getsize(name) if name and os.path.exists(str(name)) else None
    elif connection.vendor == "postgresql":
        with connection.cursor() as c:
            c.execute("SELECT pg_database_size(current_database())")
            db_bytes = c.fetchone()[0]
    folders = []
    for top in ("content", "covers", "banners", "apk", "imports"):
        size, files = _folder_size(os.path.join(settings.MEDIA_ROOT, top))
        folders.append({"name": top, "bytes": size, "files": files})
    revisions = ChapterRevision.objects.count()
    revision_chars = sum(len(t) for t in ChapterRevision.objects.values_list("text", flat=True).iterator())
    return {"db_bytes": db_bytes, "tables": tables[:15], "folders": folders, "revisions": revisions, "revision_bytes": revision_chars * 2,
            "orphans": orphan_images(delete=False)}


def run_if_due() -> None:
    """The clean-up also runs by itself once a day when the panel is opened (for a server without a nightly job)."""
    import logging

    from .models import CleanupRun

    from django.db import transaction

    # The run is recorded first, under a lock, so two staff opening the panel together (or a run that fails part way)
    # never start it again the same day; its own savepoint keeps a database error from spoiling the panel's page.
    try:
        with transaction.atomic():
            if CleanupRun.objects.select_for_update().filter(at__gte=timezone.now() - timedelta(hours=24)).exists():
                return
            run = CleanupRun.objects.create(summary={"started": True})
    except Exception:  # noqa: BLE001
        return
    try:
        with transaction.atomic():
            run_all(run)
    except Exception:  # noqa: BLE001 — tidying must never break the panel
        logging.getLogger(__name__).exception("cleanup failed")
        CleanupRun.objects.filter(pk=run.pk).update(summary={"failed": True})
