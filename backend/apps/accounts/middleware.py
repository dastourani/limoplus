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
            response["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Vary"] = "Origin"
        return response
