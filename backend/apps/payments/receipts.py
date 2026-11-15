"""Receipt PDFs: one per booking, listing every payment and refund."""

from django.conf import settings
from django.utils import timezone

from config.pdf import render_pdf

from . import services
from .models import Refund


def has_receipt(booking):
    return bool(services.received(booking))


def receipt_pdf(booking):
    payments = services.received(booking)
    refunds = Refund.objects.filter(payment__in=payments, status=Refund.State.PROCESSED).order_by("processed_at")
    user = booking.requester
    return render_pdf(
        "payments/receipt.html",
        {
            "site_name": settings.SITE_NAME,
            "booking": booking,
            "booked_by": user.name or user.email or user.phone,
            "guests": [guest.name for guest in booking.guests.all()],
            "payments": payments,
            "refunds": refunds,
            "net_paid": services.net_paid(booking),
            "now": timezone.localtime(),
        },
    )
