"""Django settings. Everything environment-specific comes from env vars (see .env.example)."""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR.parent / ".env")

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me" if DEBUG else environ.Env.NOTSET)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:3000", "http://localhost:8080"])
SITE_NAME = env("SITE_NAME", default="College Guesthouse")
SITE_URL = env("SITE_URL", default="http://localhost:3000")

INSTALLED_APPS = [
    "config.admin_app.GuesthouseAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "csp",
    "apps.accounts",
    "apps.rooms",
    "apps.bookings",
    "apps.payments",
    "apps.audit",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.audit.middleware.RequestContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
            ]
        },
    }
]

DATABASES = {"default": env.db("DATABASE_URL", default="postgres://guesthouse:guesthouse@localhost:5432/guesthouse")}
DATABASES["default"]["ATOMIC_REQUESTS"] = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# --- Auth -----------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = []  # no passwords are stored; sign-in is SSO or OTP

# Emails on this domain are college members (the SSO fallback named in the PRD).
COLLEGE_EMAIL_DOMAINS = env.list("COLLEGE_EMAIL_DOMAINS", default=["college.example.edu"])

OTP_CODE_TTL_MINUTES = env.int("OTP_CODE_TTL_MINUTES", default=10)
OTP_MAX_ATTEMPTS = env.int("OTP_MAX_ATTEMPTS", default=5)
OTP_REQUEST_RATE_PER_IDENTIFIER = env("OTP_REQUEST_RATE_PER_IDENTIFIER", default="5/h")
OTP_REQUEST_RATE_PER_IP = env("OTP_REQUEST_RATE_PER_IP", default="20/h")
OTP_VERIFY_RATE_PER_IP = env("OTP_VERIFY_RATE_PER_IP", default="30/h")
# Dev helper: return the OTP in the API response. Never enable outside local development.
OTP_DEBUG_ECHO = env.bool("OTP_DEBUG_ECHO", default=False)

# Managers and super admins must pass TOTP before staff actions.
STAFF_MFA_REQUIRED = env.bool("STAFF_MFA_REQUIRED", default=True)
OTP_TOTP_ISSUER = SITE_NAME

# College SSO over OIDC. Off until the college provides client credentials.
OIDC_ENABLED = env.bool("OIDC_ENABLED", default=False)
if OIDC_ENABLED:
    INSTALLED_APPS.append("mozilla_django_oidc")
    AUTHENTICATION_BACKENDS.insert(0, "apps.accounts.oidc.CollegeOIDCBackend")
    OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID")
    OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET")
    OIDC_OP_AUTHORIZATION_ENDPOINT = env("OIDC_OP_AUTHORIZATION_ENDPOINT")
    OIDC_OP_TOKEN_ENDPOINT = env("OIDC_OP_TOKEN_ENDPOINT")
    OIDC_OP_USER_ENDPOINT = env("OIDC_OP_USER_ENDPOINT")
    OIDC_OP_JWKS_ENDPOINT = env("OIDC_OP_JWKS_ENDPOINT")
    OIDC_RP_SIGN_ALGO = env("OIDC_RP_SIGN_ALGO", default="RS256")
    OIDC_RP_SCOPES = "openid email profile"
    LOGIN_REDIRECT_URL = "/"
    LOGOUT_REDIRECT_URL = "/"
    LOGIN_REDIRECT_URL_FAILURE = "/login?error=sso"

# Cloudflare Turnstile. Verification is skipped while the secret is empty.
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", default="")

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 24 * 7)
STAFF_SESSION_AGE = env.int("STAFF_SESSION_AGE", default=60 * 60 * 8)  # short sessions for staff roles
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # the SPA reads it to send X-CSRFToken

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)  # Caddy terminates TLS
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "img-src": ["'self'", "data:"],
        "frame-ancestors": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
    }
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "apps.bookings.exceptions.api_exception_handler",
}

# django-ratelimit: client IP comes from the proxy chain (Cloudflare -> Caddy -> app).
RATELIMIT_IP_META_KEY = "apps.audit.middleware.client_ip"
# Number of trusted reverse proxies in front of the app (Caddy = 1). 0 means use REMOTE_ADDR.
TRUSTED_PROXY_COUNT = env.int("TRUSTED_PROXY_COUNT", default=0)
RATELIMIT_ENABLE = env.bool("RATELIMIT_ENABLE", default=True)

# --- Booking rules (open questions in the PRD; all configurable) -----------
BOOKING_HOLD_HOURS = env.int("BOOKING_HOLD_HOURS", default=48)  # PENDING request holds dates this long
PAYMENT_WINDOW_HOURS = env.int("PAYMENT_WINDOW_HOURS", default=24)  # APPROVED must pay within this
BOOKING_MAX_NIGHTS = env.int("BOOKING_MAX_NIGHTS", default=14)
BOOKING_MAX_ADVANCE_DAYS = env.int("BOOKING_MAX_ADVANCE_DAYS", default=180)
NO_SHOW_HOUR = env.int("NO_SHOW_HOUR", default=12)  # noon the day after check-in
# Payment gateways. "dev" simulates a successful payment and is only allowed when listed here.
PAYMENT_GATEWAYS = env.list("PAYMENT_GATEWAYS", default=[])

# --- Files -----------------------------------------------------------------
UPLOAD_MAX_BYTES = env.int("UPLOAD_MAX_BYTES", default=5 * 1024 * 1024)
PHOTO_WIDTHS = [480, 960, 1600]
SIGNED_URL_TTL_SECONDS = env.int("SIGNED_URL_TTL_SECONDS", default=300)

MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media")))
MEDIA_URL = "/media/"
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_media")))
STATIC_URL = "/static/"
STATIC_ROOT = Path(env("STATIC_ROOT", default=str(BASE_DIR / "staticfiles")))

S3_ENABLED = env.bool("S3_ENABLED", default=False)
if S3_ENABLED:
    _s3 = {
        "endpoint_url": env("S3_ENDPOINT_URL", default=None),
        "region_name": env("S3_REGION", default="ap-south-1"),
        "access_key": env("S3_ACCESS_KEY"),
        "secret_key": env("S3_SECRET_KEY"),
    }
    STORAGES = {
        # Public derivatives of room photos (served through the CDN).
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {**_s3, "bucket_name": env("S3_PUBLIC_BUCKET"), "querystring_auth": False, "default_acl": None},
        },
        # Letters, ID copies and photo originals: private, encrypted, signed URLs only.
        "private": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                **_s3,
                "bucket_name": env("S3_PRIVATE_BUCKET"),
                "querystring_auth": True,
                "querystring_expire": SIGNED_URL_TTL_SECONDS,
                "default_acl": "private",
                "object_parameters": {"ServerSideEncryption": "AES256"},
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
else:
    STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "private": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            # No base_url: private files are only ever served through an authorised view.
            "OPTIONS": {"location": str(PRIVATE_MEDIA_ROOT)},
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# --- Email / SMS -----------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Guesthouse <guesthouse@college.example.edu>")
SMS_BACKEND = env("SMS_BACKEND", default="apps.notifications.sms.ConsoleSMSBackend")

# --- Celery ----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_BEAT_SCHEDULE = {
    "expire-stale-bookings": {"task": "apps.bookings.tasks.expire_stale_bookings", "schedule": crontab(minute="*/10")},
    "mark-no-shows": {"task": "apps.bookings.tasks.mark_no_shows", "schedule": crontab(minute=5)},
}

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = False
USE_TZ = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
