"""The booking state machine. Every status change goes through transition(), which also logs it."""

from django.db import transaction

from apps.audit import services as audit
from apps.notifications.tasks import notify_booking_status

from .exceptions import Conflict
from .models import Status as S

TRANSITIONS = {
    S.DRAFT: {S.PENDING, S.CANCELLED},
    S.PENDING: {S.APPROVED, S.REJECTED, S.SENT_BACK, S.CANCELLED, S.EXPIRED},
    S.SENT_BACK: {S.PENDING, S.CANCELLED, S.EXPIRED},
    # APPROVED -> PENDING: the guest changed the dates before paying, so the request is decided again.
    S.APPROVED: {S.CONFIRMED, S.PENDING, S.CANCELLED, S.EXPIRED},
    S.CONFIRMED: {S.ALLOTTED, S.CANCELLED, S.NO_SHOW},
    # ALLOTTED -> ALLOTTED is a room change. ALLOTTED -> CONFIRMED gives the room up when the dates
    # change and that room is not free on the new ones.
    S.ALLOTTED: {S.ALLOTTED, S.CONFIRMED, S.CHECKED_IN, S.CANCELLED, S.NO_SHOW},
    S.CHECKED_IN: {S.CHECKED_OUT},
    S.REJECTED: set(),
    S.CHECKED_OUT: set(),
    S.CANCELLED: set(),
    S.EXPIRED: set(),
    S.NO_SHOW: set(),
}

# States that keep a room of the type out of the availability count.
HOLDING = [S.PENDING, S.SENT_BACK, S.APPROVED, S.CONFIRMED, S.ALLOTTED, S.CHECKED_IN]


def can_transition(booking, to):
    return to in TRANSITIONS[booking.status]


def transition(booking, to, *, actor=None, comment="", notify=True, **changes):
    """Moves a locked booking to a new status. Must run inside transaction.atomic().

    notify=False is for callers that send their own, more specific message.
    """
    if not can_transition(booking, to):
        raise Conflict(
            f"A booking that is {booking.get_status_display().lower()} cannot move to {S(to).label.lower()}."
        )
    before = {"status": booking.status, **{k: getattr(booking, k) for k in changes}}
    booking.status = to
    for field, value in changes.items():
        setattr(booking, field, value)
    booking.save(update_fields=["status", "updated_at", *changes])
    after = {"status": to, **changes}
    if comment:
        after["comment"] = comment
    audit.log(f"booking.{to.lower()}", booking, actor=actor, before=_plain(before), after=_plain(after))
    if notify:
        booking_id = str(booking.pk)
        transaction.on_commit(lambda: notify_booking_status.delay(booking_id, str(to), comment))
    return booking


def amend(booking, action, *, actor=None, comment="", **changes):
    """Changes fields of a locked booking without changing its status, and logs it as booking.<action>."""
    before = {k: getattr(booking, k) for k in changes}
    for field, value in changes.items():
        setattr(booking, field, value)
    booking.save(update_fields=["updated_at", *changes])
    after = dict(changes)
    if comment:
        after["comment"] = comment
    audit.log(f"booking.{action}", booking, actor=actor, before=_plain(before), after=_plain(after))
    return booking


def _plain(data):
    return {k: (str(v.pk) if hasattr(v, "pk") else v) for k, v in data.items()}
