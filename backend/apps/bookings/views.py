from datetime import date

from django.db import transaction
from django.db.models import Q
from django.http import Http404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.accounts.permissions import IsAdmin, IsManager, is_manager
from apps.audit import services as audit
from apps.rooms.models import RoomType
from apps.rooms.serializers import RoomSerializer

from . import documents, routing, services
from .models import ApprovalRule, Booking, Document, Status
from .serializers import (
    ApprovalRuleSerializer,
    BookingSerializer,
    BookingWriteSerializer,
    DocumentSerializer,
)


def visible_bookings(request):
    """The only bookings a user can ever load: their own, those routed to them, or all for the desk."""
    user = request.user
    qs = Booking.objects.select_related("requester", "room_type", "room", "student_link").prefetch_related(
        "guests", "documents__guest", "approvals__approver"
    )
    if is_manager(request):
        return qs
    scope = Q(requester=user)
    if user.role == Role.APPROVER:
        scope |= Q(pk__in=routing.routed_to(user).values("pk"))
    return qs.filter(scope)


class AvailabilityView(APIView):
    """Free rooms by type for a date range. Counts only, never guest names."""

    permission_classes = [AllowAny]

    def get(self, request):
        try:
            check_in = date.fromisoformat(request.query_params.get("check_in", ""))
            check_out = date.fromisoformat(request.query_params.get("check_out", ""))
        except ValueError as exc:
            raise ValidationError({"detail": "Give check_in and check_out as YYYY-MM-DD."}) from exc
        services.validate_stay(check_in, check_out)
        nights = (check_out - check_in).days
        results = []
        for room_type in RoomType.objects.filter(is_active=True).prefetch_related("rooms", "tariffs"):
            price = room_type.price_on(check_in)
            results.append(
                {
                    "room_type": str(room_type.pk),
                    "available": services.available_count(room_type, check_in, check_out) if price is not None else 0,
                    "price_per_night": None if price is None else str(price),
                    "amount": None if price is None else str(price * nights),
                }
            )
        return Response({"check_in": check_in, "check_out": check_out, "nights": nights, "results": results})


class BookingViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ["get", "post", "patch", "head", "options"]
    serializer_class = BookingSerializer

    def get_queryset(self):
        qs = visible_bookings(self.request)
        if self.action != "list":
            return qs
        params = self.request.query_params
        if statuses := params.get("status"):
            qs = qs.filter(status__in=statuses.split(","))
        scope = params.get("scope")
        if scope == "mine":
            qs = qs.filter(requester=self.request.user)
        elif scope == "approvals":
            qs = qs.filter(status=Status.PENDING).exclude(requester=self.request.user)
            if self.request.user.role == Role.APPROVER:
                qs = qs.filter(pk__in=routing.routed_to(self.request.user).values("pk"))
        elif scope == "desk":
            qs = qs.exclude(status=Status.DRAFT)
        return qs

    def _read(self, booking, status_code=200):
        booking = visible_bookings(self.request).get(pk=booking.pk)
        return Response(BookingSerializer(booking, context=self.get_serializer_context()).data, status=status_code)

    def _own_editable(self):
        booking = self.get_object()
        if booking.requester_id != self.request.user.pk:
            raise PermissionDenied()
        if booking.status not in (Status.DRAFT, Status.SENT_BACK):
            raise ValidationError({"detail": "This request can no longer be edited."})
        return booking

    def create(self, request, *args, **kwargs):
        serializer = BookingWriteSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            booking = serializer.save()
            audit.log("booking.created", booking, actor=request.user, after={"reference": booking.reference})
        return self._read(booking, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        booking = self._own_editable()
        serializer = BookingWriteSerializer(
            booking, data=request.data, partial=True, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            serializer.save()
            audit.log("booking.edited", booking, actor=request.user, after=request.data)
        return self._read(booking)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def documents(self, request, pk=None):
        booking = self._own_editable()
        document = documents.attach(
            booking, request.user, request.data.get("type"), request.FILES.get("file"), request.data.get("guest")
        )
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        booking = self._own_editable()
        return self._read(services.submit(booking.pk, request.user))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        return self._read(services.cancel(booking.pk, request.user, by_staff=is_manager(request)))

    @action(detail=True, methods=["post"], parser_classes=[JSONParser])
    def decide(self, request, pk=None):
        booking = self.get_object()
        if request.user.role == Role.ADMIN and not is_manager(request):
            raise PermissionDenied("Two-step verification is required.")
        return self._read(
            services.decide(booking.pk, request.user, request.data.get("decision"), request.data.get("comment"))
        )

    @action(detail=True, methods=["get"], url_path="free-rooms", permission_classes=[IsManager])
    def free_rooms(self, request, pk=None):
        return Response(
            RoomSerializer(services.free_rooms(self.get_object()).select_related("room_type"), many=True).data
        )

    @action(detail=True, methods=["post"], permission_classes=[IsManager])
    def allot(self, request, pk=None):
        booking = self.get_object()
        return self._read(services.allot(booking.pk, request.user, request.data.get("room")))


class DocumentDownloadView(APIView):
    def get(self, request, pk):
        document = Document.objects.select_related("booking").filter(pk=pk).first()
        # Same 404 whether the document is missing or simply not yours.
        if document is None or not documents.can_view(request, document, manager=is_manager(request)):
            raise Http404
        return documents.serve(request, document)


class ApprovalRuleViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Super admin: route stay categories to approvers."""

    queryset = ApprovalRule.objects.select_related("approver")
    serializer_class = ApprovalRuleSerializer
    permission_classes = [IsAdmin]
    pagination_class = None

    @transaction.atomic
    def perform_create(self, serializer):
        rule = serializer.save()
        audit.log("approvalrule.created", rule, actor=self.request.user, after=serializer.data)

    @transaction.atomic
    def perform_destroy(self, rule):
        audit.log("approvalrule.deleted", rule, actor=self.request.user, before=ApprovalRuleSerializer(rule).data)
        rule.delete()
