"""Payment entry points: starting a payment, gateway webhooks, refunds and receipts."""

import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django_ratelimit.core import is_ratelimited
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager, is_manager
from apps.audit import services as audit
from apps.bookings.serializers import BookingSerializer
from apps.bookings.views import visible_bookings
from config.pdf import pdf_response

from . import gateways, receipts, services
from .models import Payment, Refund
from .serializers import PaymentSerializer, RefundSerializer


def _booking_json(request, pk):
    booking = visible_bookings(request).get(pk=pk)
    return BookingSerializer(booking, context={"request": request}).data


def _own_booking(request, pk):
    if not visible_bookings(request).filter(pk=pk, requester=request.user).exists():
        raise PermissionDenied()


def _amount(value, *, required=True):
    if value in (None, "") and not required:
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():  # "NaN" and "Infinity" parse as decimals
            raise InvalidOperation
        return amount.quantize(services.CENT)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError({"amount": ["Enter an amount in rupees."]}) from exc


class GatewaysView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        labels = dict(Payment.Gateway.choices)
        return Response([{"id": name, "label": labels[name]} for name in gateways.enabled()])


class PayView(APIView):
    """Opens an order with the chosen gateway and returns what the browser needs to pay it.

    The booking is not confirmed here or by anything the browser sends afterwards. That happens only when
    the gateway's signed webhook, or a server-to-server lookup, reports the money as received.
    """

    def post(self, request, pk):
        _own_booking(request, pk)
        payment, checkout = services.start(pk, request.user, request.data.get("gateway"))
        return Response({"payment": PaymentSerializer(payment).data, "checkout": checkout})


class PaymentStatusView(APIView):
    """Asks the gateway about this booking's open orders. For when a webhook is slow to arrive."""

    def post(self, request, pk):
        if not visible_bookings(request).filter(pk=pk).exists():
            raise Http404
        if not (is_manager(request) or visible_bookings(request).filter(pk=pk, requester=request.user).exists()):
            raise PermissionDenied()
        if is_ratelimited(request, group="payment-status", key="user", rate="20/m", method="POST", increment=True):
            return Response({"detail": "Too many checks. Please wait a moment."}, status=429)
        open_orders = Payment.objects.filter(booking_id=pk, status=Payment.State.CREATED).exclude(
            gateway=Payment.Gateway.DEV
        )
        for payment in open_orders[:3]:
            services.check(payment)
        return Response(_booking_json(request, pk))


class WebhookView(APIView):
    """Where gateways report payments and refunds. Open to the internet, so the signature is everything."""

    permission_classes = [AllowAny]
    authentication_classes = []  # no session, so no CSRF check: the signature authenticates the caller

    def post(self, request, gateway):
        if not _accepts_webhooks(gateway):
            raise Http404
        try:
            services.handle_webhook(gateway, request.body, request.headers)
        except gateways.BadSignature:
            return HttpResponse("Bad signature", status=400, content_type="text/plain")
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError, AttributeError, InvalidOperation):
            return HttpResponse("Unreadable", status=400, content_type="text/plain")
        except gateways.GatewayError:
            # A lookup the event depends on failed. A 5xx makes the gateway deliver it again later.
            return HttpResponse("Try again", status=503, content_type="text/plain")
        return HttpResponse("SUCCESS", content_type="text/plain")


def _accepts_webhooks(gateway):
    """A gateway's webhook exists only while its secret is set. An empty secret would verify anything."""
    if gateway == "dev":
        return "dev" in gateways.enabled()
    if gateway == "razorpay":
        return bool(settings.RAZORPAY_WEBHOOK_SECRET)
    if gateway == "mobikwik":
        return bool(settings.MOBIKWIK_SECRET_KEY)
    return False


class DevCompleteView(APIView):
    """The simulated gateway's "pay" button. It sends a signed webhook through the real handler."""

    def post(self, request):
        if "dev" not in gateways.enabled():
            raise Http404
        payment = Payment.objects.filter(
            gateway=Payment.Gateway.DEV, order_id=str(request.data.get("order_id", "")), booking__requester=request.user
        ).first()
        if payment is None:
            raise Http404
        outcome = "paid" if request.data.get("outcome", "paid") == "paid" else "failed"
        gateway = gateways.adapter("dev")
        services.handle_webhook("dev", *gateway.webhook_for(payment, outcome))
        return Response(_booking_json(request, payment.booking_id))


class MobikwikReturnView(APIView):
    """Where MobiKwik sends the guest's browser back. What the browser carries is not believed:
    the order is looked up with the gateway, and the guest is sent on to their booking."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        order_id = str(request.POST.get("orderId", ""))
        payment = Payment.objects.filter(gateway=Payment.Gateway.MOBIKWIK, order_id=order_id).first()
        if payment is None or not order_id:
            return HttpResponseRedirect(f"{settings.SITE_URL}/bookings")
        if payment.status == Payment.State.CREATED and settings.MOBIKWIK_SECRET_KEY:
            services.check(payment)
        return HttpResponseRedirect(f"{settings.SITE_URL}/bookings/{payment.booking_id}?returned=1")

    get = post


class ReceiptView(APIView):
    def get(self, request, pk):
        booking = visible_bookings(request).filter(pk=pk).first()
        # Receipts are for the person who paid and for the desk, not for approvers.
        if booking is None or not (booking.requester_id == request.user.pk or is_manager(request)):
            raise Http404
        if not receipts.has_receipt(booking):
            raise Http404
        audit.log("receipt.downloaded", booking, actor=request.user)
        return pdf_response(receipts.receipt_pdf(booking), f"receipt-{booking.reference}.pdf")


class BookingRefundView(APIView):
    """Manager: propose a refund outside the cancellation rules. It is then issued like any other."""

    permission_classes = [IsManager]

    def post(self, request, pk):
        services.request_refund(pk, request.user, _amount(request.data.get("amount")), request.data.get("reason"))
        return Response(_booking_json(request, pk), status=201)


class RefundViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Manager: refunds that are owed, and the buttons that send them."""

    permission_classes = [IsManager]
    serializer_class = RefundSerializer

    def get_queryset(self):
        refunds = Refund.objects.select_related("payment__booking__requester").prefetch_related("payment__refunds")
        if statuses := self.request.query_params.get("status"):
            refunds = refunds.filter(status__in=statuses.split(","))
        # A work queue: the refund that has waited longest comes first. The key makes the pages stable.
        return refunds.order_by("created_at", "pk")

    def _read(self, refund):
        return Response(RefundSerializer(self.get_queryset().get(pk=refund.pk)).data)

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        refund = services.issue(
            self.get_object().pk,
            request.user,
            amount=_amount(request.data.get("amount"), required=False),
            manual=bool(request.data.get("manual")),
            note=request.data.get("note", ""),
        )
        return self._read(refund)

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        services.withdraw(self.get_object().pk, request.user, request.data.get("note"))
        return Response(status=204)
