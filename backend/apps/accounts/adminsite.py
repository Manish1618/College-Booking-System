from urllib.parse import quote, urlsplit

from django.contrib.admin import AdminSite
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .permissions import mfa_ok


class GuesthouseAdminSite(AdminSite):
    """Django admin without password login: staff sign in through the portal (SSO/OTP + TOTP)."""

    site_header = "Guesthouse administration"

    def has_permission(self, request):
        return super().has_permission(request) and mfa_ok(request)

    def login(self, request, extra_context=None):
        """Sends the visitor to the portal sign-in, to come back to the admin page they asked for."""
        index = reverse("admin:index", current_app=self.name)
        target = request.GET.get(REDIRECT_FIELD_NAME, "")
        safe = url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()})
        # Never come back to this view itself: it only redirects, so that would loop.
        if not safe or urlsplit(target).path == request.path:
            target = index
        if self.has_permission(request):
            return redirect(target)
        if request.user.is_authenticated and not request.user.is_staff:
            # Signing in again would not help: this account has no access to the admin.
            return redirect("/")
        return redirect(f"/login?next={quote(target)}")
