import uuid

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


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
