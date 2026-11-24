import hmac

from django.db import transaction
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .service import abis_of, describe, latest, min_build, normalize_channel


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def app_version(request):
    """What the app at ?platform=android&build=N&channel=... should do: ok, optional (newer build) or required."""
    platform = request.query_params.get("platform", "android")
    build = request.query_params.get("build", "")
    channel = normalize_channel(request.query_params.get("channel") or request.headers.get("X-App-Channel"))
    newest = latest(platform, channel)
    floor = min_build(platform, channel)
    status = "ok"
    if build.isdigit():
        if int(build) < floor:
            status = "required"
        elif newest and int(build) < newest.build:
            status = "optional"
    return Response({"status": status, "channel": channel, "min_build": floor, "latest": describe(newest, abis_of(request))})


@transaction.non_atomic_requests
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def sync_github_webhook(request):
    """Webhook triggered by GitHub Actions or admin to sync the latest released APK."""
    from django.conf import settings
    from .github_sync import sync_release_from_github

    expected_secret = (getattr(settings, "RELEASE_WEBHOOK_SECRET", "") or "").strip()
    if not expected_secret:
        return Response({"error": "webhook_not_configured"}, status=503)

    secret = (request.headers.get("X-Release-Secret") or "").strip()
    if not secret or not hmac.compare_digest(secret, expected_secret):
        return Response({"error": "unauthorized"}, status=403)

    download_files = request.query_params.get("download") in ("1", "true", "True")
    channel = normalize_channel(request.query_params.get("channel"))
    rel, msg = sync_release_from_github(download_files=download_files, channel=channel)
    if not rel:
        return Response({"ok": False, "message": msg}, status=400)

    return Response({
        "ok": True,
        "message": msg,
        "channel": rel.channel,
        "build": rel.build,
        "version_name": rel.version_name,
        "download_url": rel.download_url,
    })
