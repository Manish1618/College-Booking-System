import csv
import io
from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bookings.models import Approval, Booking, DateChange, Status
from apps.payments.models import Payment, Refund
from apps.reports import services
from apps.rooms.models import Room, RoomBlock, RoomType, Tariff

from .conftest import make_booking

pytestmark = pytest.mark.django_db


@pytest.fixture
def today():
    return timezone.localdate()


def at(day, hour=10):
    return timezone.make_aware(datetime.combine(day, time(hour)))


def payment(booking, amount, paid_on, gateway="razorpay", status="PAID"):
    return Payment.objects.create(
        booking=booking, gateway=gateway, order_id=f"order_{Payment.objects.count()}", amount=amount, status=status,
        paid_at=at(paid_on) if paid_on else None,
    )  # fmt: skip


def report(client, start, end):
    return client.get("/api/reports/summary", {"from": start.isoformat(), "to": end.isoformat()})


def test_only_the_desk_and_admin_see_reports(clients, today):
    for name in ("anon", "requester", "external", "approver", "manager_no_mfa", "admin_no_mfa"):
        assert clients[name].get("/api/reports/summary").status_code == 403, name
        assert clients[name].get("/api/reports/daily.csv").status_code == 403, name
    for name in ("manager", "admin"):
        data = clients[name].get("/api/reports/summary").data
        assert data["from"] == today.replace(day=1) and data["to"].month == today.month, name
        assert data["days"] == len(data["daily"]) >= 28


def test_report_range_is_validated(clients, today):
    desk = clients["manager"]
    assert desk.get("/api/reports/summary", {"from": "last week"}).status_code == 400
    assert report(desk, today, today - timedelta(days=1)).status_code == 400
    assert "at most a year" in str(report(desk, today, today + timedelta(days=400)).data)
    assert report(desk, today, today).data["days"] == 1
    assert report(desk, today, today + timedelta(days=365)).status_code == 200


def test_occupancy_counts_paid_nights_against_rooms_in_service(clients, requester, room_type, today):
    start, end = today + timedelta(days=10), today + timedelta(days=13)  # four nights, two rooms
    suite = RoomType.objects.create(name="Suite", capacity=3)
    Tariff.objects.create(room_type=suite, price_per_night=3000, valid_from=today - timedelta(days=30))
    Room.objects.create(number="201", room_type=suite)
    make_booking(requester, room_type, (start, start + timedelta(days=2)), Status.CONFIRMED)
    # Runs past the end of the range: only the nights inside it count.
    make_booking(requester, room_type, (end, end + timedelta(days=5)), Status.ALLOTTED)
    make_booking(requester, suite, (start + timedelta(days=1), start + timedelta(days=2)), Status.CHECKED_OUT)
    # Not sold: unpaid, cancelled, or the guest never came.
    for status in (Status.PENDING, Status.APPROVED, Status.CANCELLED, Status.NO_SHOW, Status.EXPIRED):
        make_booking(requester, room_type, (start, start + timedelta(days=1)), status)
    # One room is out of service for one night, so that night has one room fewer on offer.
    RoomBlock.objects.create(
        room=room_type.rooms.get(number="102"), starts_on=start + timedelta(days=2),
        ends_on=start + timedelta(days=3), reason="Leak",
    )  # fmt: skip

    data = report(clients["manager"], start, end).data
    occupancy = data["occupancy"]
    assert (occupancy["room_nights_available"], occupancy["room_nights_sold"], occupancy["percent"]) == (11, 4, 36.4)
    by_type = {t["name"]: (t["rooms"], t["available"], t["sold"], t["percent"]) for t in occupancy["by_room_type"]}
    assert by_type == {"Double": (2, 7, 3, 42.9), "Suite": (1, 4, 1, 25.0)}
    assert [(d["available"], d["sold"]) for d in data["daily"]] == [(3, 1), (3, 2), (2, 0), (3, 1)]
    assert [d["percent"] for d in data["daily"]] == [33.3, 66.7, 0.0, 33.3]
    assert data["bookings"] == {"requested": 0, "stays": 3, "cancelled": 1}
    # A room that is deactivated is not on offer at all.
    Room.objects.filter(number="201").update(is_active=False)
    assert report(clients["manager"], start, end).data["occupancy"]["room_nights_available"] == 7


def test_revenue_is_what_was_received_less_what_was_returned(clients, requester, room_type, today):
    start, end = today - timedelta(days=5), today
    booking = make_booking(requester, room_type, (today, today + timedelta(days=2)), Status.CONFIRMED)
    first = payment(booking, Decimal("2000.00"), start)
    payment(booking, Decimal("1500.00"), today, gateway="mobikwik", status="REFUNDED")
    payment(booking, Decimal("900.00"), start - timedelta(days=1))  # before the range
    payment(booking, Decimal("700.00"), None, status="CREATED")  # never paid
    payment(booking, Decimal("600.00"), None, status="FAILED")
    Refund.objects.create(
        payment=first, amount=Decimal("500.00"), status="PROCESSED", reason="Left early",
        processed_at=at(start + timedelta(days=1)),
    )  # fmt: skip
    Refund.objects.create(
        payment=first, amount=Decimal("100.00"), status="PROCESSED", reason="Old",
        processed_at=at(start - timedelta(days=3)),
    )  # fmt: skip
    Refund.objects.create(payment=first, amount=Decimal("250.00"), status="DUE", reason="Owed")
    Refund.objects.create(payment=first, amount=Decimal("50.00"), status="FAILED", reason="Owed too")

    data = report(clients["admin"], start, end).data
    revenue = data["revenue"]
    assert (revenue["received"], revenue["refunded"], revenue["net"]) == ("3500.00", "500.00", "3000.00")
    assert revenue["refunds_outstanding"] == "300.00"
    assert revenue["by_gateway"] == [
        {"gateway": "mobikwik", "label": "MobiKwik", "received": "1500.00", "refunded": "0.00"},
        {"gateway": "razorpay", "label": "Razorpay", "received": "2000.00", "refunded": "500.00"},
    ]
    daily = {d["date"]: (d["received"], d["refunded"]) for d in data["daily"]}
    assert daily[start] == ("2000.00", "0.00") and daily[start + timedelta(days=1)] == ("0.00", "500.00")
    assert daily[today] == ("1500.00", "0.00")


def test_approvals_waiting_and_how_long_decisions_took(clients, requester, approver, room_type, today):
    now = timezone.now()
    stay = (today + timedelta(days=20), today + timedelta(days=22))
    make_booking(requester, room_type, stay, Status.PENDING, submitted_at=now - timedelta(hours=30),
                 hold_expires_at=now + timedelta(hours=18))  # fmt: skip
    make_booking(requester, room_type, stay, Status.PENDING, submitted_at=now - timedelta(hours=60),
                 hold_expires_at=now - timedelta(hours=12))  # lapsed: no longer waiting  # fmt: skip
    moving = make_booking(requester, room_type, stay, Status.CONFIRMED)
    DateChange.objects.create(
        booking=moving, check_in=stay[0], check_out=stay[1] + timedelta(days=1), price_per_night=1000, amount=3000,
        old_check_in=stay[0], old_check_out=stay[1], old_amount=2000, expires_at=now + timedelta(hours=40),
        requested_by=requester,
    )  # fmt: skip
    DateChange.objects.update(requested_at=now - timedelta(hours=8))

    def decided(decision, hours_waited):
        booking = make_booking(
            requester, room_type, stay, Status(decision), submitted_at=now - timedelta(hours=hours_waited + 1)
        )
        approval = Approval.objects.create(booking=booking, approver=approver, decision=decision)
        Approval.objects.filter(pk=approval.pk).update(decided_at=now - timedelta(hours=1))

    decided("APPROVED", 2)
    decided("APPROVED", 4)
    decided("REJECTED", 30)
    old = make_booking(requester, room_type, stay, Status.SENT_BACK, submitted_at=now - timedelta(days=40))
    Approval.objects.create(booking=old, approver=approver, decision="SENT_BACK")
    Approval.objects.filter(booking=old).update(decided_at=now - timedelta(days=39))  # outside the range

    data = report(clients["manager"], today - timedelta(days=7), today).data["approvals"]
    assert data["waiting"] == 2
    assert abs((data["oldest_waiting_since"] - (now - timedelta(hours=30))).total_seconds()) < 5
    assert data["decided"] == {"approved": 2, "rejected": 1, "sent_back": 0}
    assert data["median_hours"] == 4.0
    earlier = report(clients["manager"], today - timedelta(days=45), today - timedelta(days=30)).data["approvals"]
    assert earlier["decided"] == {"approved": 0, "rejected": 0, "sent_back": 1} and earlier["waiting"] == 2


def test_no_shows_are_listed_with_what_was_kept(clients, requester, room_type, today):
    start = today - timedelta(days=10)
    missed = make_booking(requester, room_type, (start, start + timedelta(days=2)), Status.NO_SHOW)
    paid = payment(missed, Decimal("2000.00"), start - timedelta(days=3))
    Payment.objects.filter(pk=paid.pk).update(refunded_amount=Decimal("500.00"))
    make_booking(requester, room_type, (start - timedelta(days=60), start - timedelta(days=58)), Status.NO_SHOW)
    data = report(clients["manager"], start - timedelta(days=5), today).data["no_shows"]
    assert data["count"] == 1
    assert data["bookings"] == [
        {
            "id": str(missed.pk), "reference": missed.reference, "requester_name": "Requester",
            "room_type_name": "Double", "check_in": start, "nights": 2, "kept": "1500.00",
        }
    ]  # fmt: skip


def test_daily_figures_download_as_csv(clients, requester, room_type, today):
    booking = make_booking(requester, room_type, (today, today + timedelta(days=1)), Status.CHECKED_IN)
    payment(booking, Decimal("1000.00"), today)
    resp = clients["manager"].get(
        "/api/reports/daily.csv", {"from": today.isoformat(), "to": (today + timedelta(days=1)).isoformat()}
    )
    assert resp.status_code == 200 and resp["Content-Type"].startswith("text/csv")
    assert f"guesthouse-report-{today}" in resp["Content-Disposition"] and resp["Cache-Control"] == "no-store"
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    assert rows[0] == ["Date", "Rooms on offer", "Rooms sold", "Occupancy %", "Received (Rs)", "Refunded (Rs)"]
    assert rows[1] == [today.isoformat(), "2", "1", "50.0", "1000.00", "0.00"]
    assert rows[2] == [(today + timedelta(days=1)).isoformat(), "2", "0", "0.0", "0.00", "0.00"]
    assert len(rows) == 3


def test_this_month_covers_the_whole_calendar_month():
    start, end = services.this_month(timezone.datetime(2028, 2, 10).date())
    assert (start.isoformat(), end.isoformat()) == ("2028-02-01", "2028-02-29")
    assert Booking.objects.count() == 0
