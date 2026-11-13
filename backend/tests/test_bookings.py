from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings import services
from apps.bookings.models import Booking, Status
from apps.bookings.state import TRANSITIONS
from apps.payments.models import Payment
from apps.rooms.models import Room, Tariff

from .conftest import booking_payload, client_for, make_booking, submitted_booking, upload

pytestmark = pytest.mark.django_db


def availability(client, room_type, stay):
    data = client.get(f"/api/availability?check_in={stay[0]}&check_out={stay[1]}").data
    return next(r for r in data["results"] if r["room_type"] == str(room_type.pk))


# --- The whole flow -----------------------------------------------------------
def test_official_stay_end_to_end(requester, approver, manager, room_type, stay):
    guest, hod, desk = client_for(requester), client_for(approver), client_for(manager)

    booking = submitted_booking(guest, room_type, stay)
    assert booking["status"] == "PENDING"
    assert booking["reference"].startswith("GH-")
    assert (booking["price_per_night"], booking["amount"], booking["nights"]) == ("1000.00", "2000.00", 2)
    hold = datetime.fromisoformat(booking["hold_expires_at"]) - timezone.now()
    assert timedelta(hours=47) < hold <= timedelta(hours=48)
    assert availability(guest, room_type, stay)["available"] == 1
    assert any("needs your decision" in m.subject and approver.email in m.to for m in mail.outbox)

    base = f"/api/bookings/{booking['id']}"
    assert hod.get(base).data["actions"]["decide"] is True
    booking = hod.post(f"{base}/decide", {"decision": "APPROVED"}, format="json").data
    assert booking["status"] == "APPROVED"
    pay_window = datetime.fromisoformat(booking["hold_expires_at"]) - timezone.now()
    assert timedelta(hours=23) < pay_window <= timedelta(hours=24)

    booking = guest.post(f"{base}/pay", {"gateway": "dev"}, format="json").data
    assert booking["status"] == "CONFIRMED" and booking["hold_expires_at"] is None
    payment = Payment.objects.get(booking_id=booking["id"])
    assert (payment.status, payment.amount) == ("PAID", Decimal("2000.00"))

    rooms = desk.get(f"{base}/free-rooms").data
    assert {r["number"] for r in rooms} == {"101", "102"}
    booking = desk.post(f"{base}/allot", {"room": rooms[0]["id"]}, format="json").data
    assert (booking["status"], booking["room_number"]) == ("ALLOTTED", rooms[0]["number"])

    # Every transition is logged, in order, and each one emailed the requester.
    actions = list(
        AuditLog.objects.filter(entity="booking", entity_id=booking["id"])
        .order_by("created_at")
        .values_list("action", flat=True)
    )
    assert actions == [
        "booking.created",
        "booking.pending",
        "booking.approved",
        "booking.confirmed",
        "booking.allotted",
    ]
    subjects = [m.subject for m in mail.outbox if requester.email in m.to]
    assert [s.rsplit("– ", 1)[1] for s in subjects] == ["Pending", "Approved", "Confirmed", "Allotted"]


def test_personal_stay_needs_student_link(external, approver, room_type, stay):
    guest = client_for(external)
    payload = booking_payload(room_type, stay, "PERSONAL")
    del payload["student_link"]
    resp = guest.post("/api/bookings", payload, format="json")
    assert resp.status_code == 400 and "student_link" in resp.data
    payload = booking_payload(room_type, stay, "PERSONAL")
    payload["student_link"]["year"] = 0
    assert guest.post("/api/bookings", payload, format="json").status_code == 400

    booking = submitted_booking(guest, room_type, stay, "PERSONAL")
    assert booking["status"] == "PENDING"
    assert booking["student_link"]["roll_number"] == "CS22B014"
    seen = client_for(approver).get(f"/api/bookings/{booking['id']}").data
    assert seen["student_link"]["relationship"] == "Mother"


# --- Submission rules ---------------------------------------------------------
def test_official_stay_needs_letter_and_guest_ids(requester, room_type, stay):
    client = client_for(requester)
    booking = client.post("/api/bookings", booking_payload(room_type, stay), format="json").data
    base = f"/api/bookings/{booking['id']}"
    resp = client.post(f"{base}/submit")
    assert resp.status_code == 400
    assert len(resp.data["detail"]) == 2  # no ID, no letter
    client.post(
        f"{base}/documents",
        {"type": "GUEST_ID", "guest": booking["guests"][0]["id"], "file": upload()},
        format="multipart",
    )
    resp = client.post(f"{base}/submit")
    assert resp.status_code == 400 and "recommendation letter" in resp.data["detail"][0]
    assert Booking.objects.get(pk=booking["id"]).status == Status.DRAFT
    assert availability(client, room_type, stay)["available"] == 2  # drafts hold nothing


@pytest.mark.parametrize(
    "offset_in,nights,field",
    [(-1, 2, "check_in"), (5, 0, "check_out"), (5, -1, "check_out"), (5, 15, "check_out"), (400, 2, "check_in")],
)
def test_date_validation(requester, room_type, offset_in, nights, field):
    start = timezone.localdate() + timedelta(days=offset_in)
    resp = client_for(requester).post(
        "/api/bookings", booking_payload(room_type, (start, start + timedelta(days=nights))), format="json"
    )
    assert resp.status_code == 400 and field in resp.data


def test_guest_count_is_limited_by_capacity(requester, room_type, stay):
    payload = booking_payload(room_type, stay)
    payload["guests"] = payload["guests"] * 3
    resp = client_for(requester).post("/api/bookings", payload, format="json")
    assert resp.status_code == 400 and "guests" in resp.data


def test_inactive_or_unpriced_room_type_cannot_be_booked(requester, room_type, stay):
    client = client_for(requester)
    Tariff.objects.all().delete()
    assert client.post("/api/bookings", booking_payload(room_type, stay), format="json").status_code == 400
    room_type.is_active = False
    room_type.save()
    assert client.post("/api/bookings", booking_payload(room_type, stay), format="json").status_code == 400


@pytest.mark.parametrize(
    "content,name",
    [(b"MZ\x90\x00 not a pdf", "letter.pdf"), (b"<script>alert(1)</script>", "x.png"), (b"GIF89a....", "a.jpg")],
)
def test_uploads_are_checked_by_content(requester, room_type, stay, content, name):
    client = client_for(requester)
    booking = client.post("/api/bookings", booking_payload(room_type, stay), format="json").data
    resp = client.post(
        f"/api/bookings/{booking['id']}/documents",
        {"type": "RECOMMENDATION_LETTER", "file": upload(name, content)},
        format="multipart",
    )
    assert resp.status_code == 400


def test_upload_size_cap_and_replacement(requester, room_type, stay, settings):
    client = client_for(requester)
    booking = client.post("/api/bookings", booking_payload(room_type, stay), format="json").data
    url = f"/api/bookings/{booking['id']}/documents"
    settings.UPLOAD_MAX_BYTES = 20
    assert client.post(url, {"type": "RECOMMENDATION_LETTER", "file": upload()}, format="multipart").status_code == 400
    settings.UPLOAD_MAX_BYTES = 5 * 1024 * 1024
    first = client.post(url, {"type": "RECOMMENDATION_LETTER", "file": upload()}, format="multipart").data
    second = client.post(url, {"type": "RECOMMENDATION_LETTER", "file": upload()}, format="multipart").data
    docs = client.get(f"/api/bookings/{booking['id']}").data["documents"]
    assert [d["id"] for d in docs] == [second["id"]] and first["id"] != second["id"]
    # A guest ID must name a guest of this booking.
    assert client.post(url, {"type": "GUEST_ID", "file": upload()}, format="multipart").status_code == 400


# --- Price snapshot -----------------------------------------------------------
def test_booking_keeps_the_price_it_was_booked_at(requester, manager, room_type, stay):
    client = client_for(requester)
    booking = submitted_booking(client, room_type, stay)
    resp = client_for(manager).post(
        f"/api/room-types/{room_type.pk}/tariffs",
        {"price_per_night": "1800", "valid_from": timezone.localdate().isoformat()},
        format="json",
    )
    assert resp.status_code == 201
    assert client.get(f"/api/bookings/{booking['id']}").data["amount"] == "2000.00"
    assert availability(client, room_type, stay)["price_per_night"] == "1800.00"


def test_future_tariff_applies_from_its_start_date(requester, room_type, stay):
    Tariff.objects.create(room_type=room_type, price_per_night=1500, valid_from=stay[0] + timedelta(days=30))
    client = client_for(requester)
    assert availability(client, room_type, stay)["price_per_night"] == "1000.00"
    later = (stay[0] + timedelta(days=30), stay[0] + timedelta(days=31))
    assert availability(client, room_type, later)["amount"] == "1500.00"


# --- Availability and holds ---------------------------------------------------
def test_last_room_cannot_be_requested_twice(requester, other_requester, room_type, stay):
    Room.objects.filter(number="102").update(is_active=False)
    first, second = client_for(requester), client_for(other_requester)
    submitted_booking(first, room_type, stay)
    assert availability(second, room_type, stay)["available"] == 0

    booking = second.post("/api/bookings", booking_payload(room_type, stay), format="json").data
    base = f"/api/bookings/{booking['id']}"
    second.post(
        f"{base}/documents",
        {"type": "GUEST_ID", "guest": booking["guests"][0]["id"], "file": upload()},
        format="multipart",
    )
    second.post(f"{base}/documents", {"type": "RECOMMENDATION_LETTER", "file": upload()}, format="multipart")
    assert second.post(f"{base}/submit").status_code == 409


def test_availability_counts_the_busiest_night(requester, room_type, stay):
    """Two back-to-back stays share one room, so a range spanning both still has a room free."""
    day = stay[0]
    make_booking(requester, room_type, (day, day + timedelta(days=1)), Status.CONFIRMED)
    make_booking(requester, room_type, (day + timedelta(days=1), day + timedelta(days=2)), Status.CONFIRMED)
    assert services.available_count(room_type, day, day + timedelta(days=2)) == 1
    make_booking(requester, room_type, (day, day + timedelta(days=1)), Status.PENDING)
    assert services.available_count(room_type, day, day + timedelta(days=2)) == 0
    assert services.available_count(room_type, day + timedelta(days=1), day + timedelta(days=2)) == 1
    # Check-out day is free for the next arrival.
    assert services.available_count(room_type, day + timedelta(days=2), day + timedelta(days=3)) == 2


@pytest.mark.parametrize("status", ["DRAFT", "REJECTED", "CANCELLED", "EXPIRED", "NO_SHOW", "CHECKED_OUT"])
def test_released_states_do_not_hold_rooms(requester, room_type, stay, status):
    make_booking(requester, room_type, stay, status)
    assert services.available_count(room_type, *stay) == 2


def test_unapproved_request_expires_after_hold(requester, room_type, stay):
    client = client_for(requester)
    booking = submitted_booking(client, room_type, stay)
    assert services.expire_stale() == 0
    Booking.objects.filter(pk=booking["id"]).update(hold_expires_at=timezone.now() - timedelta(minutes=1))
    assert availability(client, room_type, stay)["available"] == 2  # lapsed hold frees the dates at once
    assert services.expire_stale() == 1
    assert client.get(f"/api/bookings/{booking['id']}").data["status"] == "EXPIRED"
    assert AuditLog.objects.filter(action="booking.expired", actor__isnull=True).count() == 1


def test_unpaid_approval_expires_and_cannot_be_paid(requester, approver, room_type, stay):
    client = client_for(requester)
    booking = submitted_booking(client, room_type, stay)
    client_for(approver).post(f"/api/bookings/{booking['id']}/decide", {"decision": "APPROVED"}, format="json")
    Booking.objects.filter(pk=booking["id"]).update(hold_expires_at=timezone.now() - timedelta(minutes=1))
    assert client.post(f"/api/bookings/{booking['id']}/pay", {"gateway": "dev"}, format="json").status_code == 409
    assert services.expire_stale() == 1
    assert Booking.objects.get(pk=booking["id"]).status == Status.EXPIRED
    assert not Payment.objects.exists()


def test_no_show_after_noon_next_day(requester, room_type):
    today = timezone.localdate()
    booking = make_booking(
        requester, room_type, (today, today + timedelta(days=2)), Status.ALLOTTED, room=room_type.rooms.first()
    )
    noon_next_day = timezone.make_aware(datetime.combine(today + timedelta(days=1), time(12, 0)))
    assert services.mark_no_shows(noon_next_day - timedelta(minutes=1)) == 0
    assert services.mark_no_shows(noon_next_day + timedelta(minutes=1)) == 1
    booking.refresh_from_db()
    assert (booking.status, booking.room) == (Status.NO_SHOW, None)


# --- Approval -----------------------------------------------------------------
def test_reject_and_send_back_need_a_comment(requester, approver, room_type, stay):
    booking = make_booking(requester, room_type, stay, Status.PENDING)
    hod = client_for(approver)
    url = f"/api/bookings/{booking.pk}/decide"
    assert hod.post(url, {"decision": "REJECTED"}, format="json").status_code == 400
    assert hod.post(url, {"decision": "MAYBE"}, format="json").status_code == 400
    resp = hod.post(url, {"decision": "REJECTED", "comment": "Letter is unsigned"}, format="json")
    assert resp.data["status"] == "REJECTED"
    assert resp.data["approvals"][0]["comment"] == "Letter is unsigned"
    assert hod.post(url, {"decision": "APPROVED"}, format="json").status_code == 409  # already decided
    assert services.available_count(room_type, *stay) == 2


def test_sent_back_request_can_be_fixed_and_resubmitted(requester, approver, room_type, stay):
    guest, hod = client_for(requester), client_for(approver)
    booking = submitted_booking(guest, room_type, stay)
    base = f"/api/bookings/{booking['id']}"
    hod.post(f"{base}/decide", {"decision": "SENT_BACK", "comment": "Wrong dates"}, format="json")
    assert any("Wrong dates" in m.body for m in mail.outbox)
    assert services.available_count(room_type, *stay) == 1  # still held while the guest fixes it

    new_out = (stay[1] + timedelta(days=1)).isoformat()
    guest_row = booking["guests"][0]
    resp = guest.patch(
        base, {"check_out": new_out, "guests": [{**guest_row, "name": "Prof. V. Isitor"}]}, format="json"
    )
    assert resp.status_code == 200, resp.data
    assert (resp.data["amount"], resp.data["nights"]) == ("3000.00", 3)
    assert resp.data["guests"][0]["has_id_document"] is True  # kept the uploaded ID
    assert guest.post(f"{base}/submit").data["status"] == "PENDING"
    assert hod.post(f"{base}/decide", {"decision": "APPROVED"}, format="json").data["status"] == "APPROVED"


def test_removing_a_guest_removes_their_id(requester, room_type, stay):
    client = client_for(requester)
    payload = booking_payload(room_type, stay)
    payload["guests"].append({"name": "Second", "phone": "+919800000009", "address": "Somewhere", "id_type": "PAN"})
    booking = client.post("/api/bookings", payload, format="json").data
    base = f"/api/bookings/{booking['id']}"
    for g in booking["guests"]:
        client.post(f"{base}/documents", {"type": "GUEST_ID", "guest": g["id"], "file": upload()}, format="multipart")
    keep = next(g for g in booking["guests"] if g["name"] == "Second")
    data = client.patch(base, {"guests": [keep]}, format="json").data
    assert [g["name"] for g in data["guests"]] == ["Second"]
    assert len(data["documents"]) == 1


# --- Cancel -------------------------------------------------------------------
@pytest.mark.parametrize("status", ["DRAFT", "PENDING", "SENT_BACK", "APPROVED", "CONFIRMED", "ALLOTTED"])
def test_guest_can_cancel_before_check_in(requester, room_type, stay, status):
    room = room_type.rooms.first() if status == "ALLOTTED" else None
    booking = make_booking(requester, room_type, stay, status, room=room)
    resp = client_for(requester).post(f"/api/bookings/{booking.pk}/cancel")
    assert resp.status_code == 200 and resp.data["status"] == "CANCELLED" and resp.data["room"] is None
    assert services.available_count(room_type, *stay) == 2


@pytest.mark.parametrize("status", ["CHECKED_IN", "CHECKED_OUT", "REJECTED", "EXPIRED", "CANCELLED", "NO_SHOW"])
def test_cannot_cancel_after_check_in_or_when_closed(requester, room_type, stay, status):
    booking = make_booking(requester, room_type, stay, status)
    assert client_for(requester).post(f"/api/bookings/{booking.pk}/cancel").status_code == 409


def test_manager_can_cancel_for_a_guest(requester, manager, room_type, stay):
    booking = make_booking(requester, room_type, stay, Status.CONFIRMED)
    assert client_for(manager).post(f"/api/bookings/{booking.pk}/cancel").data["status"] == "CANCELLED"


# --- State machine ------------------------------------------------------------
def test_terminal_states_have_no_exits():
    for status in ("REJECTED", "CHECKED_OUT", "CANCELLED", "EXPIRED", "NO_SHOW"):
        assert TRANSITIONS[status] == set()
    assert set(TRANSITIONS) == set(Status.values)


@pytest.mark.parametrize("status", ["DRAFT", "PENDING", "APPROVED", "REJECTED", "CANCELLED", "CHECKED_IN"])
def test_allotment_needs_a_paid_booking(requester, manager, room_type, stay, status):
    booking = make_booking(requester, room_type, stay, status)
    resp = client_for(manager).post(
        f"/api/bookings/{booking.pk}/allot", {"room": str(room_type.rooms.first().pk)}, format="json"
    )
    assert resp.status_code == 409
    assert Booking.objects.get(pk=booking.pk).room is None


def test_payment_needs_approval_and_a_listed_gateway(requester, room_type, stay, settings):
    client = client_for(requester)
    pending = make_booking(requester, room_type, stay, Status.PENDING)
    assert client.post(f"/api/bookings/{pending.pk}/pay", {"gateway": "dev"}, format="json").status_code == 409
    approved = make_booking(requester, room_type, stay, Status.APPROVED)
    assert client.post(f"/api/bookings/{approved.pk}/pay", {"gateway": "razorpay"}, format="json").status_code == 400
    settings.PAYMENT_GATEWAYS = []  # production default: the test gateway does not exist
    assert client.post(f"/api/bookings/{approved.pk}/pay", {"gateway": "dev"}, format="json").status_code == 400
    assert Booking.objects.get(pk=approved.pk).status == Status.APPROVED


# --- No double-booking --------------------------------------------------------
def test_allot_rejects_overlap_and_wrong_room(requester, manager, room_type, stay):
    desk = client_for(manager)
    r101, r102 = room_type.rooms.order_by("number")
    first = make_booking(requester, room_type, stay, Status.CONFIRMED)
    second = make_booking(
        requester, room_type, (stay[0] + timedelta(days=1), stay[1] + timedelta(days=1)), Status.CONFIRMED
    )
    assert desk.post(f"/api/bookings/{first.pk}/allot", {"room": str(r101.pk)}, format="json").status_code == 200

    assert {r["number"] for r in desk.get(f"/api/bookings/{second.pk}/free-rooms").data} == {"102"}
    resp = desk.post(f"/api/bookings/{second.pk}/allot", {"room": str(r101.pk)}, format="json")
    assert resp.status_code == 409 and "101" in resp.data["detail"]
    second.refresh_from_db()
    assert (second.status, second.room) == (Status.CONFIRMED, None)

    other_type_room = Room.objects.create(number="900", room_type=type(room_type).objects.create(name="Other"))
    assert (
        desk.post(f"/api/bookings/{second.pk}/allot", {"room": str(other_type_room.pk)}, format="json").status_code
        == 400
    )
    r102.is_active = False
    r102.save()
    assert desk.post(f"/api/bookings/{second.pk}/allot", {"room": str(r102.pk)}, format="json").status_code == 400
    r102.is_active = True
    r102.save()
    assert (
        desk.post(f"/api/bookings/{second.pk}/allot", {"room": str(r102.pk)}, format="json").data["room_number"]
        == "102"
    )
    # A room change is allowed while allotted, but still cannot collide.
    assert desk.post(f"/api/bookings/{second.pk}/allot", {"room": str(r101.pk)}, format="json").status_code == 409


def test_back_to_back_stays_share_a_room(requester, manager, room_type, stay):
    desk = client_for(manager)
    room = room_type.rooms.first()
    first = make_booking(requester, room_type, stay, Status.CONFIRMED)
    second = make_booking(requester, room_type, (stay[1], stay[1] + timedelta(days=1)), Status.CONFIRMED)
    for booking in (first, second):
        assert desk.post(f"/api/bookings/{booking.pk}/allot", {"room": str(room.pk)}, format="json").status_code == 200


def test_database_itself_rejects_double_booking(requester, room_type, stay):
    """The guarantee must hold even if application code is bypassed entirely."""
    room = room_type.rooms.first()
    make_booking(requester, room_type, stay, Status.CHECKED_IN, room=room)
    with pytest.raises(IntegrityError, match="no_overlap"), transaction.atomic():
        make_booking(
            requester, room_type, (stay[0] + timedelta(days=1), stay[1] + timedelta(days=3)), Status.ALLOTTED, room=room
        )
    other = make_booking(requester, room_type, stay, Status.CONFIRMED, room=None)
    with pytest.raises(IntegrityError, match="no_overlap"), transaction.atomic():
        Booking.objects.filter(pk=other.pk).update(room=room, status=Status.ALLOTTED)
    with pytest.raises(IntegrityError, match="check_out_after_check_in"), transaction.atomic():
        make_booking(requester, room_type, (stay[1], stay[0]))
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'btree_gist'")
        assert cursor.fetchone()


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_for_the_last_room(requester, other_requester, room_type, stay):
    """Two guests submit at the same moment for one remaining room: exactly one wins."""
    Room.objects.filter(number="102").update(is_active=False)
    drafts = [make_booking(user, room_type, stay) for user in (requester, other_requester)]
    for draft in drafts:
        from apps.bookings.models import Document

        Document.objects.create(
            booking=draft,
            type="RECOMMENDATION_LETTER",
            file_ref="x",
            content_type="application/pdf",
            size=1,
            uploaded_by=draft.requester,
        )

    def submit(draft):
        try:
            services.submit(draft.pk, draft.requester)
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(submit, drafts))
    assert results == ["Conflict", "ok"]
    assert Booking.objects.filter(status=Status.PENDING).count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_allotment_of_the_same_room(requester, manager, room_type, stay):
    room = room_type.rooms.first()
    bookings = [make_booking(requester, room_type, stay, Status.CONFIRMED) for _ in range(2)]

    def allot(booking):
        try:
            services.allot(booking.pk, manager, room.pk)
            return "ok"
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(allot, bookings))
    assert results == ["Conflict", "ok"]
    assert Booking.objects.filter(status=Status.ALLOTTED, room=room).count() == 1
