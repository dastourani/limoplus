"""Where the web app lives.

The site's «ورود»/«شروع» links and the panel's «باز کردن وب اپ با حساب من» must all reach the web app, and the
web app is served on the main host (SITE_URL) — never on the website's own host, where the site is at the root.
"""

from django.conf import settings


def app_base_url() -> str:
    """The web app's address, without a trailing slash.

    APP_URL is either absolute (https://app.example.ir) or relative ("/"). A relative address means "this
    server", which is only true for the main host: on the website's own host there is no web app, so a
    relative address would leave the reader on the site (or land on a 404).
    """
    base = str(getattr(settings, "APP_URL", "/")).rstrip("/")
    if base.startswith(("http://", "https://")):
        return base
    return settings.SITE_URL.rstrip("/") + base
