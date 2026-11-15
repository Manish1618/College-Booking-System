import csv
from datetime import date

from django.http import HttpResponse
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsManager

from . import services


def _range(request):
    """The report's first and last day. Without parameters, the current month."""
    start, end = services.this_month()
    try:
        if value := request.query_params.get("from"):
            start = date.fromisoformat(value)
        if value := request.query_params.get("to"):
            end = date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({"detail": "Give from and to as YYYY-MM-DD."}) from exc
    if end < start:
        raise ValidationError({"to": ["The last day must not be before the first."]})
    if (end - start).days >= services.MAX_DAYS:
        raise ValidationError({"to": ["A report can cover at most a year."]})
    return start, end


class SummaryView(APIView):
    """The dashboard for the guesthouse office and the IT cell: occupancy, revenue, approvals, no-shows."""

    permission_classes = [IsManager]

    def get(self, request):
        return Response(services.summary(*_range(request)))


class DailyExportView(APIView):
    """The same range, one row per day, as a CSV file for a spreadsheet."""

    permission_classes = [IsManager]

    def get(self, request):
        start, end = _range(request)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="guesthouse-report-{start}-to-{end}.csv"'
        response["Cache-Control"] = "no-store"
        response.write("﻿")  # so that Excel reads the file as UTF-8
        writer = csv.writer(response)
        writer.writerow(["Date", "Rooms on offer", "Rooms sold", "Occupancy %", "Received (Rs)", "Refunded (Rs)"])
        for row in services.daily_rows(start, end):
            writer.writerow(
                [
                    row["date"].isoformat(),
                    row["available"],
                    row["sold"],
                    "" if row["percent"] is None else row["percent"],
                    row["received"],
                    row["refunded"],
                ]
            )
        return response
