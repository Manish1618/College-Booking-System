from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from .sms import send_sms

STATUS_MESSAGES = {
    "PENDING": "Your request was received and is waiting for approval. The dates are held for {hold} hours.",
    "SENT_BACK": "The approver sent your request back with a comment. Please update it and submit again.",
    "APPROVED": "Your request was approved. Please pay within {pay} hours to confirm the booking.",
    "REJECTED": "Your request was not approved.",
    "CONFIRMED": "Payment received. Your booking is confirmed and a room will be allotted shortly.",
    "ALLOTTED": "Room {room} has been allotted for your stay.",
    "CHECKED_IN": "You are checked in. Have a pleasant stay.",
    "CHECKED_OUT": "You are checked out. Thank you for staying with us.",
    "CANCELLED": "Your booking was cancelled.",
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
        send_mail(
            f"{settings.SITE_NAME}: booking {booking.reference} – {status.replace('_', ' ').title()}",
            body,
            None,
            [user.email],
        )
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
