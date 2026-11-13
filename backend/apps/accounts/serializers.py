from django.conf import settings
from django_otp import devices_for_user
from rest_framework import serializers

from .models import STAFF_ROLES, User


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

    def validate_email(self, value):
        return value.lower() if value else None

    def validate(self, attrs):
        if not self.instance and not attrs.get("email") and not attrs.get("phone"):
            raise serializers.ValidationError("An email or phone number is required.")
        return attrs

    def create(self, validated):
        return User.objects.create_user(**validated)
