import gzip
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone as dt_tz
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings

from apps.accounts.models import User

from . import backups
from .access import BOOK_EDITOR_GROUP
from .media import sign_content_path
from .models import BackupRun, BookEditor, ContentNode


class BackupTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.media = self.tmp / "media"
        (self.media / "content" / "b").mkdir(parents=True)
        (self.media / "apk").mkdir()
        (self.media / "content" / "b" / "a.png").write_bytes(b"png")
        (self.media / "apk" / "x.apk").write_bytes(b"apk")
        self.bale_patch = mock.patch.object(backups, "_bale", return_value=None)
        self.mock_bale = self.bale_patch.start()
        self.addCleanup(self.bale_patch.stop)
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
        r = self.client.post("/admin/catalog/cleanuprun/restore/", {"confirm": "بازگردانی", "file": self._zip({"media/a.png": b"a"})})
        self.assertEqual(r.status_code, 403)
        boss = User.objects.create_superuser("09120000010", password="x-strong-pass-1")
        self.client.force_login(boss)
        r = self.client.post("/admin/catalog/cleanuprun/restore/", {"confirm": "yes", "file": self._zip({"media/a.png": b"a"})})
        self.assertFalse((self.media / "a.png").exists())  # the word was not typed
        r = self.client.post("/admin/catalog/cleanuprun/restore/", {"confirm": "بازگردانی", "file": self._zip({"media/a.png": b"a"})})
        self.assertEqual(r.status_code, 302)
        self.assertTrue((self.media / "a.png").exists())
        # A server copy can be downloaded only by its listed name.
        (Path(backups.backup_dir()) / "limookhan-db-20260101-0300.sqlite3.gz").write_bytes(b"x")
        self.assertEqual(self.client.get("/admin/catalog/cleanuprun/backup-file/?name=limookhan-db-20260101-0300.sqlite3.gz").status_code, 200)
        self.assertEqual(self.client.get("/admin/catalog/cleanuprun/backup-file/?name=../db.sqlite3").status_code, 404)
        with mock.patch.object(backups, "send_text") as send:
            self.client.post("/admin/catalog/cleanuprun/test-bale/")
        send.assert_called_once()
        page = self.client.get("/admin/catalog/cleanuprun/")
        self.assertContains(page, "بازگردانی دیتابیس یا آوردن داده از لپ‌تاپ")

    def test_due_logic_backs_up_once_a_night(self):
        with mock.patch.object(backups, "backup_database", side_effect=lambda: BackupRun.objects.create(kind="db", ok=True)) as db, \
                mock.patch.object(backups, "backup_media", side_effect=lambda: BackupRun.objects.create(kind="media", ok=True)) as media:
            self.assertEqual(backups.run_due(), ["db", "media"])
            self.assertEqual(backups.run_due(), [])
        self.assertEqual((db.call_count, media.call_count), (1, 1))

    def test_run_due_releases_pending_royalty_balances(self):
        with mock.patch("apps.commerce.wallet.release_pending_balances", return_value=3) as mock_release:
            done = backups.run_due()
            self.assertIn("royalty-release(3)", done)
            mock_release.assert_called_once()


class StoragePanelExportTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.media = self.tmp / "media"
        (self.media / "content" / "b").mkdir(parents=True)
        (self.media / "content" / "b" / "a.png").write_bytes(b"png")
        self.override = override_settings(MEDIA_ROOT=str(self.media), BACKUP_DIR=str(self.tmp / "backups"))
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_export_database_json_unique_names_and_contents(self):
        out1 = backups.export_database_json()
        out2 = backups.export_database_json()
        self.assertNotEqual(out1.name, out2.name)
        self.assertTrue(out1.exists() and out2.exists())
        self.assertTrue(out1.name.startswith("limookhan-db-export-") and out1.name.endswith(".json.gz"))
        for out in (out1, out2):
            with gzip.open(out, "rt", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertIsInstance(payload, list)
            models_seen = {item.get("model") for item in payload}
            self.assertNotIn("contenttypes.contenttype", models_seen)
            self.assertNotIn("auth.permission", models_seen)
            self.assertIn(out.name, [item["name"] for item in backups.local_backups()])
        self.assertEqual(list(backups.backup_dir().glob(".tmp-*")), [])

    def test_export_full_media_unique_names_and_empty_media(self):
        zip1, count1 = backups.export_full_media()
        zip2, count2 = backups.export_full_media()
        self.assertIsNotNone(zip1)
        self.assertIsNotNone(zip2)
        self.assertNotEqual(zip1.name, zip2.name)
        self.assertEqual((count1, count2), (1, 1))
        for zp in (zip1, zip2):
            with zipfile.ZipFile(zp, "r") as z:
                self.assertEqual(z.namelist(), ["media/content/b/a.png"])
        self.assertEqual(list(backups.backup_dir().glob(".tmp-*")), [])

        shutil.rmtree(self.media)
        self.media.mkdir()
        none_path, zero = backups.export_full_media()
        self.assertIsNone(none_path)
        self.assertEqual(zero, 0)

    def test_export_and_nightly_backups_have_independent_retention(self):
        folder = backups.backup_dir()
        nightly_files = []
        base_ts = 1_700_000_000
        for i in range(backups.KEEP_DB):
            p = folder / f"limookhan-db-2026111{i + 1}-0300.sqlite3.gz"
            p.write_bytes(f"nightly-{i}".encode("utf-8"))
            os.utime(p, (base_ts + i * 100, base_ts + i * 100))
            nightly_files.append(p)

        # Creating many manual exports never deletes any of the 7 nightly backups.
        exports = []
        for idx in range(backups.KEEP_DB + 1):
            exp = backups.export_database_json()
            os.utime(exp, (base_ts + 10_000 + idx * 10, base_ts + 10_000 + idx * 10))
            exports.append(exp)
        for p in nightly_files:
            self.assertTrue(p.exists(), f"Nightly backup {p.name} should not be pruned by manual exports")
        kept_exports = [p for p in exports if p.exists()]
        self.assertEqual(len(kept_exports), backups.KEEP_DB_EXPORTS)

        # Creating a new nightly backup prunes only the oldest nightly backup and leaves exports intact.
        new_nightly = backups.backup_database(send=False)
        self.assertTrue(new_nightly.ok)
        self.assertFalse(nightly_files[0].exists())
        for p in nightly_files[1:]:
            self.assertTrue(p.exists())
        self.assertTrue((folder / new_nightly.files[0]).exists())
        for exp in kept_exports:
            self.assertTrue(exp.exists(), f"Manual export {exp.name} should not be pruned by nightly backup")

        # Full media exports are likewise ignored when nightly media backup prunes old zip parts.
        full_zip, _ = backups.export_full_media()
        self.assertIsNotNone(full_zip)
        for i in range(25):
            mp = folder / f"limookhan-media-202611{i + 1:02d}-0300-1.zip"
            mp.write_bytes(b"zip")
            os.utime(mp, (base_ts + i * 10, base_ts + i * 10))
        with mock.patch.object(backups, "_bale", return_value=None):
            media_run = backups.backup_media(send=False)
        self.assertTrue(media_run.ok)
        self.assertTrue(full_zip.exists())

    def test_storage_panel_exports_and_service_probe_roles(self):
        from apps.accounts.sms import SMSNotSent
        from apps.commerce.zibal import GatewayError

        book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب تست", slug="t-book")
        teacher_group, _ = Group.objects.get_or_create(name=BOOK_EDITOR_GROUP)
        teacher = User.objects.create_user("09120000018", is_staff=True)
        teacher.groups.add(teacher_group)
        BookEditor.objects.create(book=book, user=teacher)

        endpoints = ("export-json/", "export-media/", "test-sms/", "test-zibal/")

        # 1. Real book teacher cannot access manager-only storage probes/exports.
        self.client.force_login(teacher)
        for endpoint in endpoints:
            self.assertEqual(self.client.post(f"/admin/catalog/cleanuprun/{endpoint}").status_code, 403)

        # 2. Superuser inside «نمای استاد» preview cannot bypass teacher restrictions.
        boss = User.objects.create_superuser("09120000020", password="x-strong-pass-1")
        self.client.force_login(boss)
        session = self.client.session
        session["admin_view_mode"] = "teacher"
        session.save()
        for endpoint in endpoints:
            self.assertEqual(self.client.post(f"/admin/catalog/cleanuprun/{endpoint}").status_code, 403)

        # 3. Manager in normal admin mode succeeds on all endpoints.
        session = self.client.session
        session.pop("admin_view_mode", None)
        session.save()

        page = self.client.get("/admin/catalog/cleanuprun/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "خروجی قابل انتقال (JSON)")
        self.assertContains(page, "بکاپ کامل عکس‌ها (zip)")
        self.assertContains(page, "آزمایش پیامک")
        self.assertContains(page, "آزمایش درگاه زیبال")

        r_json = self.client.post("/admin/catalog/cleanuprun/export-json/")
        self.assertEqual(r_json.status_code, 200)
        body_json = b"".join(r_json.streaming_content)
        self.assertIsInstance(json.loads(gzip.decompress(body_json).decode("utf-8")), list)

        r_media = self.client.post("/admin/catalog/cleanuprun/export-media/")
        self.assertEqual(r_media.status_code, 200)
        body_media = b"".join(r_media.streaming_content)
        with zipfile.ZipFile(io.BytesIO(body_media), "r") as z:
            self.assertEqual(z.namelist(), ["media/content/b/a.png"])

        shutil.rmtree(self.media)
        self.media.mkdir()
        r_empty_media = self.client.post("/admin/catalog/cleanuprun/export-media/", follow=True)
        self.assertEqual(r_empty_media.status_code, 200)
        self.assertContains(r_empty_media, "هیچ عکس یا فایل آپلودی در پوشه‌ی media وجود ندارد.")

        # SMS test endpoint
        with override_settings(SMS_BACKEND="raygan", RAYGAN_ACCESS_HASH="h", RAYGAN_OTP_PATTERN_ID="p"), \
                mock.patch("apps.accounts.sms.send_login_code") as mock_sms:
            r_sms = self.client.post("/admin/catalog/cleanuprun/test-sms/", {"phone": "09121112233"}, follow=True)
        mock_sms.assert_called_once()
        self.assertContains(r_sms, "پیامک آزمایشی به 09121112233 ارسال شد")

        with mock.patch("apps.accounts.sms.send_login_code", side_effect=SMSNotSent("bad creds")):
            r_sms_err = self.client.post("/admin/catalog/cleanuprun/test-sms/", {"phone": "09121112233"}, follow=True)
        self.assertContains(r_sms_err, "خطا در ارسال پیامک آزمایشی")

        r_sms_bad = self.client.post("/admin/catalog/cleanuprun/test-sms/", {"phone": "123"}, follow=True)
        self.assertContains(r_sms_bad, "شماره موبایل معتبر نیست.")

        # Zibal test endpoint
        with override_settings(PAYMENTS_ENABLED=True, ZIBAL_MERCHANT="real-merchant"), \
                mock.patch("apps.commerce.zibal.request_payment", return_value="998877") as mock_zibal:
            r_zibal = self.client.post("/admin/catalog/cleanuprun/test-zibal/", follow=True)
        mock_zibal.assert_called_once()
        self.assertContains(r_zibal, "اتصال به درگاه واقعی زیبال برقرار است")
        self.assertContains(r_zibal, "998877")

        with mock.patch("apps.commerce.zibal.request_payment", side_effect=GatewayError("timeout")):
            r_zibal_err = self.client.post("/admin/catalog/cleanuprun/test-zibal/", follow=True)
        self.assertContains(r_zibal_err, "خطا در اتصال به درگاه زیبال")


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


class SplitBackupTests(BackupTests):
    """A database backup bigger than Bale takes goes in pieces; the panel joins them back, piece by piece."""

    def test_big_backup_is_sent_in_pieces_and_restored_from_them(self):
        live, other = self.tmp / "live.sqlite3", self.tmp / "laptop.sqlite3"
        for path, value in ((live, "server"), (other, "laptop")):
            con = sqlite3.connect(path)
            con.executescript("CREATE TABLE django_migrations(id, app, name); CREATE TABLE t(v);")
            con.executemany("INSERT INTO t VALUES (?)", [(value + os.urandom(64).hex(),) for _ in range(2000)])
            con.commit()
            con.close()
        settings_dict = {**backups.connection.settings_dict, "NAME": str(other)}
        sent = []
        with mock.patch.object(backups.connection, "settings_dict", settings_dict), mock.patch.object(backups.connection, "vendor", "sqlite"), \
                mock.patch.object(backups, "PART_LIMIT", 40_000), \
                mock.patch.object(backups, "send_file", side_effect=lambda p, c: sent.append((p.name, p.read_bytes(), c))):
            run = backups.backup_database()
        self.assertTrue(run.sent and len(sent) >= 3)
        self.assertTrue(all(name.endswith(f"of{len(sent)}") for name, _, _ in sent))
        self.assertIn("تکه‌ی ۱ از", sent[0][2].replace("1", "۱"))
        self.assertFalse(list(Path(backups.backup_dir()).glob("*.part*")))  # pieces are not left on the server

        settings_dict = {**backups.connection.settings_dict, "NAME": str(live)}
        with mock.patch.object(backups.connection, "settings_dict", settings_dict), mock.patch.object(backups.connection, "vendor", "sqlite"), \
                mock.patch.object(backups.connection, "close"), mock.patch("django.core.management.call_command"):
            order = list(reversed(sent))  # any order
            for i, (name, data, _) in enumerate(order):
                done = backups.restore_upload(SimpleUploadedFile(name, data))
                if i < len(order) - 1:
                    self.assertTrue(done["waiting"])
                    self.assertFalse(done["db"])
        self.assertTrue(done["db"])
        self.assertTrue(sqlite3.connect(live).execute("SELECT v FROM t").fetchone()[0].startswith("laptop"))
        self.assertFalse((Path(backups.backup_dir()) / "incoming").exists() and any((Path(backups.backup_dir()) / "incoming").iterdir()))

    def test_pieces_of_different_backups_do_not_mix(self):
        backups.restore_upload(SimpleUploadedFile("limookhan-db-x.sqlite3.gz.part1of3", b"a"))
        # Another split of the same name starts afresh (the old pieces are dropped, not mixed in).
        done = backups.restore_upload(SimpleUploadedFile("limookhan-db-x.sqlite3.gz.part2of2", b"b"))
        self.assertEqual(done["waiting"], [1])
        with self.assertRaises(backups.RestoreError):
            backups.restore_upload(SimpleUploadedFile("limookhan-db-x.sqlite3.gz.part5of3", b"b"))


class PostgresAndStorageModeTests(BackupTests):
    def test_safe_redacts_s3_secrets(self):
        with override_settings(BACKUP_S3_ACCESS_KEY="AK_TEST_KEY", BACKUP_S3_SECRET_KEY="SK_SUPER_SECRET"):
            cleaned = backups._safe(RuntimeError("upload AK_TEST_KEY with SK_SUPER_SECRET failed"))
        self.assertNotIn("AK_TEST_KEY", cleaned)
        self.assertNotIn("SK_SUPER_SECRET", cleaned)
        self.assertIn("***", cleaned)

    def test_pg_dump_backup_and_pg_restore_upload(self):
        pg_settings = {
            "NAME": "limo_db",
            "USER": "limo_user",
            "PASSWORD": "pg-secret-password",
            "HOST": "db.internal",
            "PORT": "5432",
            "OPTIONS": {"sslmode": "require"},
        }

        def fake_run(cmd, env=None, capture_output=True, text=True, check=False):
            if cmd[0] == "pg_dump":
                out_file = Path(cmd[cmd.index("--file") + 1])
                out_file.write_bytes(b"PGDMP-custom-backup-payload")
                self.assertEqual(env["PGPASSWORD"], "pg-secret-password")
                self.assertEqual(env["PGSSLMODE"], "require")
                self.assertIn("--format=custom", cmd)
                self.assertIn("--no-owner", cmd)
                self.assertIn("--no-privileges", cmd)
            elif cmd[0] == "pg_restore":
                self.assertIn("--clean", cmd)
                self.assertIn("--if-exists", cmd)
                self.assertIn("--single-transaction", cmd)
                self.assertEqual(env["PGPASSWORD"], "pg-secret-password")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(backups.connection, "vendor", "postgresql"), \
                mock.patch.object(backups.connection, "settings_dict", pg_settings), \
                mock.patch.object(backups.shutil, "which", return_value="/usr/bin/pg_dump"), \
                mock.patch.object(backups.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(backups.connections, "close_all"), \
                mock.patch("django.core.management.call_command") as mock_cmd:
            run = backups.backup_database(send=True)
            self.assertTrue(run.ok and run.sent)
            self.assertTrue(run.files[0].endswith(".dump"))
            dump_path = backups.backup_dir() / run.files[0]
            self.assertTrue(dump_path.exists())

            done = backups.restore_upload(SimpleUploadedFile(dump_path.name, dump_path.read_bytes()))
            self.assertTrue(done["db"])
            self.assertTrue(done["aside"].endswith(".dump"))
            mock_cmd.assert_called_once_with("migrate", interactive=False, verbosity=0)

        with mock.patch.object(backups.connection, "vendor", "postgresql"), \
                mock.patch.object(backups.shutil, "which", return_value="/usr/bin/pg_restore"):
            with self.assertRaises(backups.RestoreError):
                backups.restore_upload(SimpleUploadedFile("bad.dump", b"NOT_A_DUMP"))

    def test_postgres_dumpdata_fallback_uses_repeatable_read_when_pg_dump_missing(self):
        executed = []
        real_cursor = backups.connection.cursor

        class FakeCursor:
            def __init__(self):
                self._inner = real_cursor()

            def __enter__(self):
                self._inner.__enter__()
                return self

            def __exit__(self, *args):
                return self._inner.__exit__(*args)

            def execute(self, sql, params=None):
                executed.append(sql)
                if sql.startswith("SET TRANSACTION ISOLATION LEVEL"):
                    return None
                return self._inner.execute(sql, params) if params is not None else self._inner.execute(sql)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        def fake_call(cmd, *args, stdout=None, **kwargs):
            if cmd == "dumpdata":
                stdout.write('[{"model": "catalog.book", "pk": 1, "fields": {}}]')

        with mock.patch.object(backups.connection, "vendor", "postgresql"), \
                mock.patch.object(backups.connection, "in_atomic_block", False), \
                mock.patch.object(backups.connection, "cursor", side_effect=FakeCursor), \
                mock.patch.object(backups.transaction, "atomic", return_value=mock.MagicMock()), \
                mock.patch.object(backups.shutil, "which", return_value=None), \
                mock.patch("django.core.management.call_command", side_effect=fake_call):
            run = backups.backup_database(send=False)
        self.assertTrue(run.ok)
        self.assertTrue(run.files[0].endswith(".json.gz"))
        self.assertIn("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY", executed)

    def test_multipart_dump_and_json_gz_restore(self):
        payload = b"PGDMP" + (b"0123456789" * 50)
        mid = len(payload) // 2
        with mock.patch.object(backups.connection, "vendor", "postgresql"), \
                mock.patch.object(backups.shutil, "which", return_value="/usr/bin/pg_restore"), \
                mock.patch.object(backups.subprocess, "run", return_value=mock.Mock(returncode=0, stdout="", stderr="")), \
                mock.patch.object(backups.connections, "close_all"), \
                mock.patch("django.core.management.call_command"):
            first = backups.restore_upload(SimpleUploadedFile("limookhan-db-20261124-0300.dump.part2of2", payload[mid:]))
            self.assertEqual(first["waiting"], [1])
            done = backups.restore_upload(SimpleUploadedFile("limookhan-db-20261124-0300.dump.part1of2", payload[:mid]))
            self.assertTrue(done["db"])

        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(json.dumps([{"model": "catalog.book", "pk": 1, "fields": {}}]).encode("utf-8"))
        gz_bytes = buf.getvalue()
        half = len(gz_bytes) // 2
        with mock.patch.object(backups, "_db_copy", return_value=backups.backup_dir() / "before-restore-test.sqlite3"), \
                mock.patch("django.core.management.call_command") as mock_cmd:
            w = backups.restore_upload(SimpleUploadedFile("limookhan-db-20261124-0300.json.gz.part1of2", gz_bytes[:half]))
            self.assertEqual(w["waiting"], [2])
            done = backups.restore_upload(SimpleUploadedFile("limookhan-db-20261124-0300.json.gz.part2of2", gz_bytes[half:]))
            self.assertTrue(done["db"])
            called_cmds = [c.args[0] for c in mock_cmd.call_args_list]
            self.assertEqual(called_cmds, ["flush", "loaddata", "migrate"])

    def test_storage_mode_object_storage_and_both_and_pruning(self):
        fake_s3 = mock.MagicMock()
        fake_s3.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "limo/db/limookhan-db-3.sqlite3.gz", "LastModified": datetime(2026, 11, 24, tzinfo=dt_tz.utc)},
                {"Key": "limo/db/limookhan-db-2.sqlite3.gz", "LastModified": datetime(2026, 11, 23, tzinfo=dt_tz.utc)},
                {"Key": "limo/db/limookhan-db-1.sqlite3.gz", "LastModified": datetime(2026, 11, 22, tzinfo=dt_tz.utc)},
            ]
        }

        with override_settings(
            BACKUP_STORAGE_MODE="object_storage",
            BACKUP_S3_ENDPOINT="https://c123.parspack.net",
            BACKUP_S3_BUCKET="limo-backups",
            BACKUP_S3_ACCESS_KEY="ak",
            BACKUP_S3_SECRET_KEY="sk",
            BACKUP_S3_PREFIX="limo",
            BACKUP_S3_KEEP=2,
        ), mock.patch.object(backups, "_s3_client", return_value=fake_s3), mock.patch.object(backups, "send_file") as bale_send:
            self.assertTrue(backups.storage_ready())
            run = backups.backup_database(send=True)
            self.assertTrue(run.ok and run.sent)
            self.assertIn("S3: limo/db/", run.note)
            bale_send.assert_not_called()
            fake_s3.upload_file.assert_called_once()
            fake_s3.delete_objects.assert_called_once_with(
                Bucket="limo-backups",
                Delete={"Objects": [{"Key": "limo/db/limookhan-db-1.sqlite3.gz"}]},
            )

        # object_storage without credentials fails closed
        with override_settings(BACKUP_STORAGE_MODE="object_storage", BACKUP_S3_ENDPOINT="", BACKUP_S3_BUCKET=""):
            self.assertFalse(backups.storage_ready())
            with self.assertRaises(RuntimeError):
                backups.deliver_backup(self.media / "content" / "b" / "a.png", kind="db", caption="x")

        # both: uploads to S3 AND sends to Bale; partial failure still marks sent=True
        fake_s3.reset_mock()
        with override_settings(
            BACKUP_STORAGE_MODE="both",
            BACKUP_S3_ENDPOINT="https://c123.parspack.net",
            BACKUP_S3_BUCKET="limo-backups",
            BACKUP_S3_ACCESS_KEY="ak",
            BACKUP_S3_SECRET_KEY="sk",
        ), mock.patch.object(backups, "_s3_client", return_value=fake_s3), \
                mock.patch.object(backups, "send_to_bale_in_chunks", side_effect=RuntimeError("bale down")):
            res = backups.deliver_backup(self.media / "content" / "b" / "a.png", kind="db", caption="cap")
            self.assertTrue(res["sent"])
            self.assertTrue(res["sent_s3"])
            self.assertFalse(res["sent_bale"])
            self.assertIn("خطای جزئی", res["note"])


class NightlyAndGunicornConfigTests(TestCase):
    def test_run_nightly_loop_closes_connections_and_survives_errors(self):
        import threading
        from apps.catalog.management.commands import nightly as nightly_cmd

        stop = threading.Event()
        calls = 0

        def fake_run_due():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient db error")
            stop.set()
            return ["db"]

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(nightly_cmd, "run_due", side_effect=fake_run_due), \
                mock.patch.object(nightly_cmd, "close_old_connections") as mock_close:
            nightly_cmd.run_nightly_loop(
                initial_delay=0,
                interval=0.01,
                stdout=out,
                stderr=err,
                stop_event=stop,
            )

        self.assertEqual(calls, 2)
        self.assertIn("nightly failed: RuntimeError", err.getvalue())
        self.assertIn("nightly: db", out.getvalue())
        # Closed before and after each iteration.
        self.assertGreaterEqual(mock_close.call_count, 4)

    def test_start_nightly_thread_is_idempotent(self):
        from apps.catalog.management.commands import nightly as nightly_cmd

        with mock.patch.object(nightly_cmd, "_thread_started", False), \
                mock.patch("threading.Thread") as mock_thread:
            self.assertTrue(nightly_cmd.start_nightly_thread(initial_delay=120))
            self.assertFalse(nightly_cmd.start_nightly_thread(initial_delay=120))
            mock_thread.assert_called_once()
            self.assertTrue(mock_thread.call_args.kwargs["daemon"])

    def test_gunicorn_conf_skips_redundant_collectstatic_and_third_process_on_single_worker(self):
        import importlib.util
        from django.conf import settings as django_settings

        conf_path = Path(django_settings.BASE_DIR) / "gunicorn.conf.py"
        spec = importlib.util.spec_from_file_location("test_gunicorn_conf", conf_path)
        gconf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gconf)

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "apps" / "website" / "static" / "website").mkdir(parents=True)
        asset = tmp / "apps" / "website" / "static" / "website" / "site.css"
        asset.write_text("body{}", encoding="utf-8")
        req = tmp / "requirements.txt"
        req.write_text("Django==5.2\n", encoding="utf-8")

        # No manifest yet -> not fresh
        self.assertFalse(gconf._staticfiles_fresh(str(tmp)))

        manifest_dir = tmp / "staticfiles"
        manifest_dir.mkdir()
        manifest = manifest_dir / "staticfiles.json"
        manifest.write_text("{}", encoding="utf-8")
        # Force deterministic mtimes: manifest newer than static sources -> fresh
        os.utime(asset, (1000, 1000))
        os.utime(req, (1000, 1000))
        os.utime(manifest, (2000, 2000))
        self.assertTrue(gconf._staticfiles_fresh(str(tmp)))

        # Static source edited after manifest -> stale
        os.utime(asset, (3000, 3000))
        self.assertFalse(gconf._staticfiles_fresh(str(tmp)))

        # Restore fresh manifest, check on_starting skips collectstatic when fresh
        os.utime(manifest, (4000, 4000))
        with mock.patch.object(gconf, "HERE", str(tmp)), \
                mock.patch.dict(os.environ, {"_LIMO_STARTUP_DONE": "", "DISABLE_MIGRATE": "", "DISABLE_COLLECTSTATIC": ""}, clear=False), \
                mock.patch.object(gconf.subprocess, "run", return_value=mock.Mock(returncode=0)) as mock_run:
            gconf.on_starting(None)
            self.assertEqual([c.args[0][2:] for c in mock_run.call_args_list], [["migrate", "--noinput"]])

        # When _LIMO_STARTUP_DONE=1 (set by app.sh), on_starting skips both steps
        with mock.patch.dict(os.environ, {"_LIMO_STARTUP_DONE": "1"}, clear=False), \
                mock.patch.object(gconf.subprocess, "run") as mock_run:
            gconf.on_starting(None)
            mock_run.assert_not_called()

        # If migrate fails, on_starting aborts Gunicorn startup with its non-zero exit code before collectstatic/workers start
        os.utime(asset, (5000, 5000))  # stale manifest so collectstatic would also be queued
        with mock.patch.object(gconf, "HERE", str(tmp)), \
                mock.patch.dict(os.environ, {"_LIMO_STARTUP_DONE": "", "DISABLE_MIGRATE": "", "DISABLE_COLLECTSTATIC": ""}, clear=False), \
                mock.patch.object(gconf.subprocess, "run", return_value=mock.Mock(returncode=2)) as mock_run:
            with self.assertRaises(SystemExit) as ctx:
                gconf.on_starting(None)
            self.assertEqual(ctx.exception.code, 2)
            self.assertEqual([c.args[0][2:] for c in mock_run.call_args_list], [["migrate", "--noinput"]])

        # If migrate succeeds and collectstatic fails, on_starting also aborts Gunicorn startup
        with mock.patch.object(gconf, "HERE", str(tmp)), \
                mock.patch.dict(os.environ, {"_LIMO_STARTUP_DONE": "", "DISABLE_MIGRATE": "", "DISABLE_COLLECTSTATIC": ""}, clear=False), \
                mock.patch.object(gconf.subprocess, "run", side_effect=[mock.Mock(returncode=0), mock.Mock(returncode=3)]) as mock_run:
            with self.assertRaises(SystemExit) as ctx:
                gconf.on_starting(None)
            self.assertEqual(ctx.exception.code, 3)
            self.assertEqual(
                [c.args[0][2:] for c in mock_run.call_args_list],
                [["migrate", "--noinput"], ["collectstatic", "--noinput", "-v0"]],
            )

        # Single-worker + NIGHTLY_JOBS=True: no subprocess in when_ready, daemon thread in post_worker_init
        from apps.catalog.management.commands import nightly as nightly_cmd

        with mock.patch.object(gconf, "workers", 1), \
                mock.patch.dict(os.environ, {"NIGHTLY_JOBS": "True"}, clear=False), \
                mock.patch.object(gconf.subprocess, "Popen") as mock_popen, \
                mock.patch.object(nightly_cmd, "start_nightly_thread") as mock_start:
            gconf.when_ready(None)
            mock_popen.assert_not_called()
            gconf.post_worker_init(None)
            mock_start.assert_called_once_with()

        # Multi-worker + NIGHTLY_JOBS=True: spawns single subprocess in when_ready, no in-worker thread
        with mock.patch.object(gconf, "workers", 2), \
                mock.patch.dict(os.environ, {"NIGHTLY_JOBS": "True"}, clear=False), \
                mock.patch.object(gconf.subprocess, "Popen") as mock_popen, \
                mock.patch.object(nightly_cmd, "start_nightly_thread") as mock_start:
            gconf.when_ready(None)
            mock_popen.assert_called_once()
            gconf.post_worker_init(None)
            mock_start.assert_not_called()

    def test_dockerfile_uses_gunicorn_conf_not_hardcoded_three_workers(self):
        from django.conf import settings as django_settings

        dockerfile = (Path(django_settings.BASE_DIR) / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('CMD ["gunicorn", "-c", "gunicorn.conf.py"]', dockerfile)
        self.assertNotIn("--workers 3", dockerfile)
        self.assertIn("collectstatic --noinput", dockerfile)


class SqliteToActiveDatabaseRestoreAcceptanceTests(TransactionTestCase):
    """Unmocked cross-engine acceptance test: export a real SQLite DB + media zip and restore via panel."""

    def test_sqlite_json_and_media_restore_via_panel_then_create_and_read(self):
        from django.conf import settings as django_settings

        from apps.learning.models import Choice, Question

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        src_db = tmp / "source.sqlite3"
        src_media = tmp / "src_media"
        dst_media = tmp / "dst_media"
        src_backups = tmp / "src_backups"
        dst_backups = tmp / "dst_backups"
        (src_media / "content" / "old-book").mkdir(parents=True)
        dst_media.mkdir(parents=True)
        (src_media / "content" / "old-book" / "page.png").write_bytes(b"old-png-bytes")

        helper = """
import json, os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.core.management import call_command
from apps.accounts.models import User
from apps.catalog import backups
from apps.catalog.models import ContentNode
from apps.learning.models import Choice, Question

call_command("migrate", verbosity=0)
User.objects.create_superuser("09120000099", password="x-strong-pass-1")
book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب قدیمی", slug="old-book", is_published=True)
ch = book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل قدیمی", slug="old-ch-1", is_published=True)
q = Question.objects.create(
    node=ch, slug="old-q-1", stem="سؤال قدیمی", explanation="توضیح قدیمی", difficulty=Question.Difficulty.EASY
)
Choice.objects.create(question=q, text="گزینه اول", is_correct=True, order=0)
json_path = backups.export_database_json()
media_path, media_count = backups.export_full_media()
print(json.dumps({"json": str(json_path), "media": str(media_path), "media_count": media_count}))
"""
        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "DATABASE_URL": f"sqlite:///{src_db}",
            "MEDIA_ROOT": str(src_media),
            "BACKUP_DIR": str(src_backups),
            "DEBUG": "True",
            "SECRET_KEY": "sqlite-export-acceptance-key",
        }
        proc = subprocess.run(
            [sys.executable, "-c", helper],
            cwd=str(django_settings.BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        exported = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(exported["media_count"], 1)
        json_gz_bytes = Path(exported["json"]).read_bytes()
        media_zip_bytes = Path(exported["media"]).read_bytes()

        initial_boss = User.objects.create_superuser("09120000088", password="x-strong-pass-1")
        self.client.force_login(initial_boss)

        with override_settings(MEDIA_ROOT=str(dst_media), BACKUP_DIR=str(dst_backups), SERVE_MEDIA=True), \
                mock.patch.object(backups, "_db_copy", return_value=dst_backups / "before-restore-test.sqlite3"):
            r_db = self.client.post(
                "/admin/catalog/cleanuprun/restore/",
                {
                    "confirm": "بازگردانی",
                    "file": SimpleUploadedFile(Path(exported["json"]).name, json_gz_bytes),
                },
            )
            self.assertEqual(r_db.status_code, 302)

            restored_boss = User.objects.get(phone="09120000099")
            self.client.force_login(restored_boss)

            r_media = self.client.post(
                "/admin/catalog/cleanuprun/restore/",
                {
                    "confirm": "بازگردانی",
                    "file": SimpleUploadedFile(Path(exported["media"]).name, media_zip_bytes),
                },
            )
            self.assertEqual(r_media.status_code, 302)

            old_book = ContentNode.objects.get(slug="old-book", depth=1)
            old_ch = ContentNode.objects.get(slug="old-ch-1")
            self.assertEqual(old_ch.get_parent().pk, old_book.pk)
            self.assertTrue(Question.objects.filter(node=old_ch, stem="سؤال قدیمی").exists())

            # Create new records after restore (proving PostgreSQL PK sequences stay in sync).
            new_user = User.objects.create_user("09120000098")
            self.assertNotEqual(new_user.pk, restored_boss.pk)
            new_book = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب جدید", slug="new-book", is_published=True)
            new_ch = new_book.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل جدید", slug="new-ch-1", is_published=True)
            added_ch_to_old = old_book.add_child(
                kind=ContentNode.Kind.CHAPTER,
                title="فصل دوم کتاب قدیمی",
                slug="old-ch-2",
                is_published=True,
            )
            new_q = Question.objects.create(
                node=new_ch, slug="new-q-1", stem="سؤال جدید", explanation="توضیح جدید", difficulty=Question.Difficulty.MEDIUM
            )
            Choice.objects.create(question=new_q, text="گزینه جدید", is_correct=True, order=0)

            self.assertEqual(new_ch.get_parent().pk, new_book.pk)
            self.assertEqual(added_ch_to_old.get_parent().pk, old_book.pk)
            self.assertEqual(new_book.get_children_count(), 1)
            self.assertEqual(old_book.get_children_count(), 2)
            self.assertEqual(new_q.node_id, new_ch.pk)

            # Verify restored old media file opens via signed URL.
            signed_rel, _ = sign_content_path("content/old-book/page.png")
            img_resp = self.client.get(f"/media/{signed_rel}")
            self.assertEqual(img_resp.status_code, 200)
            self.assertEqual(b"".join(img_resp.streaming_content), b"old-png-bytes")



