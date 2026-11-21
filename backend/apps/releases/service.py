import logging

from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Max

from .models import AppRelease

log = logging.getLogger(__name__)
_KEY = "releases:min-build:{}"


def min_build(platform: str) -> int:
    """Oldest build still allowed to use the API (0 = all). Cached for a minute; cleared when admin saves a release."""
    key = _KEY.format(platform)
    value = cache.get(key)
    if value is None:
        try:
            value = (
                AppRelease.objects.filter(platform=platform, is_published=True, is_required=True).aggregate(m=Max("build"))["m"] or 0
            )
        except DatabaseError:
            # Table missing (migrate not run yet): never block the app because of it.
            log.warning("App releases table is not ready; run python manage.py migrate")
            return 0
        cache.set(key, value, 60)
    return value


def latest(platform: str):
    try:
        return AppRelease.objects.filter(platform=platform, is_published=True).order_by("-build").first()
    except DatabaseError:
        return None


def clear_cache():
    for platform, _ in AppRelease.PLATFORMS:
        cache.delete(_KEY.format(platform))


def abis_of(request) -> list[str]:
    """The phone's processor types, sent by the Android app (X-App-Abi, or ?abi= on app/version/), best first."""
    raw = request.headers.get("X-App-Abi", "") or request.GET.get("abi", "")
    return [a for a in raw.split(",") if a][:6]


def describe(release, abis=None):
    if not release:
        return None
    return {
        "build": release.build,
        "version_name": release.version_name,
        "notes": [line.strip() for line in release.notes.splitlines() if line.strip()],
        "download_url": release.link_for(abis),
        "required": release.is_required,
    }
