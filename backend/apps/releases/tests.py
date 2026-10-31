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
