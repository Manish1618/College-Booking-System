"""Changing the dates of a booking after it has been submitted (PRD F18: changes re-trigger approval).

Before payment, the request itself takes the new dates and goes back to the approver: nothing has been
confirmed yet, so nothing can be lost.

After payment, the booking is left exactly as it is and the new dates are recorded as a DateChange. The
change is approved, and paid for if the new stay costs more, before it replaces the old dates. If it is
refused, withdrawn or lapses, the guest still has the stay they paid for.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit import services as audit

from . import routing, services
from .exceptions import Conflict
from .models import DateChange, Status
from .state import amend, transition

UNPAID = (Status.PENDING, Status.APPROVED)
PAID = (Status.CONFIRMED, Status.ALLOTTED)
State = DateChange.State


def open_change(booking):
    """The booking's change that is still waiting for a decision or for payment, if there is one."""
    return next((change for change in booking.date_changes.all() if change.status in DateChange.OPEN), None)


def awaiting_payment(booking, now=None):
    """The approved change whose balance the guest can pay right now, if there is one."""
    change = open_change(booking)
    if change and change.status == State.AWAITING_PAYMENT and change.expires_at >= (now or timezone.now()):
        return change
    return None


def why_not(booking, *, by_staff, now=None):
    """Why the dates cannot be changed right now, or None if they can."""
    if booking.status not in UNPAID + PAID:
        return "The dates of this booking can no longer be changed."
    if open_change(booking):
        return "A change of dates is already open for this booking."
    if booking.status in PAID and not by_staff:
        # Without a cut-off, moving a stay and then cancelling it would be a way round the refund rules.
        arrival = timezone.make_aware(datetime.combine(booking.check_in, time(settings.CHECK_IN_HOUR)))
        if arrival - (now or timezone.now()) < timedelta(hours=settings.DATE_CHANGE_MIN_HOURS):
            return (
                f"Dates can be changed online until {settings.DATE_CHANGE_MIN_HOURS} hours before arrival. "
                "After that, please contact the guesthouse office."
            )
    return None


def _span(check_in, check_out):
    return f"{check_in:%d %b %Y} to {check_out:%d %b %Y}"


@transaction.atomic
def request(booking_id, actor, check_in, check_out, *, by_staff=False):
    """Asks for new dates. Returns the booking; its open change, if one was created, is on it."""
    booking = services.locked(booking_id)
    if booking.requester_id != actor.pk and not by_staff:
        raise PermissionDenied()
    if problem := why_not(booking, by_staff=by_staff):
        raise Conflict(problem)
    if (check_in, check_out) == (booking.check_in, booking.check_out):
        raise ValidationError({"check_in": ["Choose dates that differ from the current ones."]})
    services.validate_stay(check_in, check_out)
    # The booking's own nights do not count against it, so a stay can be moved by a day or extended.
    services.hold_capacity(booking.room_type_id, check_in, check_out, exclude=booking)
    price, amount = services.quote(booking.room_type, check_in, check_out)
    now = timezone.now()
    deadline = now + timedelta(hours=settings.BOOKING_HOLD_HOURS)
    moved = f"Dates changed from {_span(booking.check_in, booking.check_out)} to {_span(check_in, check_out)}."

    if booking.status in UNPAID:
        fields = {
            "check_in": check_in,
            "check_out": check_out,
            "price_per_night": price,
            "amount": amount,
            "hold_expires_at": deadline,
            "submitted_at": now,
        }
        if booking.status == Status.APPROVED:
            booking = transition(booking, Status.PENDING, actor=actor, comment=moved, notify=False, **fields)
        else:
            booking = amend(booking, "dates_changed", actor=actor, comment=moved, **fields)
        _notify(booking, "resubmitted", note=moved)
        return booking

    change = DateChange.objects.create(
        booking=booking,
        check_in=check_in,
        check_out=check_out,
        price_per_night=price,
        amount=amount,
        old_check_in=booking.check_in,
        old_check_out=booking.check_out,
        old_amount=booking.amount,
        expires_at=deadline,
        requested_by=actor,
    )
    audit.log(
        "booking.change_requested",
        booking,
        actor=actor,
        before={"check_in": booking.check_in, "check_out": booking.check_out, "amount": booking.amount},
        after={"check_in": check_in, "check_out": check_out, "amount": amount},
    )
    _notify(booking, "requested", change)
    return booking


@transaction.atomic
def decide(booking_id, approver, decision, comment=""):
    """The approver's answer to a change of dates on a paid booking."""
    booking = services.locked(booking_id)
    if not routing.can_decide(approver, booking):
        raise PermissionDenied("This request is not routed to you.")
    if decision not in ("APPROVED", "REJECTED"):
        raise ValidationError({"decision": ["Choose approve or reject."]})
    comment = (comment or "").strip()
    if decision == "REJECTED" and not comment:
        raise ValidationError({"comment": ["Add a comment so the guest knows why."]})
    change = DateChange.objects.select_for_update().filter(booking=booking, status=State.PENDING).first()
    if change is None or booking.status not in PAID:
        raise Conflict("No change of dates is waiting for a decision.")
    now = timezone.now()
    if change.expires_at < now:
        raise Conflict("The time to decide this change has run out.")
    change.decided_by, change.decided_at, change.comment = approver, now, comment

    if decision == "REJECTED":
        change.status = State.REJECTED
        change.save()
        audit.log("booking.change_rejected", booking, actor=approver, after={"comment": comment})
        _notify(booking, "rejected", change)
    elif change.balance > 0:
        # The new stay costs more. It replaces the old one when the difference is paid.
        change.status = State.AWAITING_PAYMENT
        change.expires_at = now + timedelta(hours=settings.PAYMENT_WINDOW_HOURS)
        change.save()
        audit.log("booking.change_approved", booking, actor=approver, after={"balance": change.balance})
        _notify(booking, "awaiting_payment", change)
    else:
        change.save()
        audit.log("booking.change_approved", booking, actor=approver, after={"refund": change.refund})
        apply(booking, change, actor=approver)
    return booking


def apply(booking, change, *, actor=None):
    """Moves a locked booking to the dates of an approved change. Must run inside transaction.atomic()."""
    from apps.payments import services as payments  # payments builds on bookings, so it is imported late

    moved = (
        f"Dates changed from {_span(booking.check_in, booking.check_out)} "
        f"to {_span(change.check_in, change.check_out)}."
    )
    fields = {
        "check_in": change.check_in,
        "check_out": change.check_out,
        "price_per_night": change.price_per_night,
        "amount": change.amount,
    }
    note = ""
    try:
        # The guest keeps the allotted room if it is free on the new dates. The database decides: it
        # refuses the update if another stay or a maintenance block is in the way.
        with transaction.atomic():
            amend(booking, "dates_changed", actor=actor, comment=moved, **fields)
    except IntegrityError as exc:
        if booking.status != Status.ALLOTTED or not any(n in str(exc) for n in ("no_overlap", "room_not_blocked")):
            raise
        booking.refresh_from_db()
        note = "The room allotted before is not free on the new dates, so another one will be allotted."
        transition(booking, Status.CONFIRMED, actor=actor, comment=f"{moved} {note}", notify=False, room=None, **fields)
    change.status = State.APPLIED
    change.save(update_fields=["status"])
    if change.refund > 0:
        payments.refund_surplus(
            booking, change.refund, "Dates changed: the new stay costs less.", requested_by=change.requested_by
        )
    _notify(booking, "applied", change, note=note)
    return booking


def on_balance_paid(booking, payment):
    """Called by the payment layer, with the booking locked, when the balance for a change arrives.

    Returns None once the change is applied, or the reason the money has to go back.
    """
    change = DateChange.objects.select_for_update().filter(pk=payment.date_change_id).first()
    if change is None or change.status != State.AWAITING_PAYMENT or booking.status not in PAID:
        return "Paid for a change of dates that was no longer open."
    if change.expires_at < timezone.now():
        # The window closed while the guest was paying. Honour it if the new dates are still free.
        try:
            services.hold_capacity(booking.room_type_id, change.check_in, change.check_out, exclude=booking)
        except Conflict:
            _close(booking, change, State.EXPIRED, "The balance was paid too late, and the dates had been taken.")
            return "Paid after the time to pay for the change had run out, and the dates had been taken."
    apply(booking, change)
    return None


@transaction.atomic
def withdraw(booking_id, actor, *, by_staff=False):
    booking = services.locked(booking_id)
    if booking.requester_id != actor.pk and not by_staff:
        raise PermissionDenied()
    change = DateChange.objects.select_for_update().filter(booking=booking, status__in=DateChange.OPEN).first()
    if change is None:
        raise Conflict("No change of dates is open for this booking.")
    _close(booking, change, State.WITHDRAWN, "", actor=actor)
    return booking


def close_open(booking, state, comment):
    """Ends whatever change is still open when the booking itself moves on. The booking must be locked."""
    for change in DateChange.objects.select_for_update().filter(booking=booking, status__in=DateChange.OPEN):
        _close(booking, change, state, comment)


def _close(booking, change, state, comment, *, actor=None):
    change.status = state
    change.comment = change.comment or comment
    change.save(update_fields=["status", "comment"])
    audit.log(f"booking.change_{state.lower()}", booking, actor=actor, after={"comment": comment})


def expire_stale(now=None):
    """Changes not decided, or not paid for, in time lapse. The booking keeps its original dates."""
    now = now or timezone.now()
    stale = DateChange.objects.filter(status__in=DateChange.OPEN, expires_at__lt=now)
    count = 0
    for pk, booking_id in list(stale.values_list("pk", "booking_id")):
        with transaction.atomic():
            booking = services.locked(booking_id)
            change = DateChange.objects.select_for_update().get(pk=pk)
            if change.status not in DateChange.OPEN or change.expires_at >= now:
                continue
            reason = (
                "It was not decided in time." if change.status == State.PENDING else "The balance was not paid in time."
            )
            _close(booking, change, State.EXPIRED, reason)
            _notify(booking, "expired", change, note=reason)
            count += 1
    return count


def _notify(booking, event, change=None, *, note=""):
    from apps.notifications.tasks import notify_date_change

    booking_id, change_id = str(booking.pk), str(change.pk) if change else None
    transaction.on_commit(lambda: notify_date_change.delay(booking_id, event, change_id, note))
