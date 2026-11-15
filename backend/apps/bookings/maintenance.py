"""Maintenance blocks (PRD F20): a manager takes a room out of service for a date range, with a reason.

A blocked room is not offered for allotment and does not count towards availability. The database
refuses a block that overlaps a stay allotted to the room, and an allotment that overlaps a block.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import IsManager
from apps.audit import services as audit
from apps.rooms.models import Room, RoomBlock, RoomType

from . import services
from .exceptions import Conflict
from .models import Booking, Status

MAX_DAYS = 366


class Overbooked(Conflict):
    """The block is possible, but it would leave bookings of this room type without a room."""

    default_code = "overbooked"


class RoomBlockSerializer(serializers.ModelSerializer):
    room_number = serializers.CharField(source="room.number", read_only=True)
    room_type_name = serializers.CharField(source="room.room_type.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    nights = serializers.SerializerMethodField()
    # True when the caller has been told bookings will be left without a room and wants the block anyway.
    force = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = RoomBlock
        fields = [
            "id", "room", "room_number", "room_type_name", "starts_on", "ends_on", "nights", "reason",
            "created_by_name", "created_at", "force",
        ]  # fmt: skip
        read_only_fields = ["id", "created_at"]

    def get_created_by_name(self, block):
        return str(block.created_by) if block.created_by_id else None

    def get_nights(self, block):
        return (block.ends_on - block.starts_on).days

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Say why the room is out of service.")
        return value


def _check(room, starts_on, ends_on, *, force, existing=None):
    """Everything that must hold before a room is blocked for [starts_on, ends_on). Holds the room
    type's lock, so a booking request cannot take the room's place in the count at the same moment."""
    today = timezone.localdate()
    errors = {}
    if ends_on <= starts_on:
        errors["ends_on"] = ["The room must come back into service after the day it goes out."]
    elif ends_on <= today:
        errors["ends_on"] = ["These dates are already over."]
    elif (ends_on - starts_on).days > MAX_DAYS:
        errors["ends_on"] = ["A block can last at most a year. Deactivate the room if it is gone for longer."]
    if errors:
        raise ValidationError(errors)
    room_type = RoomType.objects.select_for_update().get(pk=room.room_type_id)
    others = RoomBlock.objects.filter(room=room, starts_on__lt=ends_on, ends_on__gt=starts_on)
    if existing is not None:
        others = others.exclude(pk=existing.pk)
    if others.exists():
        raise ValidationError({"starts_on": [f"Room {room.number} is already blocked for some of those dates."]})
    stays = Booking.objects.filter(
        room=room, status__in=[Status.ALLOTTED, Status.CHECKED_IN], check_in__lt=ends_on, check_out__gt=starts_on
    ).order_by("check_in")
    if stays:
        references = ", ".join(stay.reference for stay in stays)
        raise Conflict(
            f"Room {room.number} is allotted to {references} on those dates. "
            "Move that booking to another room first, or start the block after it ends."
        )
    if room.is_active and not force:
        # What is left of the type without this block, on the nights from today on that it would cover.
        spare = services.available_count(room_type, max(starts_on, today), ends_on, without_block=existing)
        if spare < 1:
            raise Overbooked(
                f"Every {room_type.name} room is booked on at least one of those nights. Blocking room "
                f"{room.number} would leave a booking without a room. Move or cancel a booking first, or "
                "confirm that you want to block the room anyway."
            )


def _save(serializer, **extra):
    try:
        with transaction.atomic():
            return serializer.save(**extra)
    except IntegrityError as exc:
        # The database has the last word: a stay was allotted to the room in the moment before saving.
        if "block_not_over_stay" in str(exc):
            raise Conflict("A stay was just allotted to this room on those dates.") from exc
        if "no_overlapping_blocks" in str(exc):
            raise ValidationError({"starts_on": ["This room is already blocked for some of those dates."]}) from exc
        raise


class RoomBlockViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Managers: block a room for repairs, change how long it is out, or put it back into service."""

    serializer_class = RoomBlockSerializer
    permission_classes = [IsManager]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        blocks = RoomBlock.objects.select_related("room__room_type", "created_by")
        if self.action == "list":
            # Current and coming blocks. Those that are over stay in the audit log.
            since = timezone.localdate() - timedelta(days=int(self.request.query_params.get("past_days", 0) or 0))
            blocks = blocks.filter(ends_on__gt=since)
            if room := self.request.query_params.get("room"):
                blocks = blocks.filter(room=room)
        return blocks

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        room = Room.objects.select_related("room_type").get(pk=data["room"].pk)
        _check(room, data["starts_on"], data["ends_on"], force=data.pop("force", False))
        block = _save(serializer, created_by=request.user)
        audit.log("room.blocked", block, actor=request.user, after=self._plain(block), entity="room", entity_id=room.pk)
        return Response(self.get_serializer(block).data, status=201)

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        block = RoomBlock.objects.select_for_update().get(pk=self.get_object().pk)
        serializer = self.get_serializer(block, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "room" in data and data["room"].pk != block.room_id:
            raise ValidationError({"room": ["Remove this block and add one for the other room."]})
        before = self._plain(block)
        _check(
            block.room,
            data.get("starts_on", block.starts_on),
            data.get("ends_on", block.ends_on),
            force=data.pop("force", False),
            existing=block,
        )
        block = _save(serializer)
        audit.log(
            "room.block_changed",
            block,
            actor=request.user,
            before=before,
            after=self._plain(block),
            entity="room",
            entity_id=block.room_id,
        )
        return Response(self.get_serializer(block).data)

    @transaction.atomic
    def destroy(self, request, *args, **kwargs):
        block = self.get_object()
        audit.log(
            "room.unblocked",
            block,
            actor=request.user,
            before=self._plain(block),
            entity="room",
            entity_id=block.room_id,
        )
        block.delete()
        return Response(status=204)

    @staticmethod
    def _plain(block):
        return {
            "room": block.room.number,
            "starts_on": block.starts_on,
            "ends_on": block.ends_on,
            "reason": block.reason,
        }
