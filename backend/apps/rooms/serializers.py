from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import serializers

from config.serializers import WritesOnlyChangedFields

from .models import Room, RoomPhoto, RoomType, Tariff


class RoomPhotoSerializer(WritesOnlyChangedFields, serializers.ModelSerializer):
    urls = serializers.SerializerMethodField()

    class Meta:
        model = RoomPhoto
        fields = ["id", "caption", "sort_order", "is_cover", "urls"]
        read_only_fields = ["id", "sort_order", "urls"]

    def get_urls(self, photo):
        return {width: default_storage.url(path) for width, path in photo.variants.items()}


class TariffSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tariff
        fields = ["id", "price_per_night", "valid_from", "changed_by", "created_at"]
        read_only_fields = ["id", "changed_by", "created_at"]


class RoomTypeSerializer(WritesOnlyChangedFields, serializers.ModelSerializer):
    photos = RoomPhotoSerializer(many=True, read_only=True)
    price_per_night = serializers.SerializerMethodField()
    room_count = serializers.SerializerMethodField()

    class Meta:
        model = RoomType
        fields = [
            "id",
            "name",
            "description",
            "capacity",
            "amenities",
            "is_active",
            "price_per_night",
            "room_count",
            "photos",
        ]
        read_only_fields = ["id"]

    def get_price_per_night(self, room_type):
        price = room_type.price_on(timezone.localdate())
        return None if price is None else str(price)

    def get_room_count(self, room_type):
        return sum(1 for room in room_type.rooms.all() if room.is_active)


class RoomSerializer(WritesOnlyChangedFields, serializers.ModelSerializer):
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)

    class Meta:
        model = Room
        fields = ["id", "number", "room_type", "room_type_name", "floor", "is_active"]
        read_only_fields = ["id"]
