from django.http import JsonResponse

from .service import abis_of, describe, latest, min_build, normalize_channel

EXEMPT = ("/api/v1/app/version/",)


class MinimumAppVersionMiddleware:
    """
    Builds older than the newest required release of the same channel get HTTP 426 on every API call.
    Legacy/headerless Android APKs omit `X-App-Channel` and default to `test`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        platform = request.headers.get("X-App-Platform", "")
        build = request.headers.get("X-App-Build", "")
        if platform and build.isdigit() and request.path.startswith("/api/") and request.path not in EXEMPT:
            channel = normalize_channel(request.headers.get("X-App-Channel"))
            if int(build) < min_build(platform, channel):
                return JsonResponse(
                    {
                        "code": "update_required",
                        "message": "این نسخه‌ی برنامه دیگر پشتیبانی نمی‌شود. لطفاً نسخه‌ی جدید را نصب کنید.",
                        "latest": describe(latest(platform, channel), abis_of(request)),
                    },
                    status=426,
                )
        return self.get_response(request)
