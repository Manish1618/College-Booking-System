import uuid

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, RangeOperators
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Func, Q, Value


class RoomType(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    capacity = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)])
    amenities = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def price_on(self, day):
        """Price per night in force on a date: the latest tariff that started on or before it."""
        tariff = self.tariffs.filter(valid_from__lte=day).order_by("-valid_from").first()
        return tariff.price_per_night if tariff else None


class Tariff(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="tariffs")
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    valid_from = models.DateField()
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-valid_from"]
        constraints = [models.UniqueConstraint(fields=["room_type", "valid_from"], name="one_tariff_per_start_date")]


class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=20, unique=True)
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="rooms")
    floor = models.SmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["number"]

    def __str__(self):
        return self.number


class RoomBlock(models.Model):
    """A room taken out of service for some nights: repairs, deep cleaning, an inspection.

    Dates work like a stay's: starts_on is the first night the room cannot be used, and ends_on is the
    day it is back, so the night before ends_on is the last one blocked.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="blocks")
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_on", "room__number"]
        constraints = [
            models.CheckConstraint(condition=Q(ends_on__gt=F("starts_on")), name="block_ends_after_it_starts"),
            ExclusionConstraint(
                name="no_overlapping_blocks",
                expressions=[
                    ("room", RangeOperators.EQUAL),
                    (Func(F("starts_on"), F("ends_on"), Value("[)"), function="daterange"), RangeOperators.OVERLAPS),
                ],
            ),
        ]

    def __str__(self):
        return f"{self.room} {self.starts_on} to {self.ends_on}"


class RoomPhoto(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room_type = models.ForeignKey(RoomType, on_delete=models.CASCADE, related_name="photos")
    file_ref = models.CharField(max_length=255)  # original, in the private bucket
    variants = models.JSONField(default=dict, blank=True)  # {"480": "room-photos/…webp", …} in the public bucket
    caption = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["room_type"], condition=Q(is_cover=True), name="one_cover_photo_per_room_type"
            )
        ]
