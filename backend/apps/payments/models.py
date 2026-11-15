import uuid

from django.conf import settings
from django.db import models

from apps.bookings.models import Booking


class Payment(models.Model):
    class Gateway(models.TextChoices):
        RAZORPAY = "razorpay", "Razorpay"
        MOBIKWIK = "mobikwik", "MobiKwik"
        DEV = "dev", "Test payment (development only)"

    class State(models.TextChoices):
        CREATED = "CREATED", "Created"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="payments")
    gateway = models.CharField(max_length=10, choices=Gateway.choices)
    order_id = models.CharField(max_length=64, unique=True)
    gateway_payment_id = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=State.choices, default=State.CREATED)
    refunded_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    failure_reason = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_id

    @property
    def received(self):
        """Money was taken for this payment, whether or not some of it has gone back since."""
        return self.status in (self.State.PAID, self.State.REFUNDED)


class Refund(models.Model):
    """Money going back to the guest. Proposed by the cancellation rules or a manager; issued by a manager."""

    class State(models.TextChoices):
        DUE = "DUE", "Due"
        PROCESSING = "PROCESSING", "With the gateway"
        PROCESSED = "PROCESSED", "Refunded"
        FAILED = "FAILED", "Failed"

    # States in which the amount is still spoken for, so it cannot be promised twice.
    OPEN = [State.DUE, State.PROCESSING, State.FAILED]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=10, choices=State.choices, default=State.DUE)
    reason = models.CharField(max_length=255)
    # True when the money was returned outside the gateway (bank transfer, cash) and only recorded here.
    manual = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    gateway_refund_id = models.CharField(max_length=64, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    issued_at = models.DateTimeField(null=True, blank=True)  # when a manager last sent it
    # How many times it has been sent to the gateway. Each attempt has its own reference, so an answer
    # about an earlier attempt can never be taken for the current one.
    attempt = models.PositiveSmallIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    @property
    def reference(self):
        """What the gateway is given to identify the current attempt: the refund id plus the attempt number."""
        return f"{self.pk.hex}a{self.attempt}"

    @staticmethod
    def split_reference(reference):
        """(refund id, attempt) from a reference a gateway echoed back, or (None, None) if it is not ours."""
        text = str(reference)
        try:
            if text[32:33] != "a":
                raise ValueError
            return uuid.UUID(hex=text[:32]), int(text[33:])
        except ValueError:
            return None, None


class WebhookEvent(models.Model):
    """One row per gateway event already acted on, so a repeated delivery changes nothing."""

    id = models.BigAutoField(primary_key=True)
    gateway = models.CharField(max_length=10)
    event_id = models.CharField(max_length=128)
    kind = models.CharField(max_length=40)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["gateway", "event_id"], name="one_row_per_gateway_event")]
