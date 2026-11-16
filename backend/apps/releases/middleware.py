from django.http import JsonResponse

from .service import abis_of, describe, latest, min_build

EXEMPT = ("/api/v1/app/version/",)


class MinimumAppVersionMiddleware:
    """
    Builds older than the newest required release get HTTP 426 on every API call, so the app shows its update screen.
    Only requests that name their build (X-App-Platform / X-App-Build, sent by the Android app) are checked.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        platform = request.headers.get("X-App-Platform", "")
        build = request.headers.get("X-App-Build", "")
        if platform and build.isdigit() and request.path.startswith("/api/") and request.path not in EXEMPT:
            if int(build) < min_build(platform):
                return JsonResponse(
                    {
                        "code": "update_required",
                        "message": "این نسخه‌ی برنامه دیگر پشتیبانی نمی‌شود. لطفاً نسخه‌ی جدید را نصب کنید.",
                        "latest": describe(latest(platform), abis_of(request)),
                    },
                    status=426,
                )
        return self.get_response(request)
