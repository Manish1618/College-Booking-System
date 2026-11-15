"""Figures for the dashboard (PRD F19): occupancy, revenue, approvals and no-shows over a date range.

Everything is worked out from the bookings, payments and blocks themselves, so the dashboard can never
disagree with the records behind it. Nothing here names a guest except the list of no-shows, which the
desk already sees.
"""

import calendar
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Q
from django.utils import timezone

from apps.bookings.models import Approval, Booking, DateChange, Status
from apps.payments.models import Payment, Refund
from apps.rooms.models import RoomBlock, RoomType

MAX_DAYS = 366
ZERO = Decimal("0.00")
# A night counts as sold once the stay is paid for, whether the guest is still to come, in house or gone.
SOLD = [Status.CONFIRMED, Status.ALLOTTED, Status.CHECKED_IN, Status.CHECKED_OUT]


def this_month(today=None):
    today = today or timezone.localdate()
    return today.replace(day=1), today.replace(day=calendar.monthrange(today.year, today.month)[1])


def _days(start, end):
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def _percent(part, whole):
    return round(100 * part / whole, 1) if whole else None


def _bounds(start, end):
    """The range as moments in local time: from midnight on the first day to midnight after the last."""
    return (
        timezone.make_aware(datetime.combine(start, time.min)),
        timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min)),
    )


def occupancy(start, end):
    """Room-nights on offer and sold, by day and by room type.

    Rooms on offer are the rooms active today minus those out of service that night. The system does not
    keep a history of when rooms were added or deactivated, so old months use today's list of rooms.
    """
    days = _days(start, end)
    after = end + timedelta(days=1)
    types = list(RoomType.objects.prefetch_related("rooms").order_by("name"))
    rooms = {t.pk: sum(1 for room in t.rooms.all() if room.is_active) for t in types}
    sold = defaultdict(lambda: defaultdict(int))  # room type -> night -> rooms sold
    blocked = defaultdict(lambda: defaultdict(int))
    stays = Booking.objects.filter(status__in=SOLD, check_in__lt=after, check_out__gt=start)
    for room_type, first, last in stays.values_list("room_type", "check_in", "check_out"):
        for night in _days(max(first, start), min(last - timedelta(days=1), end)):
            sold[room_type][night] += 1
    blocks = RoomBlock.objects.filter(room__is_active=True, starts_on__lt=after, ends_on__gt=start)
    for room_type, first, last in blocks.values_list("room__room_type", "starts_on", "ends_on"):
        for night in _days(max(first, start), min(last - timedelta(days=1), end)):
            blocked[room_type][night] += 1

    by_type, daily = [], {day: {"available": 0, "sold": 0} for day in days}
    for room_type in types:
        if not rooms[room_type.pk] and not sold[room_type.pk]:
            continue  # a type with no rooms and no stays in the range has nothing to report
        available = taken = 0
        for day in days:
            on_offer = max(rooms[room_type.pk] - blocked[room_type.pk][day], 0)
            available += on_offer
            taken += sold[room_type.pk][day]
            daily[day]["available"] += on_offer
            daily[day]["sold"] += sold[room_type.pk][day]
        by_type.append(
            {
                "room_type": str(room_type.pk),
                "name": room_type.name,
                "rooms": rooms[room_type.pk],
                "available": available,
                "sold": taken,
                "percent": _percent(taken, available),
            }
        )
    available, taken = sum(t["available"] for t in by_type), sum(t["sold"] for t in by_type)
    summary = {
        "room_nights_available": available,
        "room_nights_sold": taken,
        "percent": _percent(taken, available),
        "by_room_type": by_type,
    }
    return summary, daily


def revenue(start, end):
    """Money received and money returned in the range, by the day it moved and by gateway."""
    since, until = _bounds(start, end)
    labels = dict(Payment.Gateway.choices)
    gateways = defaultdict(lambda: {"received": ZERO, "refunded": ZERO})
    daily = {day: {"received": ZERO, "refunded": ZERO} for day in _days(start, end)}
    payments = Payment.objects.filter(
        status__in=[Payment.State.PAID, Payment.State.REFUNDED], paid_at__gte=since, paid_at__lt=until
    )
    for gateway, amount, paid_at in payments.values_list("gateway", "amount", "paid_at"):
        gateways[gateway]["received"] += amount
        daily[timezone.localtime(paid_at).date()]["received"] += amount
    refunds = Refund.objects.filter(status=Refund.State.PROCESSED, processed_at__gte=since, processed_at__lt=until)
    for gateway, amount, processed_at in refunds.values_list("payment__gateway", "amount", "processed_at"):
        gateways[gateway]["refunded"] += amount
        daily[timezone.localtime(processed_at).date()]["refunded"] += amount
    received = sum((g["received"] for g in gateways.values()), ZERO)
    refunded = sum((g["refunded"] for g in gateways.values()), ZERO)
    owed = Refund.objects.filter(status__in=Refund.OPEN).values_list("amount", flat=True)
    summary = {
        "received": str(received),
        "refunded": str(refunded),
        "net": str(received - refunded),
        "by_gateway": [
            {"gateway": name, "label": labels.get(name, name), **{k: str(v) for k, v in sums.items()}}
            for name, sums in sorted(gateways.items())
        ],
        # Not tied to the range: what is owed back to guests right now and has not been sent.
        "refunds_outstanding": str(sum(owed, ZERO)),
    }
    return summary, daily


def approvals(start, end, now=None):
    """What is waiting for a decision right now, and how decisions went in the range."""
    now = now or timezone.now()
    since, until = _bounds(start, end)
    live = Q(hold_expires_at__isnull=True) | Q(hold_expires_at__gte=now)
    requests = Booking.objects.filter(live, status=Status.PENDING)
    moves = DateChange.objects.filter(status=DateChange.State.PENDING, expires_at__gte=now)
    waiting_since = [
        *requests.exclude(submitted_at__isnull=True).values_list("submitted_at", flat=True),
        *moves.values_list("requested_at", flat=True),
    ]
    decided = {"approved": 0, "rejected": 0, "sent_back": 0}
    hours = []
    made = Approval.objects.filter(decided_at__gte=since, decided_at__lt=until)
    for decision, decided_at, submitted_at in made.values_list("decision", "decided_at", "booking__submitted_at"):
        decided[decision.lower()] += 1
        # A request sent back and submitted again carries its latest submission time, which is after
        # the earlier decision. Those are left out of the timing rather than guessed at.
        if submitted_at and submitted_at <= decided_at:
            hours.append((decided_at - submitted_at).total_seconds() / 3600)
    changed = DateChange.objects.filter(decided_at__gte=since, decided_at__lt=until)
    for status, decided_at, requested_at in changed.values_list("status", "decided_at", "requested_at"):
        decided["rejected" if status == DateChange.State.REJECTED else "approved"] += 1
        hours.append((decided_at - requested_at).total_seconds() / 3600)
    return {
        "waiting": requests.count() + moves.count(),
        "oldest_waiting_since": min(waiting_since) if waiting_since else None,
        "decided": decided,
        "median_hours": round(median(hours), 1) if hours else None,
    }


def no_shows(start, end, limit=50):
    """Bookings in the range whose guests never arrived, newest first."""
    missed = Booking.objects.filter(status=Status.NO_SHOW, check_in__gte=start, check_in__lte=end)
    rows = []
    for booking in missed.select_related("requester", "room_type").prefetch_related("payments")[:limit]:
        kept = sum((p.amount - p.refunded_amount for p in booking.payments.all() if p.received), ZERO)
        rows.append(
            {
                "id": str(booking.pk),
                "reference": booking.reference,
                "requester_name": str(booking.requester),
                "room_type_name": booking.room_type.name,
                "check_in": booking.check_in,
                "nights": booking.nights,
                "kept": str(kept),
            }
        )
    return {"count": missed.count(), "bookings": rows}


def bookings(start, end):
    since, until = _bounds(start, end)
    in_range = Booking.objects.filter(check_in__gte=start, check_in__lte=end)
    return {
        "requested": Booking.objects.filter(submitted_at__gte=since, submitted_at__lt=until).count(),
        "stays": in_range.filter(status__in=SOLD).count(),
        "cancelled": in_range.filter(status=Status.CANCELLED).count(),
    }


def daily_rows(start, end):
    """One row per day: rooms on offer and sold, money in and out."""
    _, rooms = occupancy(start, end)
    _, money = revenue(start, end)
    return [
        {
            "date": day,
            "available": rooms[day]["available"],
            "sold": rooms[day]["sold"],
            "percent": _percent(rooms[day]["sold"], rooms[day]["available"]),
            "received": str(money[day]["received"]),
            "refunded": str(money[day]["refunded"]),
        }
        for day in _days(start, end)
    ]


def summary(start, end):
    rooms, by_day = occupancy(start, end)
    money, money_by_day = revenue(start, end)
    return {
        "from": start,
        "to": end,
        "days": (end - start).days + 1,
        "occupancy": rooms,
        "revenue": money,
        "approvals": approvals(start, end),
        "no_shows": no_shows(start, end),
        "bookings": bookings(start, end),
        "daily": [
            {
                "date": day,
                **by_day[day],
                "percent": _percent(by_day[day]["sold"], by_day[day]["available"]),
                "received": str(money_by_day[day]["received"]),
                "refunded": str(money_by_day[day]["refunded"]),
            }
            for day in _days(start, end)
        ],
    }
