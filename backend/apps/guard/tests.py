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


class StepThreeGuardOptionATests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from apps.catalog import access
        from apps.catalog.models import BookEditor

        self.group, _ = Group.objects.get_or_create(name=access.BOOK_EDITOR_GROUP)
        self.superuser = User.objects.create_superuser("09120000009", "pw123")
        self.student_a = User.objects.create_user("09120001111", first_name="علی", last_name="رضایی")
        self.student_b = User.objects.create_user("09120002222", first_name="سارا", last_name="محمدی")
        self.student_c = User.objects.create_user("09120003333")

        self.teacher = User.objects.create_user("09120004444", is_staff=True)
        self.teacher.groups.add(self.group)
        self.teacher_pub_only = User.objects.create_user("09120005555", is_staff=True)
        self.teacher_pub_only.groups.add(self.group)

        self.book_a = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب اول", slug="g-book-a", is_published=True)
        ch_a = self.book_a.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل الف", slug="g-ch-a", position=1, is_published=True)
        self.sec_a = ch_a.add_child(
            kind=ContentNode.Kind.SECTION, title="بخش الف", slug="g-sec-a", position=1,
            full_body="متن کامل درس اول برای آزمایش ردیاب متن در کتاب اول است.", is_published=True,
        )

        self.book_b = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب دوم", slug="g-book-b", is_published=True)
        ch_b = self.book_b.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل ب", slug="g-ch-b", position=1, is_published=True)
        self.sec_b = ch_b.add_child(
            kind=ContentNode.Kind.SECTION, title="بخش ب", slug="g-sec-b", position=1,
            full_body="متن کامل درس دوم برای آزمایش ایزولاسیون ردیاب متن در کتاب دوم است.", is_published=True,
        )

        self.book_c = ContentNode.add_root(kind=ContentNode.Kind.BOOK, title="کتاب سوم", slug="g-book-c", is_published=True)
        ch_c = self.book_c.add_child(kind=ContentNode.Kind.CHAPTER, title="فصل ج", slug="g-ch-c", position=1, is_published=True)
        self.sec_c = ch_c.add_child(
            kind=ContentNode.Kind.SECTION, title="بخش ج", slug="g-sec-c", position=1,
            full_body="متن کامل درس سوم برای آزمایش لغو دسترسی در کتاب سوم است.", is_published=True,
        )

        BookEditor.objects.create(book=self.book_a, user=self.teacher, can_edit_content=True)
        BookEditor.objects.create(book=self.book_c, user=self.teacher, can_edit_content=True)
        BookEditor.objects.create(book=self.book_a, user=self.teacher_pub_only, can_edit_content=False, can_request_publication=True)

        self.event_a, self.marked_a = core.record(
            self.student_a, self.sec_a, "متن کامل درس اول برای آزمایش ردیاب متن در کتاب اول", "full", "web"
        )
        self.event_b, self.marked_b = core.record(
            self.student_b, self.sec_b, "متن کامل درس دوم برای آزمایش ایزولاسیون ردیاب متن در کتاب دوم", "full", "web"
        )
        self.event_c, self.marked_c = core.record(
            self.student_c, self.sec_c, "متن کامل درس سوم برای آزمایش لغو دسترسی در کتاب سوم", "full", "web"
        )

        self.hit_b = TraceHit.objects.create(event=self.event_b, found_by=self.superuser, note="یافته کتاب دوم")
        self.hit_c = TraceHit.objects.create(event=self.event_c, found_by=self.superuser, note="یافته کتاب سوم")

    def test_teacher_menu_and_pub_only_denial(self):
        from django.contrib import admin
        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.get("/admin/")
        req.user = self.teacher
        app_list = admin.site.get_app_list(req)
        catalog_models = {m["object_name"] for a in app_list if a["app_label"] == "catalog" for m in a["models"]}
        self.assertIn("Tracker", catalog_models)
        self.assertIn("TraceHit", catalog_models)
        self.assertNotIn("CopyEvent", catalog_models)

        # Teacher without can_edit_content on any book cannot open Tracker or TraceHit
        self.client.force_login(self.teacher_pub_only)
        self.assertEqual(self.client.get("/admin/guard/tracker/").status_code, 403)
        self.assertEqual(self.client.get("/admin/guard/tracehit/").status_code, 403)

    def test_tracker_isolation_masking_and_bale_risk_superuser_only(self):
        self.client.force_login(self.teacher)
        page = self.client.get("/admin/guard/tracker/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "هشدارهای بله")
        self.assertNotContains(page, "امتیاز خطر حساب‌ها")
        self.assertNotContains(page, "/admin/guard/copyevent/")

        # Teacher cannot toggle Bale alerts
        res_bale = self.client.post("/admin/guard/tracker/", {"alerts": "on"})
        self.assertEqual(res_bale.status_code, 403)
        self.assertFalse(GuardSettings.get().bale_alerts)

        # Teacher traces combined text from Book A (owned) and Book B (unowned)
        res_trace = self.client.post("/admin/guard/tracker/", {"text": f"{self.marked_a}\n{self.marked_b}"})
        self.assertEqual(res_trace.status_code, 200)
        self.assertContains(res_trace, "0912***1111")
        self.assertContains(res_trace, "کتاب اول")
        self.assertNotContains(res_trace, "09120001111")
        self.assertNotContains(res_trace, "09120002222")
        self.assertNotContains(res_trace, "0912***2222")
        self.assertNotContains(res_trace, "کتاب دوم")

        # TraceHit created ONLY for Book A, never Book B
        self.assertTrue(TraceHit.objects.filter(event=self.event_a, found_by=self.teacher).exists())
        self.assertFalse(TraceHit.objects.filter(event=self.event_b, found_by=self.teacher).exists())

        # Unmarked similar text from Book B is also excluded for teacher
        res_sim = self.client.post("/admin/guard/tracker/", {"text": fingerprint.strip(self.marked_b)})
        self.assertEqual(res_sim.status_code, 200)
        self.assertContains(res_sim, "چیزی پیدا نشد")
        self.assertNotContains(res_sim, "09120002222")
        self.assertNotContains(res_sim, "0912***2222")

        # Teachers cannot open raw CopyEvent/Tracker object URLs
        self.assertEqual(self.client.get(f"/admin/guard/tracker/{self.event_a.pk}/change/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/guard/tracker/{self.event_a.pk}/history/").status_code, 403)

    def test_tracehit_history_isolation_masking_and_immediate_revocation(self):
        from apps.catalog.models import BookEditor

        hit_a = TraceHit.objects.create(event=self.event_a, found_by=self.teacher, note="یافته کتاب اول")

        # Teacher sees Book A & Book C hits with masked phones, never Book B
        self.client.force_login(self.teacher)
        res_list = self.client.get("/admin/guard/tracehit/")
        self.assertEqual(res_list.status_code, 200)
        self.assertContains(res_list, "کتاب اول")
        self.assertContains(res_list, "0912***1111")
        self.assertContains(res_list, "کتاب سوم")
        self.assertContains(res_list, "0912***3333")
        self.assertNotContains(res_list, "09120001111")
        self.assertNotContains(res_list, "09120003333")
        self.assertNotContains(res_list, "کتاب دوم")
        self.assertNotContains(res_list, "09120002222")
        self.assertNotContains(res_list, f"/admin/accounts/user/{self.student_a.pk}/change/")
        self.assertNotContains(res_list, f"/admin/accounts/user/{self.student_c.pk}/change/")
        self.assertNotContains(res_list, f"/admin/accounts/user/{self.superuser.pk}/change/")

        # Phone search oracle must not match raw phone for teacher
        res_probe = self.client.get("/admin/guard/tracehit/?q=09120001111")
        self.assertEqual(res_probe.status_code, 200)
        self.assertNotContains(res_probe, "0912***1111")

        # Direct URLs: allowed for Book A (masked, read-only), forbidden for Book B
        res_detail_a = self.client.get(f"/admin/guard/tracehit/{hit_a.pk}/change/")
        self.assertEqual(res_detail_a.status_code, 200)
        self.assertContains(res_detail_a, "0912***1111")
        self.assertNotContains(res_detail_a, "09120001111")
        self.assertNotContains(res_detail_a, f"/admin/accounts/user/{self.student_a.pk}/change/")
        self.assertEqual(self.client.get(f"/admin/guard/tracehit/{self.hit_b.pk}/change/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/guard/tracehit/{self.hit_b.pk}/history/").status_code, 403)

        # Revoke Book A permission immediately
        BookEditor.objects.filter(book=self.book_a, user=self.teacher).update(can_edit_content=False)

        # Book A vanishes from TraceHit list & Tracker recent hits, while Book C stays
        res_list_after = self.client.get("/admin/guard/tracehit/")
        self.assertEqual(res_list_after.status_code, 200)
        self.assertNotContains(res_list_after, "کتاب اول")
        self.assertNotContains(res_list_after, "0912***1111")
        self.assertContains(res_list_after, "کتاب سوم")

        res_tracker_after = self.client.get("/admin/guard/tracker/")
        self.assertEqual(res_tracker_after.status_code, 200)
        self.assertNotContains(res_tracker_after, "0912***1111")
        self.assertContains(res_tracker_after, "0912***3333")

        # Direct URLs to Book A finding & book trace view immediately return 403
        self.assertEqual(self.client.get(f"/admin/guard/tracehit/{hit_a.pk}/change/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/guard/tracehit/{hit_a.pk}/history/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/catalog/book/{self.book_a.pk}/trace/").status_code, 403)

        # Tracing Book A's marked text in Tracker no longer matches or creates a hit
        hit_a.delete()
        res_retrace = self.client.post("/admin/guard/tracker/", {"text": self.marked_a})
        self.assertEqual(res_retrace.status_code, 200)
        self.assertContains(res_retrace, "چیزی پیدا نشد")
        self.assertFalse(TraceHit.objects.filter(event=self.event_a, found_by=self.teacher).exists())

        # Revoke remaining Book C permission -> even lists return 403 immediately
        BookEditor.objects.filter(book=self.book_c, user=self.teacher).delete()
        self.assertEqual(self.client.get("/admin/guard/tracehit/").status_code, 403)
        self.assertEqual(self.client.get("/admin/guard/tracker/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/guard/tracehit/{self.hit_c.pk}/change/").status_code, 403)

        # Superuser still sees all hits, Bale alerts, risk table, and can edit TraceHit note
        self.client.force_login(self.superuser)
        res_admin_list = self.client.get("/admin/guard/tracehit/")
        self.assertEqual(res_admin_list.status_code, 200)
        self.assertContains(res_admin_list, "09120002222")
        self.assertContains(res_admin_list, "09120003333")
        res_note = self.client.post(f"/admin/guard/tracehit/{self.hit_b.pk}/change/", {"note": "تذکر ارسال شد"})
        self.assertEqual(res_note.status_code, 302)
        self.hit_b.refresh_from_db()
        self.assertEqual(self.hit_b.note, "تذکر ارسال شد")

    def test_mask_phone_hides_short_legacy_inputs(self):
        self.assertEqual(core.mask_phone(""), "کاربر لیموخوان")
        self.assertEqual(core.mask_phone("123456"), "کاربر لیموخوان")
        self.assertEqual(core.mask_phone("1234567"), "کاربر لیموخوان")
        self.assertEqual(core.mask_phone("12345678"), "کاربر لیموخوان")
        self.assertEqual(core.mask_phone("09123334455"), "0912***4455")

    def test_similarity_trace_prescoped_not_starved_by_other_books(self):
        from apps.catalog.models import BookEditor

        shared_quote = "این جمله مشترک برای آزمایش عدم تداخل بیش از پنجاه کپی در کتاب‌های دیگر است"
        # Older match in Book A (permitted for self.teacher)
        event_a_shared, _ = core.record(self.student_a, self.sec_a, shared_quote, "full", "web")
        # 55 newer matches in Book B (more than core.trace's 50-match cap!)
        for _ in range(55):
            core.record(self.student_b, self.sec_b, shared_quote, "full", "web")
        # Make sure Book A's shared event is strictly older than the 55 Book B events
        CopyEvent.objects.filter(pk=event_a_shared.pk).update(created_at=timezone.now() - timedelta(days=5))

        # 1) Global TrackerAdmin scoped to teacher's permitted books still finds Book A's match
        self.client.force_login(self.teacher)
        res_tracker = self.client.post("/admin/guard/tracker/", {"text": shared_quote})
        self.assertEqual(res_tracker.status_code, 200)
        self.assertContains(res_tracker, "کتاب اول")
        self.assertContains(res_tracker, "0912***1111")
        self.assertNotContains(res_tracker, "09120001111")
        self.assertNotContains(res_tracker, "کتاب دوم")
        self.assertNotContains(res_tracker, "0912***2222")

        # 2) Dedicated Book A trace view scoped to Book A alone even when teacher ALSO has Book B permission
        BookEditor.objects.create(book=self.book_b, user=self.teacher, can_edit_content=True)
        res_book = self.client.post(f"/admin/catalog/book/{self.book_a.pk}/trace/", {"text": shared_quote})
        self.assertEqual(res_book.status_code, 200)
        self.assertContains(res_book, "0912***1111")
        self.assertNotContains(res_book, "09120001111")
        self.assertNotContains(res_book, "0912***2222")


