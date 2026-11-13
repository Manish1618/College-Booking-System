import uuid

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
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
