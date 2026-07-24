"""Django settings for winecellar.

Single settings module; environment-specific values come from .env
(gitignored) via django-environ. Secrets never live in this file.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, "dev-only-insecure-key-change-for-any-deployment"),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env("DEBUG")
SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# Full origins (scheme + host) trusted for CSRF. ALLOWED_HOSTS is NOT enough
# behind a TLS-terminating proxy — POSTs 403 without this (foundation lesson).
# e.g. CSRF_TRUSTED_ORIGINS=https://wine.example.com
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# --- Production hardening (all gated on DEBUG=False; dev/tests are unaffected) ---
if not DEBUG:
    # TLS terminates at Caddy (behind Cloudflare orange-cloud); trust the proto
    # it forwards so Django knows the original request was HTTPS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    # Caddy already redirects http->https at the edge; don't double-redirect here.
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
    # HSTS, scoped to the wine host. Set SECURE_HSTS_SECONDS=0 to disable.
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "cellar",
    "assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Site-wide login requirement; auth views (login) are exempt automatically.
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Read-only enforcement for guest accounts (server-side wall). Must sit
    # after MessageMiddleware so the blocked-guest redirect can flash a message
    # (request._messages is set by then); still after auth, which is all it needs.
    "core.middleware.GuestPolicyMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# Prod only: WhiteNoise serves the hashed manifest static (right after security).
# Skipped in dev/tests where runserver serves /static/ via finders.
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.guest",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db_url("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="America/New_York")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Prod: WhiteNoise compressed + hashed manifest (needs collectstatic, DEBUG=False).
# Dev/tests: plain storage, so {% static %} works without a manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "cellar:dashboard"
LOGOUT_REDIRECT_URL = "login"

# --- AI (assistant app) ---
ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")
ANTHROPIC_MODEL = env("ANTHROPIC_MODEL", default="claude-opus-4-8")

# --- Distributor email polling (legacy IMAP ingress; kept for standalone
#     self-host use, superseded by the Email Worker webhook below) ---
DISTRIBUTOR_IMAP_HOST = env("DISTRIBUTOR_IMAP_HOST", default="")
DISTRIBUTOR_IMAP_USER = env("DISTRIBUTOR_IMAP_USER", default="")
DISTRIBUTOR_IMAP_PASSWORD = env("DISTRIBUTOR_IMAP_PASSWORD", default="")
DISTRIBUTOR_IMAP_FOLDER = env("DISTRIBUTOR_IMAP_FOLDER", default="INBOX")

# --- Distributor inbox (Email Worker -> webhook ingress) ---
# Shared bearer secret the Cloudflare Email Worker presents; blank disables the
# webhook (503) so the endpoint is inert until configured.
DISTRIBUTOR_WEBHOOK_SECRET = env("DISTRIBUTOR_WEBHOOK_SECRET", default="")
# Who composed recommendations go to, and whose TasteProfile (standing buying
# instructions + lens toggles) configures the analysis. Username resolves the
# profile; blank falls back to household-wide tastes and all lenses on.
DISTRIBUTOR_RECIPIENT = env("DISTRIBUTOR_RECIPIENT", default="")
DISTRIBUTOR_OWNER_USERNAME = env("DISTRIBUTOR_OWNER_USERNAME", default="")
# Categories forwarded untouched instead of analyzed (the model infers this too;
# these are explicit standing passes for a given household's distributor).
DISTRIBUTOR_PASS_CATEGORIES = env.list(
    "DISTRIBUTOR_PASS_CATEGORIES",
    default=[
        "spirits / whiskey",
        "beer",
        "events / tastings / classes",
        "order confirmations / receipts",
        "account / general marketing",
    ],
)

# --- Email sending (shared mail infra: Resend SMTP; see infra/docs/mail.md) ---
EMAIL_HOST = env("EMAIL_HOST", default="smtp.resend.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="resend")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")  # the Resend API key on the box
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="cellar@example.com")
# Real SMTP only when a password is configured; otherwise print to the console
# (keeps dev/CI from needing credentials).
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST_PASSWORD
    else "django.core.mail.backends.console.EmailBackend"
)

# --- Logging: detail firehose to logs/app.log, console stays quiet ---
(BASE_DIR / "logs").mkdir(exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{asctime} {levelname} {name} {message}", "style": "{"},
    },
    "handlers": {
        "file": {
            "class": "logging.FileHandler",
            "filename": BASE_DIR / "logs" / "app.log",
            "level": "DEBUG",
            "formatter": "verbose",
            "encoding": "utf-8",
        },
        "console": {
            "class": "logging.StreamHandler",
            "level": env("CONSOLE_LOG_LEVEL", default="WARNING"),
            "formatter": "verbose",
        },
    },
    "loggers": {
        "winecellar": {"handlers": ["file", "console"], "level": "DEBUG"},
    },
}
