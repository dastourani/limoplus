"""
LimoPlus backend settings.

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

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[SITE_DOMAIN.split(":")[0], "localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[SITE_URL])
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
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
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))

# --- API --------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.DeviceSessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "EXCEPTION_HANDLER": "rest_framework.views.exception_handler",
}

# --- Accounts, OTP and sessions ---------------------------------------------

MAX_ACTIVE_SESSIONS = env.int("MAX_ACTIVE_SESSIONS", default=2)
SESSION_TOKEN_LIFETIME = timedelta(days=env.int("SESSION_TOKEN_DAYS", default=60))

OTP_LENGTH = 6
OTP_LIFETIME = timedelta(minutes=2)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
OTP_MAX_PER_HOUR = 5
OTP_MAX_WRONG_PER_DAY = 15          # wrong guesses per phone in 24 hours
OTP_REQUESTS_PER_IP_PER_HOUR = 20
OTP_WRONG_PER_IP_PER_HOUR = 30

# "console" prints the code to the server log (for development);
# "raygan" sends a real SMS through RayganSMS.
SMS_BACKEND = env("SMS_BACKEND", default="console")
RAYGAN_USERNAME = env("RAYGAN_USERNAME", default="")
RAYGAN_PASSWORD = env("RAYGAN_PASSWORD", default="")
RAYGAN_SENDER_NUMBER = env("RAYGAN_SENDER_NUMBER", default="")

if not DEBUG and not TESTING and SMS_BACKEND == "console":
    raise ImproperlyConfigured("SMS_BACKEND=console is for development only. Set SMS_BACKEND=raygan on the server.")

# --- Payment (Zibal) --------------------------------------------------------
# Leave empty until the merchant code arrives; "zibal" is Zibal's test merchant.

ZIBAL_MERCHANT = env("ZIBAL_MERCHANT", default="zibal")

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
