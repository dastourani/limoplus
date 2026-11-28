"""
Backups of the real server, and putting one back.

- The database every night:
  * SQLite: via SQLite's own online backup API, gzipped into BACKUP_DIR.
  * PostgreSQL: via `pg_dump --format=custom` (consistent snapshot, `.dump`), falling back to `dumpdata` JSON inside
    a `REPEATABLE READ READ ONLY` transaction when `pg_dump` is not installed.
- Pictures and files (MEDIA_ROOT) once a week: only what changed since the last media backup, as zip parts.
- Delivery destination (`BACKUP_STORAGE_MODE`):
  * `bale_chunks` (default): send directly or in <=45 MB split parts to Bale.
  * `object_storage`: upload to S3-compatible object storage (e.g. ParsPack / Arvan) with automatic pruning.
  * `both`: upload to S3 object storage AND send to Bale.
- Restore (panel «فضای سرور», superusers only): accepts `.sqlite3`, `.sqlite3.gz`, `.dump` (PostgreSQL `pg_restore`),
  `.sql.gz`, `.json`/`.json.gz`, `.zip`, or split `.partXofY` chunks.

`python manage.py nightly` runs what is due; `nightly --loop` (started by gunicorn.conf.py when NIGHTLY_JOBS is on)
does so every hour in its own process.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import requests
from django.conf import settings
from django.db import connection, connections, transaction
from django.utils import timezone
from django.utils._os import safe_join

log = logging.getLogger(__name__)

KEEP_DB = 7
DB_EVERY = timedelta(hours=23)
DB_LATE = timedelta(hours=30)  # missed the night window (server was down): do it whenever
MEDIA_EVERY = timedelta(days=7)
NIGHT_HOURS = range(2, 7)  # Tehran time
PART_LIMIT = 45 * 1024 * 1024  # under Bale's bot upload limit
SKIP_MEDIA = ("apk/", "imports/")
MAX_RESTORE_BYTES = 8 * 1024**3  # uncompressed total of one upload
VALID_STORAGE_MODES = ("bale_chunks", "object_storage", "both")


class RestoreError(Exception):
    pass


def _safe(exc) -> str:
    """An error's text without secrets (Bale token or S3 secret key)."""
    text = str(exc)
    for secret in (
        getattr(settings, "BALE_BOT_TOKEN", ""),
        getattr(settings, "BACKUP_S3_SECRET_KEY", ""),
        getattr(settings, "BACKUP_S3_ACCESS_KEY", ""),
    ):
        if secret:
            text = text.replace(secret, "***")
    return text[:1000]


def backup_dir() -> Path:
    path = Path(settings.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp(now=None) -> str:
    return timezone.localtime(now or timezone.now()).strftime("%Y%m%d-%H%M")


def _unique_stamp(now=None) -> str:
    return f"{timezone.localtime(now or timezone.now()).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


# --- Storage destinations (Bale & S3-compatible object storage) ---------------------------------------------------


def storage_mode() -> str:
    mode = str(getattr(settings, "BACKUP_STORAGE_MODE", "bale_chunks") or "bale_chunks").strip().lower()
    return mode if mode in VALID_STORAGE_MODES else "bale_chunks"


def bale_ready() -> bool:
    return bool(settings.BALE_BOT_TOKEN and settings.BALE_CHAT_ID)


def object_storage_ready() -> bool:
    return bool(
        getattr(settings, "BACKUP_S3_ENDPOINT", "")
        and getattr(settings, "BACKUP_S3_BUCKET", "")
        and getattr(settings, "BACKUP_S3_ACCESS_KEY", "")
        and getattr(settings, "BACKUP_S3_SECRET_KEY", "")
    )


def storage_ready() -> bool:
    mode = storage_mode()
    if mode == "object_storage":
        return object_storage_ready()
    if mode == "both":
        return bale_ready() or object_storage_ready()
    return bale_ready()


BALE_TEXT_TIMEOUT = 8
BALE_FILE_TIMEOUT = 300
_BALE_NOTIFY_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bale-notify")


def _bale(method: str, data: dict, files=None, *, timeout: int = BALE_FILE_TIMEOUT) -> None:
    url = f"https://tapi.bale.ai/bot{settings.BALE_BOT_TOKEN}/{method}"
    response = requests.post(url, data=data, files=files, timeout=timeout)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or not body.get("ok", False):
        raise RuntimeError(f"Bale {method}: {response.status_code} {body.get('description', '')}".strip())


def send_file(path: Path, caption: str) -> None:
    with open(path, "rb") as f:
        _bale("sendDocument", {"chat_id": settings.BALE_CHAT_ID, "caption": caption}, files={"document": (path.name, f)}, timeout=BALE_FILE_TIMEOUT)


def send_text(text: str) -> None:
    _bale("sendMessage", {"chat_id": settings.BALE_CHAT_ID, "text": text}, timeout=BALE_TEXT_TIMEOUT)


def send_to_bale_in_chunks(path: Path, caption: str) -> str:
    """Send a backup file to Bale, splitting into <= PART_LIMIT pieces when necessary."""
    if path.stat().st_size > PART_LIMIT:
        pieces = split_file(path, PART_LIMIT)
        try:
            for i, piece in enumerate(pieces, 1):
                send_file(
                    piece,
                    f"{caption}\nتکه‌ی {i} از {len(pieces)}: برای بازگردانی همه‌ی تکه‌ها را یکی‌یکی بارگذاری کنید.",
                )
        finally:
            for piece in pieces:
                piece.unlink(missing_ok=True)
        return f"{len(pieces)} تکه در بله"
    send_file(path, caption)
    return ""


def _s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.BACKUP_S3_ENDPOINT,
        aws_access_key_id=settings.BACKUP_S3_ACCESS_KEY,
        aws_secret_access_key=settings.BACKUP_S3_SECRET_KEY,
        region_name=getattr(settings, "BACKUP_S3_REGION", "us-east-1") or "us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def upload_to_object_storage(path: Path, kind: str) -> str:
    """Upload a backup artifact to S3-compatible object storage (e.g. ParsPack) and prune older copies."""
    if not object_storage_ready():
        raise RuntimeError("تنظیمات فضای ابری S3 کامل نیست.")
    client = _s3_client()
    bucket = settings.BACKUP_S3_BUCKET
    prefix = str(getattr(settings, "BACKUP_S3_PREFIX", "limoplus-backups") or "").strip("/")
    folder_prefix = f"{prefix}/{kind}/" if prefix else f"{kind}/"
    key = f"{folder_prefix}{path.name}"
    client.upload_file(str(path), bucket, key)

    keep = int(getattr(settings, "BACKUP_S3_KEEP", 30) or 0)
    if keep > 0:
        item_prefix = f"{folder_prefix}limookhan-{kind}-"
        listed = client.list_objects_v2(Bucket=bucket, Prefix=item_prefix).get("Contents", [])
        stale = sorted(listed, key=lambda o: o["LastModified"], reverse=True)[keep:]
        if stale:
            client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": o["Key"]} for o in stale]})
    return key


def deliver_backup(path: Path, *, kind: str, caption: str) -> dict:
    """Deliver a generated backup according to BACKUP_STORAGE_MODE (`bale_chunks` | `object_storage` | `both`)."""
    mode = storage_mode()
    sent_bale = False
    sent_s3 = False
    notes = []
    errors = []

    if mode in ("object_storage", "both"):
        if object_storage_ready():
            try:
                key = upload_to_object_storage(path, kind)
                sent_s3 = True
                notes.append(f"S3: {key}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"S3: {_safe(exc)}")
                log.error("object storage upload failed: %s", _safe(exc))
        elif mode == "object_storage":
            raise RuntimeError("حالت BACKUP_STORAGE_MODE=object_storage است ولی متغیرهای S3 تنظیم نشده‌اند.")

    if mode in ("bale_chunks", "both") and bale_ready():
        try:
            chunk_note = send_to_bale_in_chunks(path, caption)
            sent_bale = True
            if chunk_note:
                notes.append(chunk_note)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"بله: {_safe(exc)}")
            log.error("bale backup delivery failed: %s", _safe(exc))

    if errors and not (sent_bale or sent_s3):
        raise RuntimeError("؛ ".join(errors))
    if errors:
        notes.append("خطای جزئی: " + "؛ ".join(errors))
    return {"sent": sent_bale or sent_s3, "sent_bale": sent_bale, "sent_s3": sent_s3, "note": " · ".join(notes)}


# --- Database helpers (SQLite + PostgreSQL pg_dump / pg_restore) ---------------------------------------------------


def _pg_env_and_args() -> tuple[dict[str, str], list[str]]:
    cfg = connection.settings_dict
    env = os.environ.copy()
    if cfg.get("PASSWORD"):
        env["PGPASSWORD"] = str(cfg["PASSWORD"])
    sslmode = (cfg.get("OPTIONS") or {}).get("sslmode")
    if sslmode:
        env["PGSSLMODE"] = str(sslmode)
    args = []
    if cfg.get("HOST"):
        args += ["-h", str(cfg["HOST"])]
    if cfg.get("PORT"):
        args += ["-p", str(cfg["PORT"])]
    if cfg.get("USER"):
        args += ["-U", str(cfg["USER"])]
    args += ["-d", str(cfg["NAME"])]
    return env, args


def _db_copy(target: Path) -> Path:
    """A consistent copy of the database. SQLite: .sqlite3; PostgreSQL: pg_dump custom .dump (or repeatable-read JSON)."""
    if connection.vendor == "sqlite":
        name = str(connection.settings_dict["NAME"])
        in_memory = name == ":memory:" or "mode=memory" in name
        dest = sqlite3.connect(str(target))
        if in_memory and connection.in_atomic_block:
            connection.ensure_connection()
            try:
                dest.executescript("\n".join(connection.connection.iterdump()))
            finally:
                dest.close()
            return target
        if in_memory:
            connection.ensure_connection()
            source = connection.connection
        else:
            source = sqlite3.connect(name, uri=name.startswith("file:"), timeout=30)
        try:
            source.backup(dest)
        finally:
            dest.close()
            if not in_memory:
                source.close()
        return target

    if connection.vendor == "postgresql" and shutil.which("pg_dump"):
        dump_path = target.with_suffix(".dump")
        env, conn_args = _pg_env_and_args()
        proc = subprocess.run(
            ["pg_dump", "--format=custom", "--compress=6", "--no-owner", "--no-privileges", *conn_args, "--file", str(dump_path)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            dump_path.unlink(missing_ok=True)
            raise RuntimeError(f"pg_dump failed: {(proc.stderr or proc.stdout).strip()}")
        return dump_path

    return _dump_json(target.with_suffix(".json"))


def _dump_json(json_path: Path) -> Path:
    from django.core.management import call_command

    with open(json_path, "w", encoding="utf-8") as out:
        if connection.vendor == "postgresql" and not connection.in_atomic_block:
            with transaction.atomic():
                with connection.cursor() as cur:
                    cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                call_command("dumpdata", "--natural-foreign", "--exclude=contenttypes", "--exclude=auth.permission", stdout=out)
        else:
            call_command("dumpdata", "--natural-foreign", "--exclude=contenttypes", "--exclude=auth.permission", stdout=out)
    return json_path


def export_database_json() -> Path:
    """Create a portable gzipped JSON fixture (`limookhan-db-export-...json.gz`) for cross-engine migration."""
    folder = backup_dir()
    token = uuid.uuid4().hex[:8]
    raw = folder / f".tmp-export-{token}.json"
    tmp_packed = folder / f".tmp-export-{token}.json.gz"
    packed = folder / f"limookhan-db-export-{_unique_stamp()}.json.gz"
    try:
        _dump_json(raw)
        with open(raw, "rb") as src, gzip.open(tmp_packed, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp_packed, packed)
    except Exception:
        packed.unlink(missing_ok=True)
        raise
    finally:
        raw.unlink(missing_ok=True)
        tmp_packed.unlink(missing_ok=True)
    _prune(folder, "limookhan-db-", KEEP_DB)
    return packed


def export_full_media() -> tuple[Path | None, int]:
    """Archive every file under MEDIA_ROOT (excluding apk/ and imports/) into a single restore-ready .zip."""
    files = _media_files(since=None)
    if not files:
        return None, 0
    folder = backup_dir()
    tmp_zip = folder / f".tmp-media-{uuid.uuid4().hex[:8]}.zip"
    out = folder / f"limookhan-media-full-{_unique_stamp()}.zip"
    try:
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_STORED) as archive:
            for path, rel in files:
                archive.write(path, "media/" + rel)
        os.replace(tmp_zip, out)
    except Exception:
        out.unlink(missing_ok=True)
        raise
    finally:
        tmp_zip.unlink(missing_ok=True)
    _prune(folder, "limookhan-media-full-", 2)
    return out, len(files)


def backup_database(send=True):
    from .models import BackupRun

    run = BackupRun.objects.create(kind=BackupRun.Kind.DB)
    folder = backup_dir()
    try:
        raw = _db_copy(folder / f"limookhan-db-{_stamp()}.sqlite3")
        if raw.suffix == ".dump":
            packed = raw
        else:
            packed = raw.with_name(raw.name + ".gz")
            try:
                with open(raw, "rb") as src, gzip.open(packed, "wb", compresslevel=6) as dst:
                    shutil.copyfileobj(src, dst)
            finally:
                raw.unlink(missing_ok=True)
        run.files, run.size, run.ok = [packed.name], packed.stat().st_size, True
        _prune(folder, "limookhan-db-", KEEP_DB)
        if send and storage_ready():
            caption = f"🗄 پشتیبان دیتابیس لیموخوان\n{_stamp()}\nاطلاعات کاربران در آن است؛ جای دیگری نفرستید."
            delivery = deliver_backup(packed, kind="db", caption=caption)
            run.sent = delivery["sent"]
            if delivery["note"]:
                run.note = delivery["note"]
    except Exception as exc:  # noqa: BLE001 — recorded and reported, never silent
        log.error("database backup failed: %s: %s", type(exc).__name__, _safe(exc))
        run.note = _safe(exc)
        _report_failure("دیتابیس", exc, send)
    run.save()
    return run


PIECE = re.compile(
    r"^(?P<base>.+\.(?:sqlite3\.gz|dump|sql\.gz|json\.gz))\.part(?P<n>\d{1,3})of(?P<m>\d{1,3})$"
)


def split_file(path: Path, size: int) -> list[Path]:
    """`name.<ext>.part1of3`, … : plain byte pieces of the file, next to it."""
    total = path.stat().st_size
    count = max(1, -(-total // size))
    pieces = []
    with open(path, "rb") as src:
        for i in range(1, count + 1):
            piece = path.with_name(f"{path.name}.part{i}of{count}")
            with open(piece, "wb") as out:
                left = size
                while left and (chunk := src.read(min(left, 1024 * 1024))):
                    out.write(chunk)
                    left -= len(chunk)
            pieces.append(piece)
    return pieces


def _media_files(since):
    root = Path(settings.MEDIA_ROOT)
    if not root.exists():
        return []
    limit = since.timestamp() if since else 0
    found = []
    for folder, _, names in os.walk(root):
        for name in names:
            path = Path(folder) / name
            rel = path.relative_to(root).as_posix()
            if rel.startswith(SKIP_MEDIA) or path.is_symlink():
                continue
            try:
                if path.stat().st_mtime > limit:
                    found.append((path, rel))
            except FileNotFoundError:
                continue
    return sorted(found, key=lambda x: x[1])


def backup_media(send=True):
    from .models import BackupRun

    last = BackupRun.objects.filter(kind=BackupRun.Kind.MEDIA, ok=True).order_by("-at").first()
    # A little overlap: a file put in place just as the last run scanned is taken again rather than missed.
    since = last.at - timedelta(minutes=30) if last else None
    run = BackupRun.objects.create(kind=BackupRun.Kind.MEDIA, since=since)
    folder = backup_dir()
    try:
        files = _media_files(since)
        parts, part, part_size = [], None, 0
        for path, rel in files:
            size = path.stat().st_size
            if part is None or (part_size and part_size + size > PART_LIMIT):
                if part:
                    part.close()
                name = folder / f"limookhan-media-{_stamp()}-{len(parts) + 1}.zip"
                part, part_size = zipfile.ZipFile(name, "w", zipfile.ZIP_STORED), 0  # pictures are already compressed
                parts.append(name)
            part.write(path, "media/" + rel)
            part_size += size
        if part:
            part.close()
        run.files = [p.name for p in parts]
        run.size = sum(p.stat().st_size for p in parts)
        run.ok = True
        run.note = f"{len(files)} فایل" + ("" if since else " (اولین پشتیبان: همه‌ی فایل‌ها)")
        if send and storage_ready() and parts:
            mode = storage_mode()
            use_s3 = mode in ("object_storage", "both") and object_storage_ready()
            use_bale = mode in ("bale_chunks", "both") and bale_ready()
            kept = []
            delivered = 0
            for i, p in enumerate(parts, 1):
                part_sent_s3 = False
                part_sent_bale = False
                if use_s3:
                    upload_to_object_storage(p, "media")
                    part_sent_s3 = True
                if use_bale:
                    if p.stat().st_size > PART_LIMIT + 5 * 1024 * 1024:  # one file bigger than a part: it stays here if not in S3
                        if not part_sent_s3:
                            send_text(f"⚠️ بخش {i} پشتیبان عکس‌ها برای بله بزرگ است؛ روی سرور در پوشه‌ی backups مانده: {p.name}")
                            kept.append(p.name)
                    else:
                        send_file(p, f"🖼 پشتیبان عکس‌ها و فایل‌های لیموخوان\n{_stamp()} — بخش {i} از {len(parts)}")
                        part_sent_bale = True
                if part_sent_s3 or part_sent_bale:
                    delivered += 1
                if p.name not in kept:
                    p.unlink(missing_ok=True)
            run.sent = delivered == len(parts) and not kept
            if kept:
                run.note += f"؛ روی سرور مانده: {', '.join(kept)}"
        _prune(folder, "limookhan-media-", 20)
    except Exception as exc:  # noqa: BLE001
        log.error("media backup failed: %s: %s", type(exc).__name__, _safe(exc))
        run.ok = False
        run.note = _safe(exc)
        _report_failure("عکس‌ها", exc, send)
    run.save()
    return run


def _prune(folder: Path, prefix: str, keep: int) -> None:
    old = sorted(folder.glob(prefix + "*"), key=lambda p: p.stat().st_mtime, reverse=True)[keep:]
    for p in old:
        p.unlink(missing_ok=True)


def _report_failure(what: str, exc: Exception, send: bool) -> None:
    if send and bale_ready():
        try:
            send_text(f"❌ پشتیبان {what} لیموخوان انجام نشد: {_safe(exc)[:300]}")
        except Exception as again:  # noqa: BLE001
            log.error("could not report the failed backup to Bale: %s", _safe(again))


def local_backups() -> list[dict]:
    """Database copies kept on this server (nightly ones and the copies made before each restore), newest first."""
    folder = backup_dir()
    files = [p for p in folder.iterdir() if p.is_file() and (p.name.startswith("limookhan-db-") or p.name.startswith("before-restore-"))]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": p.name, "size": p.stat().st_size, "at": timezone.datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.get_current_timezone()),
         "before_restore": p.name.startswith("before-restore-")}
        for p in files
    ]


def local_backup_path(name: str) -> Path:
    """Only a file from local_backups() (never a path given by the request)."""
    for item in local_backups():
        if item["name"] == name:
            return backup_dir() / item["name"]
    raise RestoreError("این پشتیبان روی سرور پیدا نشد.")


def _decompress_gz(source: Path, dest: Path) -> Path:
    room = min(MAX_RESTORE_BYTES, int(shutil.disk_usage(backup_dir()).free * 0.8))
    try:
        with gzip.open(source, "rb") as src, open(dest, "wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
                if dst.tell() > room:
                    raise RestoreError("فایل بازشده بیش از حد بزرگ است یا جای دیسک کافی نیست.")
    except RestoreError:
        raise
    except (OSError, EOFError) as exc:
        raise RestoreError("فایل gz خراب است.") from exc
    return dest


def restore_local(name: str) -> str:
    path = local_backup_path(name)
    lower = path.name.lower()
    with tempfile.TemporaryDirectory(dir=backup_dir()) as tmp:
        tmp_dir = Path(tmp)
        if lower.endswith(".dump"):
            return _restore_postgres_dump(path)
        if lower.endswith(".sql.gz"):
            return _restore_sql_file(_decompress_gz(path, tmp_dir / "backup.sql"))
        if lower.endswith(".json.gz"):
            return _restore_json_file(_decompress_gz(path, tmp_dir / "backup.json"))
        if lower.endswith(".json"):
            return _restore_json_file(path)
        if lower.endswith(".gz"):
            db = _decompress_gz(path, tmp_dir / "db.sqlite3")
            return _restore_db(db)
        db = tmp_dir / "db.sqlite3"
        shutil.copyfile(path, db)
        return _restore_db(db)


def disk() -> dict:
    """Room on the disk that holds the database and the pictures."""
    usage = shutil.disk_usage(backup_dir())
    return {"total": usage.total, "used": usage.used, "free": usage.free, "percent": round(usage.used / usage.total * 100) if usage.total else 0}


DISK_WARN = 80


def check_disk() -> None:
    """Once a day, a message in Bale when the disk is over DISK_WARN percent full."""
    info = disk()
    if info["percent"] < DISK_WARN or not bale_ready():
        return
    marker = backup_dir() / ".disk-warned"
    today = timezone.localdate().isoformat()
    if marker.exists() and marker.read_text() == today:
        return
    send_text(f"⚠️ دیسک سرور لیموخوان {info['percent']}٪ پر است ({info['free'] // 1048576} مگابایت خالی). فضای دیسک را در پارس‌پک بیشتر کنید.")
    marker.write_text(today)


def next_db_backup(now=None):
    """Roughly when the next nightly database backup happens (Tehran time), for the panel."""
    from .models import BackupRun

    now = timezone.localtime(now or timezone.now())
    last = BackupRun.objects.filter(kind=BackupRun.Kind.DB, ok=True).order_by("-at").first()
    if last is None or now - last.at > DB_LATE:
        return now
    earliest = timezone.localtime(last.at + DB_EVERY)
    start = earliest if earliest.hour in NIGHT_HOURS else earliest.replace(hour=NIGHT_HOURS[0], minute=0)
    if start < earliest:
        start += timedelta(days=1)
    return start


def run_due(now=None, force=False) -> list[str]:
    """What the hourly job does: the nightly clean-up, the nightly database backup, the weekly media backup."""
    from .maintenance import run_if_due
    from .models import BackupRun

    now = now or timezone.now()
    done = []
    run_if_due()
    try:
        check_disk()
    except Exception as exc:  # noqa: BLE001
        log.error("disk check failed: %s", _safe(exc))
    last_db = BackupRun.objects.filter(kind=BackupRun.Kind.DB, ok=True).order_by("-at").first()
    age = now - last_db.at if last_db else None
    night = timezone.localtime(now).hour in NIGHT_HOURS
    if force or age is None or age > DB_LATE or (age > DB_EVERY and night):
        backup_database()
        done.append("db")
    # Media live on this same disk; a copy here adds nothing, so they are only backed up when an external storage is ready.
    last_media = BackupRun.objects.filter(kind=BackupRun.Kind.MEDIA, ok=True).order_by("-at").first()
    if storage_ready() and (force or last_media is None or (now - last_media.at > MEDIA_EVERY and night)):
        backup_media()
        done.append("media")
    try:
        from apps.guard.alerts import nightly

        if nightly(now):
            done.append("guard-summary")
    except Exception as exc:  # noqa: BLE001
        log.error("guard summary failed: %s", _safe(exc))
    try:
        from .waitlist_sms import retry_stuck

        if retry_stuck():
            done.append("waitlist-sms")
    except Exception as exc:  # noqa: BLE001
        log.error("waitlist SMS retry failed: %s", _safe(exc))
    try:
        from apps.commerce.management.commands.check_expiring_entitlements import check_and_notify_expiring_entitlements

        expiring_res = check_and_notify_expiring_entitlements(now=now)
        if expiring_res["notified_count"] > 0:
            done.append("expiring-entitlements")
    except Exception as exc:  # noqa: BLE001
        log.error("expiring entitlements check failed: %s", _safe(exc))
    try:
        from apps.commerce.royalty import reconcile_missing_royalties

        rec_res = reconcile_missing_royalties()
        if rec_res["snapshots_created"] or rec_res["wallets_credited"]:
            done.append(f"royalty-reconcile({rec_res['snapshots_created']},{rec_res['wallets_credited']})")
    except Exception as exc:  # noqa: BLE001
        log.error("royalty reconciliation failed: %s", _safe(exc))
    try:
        from apps.commerce.wallet import release_pending_balances

        released_count = release_pending_balances(now=now)
        if released_count > 0:
            done.append(f"royalty-release({released_count})")
    except Exception as exc:  # noqa: BLE001
        log.error("royalty holds release failed: %s", _safe(exc))
    try:
        from apps.diagnostics.checks import run_all_health_checks_if_due

        health_runs = run_all_health_checks_if_due(now=now, force=force)
        found = sum(r.issues_found for r in health_runs if r.completed)
        if found > 0:
            done.append(f"health-checks({found})")
    except Exception as exc:  # noqa: BLE001
        log.error("diagnostics health checks failed: %s", _safe(exc))
    return done


# --- Restore -------------------------------------------------------------------------------------------------------


def _check_sqlite(path: Path) -> None:
    with open(path, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise RestoreError("این فایل دیتابیس SQLite نیست.")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        applied = {(a, n) for a, n in con.execute("SELECT app, name FROM django_migrations")}
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RestoreError("فایل دیتابیس خراب است.")
    except sqlite3.DatabaseError as exc:
        raise RestoreError("این فایل دیتابیس لیموخوان نیست.") from exc
    finally:
        con.close()
    # A copy from a newer version of the code (migrations this server does not have) would break: refuse it.
    from django.db.migrations.loader import MigrationLoader

    known = set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
    ours = {app for app, _ in known}
    unknown = sorted(f"{a}.{n}" for a, n in applied if a in ours and (a, n) not in known)
    if unknown:
        raise RestoreError("این دیتابیس از نسخه‌ی تازه‌تر برنامه است (" + "، ".join(unknown[:3]) + ")؛ اول کد سرور را به‌روز کنید.")


def _match_page_size(path: Path, live: str) -> None:
    """SQLite cannot copy into a database in WAL mode with another page size: give the upload the live one."""
    with sqlite3.connect(live) as con:
        size = con.execute("PRAGMA page_size").fetchone()[0]
    con = sqlite3.connect(str(path))
    try:
        if con.execute("PRAGMA page_size").fetchone()[0] != size:
            con.execute("PRAGMA journal_mode=DELETE")
            con.execute(f"PRAGMA page_size={int(size)}")
            con.execute("VACUUM")
    finally:
        con.close()


def _restore_db(path: Path) -> str:
    if connection.vendor != "sqlite":
        raise RestoreError("فایل .sqlite3 فقط روی دیتابیس SQLite قابل بازگردانی است؛ برای PostgreSQL فایل .dump یا .json.gz بارگذاری کنید.")
    _check_sqlite(path)
    live = str(connection.settings_dict["NAME"])
    aside = backup_dir() / f"before-restore-{timezone.localtime().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.sqlite3"
    connection.close()
    try:
        _match_page_size(path, live)
        src_live, copy = sqlite3.connect(live), sqlite3.connect(str(aside))
        try:
            src_live.backup(copy)
        finally:
            copy.close()
            src_live.close()
    except sqlite3.Error as exc:
        raise RestoreError(f"آماده‌سازی بازگردانی نشد؛ دیتابیس فعلی دست نخورد ({exc}).") from exc
    source, dest = sqlite3.connect(str(path)), sqlite3.connect(live, timeout=60)
    try:
        source.backup(dest)
    except sqlite3.Error as exc:
        raise RestoreError(f"جایگزینی نشد ({exc}). نسخه‌ی قبلی در backups/{aside.name} است.") from exc
    finally:
        dest.close()
        source.close()
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=0)
    except Exception as exc:  # noqa: BLE001
        raise RestoreError(f"دیتابیس جایگزین شد ولی به‌روزرسانی ساختارش خطا داد ({exc}). نسخه‌ی قبلی در backups/{aside.name} است.") from exc
    _prune(backup_dir(), "before-restore-", 10)
    return aside.name


def _pg_safety_copy() -> Path:
    """Create a safety pg_dump snapshot before replacing the PostgreSQL database."""
    aside = backup_dir() / f"before-restore-{timezone.localtime().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.dump"
    return _db_copy(aside)


def _restore_postgres_dump(path: Path) -> str:
    if connection.vendor != "postgresql":
        raise RestoreError("فایل .dump فقط روی دیتابیس PostgreSQL قابل بازگردانی است.")
    if not shutil.which("pg_restore"):
        raise RestoreError("ابزار pg_restore روی سرور نصب نیست.")
    with open(path, "rb") as f:
        if f.read(5) != b"PGDMP":
            raise RestoreError("این فایل پشتیبان معتبر pg_dump نیست.")

    aside = _pg_safety_copy()
    env, conn_args = _pg_env_and_args()
    connections.close_all()
    proc = subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges", "--single-transaction", *conn_args, str(path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RestoreError(
            f"بازگردانی pg_restore ناموفق بود ({(proc.stderr or proc.stdout).strip()[:300]}). نسخه‌ی قبلی در backups/{aside.name} است."
        )
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=0)
    except Exception as exc:  # noqa: BLE001
        raise RestoreError(f"دیتابیس بازگردانی شد ولی migrate خطا داد ({exc}). نسخه‌ی قبلی در backups/{aside.name} است.") from exc
    _prune(backup_dir(), "before-restore-", 10)
    return aside.name


def _restore_sql_file(path: Path) -> str:
    if connection.vendor != "postgresql":
        raise RestoreError("فایل .sql.gz فقط روی دیتابیس PostgreSQL قابل بازگردانی است.")
    if not shutil.which("psql"):
        raise RestoreError("ابزار psql روی سرور نصب نیست.")
    aside = _pg_safety_copy()
    env, conn_args = _pg_env_and_args()
    connections.close_all()
    proc = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "--single-transaction", *conn_args, "-f", str(path)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RestoreError(
            f"بازگردانی SQL ناموفق بود ({(proc.stderr or proc.stdout).strip()[:300]}). نسخه‌ی قبلی در backups/{aside.name} است."
        )
    from django.core.management import call_command

    try:
        call_command("migrate", interactive=False, verbosity=0)
    except Exception as exc:  # noqa: BLE001
        raise RestoreError(f"دیتابیس بازگردانی شد ولی migrate خطا داد ({exc}). نسخه‌ی قبلی در backups/{aside.name} است.") from exc
    _prune(backup_dir(), "before-restore-", 10)
    return aside.name


def _restore_json_file(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RestoreError("فایل JSON پشتیبان معتبر نیست.") from exc
    if not isinstance(payload, list):
        raise RestoreError("ساختار فایل JSON پشتیبان معتبر نیست.")

    aside = _db_copy(backup_dir() / f"before-restore-{timezone.localtime().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.sqlite3")
    from django.core.management import call_command

    try:
        with transaction.atomic():
            call_command("flush", interactive=False, verbosity=0)
            call_command("loaddata", str(path), verbosity=0)
        call_command("migrate", interactive=False, verbosity=0)
    except Exception as exc:  # noqa: BLE001
        raise RestoreError(f"بازگردانی JSON ناموفق بود ({exc}). نسخه‌ی قبلی در backups/{aside.name} است.") from exc
    _prune(backup_dir(), "before-restore-", 10)
    return aside.name


def _media_target(name: str) -> str | None:
    """The path inside MEDIA_ROOT for a zip entry under media/ (or backend/media/), else None."""
    name = name.replace("\\", "/").lstrip("/")
    for prefix in ("backend/media/", "media/"):
        if name.startswith(prefix):
            rel = name[len(prefix):]
            if rel and not rel.endswith("/") and ".." not in rel.split("/"):
                return rel
    return None


def _is_db_name(name: str) -> bool:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base.endswith(".sqlite3") and name.replace("\\", "/").count("/") <= 1


def _take_piece(uploaded, match) -> Path | None:
    """Keeps one piece of a split database backup in backups/incoming/<name>/. Returns the joined archive once every
    piece is there (the pieces are then removed), else None."""
    base, n, m = match["base"], int(match["n"]), int(match["m"])
    if not 1 <= n <= m <= 200 or "/" in base or "\\" in base or base.startswith("."):
        raise RestoreError("نام تکه درست نیست.")
    incoming = backup_dir() / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    old = timezone.now().timestamp() - 24 * 3600
    for stale in incoming.iterdir():  # sets left unfinished for a day are dropped
        if stale.stat().st_mtime < old:
            shutil.rmtree(stale, ignore_errors=True) if stale.is_dir() else stale.unlink(missing_ok=True)
    folder = incoming / base
    folder.mkdir(exist_ok=True)
    if any(not x.name.endswith(f"of{m}") for x in folder.iterdir()):
        shutil.rmtree(folder)  # pieces of another split of this name: start this set afresh
        folder.mkdir()
    with open(folder / f"part{n}of{m}", "wb") as out:
        for chunk in uploaded.chunks():
            out.write(chunk)
    missing = [i for i in range(1, m + 1) if not (folder / f"part{i}of{m}").exists()]
    if missing:
        return None
    joined = folder.parent / f"joined-{base}"
    try:
        with open(joined, "wb") as out:
            for i in range(1, m + 1):
                with open(folder / f"part{i}of{m}", "rb") as src:
                    shutil.copyfileobj(src, out, 1024 * 1024)
    except OSError as exc:
        joined.unlink(missing_ok=True)
        raise RestoreError("جای دیسک برای کنار هم گذاشتن تکه‌ها کافی نیست.") from exc
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return joined


class _Joined:
    """The joined pieces, handed to restore_upload like an uploaded file."""

    def __init__(self, path: Path):
        self.path, self.name = path, path.name

    def chunks(self):
        with open(self.path, "rb") as src:
            while chunk := src.read(1024 * 1024):
                yield chunk


def restore_upload(uploaded) -> dict:
    """Puts an uploaded backup back. Returns what was done; raises RestoreError with a message for the panel.
    A piece of a split database backup (…sqlite3.gz.part2of3 / …dump.part2of3) is kept until all pieces are there;
    meanwhile the result says which are still missing («waiting»)."""
    match = PIECE.match(uploaded.name.rsplit("/", 1)[-1].lower())
    if match:
        joined = _take_piece(uploaded, match)
        if joined is None:
            folder = backup_dir() / "incoming" / match["base"]
            m = int(match["m"])
            missing = [i for i in range(1, m + 1) if not (folder / f"part{i}of{m}").exists()]
            return {"db": False, "media": 0, "aside": "", "waiting": missing, "pieces": m}
        try:
            return restore_upload(_Joined(joined))
        finally:
            joined.unlink(missing_ok=True)
    result = {"db": False, "media": 0, "aside": ""}
    name = uploaded.name.lower()
    with tempfile.TemporaryDirectory(dir=backup_dir()) as tmp:
        tmp_dir = Path(tmp)
        raw = tmp_dir / "upload"
        with open(raw, "wb") as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        if name.endswith(".dump"):
            result["aside"] = _restore_postgres_dump(raw)
            result["db"] = True
        elif name.endswith(".sql.gz"):
            sql_file = _decompress_gz(raw, tmp_dir / "backup.sql")
            result["aside"] = _restore_sql_file(sql_file)
            result["db"] = True
        elif name.endswith(".json.gz"):
            json_file = _decompress_gz(raw, tmp_dir / "backup.json")
            result["aside"] = _restore_json_file(json_file)
            result["db"] = True
        elif name.endswith(".json"):
            result["aside"] = _restore_json_file(raw)
            result["db"] = True
        elif name.endswith(".gz"):
            db = _decompress_gz(raw, tmp_dir / "db.sqlite3")
            result["aside"] = _restore_db(db)
            result["db"] = True
        elif name.endswith(".sqlite3"):
            result["aside"] = _restore_db(raw)
            result["db"] = True
        elif name.endswith(".zip"):
            try:
                archive = zipfile.ZipFile(raw)
            except zipfile.BadZipFile as exc:
                raise RestoreError("فایل zip خراب است.") from exc
            with archive:
                entries = archive.infolist()
                if sum(e.file_size for e in entries) > MAX_RESTORE_BYTES:
                    raise RestoreError("حجم فایل‌های داخل zip بیش از حد است.")
                if sum(e.file_size for e in entries) > shutil.disk_usage(backup_dir()).free * 0.8:
                    raise RestoreError("جای خالی دیسک سرور کافی نیست.")
                db_entries = [e for e in entries if _is_db_name(e.filename)]
                media_entries = [(e, t) for e in entries if (t := _media_target(e.filename))]
                if not db_entries and not media_entries:
                    raise RestoreError("در zip نه db.sqlite3 پیدا شد و نه پوشه‌ی media.")
                if len(db_entries) > 1:
                    raise RestoreError("در zip بیش از یک فایل دیتابیس هست.")
                # The database first: if it is refused, nothing at all has changed.
                if db_entries:
                    db = tmp_dir / "db.sqlite3"
                    with archive.open(db_entries[0]) as src, open(db, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    result["aside"] = _restore_db(db)
                    result["db"] = True
                for entry, rel in media_entries:
                    if (entry.external_attr >> 16) & 0o170000 == 0o120000:  # a symlink
                        continue
                    target = Path(safe_join(str(settings.MEDIA_ROOT), rel))
                    if target.exists():  # only added, never overwritten (content pictures are named by their content)
                        result["skipped"] = result.get("skipped", 0) + 1
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    result["media"] += 1
        else:
            raise RestoreError("فقط فایل ‎.zip یا ‎.dump یا ‎.sql.gz یا ‎.json.gz یا ‎.sqlite3 یا ‎.sqlite3.gz")
    return result


def notify_bale(text: str) -> bool:
    """Send an operational alert message to Bale bot without interrupting caller if Bale is unreachable."""
    if not bale_ready():
        return False
    try:
        send_text(text)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to send Bale notification: %s", _safe(exc))
        return False


def _send_bale_quietly(text: str, log_label: str) -> None:
    try:
        notify_bale(text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to send %s: %s", log_label, _safe(exc))


def notify_bale_after_commit(text: str, *, log_label: str = "Bale notification") -> None:
    """Schedule a short Bale text alert strictly after the DB transaction commits so row locks and response latency
    never depend on Bale availability."""
    def _dispatch():
        if getattr(settings, "TESTING", False):
            _send_bale_quietly(text, log_label)
        else:
            _BALE_NOTIFY_EXECUTOR.submit(_send_bale_quietly, text, log_label)

    transaction.on_commit(_dispatch)
