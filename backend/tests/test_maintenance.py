import threading
from datetime import timedelta

import pytest
from django.db import IntegrityError, close_old_connections, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings import services
from apps.bookings.models import Booking, Status
from apps.rooms.models import Room, RoomBlock

from .conftest import make_booking

pytestmark = pytest.mark.django_db


@pytest.fixture
def today():
    return timezone.localdate()


def block(client, room, start, end, reason="Plumbing repair", **extra):
    data = {"room": str(room.pk), "starts_on": start.isoformat(), "ends_on": end.isoformat(), "reason": reason}
    return client.post("/api/room-blocks", {**data, **extra}, format="json")


def availability(client, room_type, stay):
    data = client.get("/api/availability", {"check_in": stay[0], "check_out": stay[1]}).data
    return next(r["available"] for r in data["results"] if r["room_type"] == str(room_type.pk))


def test_blocked_room_is_not_sold_or_offered_for_allotment(clients, requester, room_type, stay, today):
    desk = clients["manager"]
    room = room_type.rooms.get(number="101")
    assert availability(desk, room_type, stay) == 2
    resp = block(desk, room, stay[0], stay[1] + timedelta(days=3))
    assert resp.status_code == 201, resp.data
    assert (resp.data["room_number"], resp.data["nights"], resp.data["reason"]) == ("101", 5, "Plumbing repair")
    assert resp.data["created_by_name"] == "Manager"
    entry = AuditLog.objects.get(action="room.blocked")
    assert (entry.entity, entry.entity_id, entry.after["reason"]) == ("room", str(room.pk), "Plumbing repair")

    # One room of two is left on those nights, and all of them before and after the block.
    assert availability(desk, room_type, stay) == 1
    before = (stay[0] - timedelta(days=2), stay[0])
    assert availability(desk, room_type, before) == 2
    assert availability(desk, room_type, (stay[1] + timedelta(days=3), stay[1] + timedelta(days=5))) == 2

    booking = make_booking(requester, room_type, stay, Status.CONFIRMED)
    assert [r["number"] for r in desk.get(f"/api/bookings/{booking.pk}/free-rooms").data] == ["102"]
    resp = desk.post(f"/api/bookings/{booking.pk}/allot", {"room": str(room.pk)}, format="json")
    assert resp.status_code == 409 and "out of service" in resp.data["detail"]
    assert (
        desk.post(f"/api/bookings/{booking.pk}/allot", {"room": str(room_type.rooms.get(number="102").pk)}).data[
            "room_number"
        ]
        == "102"
    )

    listed = desk.get("/api/room-blocks").data
    assert [b["room_number"] for b in listed] == ["101"]
    assert desk.get("/api/room-blocks", {"room": str(room_type.rooms.get(number="102").pk)}).data == []


def test_block_needs_a_reason_and_sensible_dates(clients, room_type, today):
    desk, room = clients["manager"], room_type.rooms.get(number="101")
    assert block(desk, room, today, today + timedelta(days=2), reason="  ").status_code == 400
    assert "ends_on" in block(desk, room, today + timedelta(days=2), today + timedelta(days=2)).data
    assert "already over" in str(block(desk, room, today - timedelta(days=5), today - timedelta(days=1)).data)
    assert "at most a year" in str(block(desk, room, today, today + timedelta(days=400)).data)
    assert block(desk, room, today, today + timedelta(days=3)).status_code == 201
    # A room cannot be blocked twice for the same night, but a block can follow another directly.
    resp = block(desk, room, today + timedelta(days=2), today + timedelta(days=6))
    assert resp.status_code == 400 and "already blocked" in str(resp.data)
    assert block(desk, room, today + timedelta(days=3), today + timedelta(days=6)).status_code == 201
    assert RoomBlock.objects.count() == 2


def test_only_the_desk_manages_blocks(clients, room_type, today):
    room = room_type.rooms.get(number="101")
    made = block(clients["manager"], room, today, today + timedelta(days=2)).data
    for name in ("anon", "requester", "external", "approver", "manager_no_mfa", "admin_no_mfa"):
        assert clients[name].get("/api/room-blocks").status_code == 403, name
        assert block(clients[name], room, today + timedelta(days=9), today + timedelta(days=10)).status_code == 403, (
            name
        )
        assert clients[name].patch(f"/api/room-blocks/{made['id']}", {"reason": "x"}).status_code == 403, name
        assert clients[name].delete(f"/api/room-blocks/{made['id']}").status_code == 403, name
    assert clients["admin"].get("/api/room-blocks").status_code == 200
    assert RoomBlock.objects.count() == 1


def test_room_with_an_allotted_stay_cannot_be_blocked_over_it(clients, requester, room_type, stay):
    desk, room = clients["manager"], room_type.rooms.get(number="101")
    booking = make_booking(requester, room_type, stay, Status.ALLOTTED, room=room)
    resp = block(desk, room, stay[0] + timedelta(days=1), stay[1] + timedelta(days=2))
    assert resp.status_code == 409 and booking.reference in resp.data["detail"]
    # The day the guest leaves is free again, and so is every night before they arrive.
    assert block(desk, room, stay[1], stay[1] + timedelta(days=2)).status_code == 201
    assert block(desk, room, stay[0] - timedelta(days=3), stay[0]).status_code == 201
    # Once the stay moves to another room, the first one can be blocked.
    other = room_type.rooms.get(number="102")
    assert desk.post(f"/api/bookings/{booking.pk}/allot", {"room": str(other.pk)}).status_code == 200
    assert block(desk, room, stay[0], stay[1]).status_code == 201


def test_block_that_would_leave_a_booking_without_a_room_needs_confirming(clients, requester, room_type, stay):
    desk, room = clients["manager"], room_type.rooms.get(number="101")
    make_booking(requester, room_type, stay, Status.CONFIRMED)
    make_booking(requester, room_type, stay, Status.CONFIRMED)
    resp = block(desk, room, stay[0], stay[1])
    assert resp.status_code == 409 and resp.data["code"] == "overbooked"
    assert RoomBlock.objects.count() == 0
    # Nights that are not full can be blocked without being asked.
    assert block(desk, room, stay[1], stay[1] + timedelta(days=1)).status_code == 201
    # A burst pipe does not wait: the manager can go ahead knowing a booking has to be moved.
    assert block(desk, room, stay[0], stay[1], force=True).status_code == 201
    assert availability(desk, room_type, stay) == 0


def test_block_can_be_extended_shortened_and_removed(clients, requester, room_type, stay):
    desk, room = clients["manager"], room_type.rooms.get(number="101")
    made = block(desk, room, stay[0], stay[1]).data
    url = f"/api/room-blocks/{made['id']}"
    longer = (stay[1] + timedelta(days=4)).isoformat()
    resp = desk.patch(url, {"ends_on": longer, "reason": "Waiting for parts"}, format="json")
    assert resp.status_code == 200 and (resp.data["ends_on"], resp.data["reason"]) == (longer, "Waiting for parts")
    change = AuditLog.objects.get(action="room.block_changed")
    assert change.before["ends_on"] == stay[1].isoformat() and change.after["ends_on"] == longer

    # It cannot be stretched over a stay that is allotted to the room, or moved to another room.
    later = (stay[1] + timedelta(days=6), stay[1] + timedelta(days=8))
    make_booking(requester, room_type, later, Status.ALLOTTED, room=room)
    assert desk.patch(url, {"ends_on": (stay[1] + timedelta(days=7)).isoformat()}, format="json").status_code == 409
    other = room_type.rooms.get(number="102")
    assert desk.patch(url, {"room": str(other.pk)}, format="json").status_code == 400
    # Changing only the reason of a block on fully booked nights is not a new overbooking.
    make_booking(requester, room_type, stay, Status.CONFIRMED)
    assert desk.patch(url, {"reason": "Parts arrived"}, format="json").status_code == 200

    assert desk.delete(url).status_code == 204
    assert RoomBlock.objects.count() == 0 and AuditLog.objects.filter(action="room.unblocked").count() == 1
    assert availability(desk, room_type, (stay[1], stay[1] + timedelta(days=2))) == 2


def test_putting_a_room_back_keeps_the_nights_it_was_already_out(clients, room_type, manager, today):
    """Otherwise last week's occupancy would change the moment a repair is finished."""
    desk, room = clients["manager"], room_type.rooms.get(number="101")
    started = RoomBlock.objects.create(
        room=room, starts_on=today - timedelta(days=2), ends_on=today + timedelta(days=3), reason="Leak",
        created_by=manager,
    )  # fmt: skip
    report = lambda: desk.get(  # noqa: E731
        "/api/reports/summary", {"from": today - timedelta(days=2), "to": today + timedelta(days=2)}
    ).data["daily"]
    assert [day["available"] for day in report()] == [1, 1, 1, 1, 1]

    assert desk.delete(f"/api/room-blocks/{started.pk}").status_code == 204
    started.refresh_from_db()
    assert started.ends_on == today
    assert [day["available"] for day in report()] == [1, 1, 2, 2, 2]
    assert desk.get("/api/room-blocks").data == [] and desk.get("/api/desk").data["out_of_service"] == []
    entry = AuditLog.objects.get(action="room.unblocked")
    assert entry.before["ends_on"] == (today + timedelta(days=3)).isoformat()
    assert entry.after["ends_on"] == today.isoformat()
    # Asking again changes nothing, and a block that begins today has no nights to keep.
    assert desk.delete(f"/api/room-blocks/{started.pk}").status_code == 204
    assert AuditLog.objects.filter(action="room.unblocked").count() == 1
    from_today = block(desk, room, today, today + timedelta(days=2)).data
    assert desk.delete(f"/api/room-blocks/{from_today['id']}").status_code == 204
    assert list(RoomBlock.objects.values_list("pk", flat=True)) == [started.pk]


def test_blocks_on_inactive_rooms_do_not_reduce_availability_twice(clients, room_type, stay):
    desk, room = clients["manager"], room_type.rooms.get(number="101")
    Room.objects.filter(pk=room.pk).update(is_active=False)
    assert availability(desk, room_type, stay) == 1
    assert block(desk, room, stay[0], stay[1]).status_code == 201
    assert availability(desk, room_type, stay) == 1


def test_desk_lists_rooms_out_of_service_today(clients, room_type, today):
    desk = clients["manager"]
    block(desk, room_type.rooms.get(number="101"), today - timedelta(days=1), today + timedelta(days=1))
    block(desk, room_type.rooms.get(number="102"), today + timedelta(days=1), today + timedelta(days=3))
    out = desk.get("/api/desk").data["out_of_service"]
    assert [(b["room_number"], b["reason"]) for b in out] == [("101", "Plumbing repair")]


def test_database_itself_keeps_stays_and_blocks_apart(requester, manager, room_type, stay):
    """The rule holds even for code that skips the services, such as the Django admin or a script."""
    room = room_type.rooms.get(number="101")
    RoomBlock.objects.create(room=room, starts_on=stay[0], ends_on=stay[1], reason="Painting", created_by=manager)
    booking = make_booking(requester, room_type, stay, Status.CONFIRMED)
    with pytest.raises(IntegrityError, match="room_not_blocked"), transaction.atomic():
        Booking.objects.filter(pk=booking.pk).update(room=room, status=Status.ALLOTTED)
    with pytest.raises(IntegrityError, match="no_overlapping_blocks"), transaction.atomic():
        RoomBlock.objects.create(room=room, starts_on=stay[0], ends_on=stay[1], reason="Again", created_by=manager)

    other = room_type.rooms.get(number="102")
    Booking.objects.filter(pk=booking.pk).update(room=other, status=Status.ALLOTTED)
    with pytest.raises(IntegrityError, match="block_not_over_stay"), transaction.atomic():
        RoomBlock.objects.create(room=other, starts_on=stay[0], ends_on=stay[1], reason="Late", created_by=manager)
    # A stay that has ended, or was cancelled, no longer stands in the way.
    Booking.objects.filter(pk=booking.pk).update(status=Status.CHECKED_OUT)
    RoomBlock.objects.create(room=other, starts_on=stay[0], ends_on=stay[1], reason="After", created_by=manager)


@pytest.mark.django_db(transaction=True)
def test_concurrent_allotment_and_block_of_the_same_room(requester, manager, room_type, stay):
    """An allotment and a block for the same room on the same nights: exactly one of them goes through."""
    room = room_type.rooms.get(number="101")
    booking = make_booking(requester, room_type, stay, Status.CONFIRMED)
    barrier = threading.Barrier(2)
    results = {}

    def allot():
        try:
            barrier.wait(timeout=5)
            services.allot(booking.pk, manager, room.pk)
            results["allot"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["allot"] = type(exc).__name__
        finally:
            close_old_connections()

    def block_room():
        try:
            barrier.wait(timeout=5)
            with transaction.atomic():
                RoomBlock.objects.create(
                    room=room, starts_on=stay[0], ends_on=stay[1], reason="Leak", created_by=manager
                )
            results["block"] = "ok"
        except Exception as exc:  # noqa: BLE001
            results["block"] = type(exc).__name__
        finally:
            close_old_connections()

    threads = [threading.Thread(target=allot), threading.Thread(target=block_room)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results.values()) in (["Conflict", "ok"], ["IntegrityError", "ok"]), results
    allotted = Booking.objects.get(pk=booking.pk).status == Status.ALLOTTED
    assert allotted != RoomBlock.objects.exists()
