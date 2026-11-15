from django.db import transaction
from django.db.models import Max
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.permissions import IsManager, is_manager
from apps.audit import services as audit

from .models import Room, RoomPhoto, RoomType
from .serializers import RoomPhotoSerializer, RoomSerializer, RoomTypeSerializer, TariffSerializer
from .tasks import delete_photo_files, process_room_photo
from .uploads import sniff, store_private


class AuditedMixin:
    """Create/update with an audit entry holding the before and after values."""

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        audit.log(f"{obj._meta.model_name}.created", obj, actor=self.request.user, after=serializer.data)

    @transaction.atomic
    def perform_update(self, serializer):
        before = self.get_serializer(serializer.instance).data
        obj = serializer.save()
        audit.log(f"{obj._meta.model_name}.updated", obj, actor=self.request.user, before=before, after=serializer.data)


class RoomTypeViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Anyone can browse active room types. Managers create and edit them; nothing is hard-deleted."""

    serializer_class = RoomTypeSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None

    def get_permissions(self):
        return [AllowAny()] if self.action in ("list", "retrieve") else [IsManager()]

    def get_queryset(self):
        qs = RoomType.objects.prefetch_related("photos", "rooms", "tariffs")
        return qs if is_manager(self.request) else qs.filter(is_active=True)

    @action(detail=True, methods=["get", "post"])
    def tariffs(self, request, pk=None):
        room_type = self.get_object()
        if request.method == "GET":
            return Response(TariffSerializer(room_type.tariffs.all(), many=True).data)
        serializer = TariffSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if room_type.tariffs.filter(valid_from=serializer.validated_data["valid_from"]).exists():
            raise ValidationError({"valid_from": ["A price already starts on this date."]})
        with transaction.atomic():
            tariff = serializer.save(room_type=room_type, changed_by=request.user)
            audit.log("tariff.created", tariff, actor=request.user, after=TariffSerializer(tariff).data)
        return Response(TariffSerializer(tariff).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], parser_classes=[MultiPartParser, FormParser])
    def photos(self, request, pk=None):
        room_type = self.get_object()
        upload = request.FILES.get("file")
        ext, _ = sniff(upload, allow_pdf=False)
        with transaction.atomic():
            last = room_type.photos.aggregate(m=Max("sort_order"))["m"]
            photo = RoomPhoto.objects.create(
                room_type=room_type,
                file_ref=store_private(upload, "photos/originals", ext),
                caption=request.data.get("caption", "")[:200],
                sort_order=0 if last is None else last + 1,
                is_cover=not room_type.photos.exists(),
                uploaded_by=request.user,
            )
            audit.log("roomphoto.created", photo, actor=request.user, after={"room_type": str(room_type.pk)})
            transaction.on_commit(lambda: process_room_photo.delay(str(photo.pk)))
        return Response(RoomPhotoSerializer(photo).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="photos/reorder")
    def reorder_photos(self, request, pk=None):
        room_type = self.get_object()
        order = [str(i) for i in request.data.get("order", [])]
        photos = {str(p.pk): p for p in room_type.photos.all()}
        if sorted(order) != sorted(photos):
            raise ValidationError({"order": ["List every photo of this room type exactly once."]})
        with transaction.atomic():
            for position, photo_id in enumerate(order):
                RoomPhoto.objects.filter(pk=photo_id).update(sort_order=position)
            audit.log("roomphoto.reordered", room_type, actor=request.user, after={"order": order})
        return Response(RoomPhotoSerializer(RoomPhoto.objects.filter(room_type=room_type), many=True).data)


class RoomPhotoViewSet(viewsets.GenericViewSet):
    """Managers: edit caption, set as cover, replace the image or delete it."""

    queryset = RoomPhoto.objects.all()
    serializer_class = RoomPhotoSerializer
    permission_classes = [IsManager]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def partial_update(self, request, pk=None):
        photo = self.get_object()
        upload = request.FILES.get("file")
        old_ref = None
        with transaction.atomic():
            # Read again under a lock. The resize task publishes its copies under the same lock, so this
            # save cannot write back an older value of them.
            photo = RoomPhoto.objects.select_for_update().get(pk=photo.pk)
            serializer = self.get_serializer(photo, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            if serializer.validated_data.get("is_cover"):
                RoomPhoto.objects.filter(room_type=photo.room_type, is_cover=True).exclude(pk=photo.pk).update(
                    is_cover=False
                )
            if upload:
                ext, _ = sniff(upload, allow_pdf=False)
                old_ref, photo.file_ref = photo.file_ref, store_private(upload, "photos/originals", ext)
            photo = serializer.save(file_ref=photo.file_ref)
            audit.log(
                "roomphoto.updated",
                photo,
                actor=request.user,
                after={**serializer.validated_data, "replaced": bool(upload)},
            )
            if upload:
                transaction.on_commit(lambda: process_room_photo.delay(str(photo.pk)))
        if old_ref:
            delete_photo_files(old_ref, {})
        return Response(self.get_serializer(photo).data)

    def destroy(self, request, pk=None):
        photo = self.get_object()
        file_ref, variants, room_type, was_cover = photo.file_ref, photo.variants, photo.room_type, photo.is_cover
        with transaction.atomic():
            audit.log("roomphoto.deleted", photo, actor=request.user, before={"room_type": str(room_type.pk)})
            photo.delete()
            if was_cover and (first := RoomPhoto.objects.filter(room_type=room_type).first()):
                first.is_cover = True
                first.save(update_fields=["is_cover"])
        delete_photo_files(file_ref, variants)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoomViewSet(AuditedMixin, viewsets.ModelViewSet):
    """Managers only. Rooms are deactivated, not deleted, so past bookings keep their room."""

    queryset = Room.objects.select_related("room_type")
    serializer_class = RoomSerializer
    permission_classes = [IsManager]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
