import io
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.models import User

from . import backups
from .models import BackupRun


class BackupTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.media = self.tmp / "media"
        (self.media / "content" / "b").mkdir(parents=True)
        (self.media / "apk").mkdir()
        (self.media / "content" / "b" / "a.png").write_bytes(b"png")
        (self.media / "apk" / "x.apk").write_bytes(b"apk")
        self.override = override_settings(MEDIA_ROOT=str(self.media), BACKUP_DIR=str(self.tmp / "backups"), BALE_BOT_TOKEN="t", BALE_CHAT_ID="1")
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _zip(self, entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data in entries.items():
                z.writestr(name, data)
        return SimpleUploadedFile("x.zip", buf.getvalue())

    def test_weekly_media_backup_sends_new_files_only_and_skips_apk(self):
        sent = []
        with mock.patch.object(backups, "send_file", side_effect=lambda p, c: sent.append(zipfile.ZipFile(p).namelist())):
            run = backups.backup_media()
        self.assertTrue(run.ok and run.sent)
        self.assertEqual(sent, [["media/content/b/a.png"]])
        self.assertEqual(list(Path(backups.backup_dir()).glob("*.zip")), [])  # removed once sent
        BackupRun.objects.filter(pk=run.pk).update(at=run.at.replace(year=2100))
        with mock.patch.object(backups, "send_file") as send:
            again = backups.backup_media()
        send.assert_not_called()
        self.assertEqual(again.note, "0 فایل")

    def test_restore_adds_media_and_refuses_paths_outside(self):
        upload = self._zip({"media/content/new.png": b"n", "media/../evil.txt": b"x", "backend/media/covers/c.png": b"c", "other/z.txt": b"z"})
        done = backups.restore_upload(upload)
        self.assertEqual((done["db"], done["media"]), (False, 2))
        self.assertTrue((self.media / "content" / "new.png").exists())
        self.assertTrue((self.media / "covers" / "c.png").exists())
        self.assertFalse((self.tmp / "evil.txt").exists())
        self.assertTrue((self.media / "content" / "b" / "a.png").exists())  # nothing deleted
        again = backups.restore_upload(self._zip({"media/content/b/a.png": b"other"}))
        self.assertEqual((again["media"], again.get("skipped")), (0, 1))
        self.assertEqual((self.media / "content" / "b" / "a.png").read_bytes(), b"png")  # never overwritten

    def test_restore_refuses_what_is_not_a_backup(self):
        for upload in (self._zip({"notes.txt": b"x"}), self._zip({"db.sqlite3": b"not a database"}), SimpleUploadedFile("x.exe", b"MZ")):
            with self.assertRaises(backups.RestoreError):
                backups.restore_upload(upload)

    def test_database_restore_replaces_the_file_and_keeps_the_old_one(self):
        live, other = self.tmp / "live.sqlite3", self.tmp / "laptop.sqlite3"
        for path, value in ((live, "server"), (other, "laptop")):
            con = sqlite3.connect(path)
            con.executescript(f"CREATE TABLE django_migrations(id, app, name); CREATE TABLE t(v); INSERT INTO t VALUES ('{value}');")
            con.commit()
            con.close()
        settings_dict = {**backups.connection.settings_dict, "NAME": str(live)}
        with mock.patch.object(backups.connection, "settings_dict", settings_dict), mock.patch.object(backups.connection, "vendor", "sqlite"), \
                mock.patch.object(backups.connection, "close"), mock.patch("django.core.management.call_command") as migrate:
            done = backups.restore_upload(self._zip({"db.sqlite3": other.read_bytes()}))
        migrate.assert_called_once()
        self.assertTrue(done["db"])
        self.assertEqual(sqlite3.connect(live).execute("SELECT v FROM t").fetchone()[0], "laptop")
        aside = Path(backups.backup_dir()) / done["aside"]
        self.assertEqual(sqlite3.connect(aside).execute("SELECT v FROM t").fetchone()[0], "server")

    def test_panel_restore_is_for_superusers_only(self):
        staff = User.objects.create_user("09120000009", is_staff=True)
        self.client.force_login(staff)
        r = self.client.post("/admin/catalog/cleanuprun/restore/", {"confirm": "yes", "file": self._zip({"media/a.png": b"a"})})
        self.assertEqual(r.status_code, 403)
        boss = User.objects.create_superuser("09120000010", password="x-strong-pass-1")
        self.client.force_login(boss)
        r = self.client.post("/admin/catalog/cleanuprun/restore/", {"confirm": "yes", "file": self._zip({"media/a.png": b"a"})})
        self.assertEqual(r.status_code, 302)
        self.assertTrue((self.media / "a.png").exists())
        page = self.client.get("/admin/catalog/cleanuprun/")
        self.assertContains(page, "بازگردانی از پشتیبان")

    def test_due_logic_backs_up_once_a_night(self):
        with mock.patch.object(backups, "backup_database", side_effect=lambda: BackupRun.objects.create(kind="db", ok=True)) as db, \
                mock.patch.object(backups, "backup_media", side_effect=lambda: BackupRun.objects.create(kind="media", ok=True)) as media:
            self.assertEqual(backups.run_due(), ["db", "media"])
            self.assertEqual(backups.run_due(), [])
        self.assertEqual((db.call_count, media.call_count), (1, 1))


class TokenTests(TestCase):
    @override_settings(BALE_BOT_TOKEN="123:SECRET")
    def test_errors_never_show_the_bot_token(self):
        self.assertNotIn("SECRET", backups._safe(Exception("https://tapi.bale.ai/bot123:SECRET/sendDocument failed")))

    def test_newer_database_is_refused(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        db = tmp / "x.sqlite3"
        con = sqlite3.connect(db)
        con.executescript("CREATE TABLE django_migrations(id, app, name); INSERT INTO django_migrations VALUES (1, 'catalog', '9999_future');")
        con.commit()
        con.close()
        with self.assertRaisesMessage(backups.RestoreError, "تازه‌تر"):
            backups._check_sqlite(db)
