import logging

import requests
from django.conf import settings

from apps.audit.middleware import client_ip

logger = logging.getLogger(__name__)
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify(request):
    """Checks the Cloudflare Turnstile token on a form post. Skipped until the key pair is configured."""
    if not settings.TURNSTILE_SECRET_KEY:
        return True
    token = request.data.get("turnstile_token", "")
    if not token:
        return False
    try:
        resp = requests.post(
            VERIFY_URL,
            data={"secret": settings.TURNSTILE_SECRET_KEY, "response": token, "remoteip": client_ip(request)},
            timeout=5,
        )
        return bool(resp.json().get("success"))
    except (requests.RequestException, ValueError):
        logger.exception("Turnstile verification failed")
        return False
