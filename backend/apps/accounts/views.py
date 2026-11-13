from django.conf import settings
from django.contrib.auth import login, logout
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django_otp import devices_for_user
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.audit.middleware import client_ip
from apps.notifications.tasks import send_otp

from . import otp, turnstile
from .models import STAFF_ROLES, User
from .permissions import IsAdmin
from .serializers import AdminUserSerializer, MeSerializer


def _identifier(request):
    try:
        return otp.normalise_identifier(request.data.get("identifier"))
    except ValidationError as exc:
        raise DRFValidationError({"identifier": exc.messages}) from exc


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """Sets the CSRF cookie so the frontend can make its first POST, and tells it how sign-in is set up."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"oidc_enabled": settings.OIDC_ENABLED, "turnstile_site_key": settings.TURNSTILE_SITE_KEY})


@method_decorator(csrf_protect, name="dispatch")
class OTPRequestView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if not turnstile.verify(request):
            raise DRFValidationError({"detail": "The human check did not pass. Please try again."})
        kind, identifier = _identifier(request)
        # Limits are applied here (not as decorators) so the parsed JSON body is available.
        limited = is_ratelimited(
            request, group="otp-request-id", key=lambda g, r: identifier,
            rate=settings.OTP_REQUEST_RATE_PER_IDENTIFIER, method="POST", increment=True,
        ) or is_ratelimited(
            request, group="otp-request-ip", key="ip",
            rate=settings.OTP_REQUEST_RATE_PER_IP, method="POST", increment=True,
        )  # fmt: skip
        if limited:
            return Response({"detail": "Too many codes requested. Try again later."}, status=429)
        code = otp.issue_code(identifier, ip=client_ip(request))
        send_otp.delay(kind, identifier, code)
        body = {"detail": "If the address is valid, a sign-in code is on its way.", "channel": kind}
        if settings.OTP_DEBUG_ECHO and settings.DEBUG:
            body["debug_code"] = code
        return Response(body)


@method_decorator(csrf_protect, name="dispatch")
@method_decorator(ratelimit(key="ip", rate=lambda g, r: settings.OTP_VERIFY_RATE_PER_IP, method="POST"), name="post")
class OTPVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        if getattr(request, "limited", False):
            return Response({"detail": "Too many attempts. Try again later."}, status=429)
        kind, identifier = _identifier(request)
        with transaction.atomic():
            if not otp.check_code(identifier, request.data.get("code", "")):
                ok = False
            else:
                ok = True
                user, created = otp.get_or_create_user(kind, identifier, name=request.data.get("name") or "")
                if created:
                    audit.log("user.created", user, actor=user, after={"role": user.role, "via": f"{kind}_otp"})
        if not ok:
            raise DRFValidationError({"code": ["That code is wrong or has expired."]})
        if not user.is_active:
            raise PermissionDenied("This account is disabled.")
        login(request._request, user, backend="django.contrib.auth.backends.ModelBackend")
        if user.role in STAFF_ROLES:
            request.session.set_expiry(settings.STAFF_SESSION_AGE)
        audit.log("user.signed_in", user, actor=user)
        request._request.user = user
        return Response(MeSerializer(user, context={"request": request._request}).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user, context={"request": request}).data)

    def patch(self, request):
        serializer = MeSerializer(request.user, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class StaffOnly(IsAuthenticated):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.user.role in STAFF_ROLES


class TOTPSetupView(APIView):
    """Starts authenticator-app enrolment for a manager or admin."""

    permission_classes = [StaffOnly]

    def post(self, request):
        if any(True for _ in devices_for_user(request.user, confirmed=True)):
            raise DRFValidationError({"detail": "Two-step verification is already set up. Ask an admin to reset it."})
        TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
        device = TOTPDevice.objects.create(user=request.user, name="Authenticator app", confirmed=False)
        return Response({"otpauth_url": device.config_url})


class TOTPVerifyView(APIView):
    """Confirms enrolment (first code) or verifies a code for this session."""

    permission_classes = [StaffOnly]

    @method_decorator(ratelimit(key="user", rate="10/m", method="POST"))
    def post(self, request):
        if getattr(request, "limited", False):
            return Response({"detail": "Too many attempts. Try again later."}, status=429)
        code = str(request.data.get("code", "")).strip()
        device = TOTPDevice.objects.filter(user=request.user).order_by("-confirmed", "-id").first()
        if device is None:
            raise DRFValidationError({"detail": "Set up two-step verification first."})
        if not device.verify_token(code):
            raise DRFValidationError({"code": ["That code is not valid."]})
        if not device.confirmed:
            device.confirmed = True
            device.save(update_fields=["confirmed"])
            audit.log("user.mfa_enrolled", request.user, actor=request.user)
        otp_login(request._request, device)
        return Response(MeSerializer(request.user, context={"request": request._request}).data)


class UserViewSet(viewsets.ModelViewSet):
    """Super admin: manage users and roles."""

    serializer_class = AdminUserSerializer
    permission_classes = [IsAdmin]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = User.objects.all()
        if q := self.request.query_params.get("q"):
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        if role := self.request.query_params.get("role"):
            qs = qs.filter(role=role)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        user = serializer.save()
        audit.log("user.created", user, actor=self.request.user, after=serializer.data)

    @transaction.atomic
    def perform_update(self, serializer):
        before = AdminUserSerializer(serializer.instance).data
        if serializer.instance == self.request.user and (
            serializer.validated_data.get("role", "ADMIN") != "ADMIN"
            or serializer.validated_data.get("is_active") is False
        ):
            raise DRFValidationError({"detail": "You cannot remove your own admin access."})
        user = serializer.save()
        audit.log("user.updated", user, actor=self.request.user, before=before, after=serializer.data)

    def reset_mfa(self, request, pk=None):
        user = self.get_object()
        with transaction.atomic():
            TOTPDevice.objects.filter(user=user).delete()
            audit.log("user.mfa_reset", user, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
