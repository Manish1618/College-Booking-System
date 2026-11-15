from rest_framework import serializers

from apps.bookings.state import TRANSITIONS

from . import services
from .models import Payment, Refund


class PaymentSerializer(serializers.ModelSerializer):
    gateway_label = serializers.CharField(source="get_gateway_display", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id", "gateway", "gateway_label", "order_id", "gateway_payment_id", "amount", "status",
            "refunded_amount", "failure_reason", "paid_at", "created_at",
        ]  # fmt: skip


class RefundSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    booking = serializers.UUIDField(source="payment.booking_id", read_only=True)
    reference = serializers.CharField(source="payment.booking.reference", read_only=True)
    gateway_label = serializers.CharField(source="payment.get_gateway_display", read_only=True)
    requester_name = serializers.CharField(source="payment.booking.requester.__str__", read_only=True)
    limit = serializers.SerializerMethodField()

    class Meta:
        model = Refund
        fields = [
            "id", "booking", "reference", "requester_name", "gateway_label", "amount", "limit", "status",
            "status_label", "reason", "manual", "note", "failure_reason", "created_at", "processed_at",
        ]  # fmt: skip

    def get_limit(self, refund):
        """The most this refund could be changed to before it is issued."""
        if refund.status not in (Refund.State.DUE, Refund.State.FAILED):
            return None
        return str(services.refundable(refund.payment, exclude=refund))


def payment_summary(booking, *, staff):
    """Money in and out for a booking, as shown to its owner and to the desk."""
    payments = sorted(booking.payments.all(), key=lambda p: p.created_at)
    took_money = [p for p in payments if p.received]
    refunds = [r for p in took_money for r in p.refunds.all()]
    refund_on_cancel = None
    if took_money and "CANCELLED" in TRANSITIONS[booking.status]:
        percent, amount = services.cancellation_refund(booking)
        refund_on_cancel = {
            "percent": percent,
            "amount": str(amount),
            # What the desk can choose instead when the guesthouse is the one cancelling.
            "full": str(services.cancellation_refund(booking, percent=100)[1]),
        }
    return {
        "paid": str(sum((p.amount for p in took_money), services.ZERO)),
        "refunded": str(sum((p.refunded_amount for p in took_money), services.ZERO)),
        # Guests see payments that went through; the desk also sees attempts that failed.
        "payments": PaymentSerializer(payments if staff else took_money, many=True).data,
        "refunds": RefundSerializer(sorted(refunds, key=lambda r: r.created_at), many=True).data,
        "refundable": str(sum((services.refundable(p) for p in took_money), services.ZERO)),
        "refund_on_cancel": refund_on_cancel,
        # What can be paid right now: the booking's charge, or the balance for an approved change of dates.
        "due": str(services.due(booking)),
        # True while an order is open with a real gateway, so the pay screen knows to keep waiting.
        "pending": any(p.status == Payment.State.CREATED and p.gateway != Payment.Gateway.DEV for p in payments),
        "receipt": bool(took_money),
    }
