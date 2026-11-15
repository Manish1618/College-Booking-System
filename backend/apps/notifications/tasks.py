import logging

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMessage, send_mail

from .sms import send_sms

logger = logging.getLogger(__name__)

STATUS_MESSAGES = {
    "PENDING": "Your request was received and is waiting for approval. The dates are held for {hold} hours.",
    "SENT_BACK": "The approver sent your request back with a comment. Please update it and submit again.",
    "APPROVED": "Your request was approved. Please pay within {pay} hours to confirm the booking.",
    "REJECTED": "Your request was not approved.",
    "CONFIRMED": "Payment received. Your booking is confirmed and a room will be allotted shortly.",
    "ALLOTTED": "Room {room} has been allotted for your stay.",
    "CHECKED_IN": "You are checked in. Have a pleasant stay.",
    "CHECKED_OUT": "You are checked out. Thank you for staying with us.",
    "CANCELLED": "Your booking was cancelled. If a refund is due, a separate email says how much.",
    "EXPIRED": "Your booking request expired and the dates were released.",
    "NO_SHOW": "Your booking was marked as a no-show.",
}
SMS_STATUSES = {"CONFIRMED", "ALLOTTED"}


@shared_task
def send_otp(kind, identifier, code):
    message = (
        f"Your {settings.SITE_NAME} sign-in code is {code}. It expires in {settings.OTP_CODE_TTL_MINUTES} minutes."
    )
    if kind == "email":
        send_mail(f"{settings.SITE_NAME} sign-in code", message, None, [identifier])
    else:
        send_sms(identifier, message)


def _attach_receipt(message, booking):
    """The receipt PDF goes out with the confirmation. A failure to build it must not stop the email."""
    from apps.payments import receipts

    try:
        if receipts.has_receipt(booking):
            message.attach(f"receipt-{booking.reference}.pdf", receipts.receipt_pdf(booking), "application/pdf")
            message.body += "\nYour receipt is attached.\n"
    except Exception:
        logger.exception("Could not attach the receipt for booking %s", booking.reference)


@shared_task
def notify_booking_status(booking_id, status, comment=""):
    """Email on every state change; SMS as well for confirmations."""
    from apps.bookings.models import Booking
    from apps.bookings.routing import approvers_for

    booking = Booking.objects.select_related("requester", "room", "room_type").get(pk=booking_id)
    text = STATUS_MESSAGES.get(status, f"Your booking is now {status}.").format(
        hold=settings.BOOKING_HOLD_HOURS,
        pay=settings.PAYMENT_WINDOW_HOURS,
        room=booking.room.number if booking.room else "",
    )
    body = (
        f"Booking {booking.reference}\n{booking.room_type.name}, {booking.check_in:%d %b %Y} to "
        f"{booking.check_out:%d %b %Y}\n\n{text}\n"
    )
    if comment:
        body += f"\nComment: {comment}\n"
    body += f"\n{settings.SITE_URL}/bookings/{booking.pk}\n"
    user = booking.requester
    if user.email:
        message = EmailMessage(
            f"{settings.SITE_NAME}: booking {booking.reference} – {status.replace('_', ' ').title()}",
            body,
            None,
            [user.email],
        )
        if status == "CONFIRMED":
            _attach_receipt(message, booking)
        message.send()
    if user.phone and status in SMS_STATUSES:
        send_sms(user.phone, f"{settings.SITE_NAME} booking {booking.reference}: {text}")
    if status == "PENDING":
        emails = [a.email for a in approvers_for(booking) if a.email]
        if emails:
            send_mail(
                f"{settings.SITE_NAME}: booking {booking.reference} needs your decision",
                f"A {booking.get_category_display().lower()} request is waiting for you.\n\n"
                f"{settings.SITE_URL}/bookings/{booking.pk}\n",
                None,
                emails,
            )


CHANGE_MESSAGES = {
    "requested": (
        "You asked to move this booking to {new}. The request is waiting for approval. "
        "Until it is approved, your booking stays as it is: {old}."
    ),
    "resubmitted": "{note} The request is waiting for approval again, and the new dates are held for {hold} hours.",
    "awaiting_payment": (
        "Your change of dates to {new} was approved. The new stay costs Rs {balance} more. Pay that within "
        "{pay} hours to move the booking. Until then your booking stays as it is: {old}."
    ),
    "applied": "Your booking has moved to {new}. {note}",
    "rejected": "Your request to move this booking to {new} was not approved. Your booking stays as it was: {old}.",
    "expired": "Your request to move this booking to {new} has lapsed. {note} Your booking stays as it was: {old}.",
}


@shared_task
def notify_date_change(booking_id, event, change_id=None, note=""):
    """Email about a change of dates: asked for, approved, applied, refused or lapsed."""
    from apps.bookings.models import Booking, DateChange
    from apps.bookings.routing import approvers_for

    booking = Booking.objects.select_related("requester", "room_type").get(pk=booking_id)
    change = DateChange.objects.filter(pk=change_id).first() if change_id else None
    span = lambda start, end: f"{start:%d %b %Y} to {end:%d %b %Y}"  # noqa: E731
    text = (
        CHANGE_MESSAGES[event]
        .format(
            new=span(change.check_in, change.check_out) if change else "",
            old=span(change.old_check_in, change.old_check_out) if change else "",
            balance=change.balance if change else "",
            hold=settings.BOOKING_HOLD_HOURS,
            pay=settings.PAYMENT_WINDOW_HOURS,
            note=note,
        )
        .strip()
    )
    if event == "applied" and change and change.refund > 0:
        text += f" The new stay costs Rs {change.refund} less; a separate email says when that is refunded."
    body = f"Booking {booking.reference}\n{booking.room_type.name}\n\n{text}\n"
    if change and change.comment and event in ("rejected", "awaiting_payment"):
        body += f"\nComment: {change.comment}\n"
    body += f"\n{settings.SITE_URL}/bookings/{booking.pk}\n"
    if booking.requester.email:
        send_mail(
            f"{settings.SITE_NAME}: booking {booking.reference} – change of dates",
            body,
            None,
            [booking.requester.email],
        )
    if event in ("requested", "resubmitted"):
        emails = [a.email for a in approvers_for(booking) if a.email]
        if emails:
            send_mail(
                f"{settings.SITE_NAME}: booking {booking.reference} needs your decision",
                f"A change of dates on a {booking.get_category_display().lower()} request is waiting for you.\n\n"
                f"{settings.SITE_URL}/bookings/{booking.pk}\n",
                None,
                emails,
            )
