"""The desk's day (arrivals, guests in house, departures) and the guest register with its exports."""

import csv
from datetime import date

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager
from apps.audit import services as audit
from apps.rooms.models import RoomBlock
from config.pdf import pdf_response, render_pdf

from .models import RegisterEntry, Status
from .serializers import BookingSerializer


class DeskView(APIView):
    """What the desk has to do today."""

    permission_classes = [IsManager]

    def get(self, request):
        from apps.payments.models import Refund  # payments builds on bookings

        from .maintenance import RoomBlockSerializer
        from .views import visible_bookings

        today = timezone.localdate()
        bookings = visible_bookings(request)
        groups = {
            # Yesterday's late arrivals stay on the list until the no-show job closes them.
            "arrivals": bookings.filter(status__in=[Status.CONFIRMED, Status.ALLOTTED], check_in__lte=today),
            "departures": bookings.filter(status=Status.CHECKED_IN, check_out__lte=today),
            "in_house": bookings.filter(status=Status.CHECKED_IN, check_out__gt=today),
        }
        context = {"request": request}
        return Response(
            {
                "date": today,
                **{
                    name: BookingSerializer(group.order_by("check_in", "reference"), many=True, context=context).data
                    for name, group in groups.items()
                },
                "to_allot": bookings.filter(status=Status.CONFIRMED).count(),
                "out_of_service": RoomBlockSerializer(
                    RoomBlock.objects.filter(starts_on__lte=today, ends_on__gt=today).select_related(
                        "room__room_type", "created_by"
                    ),
                    many=True,
                ).data,
                "refunds_due": Refund.objects.filter(status__in=[Refund.State.DUE, Refund.State.FAILED]).count(),
            }
        )


class RegisterEntrySerializer(serializers.ModelSerializer):
    booking_reference = serializers.CharField(source="booking.reference")
    guest_name = serializers.CharField(source="guest.name")
    guest_phone = serializers.CharField(source="guest.phone")
    guest_address = serializers.CharField(source="guest.address")
    id_type = serializers.CharField(source="guest.get_id_type_display")
    room_number = serializers.CharField(source="room.number")
    entered_by_name = serializers.CharField(source="entered_by.__str__")

    class Meta:
        model = RegisterEntry
        fields = [
            "id", "serial_number", "booking", "booking_reference", "guest_name", "guest_phone", "guest_address",
            "id_type", "room_number", "arrival_at", "departure_at", "purpose", "amount_paid", "entered_by_name",
        ]  # fmt: skip


def _day(params, name):
    value = params.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({name: ["Give the date as YYYY-MM-DD."]}) from exc


def register_entries(params):
    """Register entries matching the screen's search box and arrival dates. Returns (entries, filters used)."""
    entries = RegisterEntry.objects.select_related("booking", "guest", "room", "entered_by")
    filters = {}
    if search := (params.get("search") or "").strip():
        filters["search"] = search
        entries = entries.filter(
            Q(guest__name__icontains=search)
            | Q(guest__phone__icontains=search)
            | Q(booking__reference__iexact=search)
            | Q(room__number__iexact=search)
        )
    if start := _day(params, "from"):
        filters["from"] = start
        entries = entries.filter(arrival_at__date__gte=start)
    if end := _day(params, "to"):
        filters["to"] = end
        entries = entries.filter(arrival_at__date__lte=end)
    return entries.order_by("-serial_number"), filters


def _log(request, action, filters, count):
    # The register holds names, phone numbers and addresses, so every look at it is recorded.
    audit.log(action, actor=request.user, entity="register", entity_id="register", after={**filters, "entries": count})


class RegisterView(ListAPIView):
    permission_classes = [IsManager]
    serializer_class = RegisterEntrySerializer

    def get_queryset(self):
        entries, self.filters = register_entries(self.request.query_params)
        return entries

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        _log(request, "register.viewed", self.filters, len(response.data["results"]))
        return response


COLUMNS = [
    ("No.", lambda e: e.serial_number),
    ("Booking", lambda e: e.booking.reference),
    ("Guest", lambda e: e.guest.name),
    ("Phone", lambda e: e.guest.phone),
    ("Address", lambda e: e.guest.address),
    ("ID type", lambda e: e.guest.get_id_type_display()),
    ("Room", lambda e: e.room.number),
    ("Arrival", lambda e: _when(e.arrival_at)),
    ("Departure", lambda e: _when(e.departure_at)),
    ("Purpose", lambda e: e.purpose),
    ("Amount paid (Rs)", lambda e: e.amount_paid),
]


def _when(moment):
    return timezone.localtime(moment).strftime("%d %b %Y %H:%M") if moment else ""


def _cell(value):
    """Spreadsheets run a cell that starts with one of these as a formula. Guests type some of this text."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class RegisterExportView(APIView):
    """The register as a CSV file or a printable PDF, with the same filters as the screen."""

    permission_classes = [IsManager]

    def get(self, request, kind):
        entries, filters = register_entries(request.query_params)
        entries = list(entries.order_by("serial_number"))
        _log(request, f"register.exported_{kind}", filters, len(entries))
        stamp = timezone.localdate().isoformat()
        if kind == "csv":
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="guest-register-{stamp}.csv"'
            response["Cache-Control"] = "private, no-store"
            response.write("﻿")  # lets Excel read names in Indian scripts correctly
            writer = csv.writer(response)
            writer.writerow([title for title, _ in COLUMNS])
            for entry in entries:
                writer.writerow([_cell(value(entry)) for _, value in COLUMNS])
            return response
        pdf = render_pdf(
            "bookings/register.html",
            {
                "site_name": settings.SITE_NAME,
                "titles": [title for title, _ in COLUMNS],
                "rows": [[value(entry) for _, value in COLUMNS] for entry in entries],
                "filters": filters,
                "now": timezone.localtime(),
            },
        )
        return pdf_response(pdf, f"guest-register-{stamp}.pdf")
