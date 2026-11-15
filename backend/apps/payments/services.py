"""Payment and refund rules.

A payment is marked paid in exactly one place, apply(), and only from an event that a gateway adapter has
verified: a signed webhook or a server-to-server lookup. Nothing the browser says can do it.

Locks are always taken in the same order: booking, then payment, then refund.
"""

import logging
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.bookings import changes
from apps.bookings import services as bookings
from apps.bookings.exceptions import Conflict
from apps.bookings.models import Status

from . import gateways
from .gateways import GatewayError, GatewayUnreachable
from .models import Payment, Refund, WebhookEvent

log = logging.getLogger(__name__)
ZERO = Decimal("0.00")
NO_ANSWER = "No answer from the gateway yet. This refund will be checked again automatically."
CENT = Decimal("0.01")


# --- Sums -------------------------------------------------------------------
def received(booking):
    """Payments for which money was taken, oldest first."""
    return [p for p in sorted(booking.payments.all(), key=lambda p: p.created_at) if p.received]


def net_paid(booking):
    """What the guesthouse currently holds for a booking: paid minus refunded."""
    return sum((p.amount - p.refunded_amount for p in received(booking)), ZERO)


def refundable(payment, *, exclude=None):
    """How much of a payment can still be promised back: not yet refunded and not already in a refund."""
    if not payment.received:
        return ZERO
    # Summed in Python so that a prefetched list of bookings costs no query per payment.
    promised = sum(
        (
            r.amount
            for r in payment.refunds.all()
            if r.status in Refund.OPEN and (exclude is None or r.pk != exclude.pk)
        ),
        ZERO,
    )
    return max(payment.amount - payment.refunded_amount - promised, ZERO)


# --- Paying -----------------------------------------------------------------
def payable(booking, now=None):
    return booking.status == Status.APPROVED and not (
        booking.hold_expires_at and booking.hold_expires_at < (now or timezone.now())
    )


def due(booking, now=None):
    """What the guest can pay right now: the booking's charge once approved, or the balance for an
    approved change of dates. Zero when nothing is waiting to be paid."""
    if payable(booking, now):
        return booking.amount
    change = changes.awaiting_payment(booking, now)
    return change.balance if change else ZERO


def start(booking_id, user, gateway_name):
    """Opens (or reopens) an order for what is due. Returns (payment, what the browser needs)."""
    if gateway_name not in gateways.enabled():
        raise ValidationError({"gateway": ["This payment option is not available."]})
    gateway = gateways.adapter(gateway_name)
    with transaction.atomic():
        booking = bookings.locked(booking_id)
        if booking.requester_id != user.pk:
            raise Conflict("Only the person who made the booking can pay for it.")
        change = changes.awaiting_payment(booking)
        if change is None:
            if booking.status != Status.APPROVED:
                raise Conflict("This booking is not waiting for payment.")
            if not payable(booking):
                raise Conflict("The payment window has closed.")
        amount = change.balance if change else booking.amount
        payment = None
        if gateway.reuse_orders:
            # Pressing Pay twice should not leave two open orders for the same booking.
            payment = booking.payments.filter(
                gateway=gateway_name, status=Payment.State.CREATED, amount=amount, date_change=change
            ).first()
        if payment is None:
            payment = Payment(booking=booking, gateway=gateway_name, amount=amount, date_change=change)
            try:
                # The booking stays locked for this call, which has a short timeout. It keeps a second
                # request, or the expiry job, from acting on the booking half-way through.
                payment.order_id = gateway.create_order(payment, booking)
            except GatewayError as exc:
                raise Conflict(str(exc)) from exc
            payment.save()
            audit.log(
                "payment.created",
                payment,
                actor=user,
                after={
                    "booking": str(booking.pk),
                    "gateway": gateway_name,
                    "amount": payment.amount,
                    "for": "change of dates" if change else "booking",
                },
            )
        return payment, gateway.checkout(payment, booking)


def handle_webhook(gateway_name, body, headers):
    """Verifies a webhook delivery and acts on what it reports. Raises BadSignature if it is not genuine."""
    events = gateways.adapter(gateway_name).parse_webhook(body, headers)
    return [apply(gateway_name, event) for event in events]


def apply(gateway_name, event):
    """Acts on one verified gateway event. Safe to call any number of times with the same event."""
    with transaction.atomic():
        if event.event_id:
            _, first_time = WebhookEvent.objects.get_or_create(
                gateway=gateway_name, event_id=event.event_id, defaults={"kind": event.kind}
            )
            if not first_time:
                return False
        if event.kind == gateways.PAID:
            _paid(gateway_name, event)
        elif event.kind == gateways.FAILED:
            _failed(gateway_name, event)
        elif event.kind in (gateways.REFUND_PROCESSED, gateways.REFUND_FAILED):
            _refund_event(gateway_name, event)
    return True


def _locked_payment(gateway_name, order_id):
    """The payment for a gateway order with its booking, both locked. (None, None) if we never opened it."""
    found = Payment.objects.filter(gateway=gateway_name, order_id=order_id).values_list("pk", "booking_id").first()
    if not found or not order_id:
        log.warning("Ignored a %s event for an order this system did not open.", gateway_name)
        return None, None
    booking = bookings.locked(found[1])
    return Payment.objects.select_for_update().get(pk=found[0]), booking


def _paid(gateway_name, event):
    payment, booking = _locked_payment(gateway_name, event.order_id)
    if payment is None or payment.received:
        return
    payment.gateway_payment_id = event.payment_id[:64]
    if event.amount != payment.amount:
        # Never confirm a booking on the wrong amount. Staff see this payment and settle it by hand.
        payment.status = Payment.State.FAILED
        payment.failure_reason = f"The gateway reported Rs {event.amount}, not the Rs {payment.amount} asked for."
        payment.save(update_fields=["status", "failure_reason", "gateway_payment_id"])
        audit.log("payment.amount_mismatch", payment, after={"expected": payment.amount, "reported": event.amount})
        return
    payment.status = Payment.State.PAID
    payment.paid_at = timezone.now()
    payment.failure_reason = ""
    payment.save(update_fields=["status", "paid_at", "failure_reason", "gateway_payment_id"])
    audit.log(
        "payment.paid",
        payment,
        after={"booking": str(booking.pk), "gateway": gateway_name, "amount": payment.amount},
    )
    if payment.date_change_id:
        # The balance for a change of dates: it moves the stay, it does not confirm anything.
        problem = changes.on_balance_paid(booking, payment)
    else:
        problem = _cannot_confirm(booking)
        if problem is None:
            bookings.confirm_paid(booking)
    if problem:
        propose_refund(payment, payment.amount, problem)


def _cannot_confirm(booking):
    """Why a payment that just arrived cannot confirm its booking, or None if it can."""
    if booking.status != Status.APPROVED:
        return f"Paid when the booking was already {booking.get_status_display().lower()}."
    if not payable(booking):
        # The payment window closed while the guest was paying. Honour it if the room is still there.
        try:
            bookings.hold_capacity(booking.room_type_id, booking.check_in, booking.check_out, exclude=booking)
        except Conflict:
            return "Paid after the payment window closed, and the room had been taken."
    return None


def _failed(gateway_name, event):
    payment, _ = _locked_payment(gateway_name, event.order_id)
    if payment is None or payment.status != Payment.State.CREATED:
        return
    payment.failure_reason = (event.reason or "The payment did not go through.")[:255]
    if not gateways.adapter(gateway_name).retries_within_order:
        payment.status = Payment.State.FAILED
    # Otherwise the order stays open: the guest may pay it on the next try, and if that success is
    # never reported to us, the status lookups still have to find it.
    payment.save(update_fields=["status", "failure_reason"])
    audit.log("payment.failed", payment, after={"reason": payment.failure_reason, "order": payment.status})


def check(payment):
    """Asks the gateway about an open order and acts on the answer. Returns True if it changed anything."""
    try:
        event = gateways.adapter(payment.gateway).payment_status(payment)
    except GatewayError:
        return False
    return bool(event) and apply(payment.gateway, event)


# --- Refunds ----------------------------------------------------------------
def cancellation_percent(booking, *, now=None):
    """The share of the payment that goes back when the guest cancels now (configurable rules)."""
    now = now or timezone.now()
    arrival = timezone.make_aware(datetime.combine(booking.check_in, time(settings.CHECK_IN_HOUR)))
    hours = (arrival - now).total_seconds() / 3600
    if hours >= settings.REFUND_FULL_HOURS:
        return 100
    if hours >= settings.REFUND_PARTIAL_HOURS:
        return settings.REFUND_PARTIAL_PERCENT
    return 0


def cancellation_refund(booking, *, percent=None, now=None):
    """(percent, amount) that cancelling would return. Amount is 0 when nothing was paid."""
    percent = cancellation_percent(booking, now=now) if percent is None else percent
    amount = sum((_share(p, percent) for p in received(booking)), ZERO)
    return percent, amount


def _share(payment, percent):
    return min((payment.amount * percent / 100).quantize(CENT), refundable(payment))


def propose_refund(payment, amount, reason, *, requested_by=None):
    """Records that money is owed back. A manager then issues it. Returns None if nothing is owed."""
    amount = min(Decimal(amount).quantize(CENT), refundable(payment))
    if amount <= 0:
        return None
    refund = Refund.objects.create(payment=payment, amount=amount, reason=reason[:255], requested_by=requested_by)
    audit.log(
        "refund.due",
        refund,
        actor=requested_by,
        after={"booking": str(payment.booking_id), "amount": amount, "reason": refund.reason},
    )
    _notify(refund, "due")
    return refund


def refund_surplus(booking, amount, reason, *, requested_by=None):
    """Records that part of what was paid for a booking is owed back, newest payment first.

    Called with the booking locked, when a change of dates makes the stay cost less.
    """
    remaining = Decimal(amount).quantize(CENT)
    for payment in reversed(received(booking)):
        if remaining <= 0:
            break
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        refund = propose_refund(payment, min(remaining, refundable(payment)), reason, requested_by=requested_by)
        if refund:
            remaining -= refund.amount


def on_cancelled(booking, actor, *, full=False):
    """Called with the booking locked, right after it is cancelled."""
    percent = 100 if full else cancellation_percent(booking)
    reason = (
        "Cancelled by the guesthouse: full refund."
        if full
        else f"Cancelled by the guest: {percent}% refund under the cancellation rules."
    )
    for payment in received(booking):
        propose_refund(payment, _share(payment, percent), reason, requested_by=actor)


def on_no_show(booking):
    for payment in received(booking):
        propose_refund(
            payment,
            _share(payment, settings.REFUND_NO_SHOW_PERCENT),
            f"No-show: {settings.REFUND_NO_SHOW_PERCENT}% refund under the cancellation rules.",
        )


@transaction.atomic
def request_refund(booking_id, manager, amount, reason):
    """A refund a manager decides to give outside the cancellation rules."""
    booking = bookings.locked(booking_id)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError({"reason": ["Say why this refund is being given."]})
    payment = next((p for p in received(booking) if refundable(p) >= amount), None)
    if amount <= 0 or payment is None:
        raise ValidationError({"amount": ["Enter an amount up to what can still be refunded."]})
    return propose_refund(Payment.objects.select_for_update().get(pk=payment.pk), amount, reason, requested_by=manager)


def _locked_refund(refund_id):
    found = Refund.objects.filter(pk=refund_id).values_list("payment_id", "payment__booking_id").first()
    if not found:
        raise Conflict("This refund no longer exists.")
    bookings.locked(found[1])
    payment = Payment.objects.select_for_update().get(pk=found[0])
    refund = Refund.objects.select_for_update().get(pk=refund_id)
    refund.payment = payment
    return refund


def issue(refund_id, manager, *, amount=None, manual=False, note=""):
    """Sends a due (or failed) refund to the gateway, or records one that was paid back another way."""
    note = (note or "").strip()
    with transaction.atomic():
        refund = _locked_refund(refund_id)
        if refund.status not in (Refund.State.DUE, Refund.State.FAILED):
            raise Conflict("This refund has already been issued.")
        amount = refund.amount if amount is None else Decimal(amount).quantize(CENT)
        if amount <= 0 or amount > refundable(refund.payment, exclude=refund):
            raise ValidationError({"amount": ["Enter an amount up to what can still be refunded."]})
        if manual and not note:
            raise ValidationError({"note": ["Say how the money was returned."]})
        refund.amount, refund.manual, refund.note, refund.issued_by = amount, manual, note[:255], manager
        refund.status, refund.failure_reason, refund.issued_at = Refund.State.PROCESSING, "", timezone.now()
        # A fresh attempt: a new reference, and no gateway id until this attempt is given one.
        refund.attempt += 1
        refund.gateway_refund_id = ""
        refund.save()
        audit.log("refund.issued", refund, actor=manager, after={"amount": amount, "manual": manual, "note": note})
    # The gateway call happens with nothing locked. The refund is already PROCESSING, so it cannot be
    # issued twice, and a webhook that arrives before the call returns finds it and settles it.
    attempt = refund.attempt
    if manual:
        return _settle(refund.pk, gateways.PROCESSED, attempt=attempt)
    gateway = gateways.adapter(refund.payment.gateway)
    try:
        gateway_refund_id, state = gateway.refund(refund.payment, refund)
    except GatewayUnreachable:
        # Unknown outcome: the money may have moved. Leave it PROCESSING for reconcile() to find out.
        return _settle(refund.pk, gateways.PENDING, attempt=attempt, reason=NO_ANSWER)
    except GatewayError as exc:
        return _settle(refund.pk, gateways.REJECTED, attempt=attempt, reason=str(exc))
    return _settle(refund.pk, state, attempt=attempt, gateway_refund_id=gateway_refund_id)


@transaction.atomic
def withdraw(refund_id, manager, note):
    """Drops a refund that has not gone to the gateway, for example one proposed by mistake."""
    note = (note or "").strip()
    if not note:
        raise ValidationError({"note": ["Say why this refund is being withdrawn."]})
    refund = _locked_refund(refund_id)
    if refund.status not in (Refund.State.DUE, Refund.State.FAILED):
        raise Conflict("This refund has already been issued.")
    audit.log("refund.withdrawn", refund, actor=manager, before={"amount": refund.amount}, after={"note": note})
    refund.delete()


@transaction.atomic
def _settle(refund_id, state, *, attempt=None, gateway_refund_id="", reason=""):
    """Records what the gateway said about a refund that is PROCESSING. Later repeats change nothing.

    attempt says which sending of the refund the answer is about, when the caller knows.
    """
    refund = _locked_refund(refund_id)
    fields = []
    if attempt not in (None, refund.attempt):
        return refund  # about an earlier attempt, which was already settled as failed
    if gateway_refund_id and not refund.gateway_refund_id:
        refund.gateway_refund_id = gateway_refund_id[:64]
        fields.append("gateway_refund_id")
    if refund.status == Refund.State.PROCESSING:
        if state == gateways.PROCESSED:
            payment = refund.payment
            payment.refunded_amount += refund.amount
            if payment.refunded_amount >= payment.amount:
                payment.status = Payment.State.REFUNDED
            payment.save(update_fields=["refunded_amount", "status"])
            refund.status, refund.processed_at, refund.failure_reason = Refund.State.PROCESSED, timezone.now(), ""
            fields += ["status", "processed_at", "failure_reason"]
            audit.log("refund.processed", refund, actor=refund.issued_by, after={"amount": refund.amount})
            _notify(refund, "processed")
        elif state == gateways.REJECTED:
            refund.status, refund.failure_reason = Refund.State.FAILED, (reason or "The refund failed.")[:255]
            fields += ["status", "failure_reason"]
            audit.log("refund.failed", refund, after={"reason": refund.failure_reason})
        elif reason and refund.failure_reason != reason[:255]:
            refund.failure_reason = reason[:255]
            fields.append("failure_reason")
    if fields:
        refund.save(update_fields=fields)
    return refund


def _refund_event(gateway_name, event):
    refunds = Refund.objects.filter(payment__gateway=gateway_name)
    # Our own reference names the refund and which attempt at it the gateway is talking about.
    refund_id, attempt = Refund.split_reference(event.refund_ref)
    refund = refunds.filter(pk=refund_id).first() if refund_id else None
    if refund is None and event.refund_id:
        # No reference came back, so go by the gateway's id, which is only ever the current attempt's.
        refund, attempt = refunds.filter(gateway_refund_id=event.refund_id).first(), None
    if refund is None:
        # Refunds made in the gateway's own dashboard are not known here. Staff record those by hand.
        log.warning("Ignored a %s refund event for a refund this system did not issue.", gateway_name)
        return
    state = gateways.PROCESSED if event.kind == gateways.REFUND_PROCESSED else gateways.REJECTED
    _settle(refund.pk, state, attempt=attempt, gateway_refund_id=event.refund_id, reason=event.reason)


def _notify(refund, what):
    from .tasks import notify_refund

    refund_id = str(refund.pk)
    transaction.on_commit(lambda: notify_refund.delay(refund_id, what))


# --- Scheduled housekeeping -------------------------------------------------
def reconcile(now=None):
    """Asks the gateways about orders and refunds that are still open, in case a webhook never arrived."""
    now = now or timezone.now()
    changed = 0
    open_orders = Payment.objects.filter(
        status=Payment.State.CREATED,
        created_at__gte=now - timedelta(days=settings.PAYMENT_RECONCILE_DAYS),
        created_at__lte=now - timedelta(minutes=2),
    ).exclude(gateway=Payment.Gateway.DEV)
    for payment in open_orders:
        changed += check(payment)
    waiting = Refund.objects.filter(
        status=Refund.State.PROCESSING, manual=False, issued_at__lte=now - timedelta(minutes=5)
    ).select_related("payment")
    for refund in waiting:
        attempt = refund.attempt
        try:
            state = gateways.adapter(refund.payment.gateway).refund_status(refund.payment, refund)
        except GatewayError:
            continue
        if state == gateways.UNKNOWN:
            if refund.issued_at <= now - timedelta(minutes=30):
                # Half an hour on, the gateway still has no trace of the request. Nothing moved, so it
                # is safe to send again.
                _settle(
                    refund.pk,
                    gateways.REJECTED,
                    attempt=attempt,
                    reason="The gateway has no record of this refund. Issue it again.",
                )
                changed += 1
        elif state != gateways.PENDING:
            _settle(refund.pk, state, attempt=attempt, gateway_refund_id=refund.gateway_refund_id)
            changed += 1
    return changed


def verify_recent(now=None):
    """Nightly: every payment marked paid in the last day and a half is checked against the gateway again.

    Returns the payments the gateway does not agree with. Each is logged for staff to look into.
    """
    now = now or timezone.now()
    # Payments with a refund are left out: the gateway no longer reports those as plainly paid.
    recent = (
        Payment.objects.filter(status=Payment.State.PAID, refunded_amount=0, paid_at__gte=now - timedelta(hours=36))
        .exclude(gateway=Payment.Gateway.DEV)
        .exclude(refunds__status=Refund.State.PROCESSING)
    )
    mismatched = []
    for payment in recent:
        try:
            event = gateways.adapter(payment.gateway).payment_status(payment)
        except GatewayError:
            continue
        if event is None or event.kind != gateways.PAID or event.amount != payment.amount:
            mismatched.append(payment)
            with transaction.atomic():
                audit.log(
                    "payment.reconcile_mismatch",
                    payment,
                    after={"recorded": payment.amount, "gateway": getattr(event, "amount", None)},
                )
    return mismatched
