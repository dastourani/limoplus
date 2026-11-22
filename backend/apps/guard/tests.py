import io
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import DeviceSession, User
from apps.catalog import editing
from apps.catalog.maintenance import prune_revisions
from apps.catalog.models import ChapterRevision, ContentNode

from . import alerts, core, fingerprint
from .models import CopyEvent, GuardSettings, TraceHit


class FingerprintTests(TestCase):
    def test_round_trip_and_no_zwnj(self):
        code = fingerprint.new_code()
        marked = fingerprint.mark("این یک متن نمونه‌ی کوتاه است", code)
        self.assertNotIn("‌" + "​", marked)
        self.assertTrue(all(c != "‌" for c in fingerprint.encode(code)))
        self.assertEqual(fingerprint.decode_all(marked), [code])
        self.assertEqual(fingerprint.strip(marked), "این یک متن نمونه‌ی کوتاه است")
        # Half of the text still carries it.
        self.assertEqual(fingerprint.decode_all(marked[: len(marked) // 2]), [code])

    def test_locate_skips_markdown(self):
        source = "## عنوان\n\n- **حد** تابع در $x=0$ برابر\n  ==مهم== است.\n"
        start, end = core.locate(source, "حد تابع در $x=0$ برابر مهم است")
        self.assertEqual(core.normalize(source[start:end]), "حد تابع در $x=0$ برابر مهم است")


class CopyTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        call_command("load_samples", stdout=io.StringIO())
        self.user = User.objects.create_user("09120000001")
        _, token = DeviceSession.start(self.user, "test")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.chapter = ContentNode.objects.get(slug="limits")
        self.section = self.chapter.get_children().first()
        self.paid = ContentNode.objects.get(slug="derivatives").get_children().first()
        self.phrase = "حد وجود دارد فقط اگر هر دو وجود داشته باشند"

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def copy(self, text, node=None):
        return self.client.post(f"/api/v1/nodes/{(node or self.section).id}/copy/", {"text": text}, format="json")

    def test_copy_is_a_pointer_with_a_fingerprint(self):
        self.assertIn(self.phrase, editing.export_chapter(self.chapter))
        r = self.copy(self.phrase)
        self.assertEqual(r.status_code, 201)
        self.assertEqual((r.data["used"], r.data["limit"]), (1, 30))
        event = CopyEvent.objects.get()
        self.assertIsNone(event.packed)
        self.assertIsNotNone(event.revision)
        self.assertTrue(core.is_exact(event))
        self.assertEqual(fingerprint.decode_all(r.data["text"]), [event.code])
        self.assertEqual(fingerprint.strip(r.data["text"]), self.phrase)

    def test_text_not_in_the_chapter_is_stored_packed(self):
        self.copy("متنی که در فصل نیست و جای دیگری دیده شده")
        event = CopyEvent.objects.get()
        self.assertIsNone(event.revision)
        self.assertEqual(core.text_of(event), "متنی که در فصل نیست و جای دیگری دیده شده")

    def test_daily_quota_and_locked_and_long(self):
        self.assertEqual(self.copy("x", self.paid).status_code, 403)
        self.assertEqual(self.copy("ا" * 401).status_code, 400)
        for _ in range(30):
            self.assertEqual(self.copy(self.phrase).status_code, 201)
        r = self.copy(self.phrase)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data["code"], "quota")
        self.assertEqual(self.client.get("/api/v1/copy/quota/").data, {"used": 30, "limit": 30, "left": 0})
        self.assertEqual(APIClient().post(f"/api/v1/nodes/{self.section.id}/copy/", {"text": "x"}).status_code, 401)

    def test_pointed_revisions_are_kept(self):
        self.copy(self.phrase)
        pinned = CopyEvent.objects.get().revision
        text = pinned.text
        ChapterRevision.objects.filter(pk=pinned.pk).update(updated_at=timezone.now() - timedelta(days=90), source="panel", user=None)
        # A newer one in the same week would normally replace it.
        newer = ChapterRevision.objects.create(chapter=self.chapter, text=text + "\n", source="file")
        ChapterRevision.objects.filter(pk=newer.pk).update(updated_at=timezone.now() - timedelta(days=89, hours=23))
        ChapterRevision.objects.create(chapter=self.chapter, text=text + "\n\n", source="file")
        prune_revisions()
        self.assertTrue(ChapterRevision.objects.filter(pk=pinned.pk).exists())
        # A quick panel edit does not write over a pointed version either.
        ChapterRevision.objects.exclude(pk=pinned.pk).delete()
        ChapterRevision.objects.filter(pk=pinned.pk).update(updated_at=timezone.now())
        ChapterRevision.objects.create(chapter=self.chapter, text="older", source="file")
        ChapterRevision.objects.filter(pk=pinned.pk).update(updated_at=timezone.now())
        self.section.full_body += "\n\nجمله‌ی تازه."
        self.section.save()
        editing.record_revision(self.chapter, user=None, source=ChapterRevision.Source.PANEL)
        self.assertEqual(ChapterRevision.objects.get(pk=pinned.pk).text, text)

    def test_trace_by_fingerprint_and_by_text(self):
        marked = self.copy(self.phrase).data["text"]
        event = CopyEvent.objects.get()
        found = core.trace("در کانالی دیدم: " + marked)
        self.assertEqual(found["marked"], [event])
        found = core.trace("در کانالی دیدم: " + fingerprint.strip(marked))
        self.assertEqual(found["similar"], [event])

    def test_tracker_page_switch_and_risk(self):
        admin = User.objects.create_superuser("09120000009")
        self.client.force_login(admin)
        page = self.client.get("/admin/guard/tracker/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "هشدارهای بله")
        self.assertFalse(GuardSettings.get().bale_alerts)  # off until the owner turns it on
        self.client.post("/admin/guard/tracker/", {"alerts": "on"})
        self.assertTrue(GuardSettings.get().bale_alerts)
        marked = APIClient()
        _, token = DeviceSession.start(self.user, "t2")
        marked.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        text = marked.post(f"/api/v1/nodes/{self.section.id}/copy/", {"text": self.phrase}, format="json").data["text"]
        r = self.client.post("/admin/guard/tracker/", {"text": text})
        self.assertContains(r, "09120000001")
        self.assertEqual(TraceHit.objects.count(), 1)
        risk = core.risk_of(self.user)
        self.assertEqual((risk["copies"], risk["hits"]), (1, 25))
        user_page = self.client.get(f"/admin/accounts/user/{self.user.pk}/change/")
        self.assertContains(user_page, "امتیاز خطر")
        self.assertContains(user_page, "بستن کپی متن")
        # Quick toggle buttons on the user page close and reopen copy/report permissions.
        self.client.post(f"/admin/accounts/user/{self.user.pk}/change/", {"_quick_action": "toggle_copy"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.can_copy)
        self.assertEqual(marked.post(f"/api/v1/nodes/{self.section.id}/copy/", {"text": self.phrase}, format="json").status_code, 403)
        self.client.post(f"/admin/accounts/user/{self.user.pk}/change/", {"_quick_action": "toggle_copy"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.can_copy)

    def test_alerts_are_off_by_default(self):
        with override_settings(BALE_BOT_TOKEN="t", BALE_CHAT_ID="1"), mock.patch("apps.catalog.backups.send_text") as send:
            for _ in range(30):
                self.copy(self.phrase)
            self.assertFalse(alerts.nightly(timezone.now().replace(hour=0) + timedelta(hours=23 + 3)))
            send.assert_not_called()

    def test_alerts_when_on(self):
        GuardSettings.objects.update_or_create(pk=1, defaults={"bale_alerts": True})
        with override_settings(BALE_BOT_TOKEN="t", BALE_CHAT_ID="1"), mock.patch("apps.catalog.backups.send_text") as send, \
                mock.patch("apps.guard.alerts._send_later") as later:
            for _ in range(31):
                self.copy(self.phrase)
            self.assertEqual(len([c for c in later.call_args_list if "کپی امروز" in c.args[0]]), 1)
            for i in range(6):
                DeviceSession.start(self.user, f"phone {i}")
            self.assertEqual(len([c for c in later.call_args_list if "دستگاه" in c.args[0]]), 1)  # once a day per account
            night = timezone.localtime().replace(hour=3)
            self.assertTrue(alerts.nightly(night))
            self.assertFalse(alerts.nightly(night))  # once a night
            self.assertIn("خلاصه‌ی شبانه", send.call_args_list[-1].args[0])


    def test_tracker_teacher_isolation(self):
        from apps.catalog.models import BookEditor
        from django.contrib.auth.models import Group

        # Create teacher
        teacher = User.objects.create_user("09121112233", is_staff=True)
        teacher_group, _ = Group.objects.get_or_create(name="استاد کتاب")
        teacher.groups.add(teacher_group)

        # Grant teacher contentnode change perm
        from django.contrib.auth.models import Permission
        p = Permission.objects.get(codename="change_contentnode")
        teacher.user_permissions.add(p)

        self.client.force_login(teacher)
        page = self.client.get("/admin/guard/tracker/")
        self.assertEqual(page.status_code, 200)
        # Teacher does NOT see Bale alert switch or full risk table
        self.assertNotContains(page, "هشدارهای بله:")
        self.assertNotContains(page, "امتیاز خطر حساب‌ها")
        self.assertContains(page, "ردیاب هوشمند حق تألیف لیموخوان")

        # Copy event from book assigned vs unassigned
        book = self.chapter.book()
        marked = APIClient()
        _, token = DeviceSession.start(self.user, "t_iso")
        marked.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        text = marked.post(f"/api/v1/nodes/{self.section.id}/copy/", {"text": self.phrase}, format="json").data["text"]

        # Teacher does NOT own this book yet -> Trace returns empty for teacher
        res_empty = self.client.post("/admin/guard/tracker/", {"text": text})
        self.assertNotContains(res_empty, "0912***0001")

        # Now assign book to teacher
        BookEditor.objects.create(book=book, user=teacher, can_edit_content=True)

        # Trace again -> now teacher sees it masked!
        res_found = self.client.post("/admin/guard/tracker/", {"text": text})
        self.assertContains(res_found, "0912***0001")
        self.assertNotContains(res_found, "09120000001")  # Full phone is masked!
