from django.core.cache import cache
from django.test import TestCase
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
        self.assertContains(page, "https://x.ir/all.apk")
        self.assertContains(page, "https://x.ir/64.apk")
        self.assertContains(page, "https://x.ir/32.apk")
