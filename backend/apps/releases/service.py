from django.core.cache import cache
from django.db.models import Max

from .models import AppRelease

_KEY = "releases:min-build:{}"


def min_build(platform: str) -> int:
    """Oldest build still allowed to use the API (0 = all). Cached for a minute; cleared when admin saves a release."""
    key = _KEY.format(platform)
    value = cache.get(key)
    if value is None:
        value = (
            AppRelease.objects.filter(platform=platform, is_published=True, is_required=True).aggregate(m=Max("build"))["m"] or 0
        )
        cache.set(key, value, 60)
    return value


def latest(platform: str):
    return AppRelease.objects.filter(platform=platform, is_published=True).order_by("-build").first()


def clear_cache():
    for platform, _ in AppRelease.PLATFORMS:
        cache.delete(_KEY.format(platform))


def describe(release):
    if not release:
        return None
    return {
        "build": release.build,
        "version_name": release.version_name,
        "notes": [line.strip() for line in release.notes.splitlines() if line.strip()],
        "download_url": release.download_url,
        "required": release.is_required,
    }
