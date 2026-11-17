from django.conf import settings


class WebsiteHostMiddleware:
    """On the website's own host (WEBSITE_HOSTS in .env, e.g. limookhan.ir), the site is served at the root instead of
    the web app; the API, the panel, static files and media stay where they are. Other hosts (the app's, or localhost)
    keep the web app at the root and show the site under /site/."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.hosts = {h.lower() for h in getattr(settings, "WEBSITE_HOSTS", [])}

    def __call__(self, request):
        is_site_host = bool(self.hosts and request.get_host().split(":")[0].lower() in self.hosts)
        if is_site_host:
            request.urlconf = "config.website_urls"
        response = self.get_response(request)
        if (is_site_host or request.path.startswith("/site/")) and response.get("Content-Type", "").startswith("text/html"):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
        return response
