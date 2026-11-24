from django.core.cache import cache
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from .models import AppRelease


class AppVersionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def add(self, build, required=False, published=True):
        AppRelease.objects.create(build=build, download_url=f"https://example.com/{build}.apk", is_required=required, is_published=published, notes="یک\n\nدو")
        cache.clear()

    def status(self, build):
        return self.client.get(f"/api/v1/app/version/?platform=android&build={build}").json()

    def test_no_releases_is_ok(self):
        self.assertEqual(self.status(9)["status"], "ok")

    def test_newer_build_is_optional(self):
        self.add(10)
        data = self.status(9)
        self.assertEqual(data["status"], "optional")
        self.assertEqual(data["latest"]["build"], 10)
        self.assertEqual(data["latest"]["notes"], ["یک", "دو"])
        self.assertEqual(self.status(10)["status"], "ok")

    def test_required_release_cuts_off_older_builds(self):
        self.add(10, required=True)
        self.add(11)
        self.assertEqual(self.status(9)["status"], "required")
        self.assertEqual(self.status(10)["status"], "optional")
        old = self.client.get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="9")
        self.assertEqual(old.status_code, 426)
        self.assertEqual(old.json()["code"], "update_required")
        self.assertEqual(old.json()["latest"]["build"], 11)
        self.assertEqual(self.client.get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="10").status_code, 200)
        # Clients that do not name a build (web, tools) are not blocked.
        self.assertEqual(self.client.get("/api/v1/majors/").status_code, 200)

    def test_unpublished_release_is_ignored(self):
        self.add(12, required=True, published=False)
        self.assertEqual(self.status(9)["status"], "ok")
        self.assertEqual(self.client.get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="9").status_code, 200)


class MissingTableTests(TestCase):
    def test_api_keeps_working_without_the_releases_table(self):
        from unittest import mock

        from django.db import DatabaseError

        cache.clear()
        with mock.patch("apps.releases.service.AppRelease.objects.filter", side_effect=DatabaseError("no such table")):
            r = APIClient().get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="10")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(APIClient().get("/api/v1/app/version/?platform=android&build=10").json()["status"], "ok")


class UploadedApkTests(TestCase):
    def test_uploaded_apk_is_the_download_link(self):
        import shutil
        import tempfile

        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        with override_settings(MEDIA_ROOT=media, SITE_URL="https://api.example.ir"):
            r = AppRelease(build=12, apk=SimpleUploadedFile("limookhan-12.apk", b"PK"))
            r.full_clean()
            r.save()
            self.assertTrue(r.link.startswith("https://api.example.ir/media/apk/limookhan-12"))
            with self.assertRaises(ValidationError):
                AppRelease(build=13).full_clean()
            with self.assertRaises(ValidationError):
                AppRelease(build=14, apk=SimpleUploadedFile("x.zip", b"PK")).full_clean()


class ThreeFilesTests(TestCase):
    """One universal APK, plus two lighter ones; the app's update and the 426 notice get the one that fits the phone."""

    def setUp(self):
        cache.clear()
        AppRelease.objects.create(build=20, download_url="https://x.ir/all.apk", url_arm64="https://x.ir/64.apk",
                                  url_32="https://x.ir/32.apk", is_required=True)
        cache.clear()

    def url(self, **headers):
        return APIClient().get("/api/v1/app/version/?platform=android&build=19", **headers).json()["latest"]["download_url"]

    def test_file_per_phone(self):
        self.assertEqual(self.url(), "https://x.ir/all.apk")  # old builds send nothing
        self.assertEqual(self.url(HTTP_X_APP_ABI="arm64-v8a,armeabi-v7a,armeabi"), "https://x.ir/64.apk")
        self.assertEqual(self.url(HTTP_X_APP_ABI="armeabi-v7a,armeabi"), "https://x.ir/32.apk")
        self.assertEqual(self.url(HTTP_X_APP_ABI="x86_64"), "https://x.ir/all.apk")
        r = APIClient().get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="19", HTTP_X_APP_ABI="armeabi-v7a")
        self.assertEqual(r.status_code, 426)
        self.assertEqual(r.json()["latest"]["download_url"], "https://x.ir/32.apk")

    def test_missing_light_file_falls_back(self):
        AppRelease.objects.filter(build=20).update(url_32="")
        self.assertEqual(self.url(HTTP_X_APP_ABI="armeabi-v7a"), "https://x.ir/all.apk")

    def test_website_shows_all_three(self):
        page = self.client.get("/site/download/")
        if page.status_code == 404:
            self.skipTest("website not at /site/ here")
        # Before an official release exists, test releases are hidden and the site says official isn't published yet.
        self.assertContains(page, "نسخهٔ رسمی هنوز منتشر نشده")
        self.assertNotContains(page, "https://x.ir/all.apk")

        AppRelease.objects.create(
            channel=AppRelease.CHANNEL_OFFICIAL,
            build=1,
            download_url="https://x.ir/official-all.apk",
            url_arm64="https://x.ir/official-64.apk",
            url_32="https://x.ir/official-32.apk",
        )
        page_official = self.client.get("/site/download/")
        self.assertContains(page_official, "https://x.ir/official-all.apk")
        self.assertContains(page_official, "https://x.ir/official-64.apk")
        self.assertContains(page_official, "https://x.ir/official-32.apk")


class SyncGithubWebhookTests(TransactionTestCase):
    ENDPOINT = "/api/v1/releases/sync-github/"

    def test_unconfigured_secret_rejects_even_with_django_secret_key(self):
        from django.test import override_settings

        with override_settings(RELEASE_WEBHOOK_SECRET=""):
            res = APIClient().post(self.ENDPOINT, HTTP_X_RELEASE_SECRET="test-only")
            self.assertEqual(res.status_code, 503)

    def test_query_secret_is_ignored_and_header_is_required(self):
        from django.test import override_settings

        with override_settings(RELEASE_WEBHOOK_SECRET="whsec-123"):
            res_qs = APIClient().post(f"{self.ENDPOINT}?secret=whsec-123")
            self.assertEqual(res_qs.status_code, 403)
            res_bad = APIClient().post(self.ENDPOINT, HTTP_X_RELEASE_SECRET="wrong")
            self.assertEqual(res_bad.status_code, 403)

    def test_valid_header_syncs_and_downloads_outside_transaction(self):
        import shutil
        import tempfile
        from unittest import mock

        from django.db import connection
        from django.test import override_settings

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, True)
        sample_rel = {
            "tag_name": "apk-105",
            "body": "- بهبود سرعت\n- `limookhan-test-105.apk`",
            "assets": [
                {"name": "limookhan-test-105.apk", "browser_download_url": "https://example.com/u.apk"},
                {"name": "limookhan-test-105-arm64.apk", "browser_download_url": "https://example.com/64.apk"},
            ],
        }
        in_atomic_during_fetch = []

        def fake_fetch(url, field_name):
            in_atomic_during_fetch.append(connection.in_atomic_block)
            return b"PK\x03\x04apk"

        with (
            override_settings(RELEASE_WEBHOOK_SECRET="whsec-123", MEDIA_ROOT=media),
            mock.patch("apps.releases.github_sync.fetch_latest_github_release", return_value=sample_rel),
            mock.patch("apps.releases.github_sync._fetch_asset_bytes", side_effect=fake_fetch),
        ):
            res = APIClient().post(f"{self.ENDPOINT}?download=1", HTTP_X_RELEASE_SECRET="whsec-123")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["build"], 105)
        self.assertEqual(res.json()["channel"], AppRelease.CHANNEL_TEST)
        self.assertEqual(in_atomic_during_fetch, [False, False])
        rel = AppRelease.objects.get(build=105, channel=AppRelease.CHANNEL_TEST)
        self.assertTrue(rel.apk.name.endswith(".apk"))
        self.assertTrue(rel.apk_arm64.name.endswith(".apk"))


class AppReleaseChannelIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_channels_are_isolated_and_headerless_defaults_to_test(self):
        # Test channel and official channel can share the same build number independently.
        test_rel = AppRelease.objects.create(channel=AppRelease.CHANNEL_TEST, build=10, download_url="https://x.ir/test-10.apk", is_required=False)
        off_rel = AppRelease.objects.create(channel=AppRelease.CHANNEL_OFFICIAL, build=10, download_url="https://x.ir/off-10.apk", is_required=True)
        self.assertEqual(test_rel.channel, AppRelease.CHANNEL_TEST)
        self.assertEqual(off_rel.channel, AppRelease.CHANNEL_OFFICIAL)

        # Headerless legacy build 5 defaults to `test`, so official required=10 does NOT block it.
        ok_legacy = self.client.get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="5")
        self.assertEqual(ok_legacy.status_code, 200)

        # Official build 5 IS blocked by official required=10 and gets the official APK link.
        blocked_off = self.client.get("/api/v1/majors/", HTTP_X_APP_PLATFORM="android", HTTP_X_APP_BUILD="5", HTTP_X_APP_CHANNEL="official")
        self.assertEqual(blocked_off.status_code, 426)
        self.assertEqual(blocked_off.json()["latest"]["download_url"], "https://x.ir/off-10.apk")

        # app/version/ respects ?channel= and X-App-Channel independently.
        v_test = self.client.get("/api/v1/app/version/?platform=android&build=5&channel=test").json()
        self.assertEqual(v_test["status"], "optional")
        self.assertEqual(v_test["latest"]["download_url"], "https://x.ir/test-10.apk")
        v_off = self.client.get("/api/v1/app/version/?platform=android&build=5&channel=official").json()
        self.assertEqual(v_off["status"], "required")
        self.assertEqual(v_off["latest"]["download_url"], "https://x.ir/off-10.apk")

    def test_github_sync_separates_official_and_test_releases(self):
        import json
        from io import BytesIO
        from unittest import mock
        from apps.releases.github_sync import sync_release_from_github

        releases_payload = json.dumps([
            {
                "tag_name": "apk-25",
                "prerelease": True,
                "body": "- test build 25",
                "assets": [{"name": "limookhan-test-25.apk", "browser_download_url": "https://example.com/test-25.apk"}],
            },
            {
                "tag_name": "official-3",
                "prerelease": False,
                "body": "- official build 3",
                "assets": [{"name": "limookhan-3.apk", "browser_download_url": "https://example.com/official-3.apk"}],
            },
        ]).encode("utf-8")

        class FakeResp(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **kw: FakeResp(releases_payload)):
            off_rel, _ = sync_release_from_github(channel=AppRelease.CHANNEL_OFFICIAL)
            test_rel, _ = sync_release_from_github(channel=AppRelease.CHANNEL_TEST)

        self.assertEqual((off_rel.channel, off_rel.build), (AppRelease.CHANNEL_OFFICIAL, 3))
        self.assertEqual((test_rel.channel, test_rel.build), (AppRelease.CHANNEL_TEST, 25))

