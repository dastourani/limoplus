"""
LimooKhan backend settings.

Every value that differs between your computer and the real server comes from
`backend/.env` (see `.env.example`). Nothing secret or host-specific is written
in this file.
"""

import sys
from datetime import timedelta
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

# --- Core -------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY")
# Key for hashing login codes and session tokens. Kept separate so SECRET_KEY can be
# rotated without signing every user out. Changing HASH_KEY signs everyone out.
HASH_KEY = env("HASH_KEY", default=SECRET_KEY)
DEBUG = env.bool("DEBUG", default=False)
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

# Number of reverse proxies (e.g. nginx) in front of the app that append to
# X-Forwarded-For. 0 = use the direct connection address only.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)

# The one setting that changes when moving to a real domain.
SITE_DOMAIN = env("SITE_DOMAIN", default="localhost:8000")
SITE_SCHEME = env("SITE_SCHEME", default="http" if DEBUG else "https")
SITE_URL = f"{SITE_SCHEME}://{SITE_DOMAIN}"

# Address of the admin panel. On the real server use something only you know, e.g. "manage-7f3k/".
ADMIN_URL = env("ADMIN_URL", default="admin/").strip("/") + "/"
# «باز کردن وب اپ با حساب من» (panel → web app without an SMS): how long the one-time code works.
PANEL_LOGIN_SECONDS = 60



def env_hosts(name, default=None):
    """A comma-separated list from the environment. Some hosting panels turn «www.example.ir» into a Markdown link
    («[www.example.ir](https://www.example.ir)») when it is typed in: keep only the text inside the brackets."""
    import re

    raw = env.str(name, default=None)
    if raw is None:
        return list(default or [])
    raw = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)
    return [item.strip() for item in raw.split(",") if item.strip()]


ALLOWED_HOSTS = env_hosts("ALLOWED_HOSTS", default=[SITE_DOMAIN.split(":")[0], "localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env_hosts("CSRF_TRUSTED_ORIGINS", default=[SITE_URL])
CORS_ALLOWED_ORIGINS = env_hosts("CORS_ALLOWED_ORIGINS")

INSTALLED_APPS = [
    "config.admin.LimoAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "treebeard",
    "apps.accounts",
    "apps.catalog",
    "apps.learning",
    "apps.study",
    "apps.commerce",
    "apps.releases",
    "apps.website",
    "apps.guard",
    "apps.diagnostics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.middleware.SimpleCorsMiddleware",
    "apps.diagnostics.middleware.RequestDiagnosticsMiddleware",
    "apps.accounts.middleware.AdminLoginThrottleMiddleware",
    "apps.releases.middleware.MinimumAppVersionMiddleware",
    "apps.website.middleware.WebsiteHostMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # backend/templates: the panel's own admin/base_site.html (before django.contrib.admin's).
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------
# PostgreSQL in Docker and on the server; SQLite only as a quick local fallback.

# An empty or missing DATABASE_URL means SQLite in backend/db.sqlite3. The SQLite path is set directly (not as a URL)
# so Windows paths with spaces or brackets, e.g. "C:\\Dropbox (Maestral)\\...", work.
if env.str("DATABASE_URL", default="").strip():
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # SQLite (the laptop server): the app sends several requests at once. Each request takes the write lock when it
    # starts and others wait for it (up to 20 s) instead of failing with «database is locked»; WAL lets reads go on
    # while one request writes. PostgreSQL on the real server needs none of this.
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"timeout": 20, "transaction_mode": "IMMEDIATE", "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"}
    )

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

# --- Language and time ------------------------------------------------------

LANGUAGE_CODE = "fa"
TIME_ZONE = "Asia/Tehran"
USE_I18N = True
USE_TZ = True

# --- Files ------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise serves the panel's and the website's static files when there is no nginx in front (e.g. ParsPack PaaS).
# The hashed (manifest) storage needs `collectstatic` first, so it is used only on the real server.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG or TESTING
        else "config.storage.StaticStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
# True when no web server (nginx) serves MEDIA_ROOT, e.g. on ParsPack PaaS. Point MEDIA_ROOT at a persistent disk there.
SERVE_MEDIA = env.bool("SERVE_MEDIA", default=False)

# Backups (apps/catalog/backups.py): kept in BACKUP_DIR (on the server: the persistent disk) and sent to the admin's
# chat in Bale when the bot is set. A Bale bot token from @BotFather in Bale; the chat id of the admin's chat with it.
BACKUP_DIR = Path(env("BACKUP_DIR", default=str(BASE_DIR / "backups")))
# Backup storage mode: 'bale_chunks' (default), 'object_storage' (S3-compatible e.g. ParsPack), or 'both'.
BACKUP_STORAGE_MODE = env("BACKUP_STORAGE_MODE", default="bale_chunks")
BACKUP_S3_ENDPOINT = env("BACKUP_S3_ENDPOINT", default="")
BACKUP_S3_BUCKET = env("BACKUP_S3_BUCKET", default="")
BACKUP_S3_ACCESS_KEY = env("BACKUP_S3_ACCESS_KEY", default="")
BACKUP_S3_SECRET_KEY = env("BACKUP_S3_SECRET_KEY", default="")
BACKUP_S3_REGION = env("BACKUP_S3_REGION", default="us-east-1")
BACKUP_S3_PREFIX = env("BACKUP_S3_PREFIX", default="limoplus-backups")
BACKUP_S3_KEEP = env.int("BACKUP_S3_KEEP", default=30)
BALE_BOT_TOKEN = env("BALE_BOT_TOKEN", default="")
BALE_CHAT_ID = env("BALE_CHAT_ID", default="")
# The website (apps/website): the hosts where it is served at the root (e.g. limookhan.ir,www.limookhan.ir); elsewhere
# it is at /site/. APP_URL: the web app's address for the site's «ورود» and «شروع» links (e.g. https://app.limookhan.ir).
WEBSITE_HOSTS = env_hosts("WEBSITE_HOSTS")
APP_URL = env("APP_URL", default="/")
# The web version of the app (served at the root by apps.catalog.webapp); update.bat fills it.
WEBAPP_DIR = Path(env("WEBAPP_DIR", default=str(BASE_DIR / "webapp")))

# --- API --------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.DeviceSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

# --- Accounts, OTP and sessions ---------------------------------------------

MAX_ACTIVE_SESSIONS = env.int("MAX_ACTIVE_SESSIONS", default=2)
# A device not used for this long is signed out by itself (it no longer takes one of the places above).
# More new sign-ins than this in 7 days marks a user «تعویض زیاد دستگاه» in the panel (often a shared account).
DEVICE_SWITCH_ALERT = env.int("DEVICE_SWITCH_ALERT", default=4)
SESSION_IDLE = timedelta(days=env.int("SESSION_IDLE_DAYS", default=30))
SESSION_TOKEN_LIFETIME = timedelta(days=env.int("SESSION_TOKEN_DAYS", default=60))

OTP_LENGTH = 6
OTP_LIFETIME = timedelta(minutes=2)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
OTP_MAX_PER_HOUR = 5
OTP_MAX_WRONG_PER_DAY = 15          # wrong guesses per phone in 24 hours
OTP_REQUESTS_PER_IP_PER_HOUR = 20
OTP_WRONG_PER_IP_PER_HOUR = 30

# Public teacher-application form: database-backed hourly submission limits (accounts.ratelimit).
TEACHER_APPLICATIONS_PER_IP_PER_HOUR = env.int("TEACHER_APPLICATIONS_PER_IP_PER_HOUR", default=5)
TEACHER_APPLICATIONS_PER_PHONE_PER_HOUR = env.int("TEACHER_APPLICATIONS_PER_PHONE_PER_HOUR", default=1)

# Public contact/support form: database-backed hourly submission limits (accounts.ratelimit).
CONTACT_MESSAGES_PER_IP_PER_HOUR = env.int("CONTACT_MESSAGES_PER_IP_PER_HOUR", default=8)
CONTACT_MESSAGES_PER_SENDER_PER_HOUR = env.int("CONTACT_MESSAGES_PER_SENDER_PER_HOUR", default=4)

# Shared secret for GitHub Actions -> /api/v1/releases/sync-github/ webhook (header X-Release-Secret).
RELEASE_WEBHOOK_SECRET = env("RELEASE_WEBHOOK_SECRET", default="")

# "console" prints the code to the server log (for development);
# "raygan" sends a real SMS through RayganSMS.
# «خبر دادن به منتظران» (panel, coming-soon books): off until set to True here; the panel then sends one SMS to each
# learner who pressed «خبرم کن», after a confirmation page.
WAITLIST_SMS_ENABLED = env.bool("WAITLIST_SMS_ENABLED", default=False)
SMS_BACKEND = env("SMS_BACKEND", default="console")
RAYGAN_USERNAME = env("RAYGAN_USERNAME", default="")
RAYGAN_PASSWORD = env("RAYGAN_PASSWORD", default="")
RAYGAN_SENDER_NUMBER = env("RAYGAN_SENDER_NUMBER", default="")
# Login codes through RayganSMS's approved pattern (accounts/sms.py): both set = codes go that way.
RAYGAN_ACCESS_HASH = env("RAYGAN_ACCESS_HASH", default="")
RAYGAN_OTP_PATTERN_ID = env("RAYGAN_OTP_PATTERN_ID", default="")
# Adds the Android app's hash line to the login SMS so the phone reads the code by itself. Turn off if the SMS
# provider or operator holds back messages with it.
OTP_SMS_APP_HASH = env.bool("OTP_SMS_APP_HASH", default=True)

if not DEBUG and not TESTING and SMS_BACKEND == "console":
    raise ImproperlyConfigured("SMS_BACKEND=console is for development only. Set SMS_BACKEND=raygan on the server.")

# --- Email ------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend" if (DEBUG or TESTING) else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=15)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="لیموخوان <noreply@limookhan.ir>")
EMAIL_VERIFICATION_EXPIRY_HOURS = env.int("EMAIL_VERIFICATION_EXPIRY_HOURS", default=24)

# --- Payment (Zibal) --------------------------------------------------------
# Leave empty until the merchant code arrives; "zibal" is Zibal's test merchant.

ZIBAL_MERCHANT = env("ZIBAL_MERCHANT", default="zibal")
# False = buying is switched off (the server runs without a real merchant code; nothing can be paid or settled).
PAYMENTS_ENABLED = env.bool("PAYMENTS_ENABLED", default=True)
if not DEBUG and not TESTING and PAYMENTS_ENABLED and ZIBAL_MERCHANT == "zibal":
    # The test merchant "pays" without real money; it must never run on the real server.
    raise ImproperlyConfigured("ZIBAL_MERCHANT=zibal is Zibal's test merchant. Set the real merchant code on the server, or PAYMENTS_ENABLED=False.")
# Where the payment result page sends the user afterwards: the app's deep link (or the web app's address).
APP_RETURN_URL = env("APP_RETURN_URL", default="limookhan://payment-result")
TEST_APP_RETURN_URL = env("TEST_APP_RETURN_URL", default="limookhan-test://payment-result")

# --- Security on the real server --------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=not TESTING)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
