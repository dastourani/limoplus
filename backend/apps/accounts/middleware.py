from django.conf import settings


class SimpleCorsMiddleware:
    """Lets the web version of the app call the API from the origins listed in CORS_ALLOWED_ORIGINS."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")
        allowed = origin and (origin in settings.CORS_ALLOWED_ORIGINS or (settings.DEBUG and "*" in settings.CORS_ALLOWED_ORIGINS))
        if allowed and request.method == "OPTIONS":
            from django.http import HttpResponse

            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-App-Platform, X-App-Build, X-App-Abi, X-App-Channel, X-View-As"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Vary"] = "Origin"
        return response


ADMIN_FAILS_PER_IP_PER_HOUR = 10
ADMIN_FAILS_PER_PHONE_PER_HOUR = 5


class AdminLoginThrottleMiddleware:
    """
    Blocks guesses on the superuser-only password fallback: after 10 wrong passwords from one address, or 5 for one
    admin phone in an hour, further password attempts are refused. OTP attempts use the shared OTP rate limits.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import HttpResponse
        from django.urls import reverse

        from . import ratelimit
        from .views import _client_ip

        if (
            request.method == "POST"
            and request.path == reverse("admin:login")
            and request.POST.get("action", "password") in ("", "password")
        ):
            from .phone import InvalidPhone, normalize_phone

            raw_phone = (request.POST.get("username") or "").strip()
            try:
                phone = normalize_phone(raw_phone)
            except InvalidPhone:
                phone = raw_phone
            phone = phone[:100]  # Keep the lookup key within RateBucket.key's 120-character column.
            if (
                ratelimit.count(f"admin-fail-ip:{_client_ip(request)}") >= ADMIN_FAILS_PER_IP_PER_HOUR
                or ratelimit.count(f"admin-fail-phone:{phone}") >= ADMIN_FAILS_PER_PHONE_PER_HOUR
            ):
                return HttpResponse(
                    "<p dir='rtl' style='font-family:Tahoma;padding:24px'>تلاش‌های ناموفق زیاد بود. یک ساعت دیگر دوباره امتحان کنید.</p>",
                    status=429,
                )
        return self.get_response(request)
