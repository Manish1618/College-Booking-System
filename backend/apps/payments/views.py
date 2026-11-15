"""Payment entry points.

Phase 3 adds real Razorpay and MobiKwik orders plus signed-webhook verification. Until then only the
"dev" gateway works, and only where PAYMENT_GATEWAYS lists it, so the rest of the flow can be exercised.
"""

import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit import services as audit
from apps.bookings import services
from apps.bookings.exceptions import Conflict
from apps.bookings.models import Status
from apps.bookings.serializers import BookingSerializer
from apps.bookings.views import visible_bookings

from .models import Payment


class GatewaysView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        labels = dict(Payment.Gateway.choices)
        return Response([{"id": g, "label": labels[g]} for g in settings.PAYMENT_GATEWAYS if g in labels])


class PayView(APIView):
    def post(self, request, pk):
        owned = visible_bookings(request).filter(pk=pk, requester=request.user).exists()
        if not owned:
            raise PermissionDenied()
        gateway = request.data.get("gateway")
        if gateway not in settings.PAYMENT_GATEWAYS or gateway not in Payment.Gateway.values:
            raise ValidationError({"gateway": ["This payment option is not available."]})
        if gateway != Payment.Gateway.DEV:
            raise ValidationError({"gateway": ["Online payment through this gateway is not connected yet."]})
        with transaction.atomic():
            booking = services.locked(pk)
            if booking.status != Status.APPROVED:
                raise Conflict("This booking is not waiting for payment.")
            if booking.hold_expires_at and booking.hold_expires_at < timezone.now():
                raise Conflict("The payment window has closed.")
            payment = Payment.objects.create(
                booking=booking,
                gateway=gateway,
                order_id=f"dev_{uuid.uuid4().hex}",
                gateway_payment_id=f"devpay_{uuid.uuid4().hex[:16]}",
                amount=booking.amount,
                status=Payment.State.PAID,
                paid_at=timezone.now(),
            )
            audit.log("payment.paid", payment, actor=request.user, after={"gateway": gateway, "amount": booking.amount})
            services.confirm_paid(booking, actor=request.user)
        booking = visible_bookings(request).get(pk=pk)
        return Response(BookingSerializer(booking, context={"request": request}).data)
