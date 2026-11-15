import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings import services
from apps.bookings.models import Booking, Document, Guest, RegisterEntry, Status
from apps.payments.models import Payment, Refund

from .conftest import client_for, make_booking

pytestmark = pytest.mark.django_db


@pytest.fixture
def today():
    return timezone.localdate()


def allotted(user, room_type, start, nights=2, number="101", paid=True, **guest):
    """A paid booking with a room, arriving on the given day."""
    room = room_type.rooms.get(number=number)
    booking = make_booking(user, room_type, (start, start + timedelta(days=nights)), Status.ALLOTTED, room=room)
    if guest:
        Guest.objects.filter(booking=booking).update(**guest)
    if paid:
        Payment.objects.create(
            booking=booking, gateway="dev", order_id=f"dev_{booking.reference}", gateway_payment_id="devpay_1",
            amount=booking.amount, status="PAID", paid_at=timezone.now(),
        )  # fmt: skip
    return booking


def add_guest(booking, name, with_id=True):
    document = None
    if with_id:
        document = Document.objects.create(
            booking=booking, type="GUEST_ID", file_ref="x/second.pdf", content_type="application/pdf", size=10,
            uploaded_by=booking.requester,
        )  # fmt: skip
    return Guest.objects.create(
        booking=booking, name=name, phone="+919800000009", address="Addr 2", id_type="AADHAAR", id_document=document
    )


def check_in(client, booking, guests=None):
    guests = booking.guests.all() if guests is None else guests
    return client.post(f"/api/bookings/{booking.pk}/check-in", {"guests": [str(g.pk) for g in guests]}, format="json")


# --- Check-in and check-out ---------------------------------------------------
def test_check_in_verifies_ids_and_writes_the_register(requester, manager, room_type, today):
    desk = client_for(manager)
    booking = allotted(requester, room_type, today)
    second = add_guest(booking, "Second Guest")
    assert desk.get(f"/api/bookings/{booking.pk}").data["actions"]["check_in"] is True

    # Nobody ticked, an unknown guest, and a repeated guest are all refused.
    assert check_in(desk, booking, []).status_code == 400
    assert (
        desk.post(f"/api/bookings/{booking.pk}/check-in", {"guests": ["not-an-id"]}, format="json").status_code == 400
    )
    stranger = make_booking(requester, room_type, (today, today + timedelta(days=1))).guests.get()
    assert check_in(desk, booking, [stranger]).status_code == 400
    assert Booking.objects.get(pk=booking.pk).status == Status.ALLOTTED

    resp = check_in(desk, booking)
    assert resp.status_code == 200 and resp.data["status"] == "CHECKED_IN"
    assert all(g["id_verified"] for g in resp.data["guests"])
    assert set(Document.objects.filter(guest__booking=booking).values_list("verified_by", flat=True)) == {manager.pk}
    entries = list(RegisterEntry.objects.order_by("serial_number"))
    assert [e.serial_number for e in entries] == [1, 2]
    assert {e.guest_id for e in entries} == {second.pk, booking.guests.exclude(pk=second.pk).get().pk}
    assert all(e.room.number == "101" and e.entered_by == manager and e.departure_at is None for e in entries)
    # The booking's payment appears once, so the register's amount column adds up.
    assert [e.amount_paid for e in entries] == [Decimal("2000.00"), Decimal("0.00")]
    assert AuditLog.objects.filter(action="booking.checked_in", actor=manager).count() == 1
    assert AuditLog.objects.get(action="register.entered").after["serials"] == [1, 2]
    assert check_in(desk, booking).status_code == 409  # not twice

    out = desk.post(f"/api/bookings/{booking.pk}/check-out")
    assert out.status_code == 200 and out.data["status"] == "CHECKED_OUT"
    assert RegisterEntry.objects.filter(departure_at__isnull=False).count() == 2
    assert desk.post(f"/api/bookings/{booking.pk}/check-out").status_code == 409


def test_only_guests_who_arrived_are_entered(requester, manager, room_type, today):
    booking = allotted(requester, room_type, today)
    absent = add_guest(booking, "Absent Guest")
    arrived = booking.guests.exclude(pk=absent.pk).get()
    assert check_in(client_for(manager), booking, [arrived]).status_code == 200
    assert list(RegisterEntry.objects.values_list("guest", flat=True)) == [arrived.pk]
    absent.refresh_from_db()
    assert absent.id_verified is False


def test_guest_without_an_id_copy_cannot_be_checked_in(requester, manager, room_type, today):
    booking = allotted(requester, room_type, today)
    add_guest(booking, "No Papers", with_id=False)
    resp = check_in(client_for(manager), booking)
    assert resp.status_code == 400 and "ID copy" in str(resp.data)
    assert RegisterEntry.objects.count() == 0 and Booking.objects.get(pk=booking.pk).status == Status.ALLOTTED


def test_check_in_only_during_the_stay_and_only_with_a_room(requester, manager, room_type, today):
    desk = client_for(manager)
    early = allotted(requester, room_type, today + timedelta(days=1))
    assert desk.get(f"/api/bookings/{early.pk}").data["actions"]["check_in"] is False
    resp = check_in(desk, early)
    assert resp.status_code == 409 and "starts on" in str(resp.data)

    over = allotted(requester, room_type, today - timedelta(days=3), number="102")
    assert check_in(desk, over).status_code == 409

    no_room = make_booking(requester, room_type, (today, today + timedelta(days=1)), Status.CONFIRMED)
    assert check_in(desk, no_room).status_code == 409
    assert RegisterEntry.objects.count() == 0


def test_serial_numbers_run_on_without_gaps(requester, other_requester, manager, room_type, today):
    desk = client_for(manager)
    first = allotted(requester, room_type, today)
    add_guest(first, "Second Guest")
    second = allotted(other_requester, room_type, today, number="102")
    assert check_in(desk, first).status_code == 200
    assert check_in(desk, second).status_code == 200
    assert list(RegisterEntry.objects.values_list("serial_number", flat=True)) == [1, 2, 3]


def test_desk_actions_are_for_managers(clients, requester, room_type, today):
    booking = allotted(requester, room_type, today)
    guests = {"guests": [str(booking.guests.get().pk)]}
    for name in ("requester", "approver", "external", "manager_no_mfa"):
        assert clients[name].post(f"/api/bookings/{booking.pk}/check-in", guests, format="json").status_code in (
            403,
            404,
        ), name
        for path in ("/api/desk", "/api/register", "/api/register.csv", "/api/register.pdf"):
            assert clients[name].get(path).status_code == 403, (name, path)
    assert clients["anon"].get("/api/register.csv").status_code == 403
    assert clients["manager"].post(f"/api/bookings/{booking.pk}/check-in", guests, format="json").status_code == 200
    for name in ("requester", "approver"):
        assert clients[name].post(f"/api/bookings/{booking.pk}/check-out").status_code in (403, 404), name
    assert clients["requester"].get(f"/api/bookings/{booking.pk}").data["actions"]["check_out"] is False


# --- The desk's day -----------------------------------------------------------
def test_desk_shows_arrivals_departures_and_guests_in_house(requester, other_requester, manager, room_type, today):
    desk = client_for(manager)
    arriving = allotted(requester, room_type, today)
    waiting_for_room = make_booking(other_requester, room_type, (today, today + timedelta(days=1)), Status.CONFIRMED)
    tomorrow = make_booking(
        other_requester, room_type, (today + timedelta(days=1), today + timedelta(days=2)), Status.CONFIRMED
    )
    data = desk.get("/api/desk").data
    assert {b["id"] for b in data["arrivals"]} == {str(arriving.pk), str(waiting_for_room.pk)}
    assert (data["in_house"], data["departures"], data["to_allot"]) == ([], [], 2)
    assert str(tomorrow.pk) not in {b["id"] for b in data["arrivals"]}

    check_in(desk, arriving)
    data = desk.get("/api/desk").data
    assert [b["id"] for b in data["in_house"]] == [str(arriving.pk)]
    assert [b["id"] for b in data["arrivals"]] == [str(waiting_for_room.pk)]
    # On the last day the guest moves to the departures list.
    Booking.objects.filter(pk=arriving.pk).update(check_in=today - timedelta(days=2), check_out=today)
    data = desk.get("/api/desk").data
    assert [b["id"] for b in data["departures"]] == [str(arriving.pk)] and data["in_house"] == []


# --- The register -------------------------------------------------------------
@pytest.fixture
def register(requester, other_requester, manager, room_type, today):
    desk = client_for(manager)
    first = allotted(requester, room_type, today, name="Asha Rao", phone="+919811111111")
    second = allotted(other_requester, room_type, today, number="102", name="=HYPERLINK(1)", address="@home")
    check_in(desk, first)
    check_in(desk, second)
    RegisterEntry.objects.filter(booking=second).update(arrival_at=timezone.now() - timedelta(days=40))
    return desk, first, second


def test_register_search_dates_and_access_log(register, manager, today):
    desk, first, second = register
    rows = desk.get("/api/register").data["results"]
    assert [r["serial_number"] for r in rows] == [2, 1]
    assert rows[1] == {
        **rows[1],
        "booking_reference": first.reference, "guest_name": "Asha Rao", "guest_phone": "+919811111111",
        "id_type": "Passport", "room_number": "101", "purpose": "Visit", "amount_paid": "2000.00",
        "entered_by_name": "Manager", "departure_at": None,
    }  # fmt: skip
    search = lambda query: [r["serial_number"] for r in desk.get(f"/api/register?{query}").data["results"]]  # noqa: E731
    assert search("search=asha") == [1]
    assert search("search=9811111111") == [1]
    assert search(f"search={second.reference.lower()}") == [2]
    assert search("search=102") == [2]
    assert search(f"from={today}") == [1]
    assert search(f"to={today - timedelta(days=30)}") == [2]
    assert search(f"from={today - timedelta(days=60)}&to={today}") == [2, 1]
    assert desk.get("/api/register?from=yesterday").status_code == 400
    # Every look at the register is recorded with who looked and what they searched for.
    logs = AuditLog.objects.filter(action="register.viewed", actor=manager)
    assert logs.count() == 8
    assert logs.filter(after__search="asha", after__entries=1).exists()


def test_register_csv_export_is_safe_to_open_in_a_spreadsheet(register, manager):
    desk, first, _ = register
    resp = desk.get("/api/register.csv")
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/csv")
    assert "attachment" in resp["Content-Disposition"] and "no-store" in resp["Cache-Control"]
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert rows[0][:5] == ["No.", "Booking", "Guest", "Phone", "Address"]
    assert rows[1][:3] == ["1", first.reference, "Asha Rao"] and rows[1][-1] == "2000.00"
    # Text a guest typed cannot become a formula.
    assert rows[2][2] == "'=HYPERLINK(1)" and rows[2][4] == "'@home" and rows[1][3] == "'+919811111111"
    assert [r[0] for r in csv.reader(io.StringIO(desk.get("/api/register.csv?search=asha").content.decode()))][1:] == [
        "1"
    ]
    log = AuditLog.objects.filter(action="register.exported_csv", actor=manager).order_by("created_at").first()
    assert log.after["entries"] == 2


def test_register_pdf_export(register, manager):
    desk, _, _ = register
    resp = desk.get("/api/register.pdf?search=asha")
    assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf" and resp.content[:5] == b"%PDF-"
    assert AuditLog.objects.get(action="register.exported_pdf").after == {"search": "asha", "entries": 1}
    assert desk.get("/api/register.xlsx").status_code == 404


# --- No-shows -----------------------------------------------------------------
def test_no_show_refund_follows_the_configured_share(requester, room_type, today, settings):
    booking = allotted(requester, room_type, today - timedelta(days=2), nights=3)
    assert services.mark_no_shows() == 1
    assert Booking.objects.get(pk=booking.pk).status == Status.NO_SHOW and Refund.objects.count() == 0

    settings.REFUND_NO_SHOW_PERCENT = 25
    other = allotted(requester, room_type, today - timedelta(days=2), nights=3, number="102")
    assert services.mark_no_shows() == 1
    refund = Refund.objects.get()
    assert (refund.payment.booking_id, refund.amount, refund.status) == (other.pk, Decimal("750.00"), "DUE")
