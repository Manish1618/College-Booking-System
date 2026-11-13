"""Booking rules. Views stay thin; everything that changes a booking lives here, inside a transaction."""

from collections import Counter
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.rooms.models import Room, RoomType

from . import routing
from .exceptions import Conflict
from .models import Approval, Booking, Category, Document, Status
from .state import HOLDING, transition


# --- Availability -----------------------------------------------------------
def _live_holds(now=None):
    """Bookings that currently take a room of their type. A lapsed hold stops counting at once."""
    now = now or timezone.now()
    return Q(status__in=HOLDING) & ~Q(
        status__in=[Status.PENDING, Status.SENT_BACK, Status.APPROVED], hold_expires_at__lt=now
    )


def available_count(room_type, check_in, check_out, *, exclude=None):
    """Free rooms of a type across a stay: total active rooms minus the busiest night's bookings."""
    total = room_type.rooms.filter(is_active=True).count()
    overlapping = Booking.objects.filter(
        _live_holds(), room_type=room_type, check_in__lt=check_out, check_out__gt=check_in
    )
    if exclude is not None:
        overlapping = overlapping.exclude(pk=exclude.pk)
    per_night = Counter()
    for start, end in overlapping.values_list("check_in", "check_out"):
        night = max(start, check_in)
        while night < min(end, check_out):
            per_night[night] += 1
            night += timedelta(days=1)
    return max(total - max(per_night.values(), default=0), 0)


def validate_stay(check_in, check_out):
    today = timezone.localdate()
    errors = {}
    if check_in < today:
        errors["check_in"] = ["Check-in cannot be in the past."]
    elif check_in > today + timedelta(days=settings.BOOKING_MAX_ADVANCE_DAYS):
        errors["check_in"] = [f"Bookings open {settings.BOOKING_MAX_ADVANCE_DAYS} days ahead."]
    if check_out <= check_in:
        errors["check_out"] = ["Check-out must be after check-in."]
    elif (check_out - check_in).days > settings.BOOKING_MAX_NIGHTS:
        errors["check_out"] = [f"A stay can be at most {settings.BOOKING_MAX_NIGHTS} nights."]
    if errors:
        raise ValidationError(errors)


def quote(room_type, check_in, check_out):
    """(price per night, total). The tariff in force on the check-in date applies to the whole stay."""
    price = room_type.price_on(check_in)
    if price is None:
        raise ValidationError({"room_type": ["No price is set for this room type on those dates."]})
    return price, price * (check_out - check_in).days


def locked(booking_id):
    return Booking.objects.select_for_update().get(pk=booking_id)


# --- Requester actions ------------------------------------------------------
@transaction.atomic
def submit(booking_id, actor):
    booking = locked(booking_id)
    if booking.status not in (Status.DRAFT, Status.SENT_BACK):
        raise Conflict("This request has already been submitted.")
    validate_stay(booking.check_in, booking.check_out)
    errors = []
    guests = list(booking.guests.all())
    if not guests:
        errors.append("Add at least one guest.")
    if len(guests) > booking.room_type.capacity:
        errors.append(f"This room type takes at most {booking.room_type.capacity} guests.")
    if any(g.id_document_id is None for g in guests):
        errors.append("Upload a government ID for every guest.")
    if booking.category == Category.OFFICIAL:
        if not booking.documents.filter(type=Document.Type.RECOMMENDATION_LETTER).exists():
            errors.append("Upload the recommendation letter from a college authority.")
    elif not hasattr(booking, "student_link"):
        errors.append("Enter the student's details.")
    if errors:
        raise ValidationError({"detail": errors})
    # Lock the room type so two requests cannot both take the last room.
    room_type = RoomType.objects.select_for_update().get(pk=booking.room_type_id)
    if not room_type.is_active:
        raise Conflict("This room type is no longer offered.")
    if available_count(room_type, booking.check_in, booking.check_out, exclude=booking) < 1:
        raise Conflict("No rooms of this type are free for those dates any more.")
    now = timezone.now()
    return transition(
        booking,
        Status.PENDING,
        actor=actor,
        submitted_at=now,
        hold_expires_at=now + timedelta(hours=settings.BOOKING_HOLD_HOURS),
    )


@transaction.atomic
def cancel(booking_id, actor, *, by_staff=False):
    booking = locked(booking_id)
    if booking.requester_id != actor.pk and not by_staff:
        raise PermissionDenied()
    return transition(booking, Status.CANCELLED, actor=actor, room=None, hold_expires_at=None)


# --- Approver ---------------------------------------------------------------
@transaction.atomic
def decide(booking_id, approver, decision, comment=""):
    booking = locked(booking_id)
    if not routing.can_decide(approver, booking):
        raise PermissionDenied("This request is not routed to you.")
    if decision not in Approval.Decision.values:
        raise ValidationError({"decision": ["Choose approve, reject or send back."]})
    comment = (comment or "").strip()
    if decision != Approval.Decision.APPROVED and not comment:
        raise ValidationError({"comment": ["Add a comment so the guest knows why."]})
    if booking.status != Status.PENDING:
        raise Conflict("This request is not waiting for a decision.")
    Approval.objects.create(booking=booking, approver=approver, decision=decision, comment=comment)
    changes = {}
    if decision == Approval.Decision.APPROVED:
        changes["hold_expires_at"] = timezone.now() + timedelta(hours=settings.PAYMENT_WINDOW_HOURS)
    elif decision == Approval.Decision.REJECTED:
        changes["hold_expires_at"] = None
    return transition(booking, Status(decision), actor=approver, comment=comment, **changes)


# --- Payment ----------------------------------------------------------------
def confirm_paid(booking, actor=None):
    """Called by the payment layer, with the booking row locked, once a payment is verified."""
    return transition(booking, Status.CONFIRMED, actor=actor, hold_expires_at=None)


# --- Manager ----------------------------------------------------------------
def free_rooms(booking):
    """Active rooms of the booked type with no live stay overlapping these dates."""
    taken = Booking.objects.filter(
        status__in=[Status.ALLOTTED, Status.CHECKED_IN],
        room__isnull=False,
        check_in__lt=booking.check_out,
        check_out__gt=booking.check_in,
    ).exclude(pk=booking.pk)
    return Room.objects.filter(room_type=booking.room_type, is_active=True).exclude(pk__in=taken.values("room"))


@transaction.atomic
def allot(booking_id, manager, room_id):
    booking = locked(booking_id)
    room = Room.objects.filter(pk=room_id, is_active=True).first()
    if room is None or room.room_type_id != booking.room_type_id:
        raise ValidationError({"room": ["Choose an active room of the booked type."]})
    try:
        # The savepoint lets the exclusion constraint reject an overlap without breaking the outer transaction.
        with transaction.atomic():
            return transition(booking, Status.ALLOTTED, actor=manager, room=room)
    except IntegrityError as exc:
        if "no_overlap" in str(exc):
            raise Conflict(f"Room {room.number} is already allotted for those dates.") from exc
        raise


# --- Scheduled housekeeping -------------------------------------------------
def expire_stale(now=None):
    """Requests not approved within the hold, or not paid in time after approval, expire and free their dates."""
    now = now or timezone.now()
    stale = Booking.objects.filter(
        status__in=[Status.PENDING, Status.SENT_BACK, Status.APPROVED], hold_expires_at__lt=now
    ).values_list("pk", flat=True)
    count = 0
    for pk in list(stale):
        with transaction.atomic():
            booking = locked(pk)
            if booking.status in (Status.PENDING, Status.SENT_BACK, Status.APPROVED) and booking.hold_expires_at < now:
                transition(booking, Status.EXPIRED, hold_expires_at=None)
                count += 1
    return count


def mark_no_shows(now=None):
    """A booking not checked in by noon on the day after check-in becomes a no-show."""
    now = timezone.localtime(now or timezone.now())
    count = 0
    candidates = Booking.objects.filter(status__in=[Status.CONFIRMED, Status.ALLOTTED], check_in__lt=now.date())
    for pk, check_in in list(candidates.values_list("pk", "check_in")):
        deadline = timezone.make_aware(datetime.combine(check_in + timedelta(days=1), time(settings.NO_SHOW_HOUR)))
        if now < deadline:
            continue
        with transaction.atomic():
            booking = locked(pk)
            if booking.status in (Status.CONFIRMED, Status.ALLOTTED):
                transition(booking, Status.NO_SHOW, room=None)
                count += 1
    return count
