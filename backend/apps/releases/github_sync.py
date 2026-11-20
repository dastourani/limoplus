"""
Service to synchronise app releases directly from GitHub Releases.
Fetches latest release assets (universal APK, arm64, 32bit) and stores either download URLs
or automatically downloads the APK files to media storage for faster domestic downloads.
"""

import json
import logging
import re
import urllib.request
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from .models import AppRelease
from .service import clear_cache

log = logging.getLogger(__name__)

GITHUB_REPO = getattr(settings, "GITHUB_REPOSITORY", "dastourani/limoplus")


def fetch_latest_github_release(repo: str = GITHUB_REPO) -> dict | None:
    """Fetch the newest release metadata from GitHub API."""
    url = f"https://api.github.com/repos/{repo}/releases"
    headers = {"User-Agent": "Limoplus-AppRelease-Sync", "Accept": "application/vnd.github.v3+json"}
    token = getattr(settings, "GITHUB_TOKEN", None)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not isinstance(data, list) or not data:
                return None
            for rel in data:
                tag = rel.get("tag_name", "")
                if tag.startswith("apk-"):
                    return rel
            return data[0]
    except Exception as exc:
        log.warning("Failed to fetch GitHub releases: %s", exc)
        return None


def sync_release_from_github(download_files: bool = False, repo: str = GITHUB_REPO) -> tuple[AppRelease | None, str]:
    """
    Reads the latest GitHub APK release and creates or updates the corresponding AppRelease row.
    If download_files is True, downloads the APK assets into the server's media storage.
    """
    rel = fetch_latest_github_release(repo)
    if not rel:
        return None, "هیچ نسخه‌ای در Releases گیت‌هاب یافت نشد یا ارتباط برقرار نشد."

    tag = rel.get("tag_name", "")
    match = re.search(r"(\d+)", tag)
    if not match:
        return None, f"تگ نسخه ({tag}) فاقد شماره ساخت معتبر است."

    build_num = int(match.group(1))
    version_name = f"1.0.{build_num}"

    # Extract assets
    universal_url = ""
    arm64_url = ""
    bit32_url = ""

    assets = rel.get("assets", [])
    for a in assets:
        name = a.get("name", "").lower()
        dl = a.get("browser_download_url", "")
        if "arm64" in name:
            arm64_url = dl
        elif "32bit" in name or "armeabi" in name:
            bit32_url = dl
        elif name.endswith(".apk"):
            universal_url = dl

    if not universal_url and not arm64_url and not bit32_url:
        return None, "فایل APK در فایل‌های پیوست این نسخه یافت نشد."

    # Body / notes
    body = rel.get("body", "").strip()
    notes_lines = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("- `limookhan"):
            continue
        clean_line = re.sub(r"^[#\-*•]\s*", "", line).strip()
        if clean_line:
            notes_lines.append(clean_line)
    notes = "\n".join(notes_lines) or "بهبود کارایی و حل مشکلات گزارش‌شده"

    with transaction.atomic():
        release, created = AppRelease.objects.get_or_create(
            platform=AppRelease.ANDROID,
            build=build_num,
            defaults={
                "version_name": version_name,
                "notes": notes,
                "download_url": universal_url,
                "url_arm64": arm64_url,
                "url_32": bit32_url,
                "is_published": True,
            },
        )
        if not created:
            if not release.download_url and universal_url:
                release.download_url = universal_url
            if not release.url_arm64 and arm64_url:
                release.url_arm64 = arm64_url
            if not release.url_32 and bit32_url:
                release.url_32 = bit32_url
            if not release.notes:
                release.notes = notes
            release.save()

        # If file download was requested, download into media storage
        if download_files:
            _download_asset_to_field(universal_url, release, "apk", f"limookhan-{build_num}.apk")
            if arm64_url:
                _download_asset_to_field(arm64_url, release, "apk_arm64", f"limookhan-{build_num}-arm64.apk")
            if bit32_url:
                _download_asset_to_field(bit32_url, release, "apk_32", f"limookhan-{build_num}-32bit.apk")
            release.save()

        clear_cache()

    # Send Bale alert
    try:
        from apps.catalog.backups import notify_bale
        from apps.catalog.panel_display import fa_number
        notify_bale(
            f"🚀 نسخه جدید اپلیکیشن همگام‌سازی شد\n"
            f"شماره ساخت: {fa_number(build_num)} (نسخه {version_name})\n"
            f"فایل‌ها: {'دانلود مستقیم در سرور پارس‌پک' if download_files else 'لینک‌های مستقیم گیت‌هاب'}\n"
            f"تغییرات: {notes[:100]}"
        )
    except Exception:
        pass

    action_text = "ثبت شد" if created else "به‌روزرسانی شد"
    return release, f"نسخه {build_num} ({version_name}) با موفقیت {action_text}."


def _download_asset_to_field(url: str, instance: AppRelease, field_name: str, filename: str):
    """Downloads a file from url and saves it into the FileField."""
    if not url:
        return
    existing = getattr(instance, field_name)
    if existing and existing.name:
        return  # already has a file

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Limoplus-Downloader"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = resp.read()
            getattr(instance, field_name).save(filename, ContentFile(content), save=False)
            log.info("Saved %s to %s (%d bytes)", url, field_name, len(content))
    except Exception as exc:
        log.warning("Failed to download %s to %s: %s", url, field_name, exc)
