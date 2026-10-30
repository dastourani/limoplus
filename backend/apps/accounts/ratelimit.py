"""Hourly counters in the database, so every server process sees the same numbers."""

from django.db import IntegrityError, connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import RateBucket


def _window():
    return timezone.now().replace(minute=0, second=0, microsecond=0)


def count(key: str) -> int:
    bucket = RateBucket.objects.filter(key=key, window_start=_window()).first()
    return bucket.count if bucket else 0


def hit(key: str) -> None:
    window = _window()
    if RateBucket.objects.filter(key=key, window_start=window).update(count=F("count") + 1):
        return
    try:
        with transaction.atomic():
            RateBucket.objects.create(key=key, window_start=window, count=1)
    except IntegrityError:
        RateBucket.objects.filter(key=key, window_start=window).update(count=F("count") + 1)


def lock(name: str) -> None:
    """Serialise work on one key (e.g. a phone number) until the transaction ends."""
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [name])
    # SQLite (development only) already serialises writes.
