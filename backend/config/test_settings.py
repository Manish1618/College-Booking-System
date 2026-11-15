import os
import tempfile

os.environ.setdefault("SECRET_KEY", "test-only")

from .settings import *  # noqa: E402,F401,F403

DEBUG = False
SECRET_KEY = "test"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CELERY_TASK_ALWAYS_EAGER = True
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
RATELIMIT_ENABLE = False
SILENCED_SYSTEM_CHECKS = ["django_ratelimit.E003", "django_ratelimit.W001"]
STAFF_MFA_REQUIRED = True
OTP_DEBUG_ECHO = False
PAYMENT_GATEWAYS = ["dev"]
COLLEGE_EMAIL_DOMAINS = ["college.example.edu"]
MEDIA_ROOT = tempfile.mkdtemp(prefix="gh-media-")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "private": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": tempfile.mkdtemp(prefix="gh-private-")},
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
