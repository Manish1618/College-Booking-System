from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from . import services
from .models import Refund

REFUND_MESSAGES = {
    "due": "A refund of Rs {amount} is due to you. The guesthouse office will issue it shortly.",
    "processed": (
        "Rs {amount} has been refunded. Money sent back through the payment gateway usually reaches the "
        "original payment method within 5 to 7 working days."
    ),
}


@shared_task
def reconcile():
    return services.reconcile()


@shared_task
def verify_recent():
    """Nightly check of recent payments against the gateways. Managers are told about any that disagree."""
    mismatched = services.verify_recent()
    if mismatched:
        staff = get_user_model().objects.filter(role__in=["MANAGER", "ADMIN"], is_active=True).exclude(email=None)
        lines = [f"{p.order_id}: recorded Rs {p.amount} for booking {p.booking.reference}" for p in mismatched]
        send_mail(
            f"{settings.SITE_NAME}: payments to check",
            "The nightly check found payments that the gateway does not report the same way:\n\n" + "\n".join(lines),
            None,
            [user.email for user in staff if user.email],
        )
    return len(mismatched)


@shared_task
def notify_refund(refund_id, what):
    refund = Refund.objects.select_related("payment__booking__requester").filter(pk=refund_id).first()
    if refund is None or what not in REFUND_MESSAGES:
        return
    booking = refund.payment.booking
    user = booking.requester
    if not user.email:
        return
    body = (
        f"Booking {booking.reference}\n\n{REFUND_MESSAGES[what].format(amount=refund.amount)}\n\n"
        f"Reason: {refund.reason}\n\n{settings.SITE_URL}/bookings/{booking.pk}\n"
    )
    title = "refund due" if what == "due" else "refund issued"
    send_mail(f"{settings.SITE_NAME}: booking {booking.reference} – {title}", body, None, [user.email])
