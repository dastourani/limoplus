from django.conf import settings


class WebsiteHostMiddleware:
    """On the website's own host (WEBSITE_HOSTS in .env, e.g. limookhan.ir), the site is served at the root instead of
    the web app; the API, the panel, static files and media stay where they are. Other hosts (the app's, or localhost)
    keep the web app at the root and show the site under /site/."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.hosts = {h.lower() for h in getattr(settings, "WEBSITE_HOSTS", [])}

    def __call__(self, request):
        if self.hosts and request.get_host().split(":")[0].lower() in self.hosts:
            request.urlconf = "config.website_urls"
        return self.get_response(request)
