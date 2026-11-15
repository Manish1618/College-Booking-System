from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.permissions import is_manager
from apps.rooms.models import RoomType

from . import routing, services
from .models import Approval, ApprovalRule, Booking, Category, Document, Guest, Status, StudentLink
from .state import TRANSITIONS


class GuestSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(required=False)
    has_id_document = serializers.SerializerMethodField()

    class Meta:
        model = Guest
        fields = ["id", "name", "phone", "address", "id_type", "id_document", "has_id_document", "id_verified"]
        read_only_fields = ["id_document", "id_verified"]

    def get_has_id_document(self, guest):
        return guest.id_document_id is not None


class StudentLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentLink
        fields = ["student_name", "roll_number", "programme", "year", "relationship", "record_check"]
        read_only_fields = ["record_check"]

    def validate_year(self, value):
        if not 1 <= value <= 8:
            raise serializers.ValidationError("Enter the student's current year of study.")
        return value


class DocumentSerializer(serializers.ModelSerializer):
    guest = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = ["id", "type", "guest", "content_type", "size", "created_at"]

    def get_guest(self, doc):
        guest = getattr(doc, "guest", None)
        return str(guest.pk) if guest else None


class ApprovalSerializer(serializers.ModelSerializer):
    approver_name = serializers.CharField(source="approver.__str__", read_only=True)

    class Meta:
        model = Approval
        fields = ["id", "decision", "comment", "approver_name", "decided_at"]


class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "name", "email", "phone", "department", "role"]


class BookingSerializer(serializers.ModelSerializer):
    """Read shape. What a viewer sees and may do depends on their role and the booking's state."""

    status_label = serializers.CharField(source="get_status_display", read_only=True)
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    room_number = serializers.CharField(source="room.number", read_only=True, default=None)
    nights = serializers.IntegerField(read_only=True)
    requester = PersonSerializer(read_only=True)
    guests = serializers.SerializerMethodField()
    student_link = serializers.SerializerMethodField()
    documents = DocumentSerializer(many=True, read_only=True)
    approvals = ApprovalSerializer(many=True, read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id", "reference", "status", "status_label", "category", "purpose", "check_in", "check_out", "nights",
            "room_type", "room_type_name", "room", "room_number", "price_per_night", "amount", "hold_expires_at",
            "submitted_at", "created_at", "requester", "guests", "student_link", "documents", "approvals", "actions",
        ]  # fmt: skip

    def _viewer(self, booking):
        request = self.context["request"]
        return request, booking.requester_id == request.user.pk, is_manager(request)

    def get_guests(self, booking):
        _, owner, manager = self._viewer(booking)
        guests = booking.guests.all()
        if owner or manager:
            return GuestSerializer(guests, many=True).data
        # Approvers decide on the letter or student link; they do not need contact details or IDs.
        return [{"id": str(g.pk), "name": g.name} for g in guests]

    def get_student_link(self, booking):
        link = getattr(booking, "student_link", None)
        return StudentLinkSerializer(link).data if link else None

    def get_actions(self, booking):
        request, owner, manager = self._viewer(booking)
        allowed = TRANSITIONS[booking.status]
        return {
            "edit": owner and booking.status in (Status.DRAFT, Status.SENT_BACK),
            "submit": owner and Status.PENDING in allowed,
            "cancel": (owner or manager) and Status.CANCELLED in allowed,
            "decide": booking.status == Status.PENDING
            and routing.can_decide(request.user, booking)
            and (request.user.role == "APPROVER" or manager),
            "pay": owner and booking.status == Status.APPROVED,
            "allot": manager and Status.ALLOTTED in allowed,
        }


class BookingWriteSerializer(serializers.ModelSerializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.filter(is_active=True))
    guests = GuestSerializer(many=True, required=False)
    student_link = StudentLinkSerializer(required=False, allow_null=True)

    class Meta:
        model = Booking
        fields = ["room_type", "check_in", "check_out", "category", "purpose", "guests", "student_link"]

    def validate(self, attrs):
        get = lambda name: attrs.get(name, getattr(self.instance, name, None))  # noqa: E731
        services.validate_stay(get("check_in"), get("check_out"))
        guests = attrs.get("guests")
        if guests is not None and len(guests) > get("room_type").capacity:
            raise serializers.ValidationError(
                {"guests": [f"This room type takes at most {get('room_type').capacity} guests."]}
            )
        if get("category") == Category.PERSONAL and not self.instance and not attrs.get("student_link"):
            raise serializers.ValidationError({"student_link": ["Enter the student's details for a personal stay."]})
        # The price is a snapshot: it is quoted when the booking is made, and again only if the stay itself changes.
        stay = ("room_type", "check_in", "check_out")
        if not self.instance or any(n in attrs and attrs[n] != getattr(self.instance, n) for n in stay):
            attrs["price_per_night"], attrs["amount"] = services.quote(*(get(n) for n in stay))
        return attrs

    @transaction.atomic
    def create(self, validated):
        guests = validated.pop("guests", [])
        link = validated.pop("student_link", None)
        booking = Booking.objects.create(requester=self.context["request"].user, **validated)
        self._sync(booking, guests, link)
        return booking

    @transaction.atomic
    def update(self, booking, validated):
        guests = validated.pop("guests", None)
        link = validated.pop("student_link", None)
        for field, value in validated.items():
            setattr(booking, field, value)
        booking.save()
        self._sync(booking, guests, link)
        return booking

    def _sync(self, booking, guests, link):
        if guests is not None:
            existing = {g.pk: g for g in booking.guests.all()}
            kept = set()
            for data in guests:
                guest = existing.get(data.pop("id", None))
                if guest:
                    for field, value in data.items():
                        setattr(guest, field, value)
                    guest.save()
                else:
                    guest = Guest.objects.create(booking=booking, **data)
                kept.add(guest.pk)
            for pk, guest in existing.items():
                if pk not in kept:
                    from .documents import remove_document

                    if guest.id_document:
                        remove_document(guest.id_document)
                    guest.delete()
        if booking.category == Category.PERSONAL and link:
            StudentLink.objects.update_or_create(booking=booking, defaults=link)
        elif booking.category == Category.OFFICIAL:
            StudentLink.objects.filter(booking=booking).delete()


class ApprovalRuleSerializer(serializers.ModelSerializer):
    approver_name = serializers.CharField(source="approver.__str__", read_only=True)

    class Meta:
        model = ApprovalRule
        fields = ["id", "category", "approver", "approver_name"]

    def validate_approver(self, user):
        if user.role != "APPROVER":
            raise serializers.ValidationError("Give this user the approver role first.")
        return user
