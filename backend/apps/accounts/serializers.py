from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django_otp import devices_for_user
from rest_framework import serializers

from .models import STAFF_ROLES, User
from .otp import normalise_identifier


class MeSerializer(serializers.ModelSerializer):
    mfa = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email", "phone", "role", "department", "mfa"]
        read_only_fields = ["id", "email", "phone", "role", "mfa"]

    def get_mfa(self, user):
        request = self.context["request"]
        return {
            "required": settings.STAFF_MFA_REQUIRED and user.role in STAFF_ROLES,
            "enrolled": any(True for _ in devices_for_user(user, confirmed=True)),
            "verified": getattr(request.user, "otp_device", None) is not None,
        }


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "name", "email", "phone", "role", "department", "is_active", "date_joined", "last_login"]
        read_only_fields = ["id", "date_joined", "last_login"]

    def _unused(self, field, value):
        """The stored form can differ from what was typed, so uniqueness is checked on the stored form."""
        taken = User.objects.filter(**{field: value})
        if self.instance:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError(f"Another user already has this {field}.")
        return value

    def validate_email(self, value):
        return self._unused("email", value.lower()) if value else None

    def validate_phone(self, value):
        """Stores the number the way sign-in looks it up, so the person reaches this account."""
        if not value:
            return None
        try:
            kind, number = normalise_identifier(value)
        except DjangoValidationError as error:
            raise serializers.ValidationError("Enter a valid phone number.") from error
        if kind != "phone":
            raise serializers.ValidationError("Enter a valid phone number.")
        return self._unused("phone", number)

    def validate(self, attrs):
        if not self.instance and not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError("An email or phone number is required.")
        return attrs

    def create(self, validated):
        return User.objects.create_user(**validated)
