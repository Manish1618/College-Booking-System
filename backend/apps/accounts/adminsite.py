from urllib.parse import quote

from django.contrib.admin import AdminSite
from django.shortcuts import redirect

from .permissions import mfa_ok


class GuesthouseAdminSite(AdminSite):
    """Django admin without password login: staff sign in through the portal (SSO/OTP + TOTP)."""

    site_header = "Guesthouse administration"

    def has_permission(self, request):
        return super().has_permission(request) and mfa_ok(request)

    def login(self, request, extra_context=None):
        return redirect(f"/login?next={quote(request.get_full_path())}")
