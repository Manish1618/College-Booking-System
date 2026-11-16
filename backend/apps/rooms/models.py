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


class SiteContent(models.Model):
    """The public site's wording, edited by managers on the Website screen. There is one row."""

    SINGLETON_ID = 1

    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_ID, editable=False)
    name = models.CharField(max_length=60, default="College Guesthouse")
    tagline = models.CharField(max_length=80, default="Rooms on campus")
    headline = models.CharField(max_length=80, default="Stay on campus,")
    headline_accent = models.CharField(max_length=40, blank=True, default="quietly.")
    intro = models.TextField(
        max_length=400,
        default=(
            "Pick your dates and a room. The college approves your request, then "
            "you pay online and your room is ready when you arrive."
        ),
    )
    step1_title = models.CharField(max_length=60, default="You send a request")
    step1_body = models.TextField(
        max_length=300, default="Choose dates and a room, and tell us who is staying and why you are visiting."
    )
    step2_title = models.CharField(max_length=60, default="The college approves it")
    step2_body = models.TextField(
        max_length=300,
        default=(
            "Your request goes to the college for approval. You hear back by email, and nothing is charged until then."
        ),
    )
    step3_title = models.CharField(max_length=60, default="You pay, and arrive")
    step3_body = models.TextField(
        max_length=300,
        default="Pay online once approved. Your room is allotted and waiting at the desk when you check in.",
    )
    footer_about = models.TextField(
        max_length=300, default="Rooms on campus for visiting faculty, families of students and guests of the college."
    )
    contact_phone = models.CharField(max_length=40, blank=True)
    contact_email = models.EmailField(blank=True)
    address = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_ID
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=cls.SINGLETON_ID)[0]

    def __str__(self):
        return self.name
