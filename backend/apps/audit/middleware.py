import contextvars

from django.conf import settings

_current_ip = contextvars.ContextVar("audit_ip", default=None)


def client_ip(request):
    """Client IP as seen through the trusted proxy chain (also used by django-ratelimit)."""
    hops = settings.TRUSTED_PROXY_COUNT
    forwarded = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    if hops and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.META.get("REMOTE_ADDR", "")


def current_ip():
    return _current_ip.get()


class RequestContextMiddleware:
    """Makes the request IP available to the audit log without threading it through every call."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_ip.set(client_ip(request) or None)
        try:
            return self.get_response(request)
        finally:
            _current_ip.reset(token)
