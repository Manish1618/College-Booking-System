import secrets
import uuid

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models import F, Func, Q, Value

from apps.rooms.models import Room, RoomType

REFERENCE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I


def new_reference():
    return "GH-" + "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(8))


class Status(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING = "PENDING", "Pending approval"
    SENT_BACK = "SENT_BACK", "Sent back"
    APPROVED = "APPROVED", "Approved, awaiting payment"
    REJECTED = "REJECTED", "Rejected"
    CONFIRMED = "CONFIRMED", "Confirmed"
    ALLOTTED = "ALLOTTED", "Room allotted"
    CHECKED_IN = "CHECKED_IN", "Checked in"
    CHECKED_OUT = "CHECKED_OUT", "Checked out"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"
    NO_SHOW = "NO_SHOW", "No-show"


class Category(models.TextChoices):
    OFFICIAL = "OFFICIAL", "Official stay"
    PERSONAL = "PERSONAL", "Personal stay"


class Booking(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=12, unique=True, default=new_reference, editable=False)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bookings")
    room_type = models.ForeignKey(RoomType, on_delete=models.PROTECT, related_name="bookings")
    room = models.ForeignKey(Room, null=True, blank=True, on_delete=models.PROTECT, related_name="bookings")
    check_in = models.DateField()
    check_out = models.DateField()
    category = models.CharField(max_length=10, choices=Category.choices)
    purpose = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    # Snapshot taken when the request is made; later tariff changes never alter it.
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # Deadline of the current hold: approval deadline while PENDING/SENT_BACK, payment deadline while APPROVED.
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["room_type", "check_in", "check_out"])]
        constraints = [
            models.CheckConstraint(condition=Q(check_out__gt=F("check_in")), name="check_out_after_check_in"),
            # The no-double-booking rule from the PRD: one room cannot hold two live stays on the same night.
            ExclusionConstraint(
                name="no_overlap",
                expressions=[
                    ("room", RangeOperators.EQUAL),
                    (Func(F("check_in"), F("check_out"), Value("[)"), function="daterange"), RangeOperators.OVERLAPS),
                ],
                condition=Q(room__isnull=False) & Q(status__in=["ALLOTTED", "CHECKED_IN"]),
            ),
        ]

    def __str__(self):
        return self.reference

    @property
    def nights(self):
        return (self.check_out - self.check_in).days


class StudentLink(models.Model):
    """Personal stays: the student whose guardian is visiting."""

    class RecordCheck(models.TextChoices):
        NOT_AVAILABLE = "NOT_AVAILABLE", "Student records not connected"
        MATCHED = "MATCHED", "Matches student records"
        MISMATCH = "MISMATCH", "Does not match student records"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name="student_link")
    student_name = models.CharField(max_length=150)
    roll_number = models.CharField(max_length=40)
    programme = models.CharField(max_length=120)
    year = models.PositiveSmallIntegerField()
    relationship = models.CharField(max_length=60)
    record_check = models.CharField(max_length=14, choices=RecordCheck.choices, default=RecordCheck.NOT_AVAILABLE)


class Document(models.Model):
    class Type(models.TextChoices):
        RECOMMENDATION_LETTER = "RECOMMENDATION_LETTER", "Recommendation letter"
        GUEST_ID = "GUEST_ID", "Guest ID"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="documents")
    type = models.CharField(max_length=24, choices=Type.choices)
    file_ref = models.CharField(max_length=255)  # key in the private bucket
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class Guest(models.Model):
    class IdType(models.TextChoices):
        AADHAAR = "AADHAAR", "Aadhaar"
        PASSPORT = "PASSPORT", "Passport"
        DRIVING_LICENCE = "DRIVING_LICENCE", "Driving licence"
        VOTER_ID = "VOTER_ID", "Voter ID"
        PAN = "PAN", "PAN card"
        OTHER = "OTHER", "Other government ID"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="guests")
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=15)
    address = models.TextField()
    id_type = models.CharField(max_length=16, choices=IdType.choices)
    id_document = models.OneToOneField(Document, null=True, blank=True, on_delete=models.SET_NULL, related_name="guest")
    id_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]


class Approval(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        SENT_BACK = "SENT_BACK", "Sent back"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="approvals")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decision = models.CharField(max_length=10, choices=Decision.choices)
    comment = models.TextField(blank=True)
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["decided_at"]


class ApprovalRule(models.Model):
    """Routing: which approver decides which stay category. With no rule for a category, any approver may."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.CharField(max_length=10, choices=Category.choices)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="approval_rules")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["category", "approver"], name="one_rule_per_category_approver")]


class RegisterEntry(models.Model):
    """The guest register. Entries are created at check-in (Phase 3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    serial_number = models.PositiveIntegerField(unique=True)
    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="register_entries")
    guest = models.ForeignKey(Guest, on_delete=models.PROTECT, related_name="register_entries")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="register_entries")
    arrival_at = models.DateTimeField()
    departure_at = models.DateTimeField(null=True, blank=True)
    purpose = models.TextField()
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["serial_number"]
