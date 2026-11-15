from django.conf import settings
from rest_framework.permissions import BasePermission

from .models import Role


def mfa_ok(request):
    """True when the user has passed TOTP in this session (or MFA is switched off for development)."""
    if not settings.STAFF_MFA_REQUIRED:
        return True
    return getattr(request.user, "otp_device", None) is not None


def is_manager(request):
    user = request.user
    return user.is_authenticated and user.role in (Role.MANAGER, Role.ADMIN) and mfa_ok(request)


def is_admin(request):
    user = request.user
    return user.is_authenticated and user.role == Role.ADMIN and mfa_ok(request)


def is_approver(request):
    user = request.user
    if not user.is_authenticated:
        return False
    return user.role == Role.APPROVER or is_admin(request)


class IsManager(BasePermission):
    message = "Guesthouse manager access with two-step verification is required."

    def has_permission(self, request, view):
        return is_manager(request)


class IsAdmin(BasePermission):
    message = "Super admin access with two-step verification is required."

    def has_permission(self, request, view):
        return is_admin(request)


class IsApprover(BasePermission):
    def has_permission(self, request, view):
        return is_approver(request)
