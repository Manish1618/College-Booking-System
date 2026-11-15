"""Booking rules. Views stay thin; everything that changes a booking lives here, inside a transaction."""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Max, Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit import services as audit
from apps.rooms.models import Room, RoomBlock, RoomType

from . import routing
from .exceptions import Conflict
from .models import Approval, Booking, Category, DateChange, Document, RegisterEntry, Status
from .state import HOLDING, transition


# --- Availability -----------------------------------------------------------
def _live_holds(now=None):
    """Bookings that currently take a room of their type. A lapsed hold stops counting at once."""
    now = now or timezone.now()
    return Q(status__in=HOLDING) & ~Q(
        status__in=[Status.PENDING, Status.SENT_BACK, Status.APPROVED], hold_expires_at__lt=now
    )


def _nights(start, end, check_in, check_out):
    """The nights of [start, end) that fall inside the stay [check_in, check_out)."""
    night, last = max(start, check_in), min(end, check_out)
    while night < last:
        yield night
        night += timedelta(days=1)


def available_count(room_type, check_in, check_out, *, exclude=None, without_block=None):
    """Free rooms of a type across a stay: on its busiest night, the rooms in service minus those taken.

    A room is taken by a live booking, and also by the new dates of a change that is still open, so the
    dates a guest has asked to move to cannot be sold to someone else while the change is decided.
    """
    now = timezone.now()
    total = room_type.rooms.filter(is_active=True).count()
    span = {"check_in__lt": check_out, "check_out__gt": check_in}
    stays = Booking.objects.filter(_live_holds(now), room_type=room_type, **span)
    moves = DateChange.objects.filter(
        status__in=DateChange.OPEN, expires_at__gte=now, booking__room_type=room_type, **span
    )
    if exclude is not None:
        stays, moves = stays.exclude(pk=exclude.pk), moves.exclude(booking=exclude)
    held = defaultdict(set)  # booking -> nights it holds; its current and its new dates count once
    for pk, start, end in [*stays.values_list("pk", "check_in", "check_out")] + [
        *moves.values_list("booking_id", "check_in", "check_out")
    ]:
        held[pk].update(_nights(start, end, check_in, check_out))
    per_night = Counter(night for nights in held.values() for night in nights)
    blocks = RoomBlock.objects.filter(
        room__room_type=room_type, room__is_active=True, starts_on__lt=check_out, ends_on__gt=check_in
    )
    if without_block is not None:
        blocks = blocks.exclude(pk=without_block.pk)  # a block being changed does not count against itself
    for start, end in blocks.values_list("starts_on", "ends_on"):
        per_night.update(_nights(start, end, check_in, check_out))  # a room out of service is not for sale
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


def hold_capacity(room_type_id, check_in, check_out, *, exclude):
    """Confirms a room of the type is free for the stay, holding a lock on the room type.

    The lock lasts until the surrounding transaction ends, so two requests cannot both take the last room.
    """
    room_type = RoomType.objects.select_for_update().get(pk=room_type_id)
    if not room_type.is_active:
        raise Conflict("This room type is no longer offered.")
    if available_count(room_type, check_in, check_out, exclude=exclude) < 1:
        raise Conflict("No rooms of this type are free for those dates any more.")


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
    hold_capacity(booking.room_type_id, booking.check_in, booking.check_out, exclude=booking)
    now = timezone.now()
    return transition(
        booking,
        Status.PENDING,
        actor=actor,
        submitted_at=now,
        hold_expires_at=now + timedelta(hours=settings.BOOKING_HOLD_HOURS),
    )


@transaction.atomic
def cancel(booking_id, actor, *, by_staff=False, full_refund=False, reason=""):
    """Cancels and releases the room. If money was paid, the refund the rules allow becomes due.

    full_refund is for the desk only: the guesthouse, not the guest, is the one cancelling.
    """
    from apps.payments import services as payments  # payments builds on bookings, so it is imported late

    from . import changes

    booking = locked(booking_id)
    if booking.requester_id != actor.pk and not by_staff:
        raise PermissionDenied()
    booking = transition(
        booking, Status.CANCELLED, actor=actor, comment=(reason or "").strip(), room=None, hold_expires_at=None
    )
    changes.close_open(booking, DateChange.State.WITHDRAWN, "The booking was cancelled.")
    payments.on_cancelled(booking, actor, full=by_staff and full_refund)
    return booking


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
    if booking.hold_expires_at and booking.hold_expires_at < timezone.now():
        # A lapsed hold no longer reserves the dates, so someone else may hold them by now.
        raise Conflict("The hold on this request has run out, so it can no longer be decided.")
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
    blocked = RoomBlock.objects.filter(starts_on__lt=booking.check_out, ends_on__gt=booking.check_in)
    return (
        Room.objects.filter(room_type=booking.room_type, is_active=True)
        .exclude(pk__in=taken.values("room"))
        .exclude(pk__in=blocked.values("room"))
    )


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
        if "room_not_blocked" in str(exc):
            raise Conflict(f"Room {room.number} is out of service on those dates.") from exc
        if "no_overlap" in str(exc):
            raise Conflict(f"Room {room.number} is already allotted for those dates.") from exc
        raise


# --- Desk: arrivals and departures ------------------------------------------
REGISTER_LOCK = 0x47485247  # advisory lock key ("GHRG"): one writer of register serial numbers at a time


@transaction.atomic
def check_in(booking_id, manager, guest_ids):
    """Checks in the guests whose ID the desk has compared with the uploaded copy, and enters them
    in the guest register. guest_ids are the guests who arrived; at least one is needed.

    Guests on one booking need not arrive together: calling this again adds the later arrivals.
    """
    from apps.payments import services as payments

    booking = locked(booking_id)
    if booking.status not in (Status.ALLOTTED, Status.CHECKED_IN):
        raise Conflict("Only a booking with an allotted room can be checked in.")
    first_arrival = booking.status == Status.ALLOTTED
    today = timezone.localdate()
    if today < booking.check_in:
        raise Conflict(f"This stay starts on {booking.check_in:%d %b %Y}. It cannot be checked in earlier.")
    if today >= booking.check_out:
        raise Conflict("This stay has already ended.")
    wanted = set(guest_ids)
    guests = [guest for guest in booking.guests.select_related("id_document") if guest.pk in wanted]
    if not guests or len(guests) != len(wanted):
        raise ValidationError({"guests": ["Tick each arriving guest once their ID has been checked."]})
    if any(guest.id_document is None for guest in guests):
        raise ValidationError({"guests": ["A guest has no uploaded ID copy to check against."]})
    if RegisterEntry.objects.filter(booking=booking, guest__in=guests).exists():
        raise Conflict("A guest you ticked is already checked in.")
    if first_arrival:
        from . import changes

        booking = transition(booking, Status.CHECKED_IN, actor=manager)
        changes.close_open(booking, DateChange.State.EXPIRED, "The stay began before the change was settled.")

    now = timezone.now()
    with connection.cursor() as cursor:
        # Serial numbers must have no gaps and no repeats, so entries are numbered one check-in at a time.
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [REGISTER_LOCK])
    serial = RegisterEntry.objects.aggregate(last=Max("serial_number"))["last"] or 0
    paid = payments.net_paid(booking)
    for index, guest in enumerate(guests):
        guest.id_verified = True
        guest.save(update_fields=["id_verified"])
        Document.objects.filter(pk=guest.id_document_id).update(verified_by=manager)
        RegisterEntry.objects.create(
            serial_number=serial + index + 1,
            booking=booking,
            guest=guest,
            room=booking.room,
            arrival_at=now,
            purpose=booking.purpose,
            # The booking's payment is written once, against its first guest, so the column adds up.
            amount_paid=paid if first_arrival and index == 0 else 0,
            entered_by=manager,
        )
    audit.log(
        "register.entered",
        booking,
        actor=manager,
        after={"serials": [serial + 1, serial + len(guests)], "ids_verified": [str(g.pk) for g in guests]},
    )
    return booking


@transaction.atomic
def check_out(booking_id, manager):
    booking = locked(booking_id)
    booking = transition(booking, Status.CHECKED_OUT, actor=manager)
    booking.register_entries.filter(departure_at__isnull=True).update(departure_at=timezone.now())
    return booking


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
    from apps.payments import services as payments

    now = timezone.localtime(now or timezone.now())
    count = 0
    candidates = Booking.objects.filter(status__in=[Status.CONFIRMED, Status.ALLOTTED], check_in__lt=now.date())
    # A guest who has asked to move the stay is not a no-show while that request is still open. If it is
    # refused or lapses, the next run of this job judges the booking on its original dates.
    candidates = candidates.exclude(date_changes__status__in=DateChange.OPEN)
    for pk, check_in in list(candidates.values_list("pk", "check_in")):
        deadline = timezone.make_aware(datetime.combine(check_in + timedelta(days=1), time(settings.NO_SHOW_HOUR)))
        if now < deadline:
            continue
        with transaction.atomic():
            booking = locked(pk)
            if booking.check_in != check_in or booking.date_changes.filter(status__in=DateChange.OPEN).exists():
                continue  # the dates moved, or a move was asked for, since the query above
            if booking.status in (Status.CONFIRMED, Status.ALLOTTED):
                transition(booking, Status.NO_SHOW, room=None)
                payments.on_no_show(booking)
                count += 1
    return count
