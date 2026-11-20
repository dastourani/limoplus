"""
Backups of the real server, and putting one back.

- The database every night: SQLite through its own backup API (a consistent copy while the app runs), PostgreSQL as
  Django's `dumpdata` JSON; gzipped into BACKUP_DIR (the last KEEP_DB kept) and sent to the admin's chat in Bale.
- Pictures and files (MEDIA_ROOT) once a week: only what changed since the last media backup, as zip parts small
  enough for Bale. The APK folder and half-finished imports are left out.
- Restore (panel «فضای سرور», superusers only): a .zip with db.sqlite3 and/or a media/ folder (e.g. from the laptop),
  a database backup (.sqlite3 / .sqlite3.gz), or a weekly media zip. The current database is copied aside first,
  the uploaded one is copied in with SQLite's backup API, then `migrate` brings an older copy up to date.
  Pictures are added (never deleted), with every path checked to stay inside MEDIA_ROOT.

`python manage.py nightly` runs what is due; `nightly --loop` (started by gunicorn.conf.py when NIGHTLY_JOBS is on)
does so every hour in its own process.
"""

from __future__ import annotations

import gzip
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

import requests
from django.conf import settings
from django.db import connection
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


class RestoreError(Exception):
    pass


def _safe(exc) -> str:
    """An error's text without the Bale bot token (requests puts the whole URL in its messages)."""
    text = str(exc)
    if settings.BALE_BOT_TOKEN:
        text = text.replace(settings.BALE_BOT_TOKEN, "***")
    return text[:1000]


def backup_dir() -> Path:
    path = Path(settings.BACKUP_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _stamp(now=None) -> str:
    return timezone.localtime(now or timezone.now()).strftime("%Y%m%d-%H%M")


# --- Bale ----------------------------------------------------------------------------------------------------------


def bale_ready() -> bool:
    return bool(settings.BALE_BOT_TOKEN and settings.BALE_CHAT_ID)


def _bale(method: str, data: dict, files=None) -> None:
    url = f"https://tapi.bale.ai/bot{settings.BALE_BOT_TOKEN}/{method}"
    response = requests.post(url, data=data, files=files, timeout=300)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or not body.get("ok", False):
        raise RuntimeError(f"Bale {method}: {response.status_code} {body.get('description', '')}".strip())


def send_file(path: Path, caption: str) -> None:
    with open(path, "rb") as f:
        _bale("sendDocument", {"chat_id": settings.BALE_CHAT_ID, "caption": caption}, files={"document": (path.name, f)})


def send_text(text: str) -> None:
    _bale("sendMessage", {"chat_id": settings.BALE_CHAT_ID, "text": text})


# --- Making backups ------------------------------------------------------------------------------------------------


def _db_copy(target: Path) -> Path:
    """A consistent copy of the database. SQLite: a .sqlite3 file; PostgreSQL: dumpdata JSON."""
    if connection.vendor == "sqlite":
        source = sqlite3.connect(str(connection.settings_dict["NAME"]))
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
        finally:
            dest.close()
            source.close()
        return target
    from django.core.management import call_command

    target = target.with_suffix(".json")
    with open(target, "w", encoding="utf-8") as out:
        call_command("dumpdata", "--natural-foreign", "--exclude=contenttypes", "--exclude=auth.permission", stdout=out)
    return target


def backup_database(send=True):
    from .models import BackupRun

    run = BackupRun.objects.create(kind=BackupRun.Kind.DB)
    folder = backup_dir()
    try:
        raw = _db_copy(folder / f"limookhan-db-{_stamp()}.sqlite3")
        packed = raw.with_name(raw.name + ".gz")
        try:
            with open(raw, "rb") as src, gzip.open(packed, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
        finally:
            raw.unlink(missing_ok=True)
        run.files, run.size, run.ok = [packed.name], packed.stat().st_size, True
        _prune(folder, "limookhan-db-", KEEP_DB)
        if send and bale_ready():
            caption = f"🗄 پشتیبان دیتابیس لیموخوان\n{_stamp()}\nاطلاعات کاربران در آن است؛ جای دیگری نفرستید."
            if run.size > PART_LIMIT:
                # Bigger than Bale takes: sent in pieces; «بازگردانی» in the panel takes the pieces one by one and joins them.
                pieces = split_file(packed, PART_LIMIT)
                try:
                    for i, piece in enumerate(pieces, 1):
                        send_file(piece, f"{caption}\nتکه‌ی {i} از {len(pieces)}: برای بازگردانی همه‌ی تکه‌ها را یکی‌یکی بارگذاری کنید.")
                finally:
                    for piece in pieces:
                        piece.unlink(missing_ok=True)
                run.note = f"{len(pieces)} تکه"
            else:
                send_file(packed, caption)
            run.sent = True
    except Exception as exc:  # noqa: BLE001 — recorded and reported, never silent
        log.error("database backup failed: %s: %s", type(exc).__name__, _safe(exc))
        run.note = _safe(exc)
        _report_failure("دیتابیس", exc, send)
    run.save()
    return run


PIECE = re.compile(r"^(?P<base>.+\.sqlite3\.gz)\.part(?P<n>\d{1,3})of(?P<m>\d{1,3})$")


def split_file(path: Path, size: int) -> list[Path]:
    """`name.sqlite3.gz.part1of3`, … : plain byte pieces of the file, next to it."""
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
        if send and bale_ready() and parts:
            kept = []
            for i, p in enumerate(parts, 1):
                if p.stat().st_size > PART_LIMIT + 5 * 1024 * 1024:  # one file bigger than a part: it stays here
                    send_text(f"⚠️ بخش {i} پشتیبان عکس‌ها برای بله بزرگ است؛ روی سرور در پوشه‌ی backups مانده: {p.name}")
                    kept.append(p.name)
                    continue
                send_file(p, f"🖼 پشتیبان عکس‌ها و فایل‌های لیموخوان\n{_stamp()} — بخش {i} از {len(parts)}")
                p.unlink(missing_ok=True)  # sent: the disk holds the media themselves anyway
            run.sent = not kept
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


def restore_local(name: str) -> str:
    path = local_backup_path(name)
    with tempfile.TemporaryDirectory(dir=backup_dir()) as tmp:
        db = Path(tmp) / "db.sqlite3"
        if path.name.endswith(".gz"):
            with gzip.open(path, "rb") as src, open(db, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
        else:
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
    # Media live on this same disk; a copy here adds nothing, so they are only backed up when they can go to Bale.
    last_media = BackupRun.objects.filter(kind=BackupRun.Kind.MEDIA, ok=True).order_by("-at").first()
    if bale_ready() and (force or last_media is None or (now - last_media.at > MEDIA_EVERY and night)):
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
        raise RestoreError("بازگردانی دیتابیس از این صفحه فقط برای SQLite است.")
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
    """Keeps one piece of a split database backup in backups/incoming/<name>/. Returns the joined .gz once every
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
    A piece of a split database backup (…sqlite3.gz.part2of3) is kept until all pieces are there; meanwhile the
    result says which are still missing («waiting»)."""
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
        tmp = Path(tmp)
        raw = tmp / "upload"
        with open(raw, "wb") as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        if name.endswith(".gz"):
            db = tmp / "db.sqlite3"
            room = min(MAX_RESTORE_BYTES, int(shutil.disk_usage(backup_dir()).free * 0.8))
            try:
                with gzip.open(raw, "rb") as src, open(db, "wb") as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
                        if dst.tell() > room:
                            raise RestoreError("فایل بازشده بیش از حد بزرگ است یا جای دیسک کافی نیست.")
            except (OSError, EOFError) as exc:
                raise RestoreError("فایل gz خراب است.") from exc
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
                    db = tmp / "db.sqlite3"
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
            raise RestoreError("فقط فایل ‎.zip یا ‎.sqlite3 یا ‎.sqlite3.gz")
    return result


def notify_bale(text: str) -> bool:
    """Send an operational alert message to Bale bot without interrupting caller if Bale is unreachable."""
    if not bale_ready():
        return False
    try:
        send_text(text)
        return True
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Failed to send Bale notification: %s", _safe(exc))
        return False
