from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings import changes, services
from apps.bookings.models import Booking, DateChange, Status
from apps.bookings.tasks import expire_stale_bookings
from apps.payments.models import Payment, Refund
from apps.rooms.models import RoomBlock

from .conftest import client_for, make_booking, pay

pytestmark = pytest.mark.django_db


def paid(user, room_type, stay, status=Status.CONFIRMED, room=None):
    """A booking that has been paid for in full, optionally with a room."""
    booking = make_booking(user, room_type, stay, status, room=room)
    Payment.objects.create(
        booking=booking, gateway="dev", order_id=f"dev_{booking.reference}", gateway_payment_id="devpay_1",
        amount=booking.amount, status="PAID", paid_at=timezone.now(),
    )  # fmt: skip
    return booking


def move(client, booking, check_in, check_out):
    data = {"check_in": check_in.isoformat(), "check_out": check_out.isoformat()}
    return client.post(f"/api/bookings/{booking.pk}/date-change", data, format="json")


def decide(client, booking, decision="APPROVED", comment=""):
    data = {"decision": decision, "comment": comment}
    return client.post(f"/api/bookings/{booking.pk}/date-change/decide", data, format="json")


def availability(client, room_type, stay):
    data = client.get("/api/availability", {"check_in": stay[0], "check_out": stay[1]}).data
    return next(r["available"] for r in data["results"] if r["room_type"] == str(room_type.pk))


def shifted(stay, days, nights=None):
    start = stay[0] + timedelta(days=days)
    return start, start + timedelta(days=nights if nights is not None else (stay[1] - stay[0]).days)


# --- Before payment: the request itself changes and is decided again -----------
def test_pending_request_takes_new_dates_and_stays_pending(requester, approver, room_type, stay):
    booking = make_booking(
        requester, room_type, stay, Status.PENDING, hold_expires_at=timezone.now() + timedelta(hours=3)
    )
    client = client_for(requester)
    assert client.get(f"/api/bookings/{booking.pk}").data["actions"]["change_dates"] is True
    new = shifted(stay, 5, nights=3)
    mail.outbox.clear()
    data = move(client, booking, *new).data
    assert (data["status"], data["check_in"], data["nights"], data["amount"]) == (
        "PENDING", new[0].isoformat(), 3, "3000.00",
    )  # fmt: skip
    assert data["date_change"] is None  # nothing was confirmed, so there is nothing to keep on the side
    booking.refresh_from_db()
    assert booking.hold_expires_at > timezone.now() + timedelta(hours=47)
    entry = AuditLog.objects.get(action="booking.dates_changed")
    assert entry.before["check_in"] == stay[0].isoformat() and entry.after["check_in"] == new[0].isoformat()
    assert {tuple(m.to) for m in mail.outbox} == {(requester.email,), (approver.email,)}
    assert "waiting for approval again" in mail.outbox[0].body
    assert (
        client_for(approver)
        .post(f"/api/bookings/{booking.pk}/decide", {"decision": "APPROVED"}, format="json")
        .data["status"]
        == "APPROVED"
    )


def test_approved_but_unpaid_request_goes_back_for_approval(requester, approver, room_type, stay):
    booking = make_booking(
        requester, room_type, stay, Status.APPROVED, hold_expires_at=timezone.now() + timedelta(hours=20)
    )
    client = client_for(requester)
    data = move(client, booking, *shifted(stay, 1)).data
    assert data["status"] == "PENDING" and data["actions"]["pay"] is False
    assert data["payment"]["due"] == "0.00"
    assert client.post(f"/api/bookings/{booking.pk}/pay", {"gateway": "dev"}, format="json").status_code == 409
    entry = AuditLog.objects.get(action="booking.pending")
    assert "Dates changed from" in entry.after["comment"]
    assert (
        client_for(approver)
        .post(f"/api/bookings/{booking.pk}/decide", {"decision": "APPROVED"}, format="json")
        .data["status"]
        == "APPROVED"
    )
    pay(client, booking.pk)
    assert Booking.objects.get(pk=booking.pk).status == Status.CONFIRMED


def test_order_opened_before_the_dates_changed_cannot_confirm_the_new_stay(requester, approver, room_type, stay):
    """The gateway still accepts the old order, at the old price. The money goes back; it does not confirm."""
    booking = make_booking(
        requester, room_type, stay, Status.APPROVED, hold_expires_at=timezone.now() + timedelta(hours=20)
    )
    client = client_for(requester)
    old_order = client.post(f"/api/bookings/{booking.pk}/pay", {"gateway": "dev"}, format="json").data["payment"]
    assert old_order["amount"] == "2000.00"
    assert move(client, booking, *shifted(stay, 0, nights=3)).data["amount"] == "3000.00"
    client_for(approver).post(f"/api/bookings/{booking.pk}/decide", {"decision": "APPROVED"}, format="json")

    done = client.post("/api/payments/dev/complete", {"order_id": old_order["order_id"], "outcome": "paid"})
    assert done.status_code == 200, done.data
    data = client.get(f"/api/bookings/{booking.pk}").data
    assert data["status"] == "APPROVED" and data["actions"]["pay"] is True and data["payment"]["due"] == "3000.00"
    refund = Refund.objects.get()
    assert (refund.amount, refund.status) == (Decimal("2000.00"), "DUE")
    assert "earlier order" in refund.reason and "3000" in refund.reason

    # Paying the current price confirms it, and the earlier payment is still owed back in full.
    pay(client, booking.pk)
    data = client.get(f"/api/bookings/{booking.pk}").data
    assert (data["status"], data["payment"]["paid"]) == ("CONFIRMED", "5000.00")
    assert data["payment"]["refund_on_cancel"]["amount"] == "3000.00"
    assert Refund.objects.count() == 1


# --- After payment: the booking is kept until the change is approved -----------
def test_paid_booking_is_untouched_until_its_change_is_approved(requester, other_requester, approver, room_type, stay):
    booking = paid(requester, room_type, stay)
    client, new = client_for(requester), shifted(stay, 7)
    assert availability(client, room_type, new) == 2
    mail.outbox.clear()
    data = move(client, booking, *new).data
    assert (data["status"], data["check_in"]) == ("CONFIRMED", stay[0].isoformat())
    change = data["date_change"]
    assert (change["status"], change["open"], change["check_in"]) == ("PENDING", True, new[0].isoformat())
    assert (change["balance"], change["refund"], change["old_check_in"]) == ("0.00", "0.00", stay[0].isoformat())
    assert data["actions"] == {**data["actions"], "change_dates": False, "withdraw_change": True, "pay": False}
    assert "stays as it is" in mail.outbox[0].body and mail.outbox[1].to == [approver.email]

    # Both the stay the guest has and the stay they asked for are held.
    assert availability(client, room_type, stay) == 1 and availability(client, room_type, new) == 1
    # The approver finds it in the queue, sees what is asked, and approves.
    desk = client_for(approver)
    assert [b["id"] for b in desk.get("/api/bookings?scope=approvals").data["results"]] == [str(booking.pk)]
    seen = desk.get(f"/api/bookings/{booking.pk}").data
    assert seen["actions"]["decide_change"] is True and seen["actions"]["decide"] is False
    mail.outbox.clear()
    data = decide(desk, booking).data
    assert (data["status"], data["check_in"], data["check_out"]) == ("CONFIRMED", *[d.isoformat() for d in new])
    assert (data["date_change"]["status"], data["date_change"]["open"]) == ("APPLIED", False)
    assert "has moved to" in mail.outbox[0].body
    # The old nights are free again and nothing is owed either way.
    assert availability(client, room_type, stay) == 2 and availability(client, room_type, new) == 1
    assert Refund.objects.count() == 0 and Payment.objects.count() == 1
    assert desk.get("/api/bookings?scope=approvals").data["results"] == []
    assert AuditLog.objects.filter(action="booking.dates_changed").count() == 1


def test_longer_stay_moves_when_the_balance_is_paid(requester, approver, room_type, stay):
    booking = paid(requester, room_type, stay)
    client, new = client_for(requester), shifted(stay, 0, nights=3)
    assert move(client, booking, *new).data["date_change"]["balance"] == "1000.00"
    mail.outbox.clear()
    data = decide(client_for(approver), booking, comment="Fine").data
    assert (data["check_out"], data["amount"]) == (stay[1].isoformat(), "2000.00")  # not moved yet
    assert data["date_change"]["status"] == "AWAITING_PAYMENT"
    assert "Rs 1000.00 more" in mail.outbox[0].body and "Comment: Fine" in mail.outbox[0].body

    data = client.get(f"/api/bookings/{booking.pk}").data
    assert data["actions"]["pay"] is True and data["payment"]["due"] == "1000.00"
    mail.outbox.clear()
    pay(client, booking.pk)
    data = client.get(f"/api/bookings/{booking.pk}").data
    assert (data["check_out"], data["nights"], data["amount"]) == (new[1].isoformat(), 3, "3000.00")
    assert (data["payment"]["paid"], data["payment"]["due"], data["actions"]["pay"]) == ("3000.00", "0.00", False)
    assert data["date_change"]["status"] == "APPLIED" and data["status"] == "CONFIRMED"
    balance = Payment.objects.get(date_change__isnull=False)
    assert (balance.amount, balance.status) == (Decimal("1000.00"), "PAID")
    assert AuditLog.objects.get(action="payment.created").after["for"] == "change of dates"
    assert any("has moved to" in m.body for m in mail.outbox)


def test_shorter_stay_moves_at_once_and_the_difference_is_refunded(requester, approver, manager, room_type, stay):
    booking = paid(requester, room_type, stay)
    client, new = client_for(requester), shifted(stay, 0, nights=1)
    assert move(client, booking, *new).data["date_change"]["refund"] == "1000.00"
    data = decide(client_for(approver), booking).data
    assert (data["check_out"], data["amount"]) == (new[1].isoformat(), "1000.00")
    refund = Refund.objects.get()
    assert (refund.amount, refund.status, refund.reason) == (
        Decimal("1000.00"), "DUE", "Dates changed: the new stay costs less.",
    )  # fmt: skip
    # The manager issues it like any other refund.
    assert client_for(manager).post(f"/api/refunds/{refund.pk}/issue").data["status"] == "PROCESSED"
    assert client.get(f"/api/bookings/{booking.pk}").data["payment"]["refunded"] == "1000.00"


@pytest.mark.parametrize("surplus_sent", [False, True])
def test_cancelling_after_a_cheaper_change_refunds_a_share_of_the_new_price(
    requester, approver, manager, room_type, stay, settings, surplus_sent
):
    """Half back on cancelling means half of what the stay costs now, not half of everything once paid."""
    settings.REFUND_FULL_HOURS, settings.REFUND_PARTIAL_HOURS = 24 * 90, 24 * 5  # ten days out: the 50% window
    booking = paid(requester, room_type, stay)
    client = client_for(requester)
    move(client, booking, *shifted(stay, 0, nights=1))
    decide(client_for(approver), booking)
    surplus = Refund.objects.get()
    if surplus_sent:
        assert client_for(manager).post(f"/api/refunds/{surplus.pk}/issue").data["status"] == "PROCESSED"

    offer = client.get(f"/api/bookings/{booking.pk}").data["payment"]["refund_on_cancel"]
    assert offer == {"percent": 50, "amount": "500.00", "full": "1000.00"}
    assert client.post(f"/api/bookings/{booking.pk}/cancel").data["status"] == "CANCELLED"
    on_cancel = Refund.objects.exclude(pk=surplus.pk).get()
    assert on_cancel.amount == Decimal("500.00") and "50%" in on_cancel.reason
    # Rs 2000 came in: Rs 1000 for the shorter stay's difference, Rs 500 on cancelling, Rs 500 kept.
    assert sum(r.amount for r in Refund.objects.all()) == Decimal("1500.00")


def test_cancelling_a_lengthened_stay_refunds_across_both_payments(requester, approver, room_type, stay, settings):
    settings.REFUND_FULL_HOURS, settings.REFUND_PARTIAL_HOURS = 24 * 90, 24 * 5
    booking = paid(requester, room_type, stay)
    client = client_for(requester)
    move(client, booking, *shifted(stay, 0, nights=3))
    decide(client_for(approver), booking)
    pay(client, booking.pk)
    offer = client.get(f"/api/bookings/{booking.pk}").data["payment"]["refund_on_cancel"]
    assert offer == {"percent": 50, "amount": "1500.00", "full": "3000.00"}
    client.post(f"/api/bookings/{booking.pk}/cancel")
    assert sorted(r.amount for r in Refund.objects.all()) == [Decimal("500.00"), Decimal("1000.00")]


def test_rejected_change_leaves_the_booking_as_it_was(requester, approver, room_type, stay):
    booking = paid(requester, room_type, stay)
    client, desk, new = client_for(requester), client_for(approver), shifted(stay, 7)
    move(client, booking, *new)
    assert decide(desk, booking, "REJECTED").status_code == 400  # a reason is needed
    assert decide(desk, booking, "SENT_BACK", "no").status_code == 400
    mail.outbox.clear()
    data = decide(desk, booking, "REJECTED", "The guesthouse is closed that week").data
    assert (data["status"], data["check_in"]) == ("CONFIRMED", stay[0].isoformat())
    assert (data["date_change"]["status"], data["date_change"]["comment"]) == (
        "REJECTED", "The guesthouse is closed that week",
    )  # fmt: skip
    assert "was not approved" in mail.outbox[0].body and "closed that week" in mail.outbox[0].body
    assert availability(client, room_type, new) == 2
    assert decide(desk, booking).status_code == 409  # nothing left to decide
    # The guest can ask again, for other dates.
    assert move(client, booking, *shifted(stay, 3)).data["date_change"]["status"] == "PENDING"


def test_change_lapses_if_not_decided_or_not_paid_in_time(requester, approver, room_type, stay):
    booking = paid(requester, room_type, stay)
    client, new = client_for(requester), shifted(stay, 0, nights=3)
    move(client, booking, *new)
    DateChange.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert availability(client, room_type, (stay[1], new[1])) == 2  # a lapsed change holds nothing
    assert decide(client_for(approver), booking).status_code == 409
    mail.outbox.clear()
    assert expire_stale_bookings() == 1
    change = DateChange.objects.get()
    assert (change.status, change.comment) == ("EXPIRED", "It was not decided in time.")
    assert "has lapsed" in mail.outbox[0].body and Booking.objects.get(pk=booking.pk).check_out == stay[1]

    move(client, booking, *new)
    decide(client_for(approver), booking)
    DateChange.objects.filter(status="AWAITING_PAYMENT").update(expires_at=timezone.now() - timedelta(minutes=1))
    data = client.get(f"/api/bookings/{booking.pk}").data
    assert data["actions"]["pay"] is False and data["payment"]["due"] == "0.00"
    assert client.post(f"/api/bookings/{booking.pk}/pay", {"gateway": "dev"}, format="json").status_code == 409
    assert expire_stale_bookings() == 1
    assert list(DateChange.objects.values_list("status", flat=True)) == ["EXPIRED", "EXPIRED"]
    booking.refresh_from_db()
    assert (booking.status, booking.check_out, booking.amount) == (Status.CONFIRMED, stay[1], Decimal("2000.00"))


def test_balance_paid_after_the_change_closed_is_refunded(requester, approver, room_type, stay):
    booking = paid(requester, room_type, stay)
    client, new = client_for(requester), shifted(stay, 0, nights=3)
    move(client, booking, *new)
    decide(client_for(approver), booking)
    order = client.post(f"/api/bookings/{booking.pk}/pay", {"gateway": "dev"}, format="json").data["payment"]
    # The guest thinks again and withdraws, then the payment page that was still open is completed.
    assert client.delete(f"/api/bookings/{booking.pk}/date-change").data["date_change"]["status"] == "WITHDRAWN"
    client.post("/api/payments/dev/complete", {"order_id": order["order_id"], "outcome": "paid"}, format="json")
    booking.refresh_from_db()
    assert (booking.check_out, booking.amount) == (stay[1], Decimal("2000.00"))
    refund = Refund.objects.get()
    assert (refund.amount, refund.reason) == (Decimal("1000.00"), "Paid for a change of dates that was no longer open.")


def test_balance_paid_just_after_the_window_still_counts_if_the_dates_are_free(
    requester, other_requester, approver, room_type, stay
):
    booking = paid(requester, room_type, stay)
    client, new = client_for(requester), shifted(stay, 0, nights=3)
    move(client, booking, *new)
    decide(client_for(approver), booking)
    order = client.post(f"/api/bookings/{booking.pk}/pay", {"gateway": "dev"}, format="json").data["payment"]
    DateChange.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    client.post("/api/payments/dev/complete", {"order_id": order["order_id"], "outcome": "paid"}, format="json")
    assert Booking.objects.get(pk=booking.pk).check_out == new[1]

    # The same, but someone else took the extra night in the meantime: the money goes back.
    other, theirs = paid(other_requester, room_type, shifted(stay, 20)), client_for(other_requester)
    late = shifted(stay, 20, nights=3)
    move(theirs, other, *late)
    decide(client_for(approver), other)
    order = theirs.post(f"/api/bookings/{other.pk}/pay", {"gateway": "dev"}, format="json").data["payment"]
    DateChange.objects.filter(booking=other).update(expires_at=timezone.now() - timedelta(minutes=1))
    for _ in range(2):
        make_booking(requester, room_type, (late[1] - timedelta(days=1), late[1]), Status.CONFIRMED)
    resp = theirs.post("/api/payments/dev/complete", {"order_id": order["order_id"], "outcome": "paid"}, format="json")
    assert resp.status_code == 200
    other.refresh_from_db()
    assert other.check_out == late[1] - timedelta(days=1)
    assert DateChange.objects.get(booking=other).status == "EXPIRED"
    assert Refund.objects.get().reason.startswith("Paid after the time to pay for the change had run out")


# --- Rooms --------------------------------------------------------------------
def test_allotted_room_is_kept_when_free_and_released_when_not(requester, other_requester, approver, room_type, stay):
    room = room_type.rooms.get(number="101")
    booking = paid(requester, room_type, stay, Status.ALLOTTED, room=room)
    client, desk = client_for(requester), client_for(approver)
    new = shifted(stay, 1)
    move(client, booking, *new)
    data = decide(desk, booking).data
    assert (data["status"], data["room_number"], data["check_in"]) == ("ALLOTTED", "101", new[0].isoformat())

    # Someone else has room 101 on the next dates asked for: the stay moves, and a room is allotted again.
    later = shifted(stay, 10)
    paid(other_requester, room_type, later, Status.ALLOTTED, room=room)
    move(client, booking, *later)
    mail.outbox.clear()
    data = decide(desk, booking).data
    assert (data["status"], data["room_number"], data["check_in"]) == ("CONFIRMED", None, later[0].isoformat())
    assert "another one will be allotted" in mail.outbox[0].body
    assert "not free on the new dates" in AuditLog.objects.get(action="booking.confirmed").after["comment"]

    # The same when the room is out of service on the new dates.
    other = room_type.rooms.get(number="102")
    Booking.objects.filter(pk=booking.pk).update(room=other, status=Status.ALLOTTED)
    blocked = shifted(stay, 30)
    RoomBlock.objects.create(room=other, starts_on=blocked[0], ends_on=blocked[1], reason="Painting")
    move(client, booking, *blocked)
    data = decide(desk, booking).data
    assert (data["status"], data["room_number"], data["check_in"]) == ("CONFIRMED", None, blocked[0].isoformat())


def test_new_dates_must_be_free_but_the_bookings_own_nights_do_not_count(requester, other_requester, room_type, stay):
    booking = paid(requester, room_type, stay)
    client = client_for(requester)
    # Every other room is taken on the nights around the stay, so only this booking's own room is left.
    paid(other_requester, room_type, (stay[0] - timedelta(days=1), stay[1] + timedelta(days=1)))
    assert move(client, booking, stay[0], stay[1] + timedelta(days=1)).status_code == 200
    assert client.delete(f"/api/bookings/{booking.pk}/date-change").status_code == 200
    # Dates on which both rooms are taken by others cannot be asked for.
    full = shifted(stay, 20)
    for _ in range(2):
        paid(other_requester, room_type, full)
    resp = move(client, booking, *full)
    assert resp.status_code == 409 and "No rooms of this type are free" in resp.data["detail"]
    assert DateChange.objects.filter(status="PENDING").count() == 0


# --- Who, and when ------------------------------------------------------------
def test_guest_can_move_a_paid_stay_only_until_the_cut_off_but_the_desk_can_later(
    requester, manager, room_type, settings
):
    today = timezone.localdate()
    soon = (today + timedelta(days=1), today + timedelta(days=3))
    booking = paid(requester, room_type, soon)
    client, desk = client_for(requester), client_for(manager)
    assert client.get(f"/api/bookings/{booking.pk}").data["actions"]["change_dates"] is False
    resp = move(client, booking, *shifted(soon, 7))
    assert resp.status_code == 409 and "48 hours before arrival" in resp.data["detail"]
    # The desk takes the call and enters the change for the guest. It still needs approval.
    assert desk.get(f"/api/bookings/{booking.pk}").data["actions"]["change_dates"] is True
    data = move(desk, booking, *shifted(soon, 7)).data
    assert (data["status"], data["date_change"]["status"]) == ("CONFIRMED", "PENDING")
    assert DateChange.objects.get().requested_by == manager
    # An unpaid request has no cut-off: nothing has been paid that the rules would protect.
    unpaid = make_booking(requester, room_type, soon, Status.PENDING, hold_expires_at=timezone.now() + timedelta(1))
    assert move(client, unpaid, *shifted(soon, 2)).status_code == 200


def test_who_may_ask_for_decide_and_withdraw_a_change(clients, requester, other_requester, approver, room_type, stay):
    booking = paid(requester, room_type, stay)
    new = shifted(stay, 7)
    assert move(client_for(other_requester), booking, *new).status_code == 404
    assert move(clients["approver"], booking, *new).status_code == 403  # can see it, cannot change it
    assert move(clients["anon"], booking, *new).status_code == 403
    assert move(clients["requester"], booking, *new).status_code == 200
    for name in ("requester", "external", "manager_no_mfa", "admin_no_mfa"):
        assert decide(clients[name], booking).status_code in (403, 404), name
    assert clients["manager"].get(f"/api/bookings/{booking.pk}").data["actions"]["decide_change"] is False
    assert decide(clients["manager"], booking).status_code == 403  # the desk does not approve
    assert clients["approver"].delete(f"/api/bookings/{booking.pk}/date-change").status_code == 403
    assert client_for(other_requester).delete(f"/api/bookings/{booking.pk}/date-change").status_code == 404
    assert DateChange.objects.get().status == "PENDING"
    assert decide(clients["admin"], booking).data["check_in"] == new[0].isoformat()
    # Nobody approves a change to their own booking.
    own = paid(approver, room_type, shifted(stay, 30))
    move(clients["approver"], own, *shifted(stay, 40))
    assert decide(clients["approver"], own).status_code == 403


@pytest.mark.parametrize(
    "status", [Status.DRAFT, Status.SENT_BACK, Status.CHECKED_IN, Status.CHECKED_OUT, Status.CANCELLED]
)
def test_dates_cannot_be_changed_in_other_states(requester, room_type, stay, status):
    booking = make_booking(requester, room_type, stay, status)
    client = client_for(requester)
    assert client.get(f"/api/bookings/{booking.pk}").data["actions"]["change_dates"] is False
    assert move(client, booking, *shifted(stay, 3)).status_code == 409


def test_new_dates_are_checked_like_any_stay(requester, room_type, stay, settings):
    booking = paid(requester, room_type, stay)
    client, today = client_for(requester), timezone.localdate()
    assert "differ" in str(move(client, booking, *stay).data)
    assert "past" in str(move(client, booking, today - timedelta(days=2), today).data)
    assert move(client, booking, stay[1], stay[0]).status_code == 400
    assert move(client, booking, stay[0], stay[0] + timedelta(days=settings.BOOKING_MAX_NIGHTS + 1)).status_code == 400
    assert (
        client.post(f"/api/bookings/{booking.pk}/date-change", {"check_in": "soon"}, format="json").status_code == 400
    )
    assert move(client, booking, *shifted(stay, 2)).status_code == 200
    resp = move(client, booking, *shifted(stay, 4))
    assert resp.status_code == 409 and "already open" in resp.data["detail"]


def test_new_dates_are_priced_at_the_tariff_then_in_force(requester, approver, room_type, stay):
    from apps.rooms.models import Tariff

    booking = paid(requester, room_type, stay)
    new = shifted(stay, 30)
    Tariff.objects.create(room_type=room_type, price_per_night=1200, valid_from=new[0])
    change = move(client_for(requester), booking, *new).data["date_change"]
    assert (change["amount"], change["balance"]) == ("2400.00", "400.00")


# --- The booking moves on while a change is open -----------------------------
def test_cancelling_or_checking_in_closes_an_open_change(requester, manager, room_type, stay):
    booking = paid(requester, room_type, stay)
    client = client_for(requester)
    move(client, booking, *shifted(stay, 7))
    assert client.post(f"/api/bookings/{booking.pk}/cancel").data["date_change"]["status"] == "WITHDRAWN"
    assert availability(client, room_type, shifted(stay, 7)) == 2

    today = timezone.localdate()
    room = room_type.rooms.get(number="101")
    staying = paid(requester, room_type, (today, today + timedelta(days=2)), Status.ALLOTTED, room=room)
    desk = client_for(manager)
    move(desk, staying, today, today + timedelta(days=3))
    guests = [str(g.pk) for g in staying.guests.all()]
    data = desk.post(f"/api/bookings/{staying.pk}/check-in", {"guests": guests}, format="json").data
    assert (data["status"], data["date_change"]["status"]) == ("CHECKED_IN", "EXPIRED")
    assert "stay began" in data["date_change"]["comment"]


def test_guest_waiting_on_a_change_is_not_marked_a_no_show(requester, manager, room_type):
    today = timezone.localdate()
    booking = paid(requester, room_type, (today - timedelta(days=1), today + timedelta(days=1)))
    changes.request(booking.pk, manager, today + timedelta(days=5), today + timedelta(days=7), by_staff=True)
    late = timezone.now() + timedelta(days=1)
    assert services.mark_no_shows(late) == 0
    # Once the change is refused, the booking is judged on its own dates again.
    DateChange.objects.update(status="REJECTED")
    assert services.mark_no_shows(late) == 1
    assert Booking.objects.get(pk=booking.pk).status == Status.NO_SHOW
