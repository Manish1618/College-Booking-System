import pytest
from django.core.files.storage import default_storage, storages
from PIL import Image

from apps.audit.models import AuditLog
from apps.rooms.models import RoomPhoto, RoomType

from .conftest import PDF, client_for, png_bytes, upload

pytestmark = pytest.mark.django_db


def test_manager_creates_room_type_room_and_price(manager):
    desk = client_for(manager)
    resp = desk.post(
        "/api/room-types",
        {"name": "Suite", "capacity": 3, "amenities": ["AC", "TV"], "description": "Big"},
        format="json",
    )
    assert resp.status_code == 201
    type_id = resp.data["id"]
    assert resp.data["price_per_night"] is None
    assert (
        desk.post(
            f"/api/room-types/{type_id}/tariffs", {"price_per_night": "2500", "valid_from": "2026-01-01"}, format="json"
        ).status_code
        == 201
    )
    assert (
        desk.post(
            f"/api/room-types/{type_id}/tariffs", {"price_per_night": "2600", "valid_from": "2026-01-01"}, format="json"
        ).status_code
        == 400
    )
    assert (
        desk.post(
            f"/api/room-types/{type_id}/tariffs", {"price_per_night": "-1", "valid_from": "2026-02-01"}, format="json"
        ).status_code
        == 400
    )
    assert (
        desk.post("/api/rooms", {"number": "301", "room_type": type_id, "floor": 3}, format="json").status_code == 201
    )
    assert desk.post("/api/rooms", {"number": "301", "room_type": type_id}, format="json").status_code == 400

    data = desk.get(f"/api/room-types/{type_id}").data
    assert (data["price_per_night"], data["room_count"]) == ("2500.00", 1)
    assert set(AuditLog.objects.values_list("action", flat=True)) == {
        "roomtype.created",
        "tariff.created",
        "room.created",
    }


def test_inactive_types_are_hidden_from_guests(manager, requester, room_type):
    desk = client_for(manager)
    before = desk.patch(f"/api/room-types/{room_type.pk}", {"is_active": False}, format="json")
    assert before.status_code == 200
    assert client_for(requester).get("/api/room-types").data == []
    assert client_for(requester).get(f"/api/room-types/{room_type.pk}").status_code == 404
    assert len(desk.get("/api/room-types").data) == 1
    log = AuditLog.objects.get(action="roomtype.updated")
    assert (log.before["is_active"], log.after["is_active"]) == (True, False)


def test_rooms_and_types_cannot_be_deleted(manager, room_type):
    desk = client_for(manager)
    assert desk.delete(f"/api/room-types/{room_type.pk}").status_code == 405
    assert desk.delete(f"/api/rooms/{room_type.rooms.first().pk}").status_code == 405


def test_photo_pipeline(manager, room_type, settings):
    desk = client_for(manager)
    url = f"/api/room-types/{room_type.pk}/photos"
    first = desk.post(
        url, {"file": upload("IMG_001.PNG", png_bytes((2400, 1600))), "caption": "Bed"}, format="multipart"
    )
    assert first.status_code == 201, first.data
    second = desk.post(url, {"file": upload("b.png", png_bytes((600, 400)))}, format="multipart")
    assert (first.data["is_cover"], second.data["is_cover"]) == (True, False)

    photo = RoomPhoto.objects.get(pk=first.data["id"])
    assert "IMG_001" not in photo.file_ref and storages["private"].exists(photo.file_ref)
    assert set(photo.variants) == {"480", "960", "1600"}
    for width, path in photo.variants.items():
        with default_storage.open(path) as fh:
            image = Image.open(fh)
            assert image.format == "WEBP" and image.width == int(width)
    small = RoomPhoto.objects.get(pk=second.data["id"])
    with default_storage.open(small.variants["1600"]) as fh:
        assert Image.open(fh).width == 600  # never upscaled

    listed = desk.get(f"/api/room-types/{room_type.pk}").data["photos"]
    assert [p["id"] for p in listed] == [first.data["id"], second.data["id"]]
    assert listed[0]["urls"]["480"].startswith("/media/room-photos/")

    # Reorder, change cover.
    order = [second.data["id"], first.data["id"]]
    assert [p["id"] for p in desk.post(f"{url}/reorder", {"order": order}, format="json").data] == order
    assert desk.post(f"{url}/reorder", {"order": order[:1]}, format="json").status_code == 400
    assert desk.patch(f"/api/photos/{second.data['id']}", {"is_cover": True}, format="json").status_code == 200
    assert list(RoomPhoto.objects.filter(is_cover=True).values_list("pk", flat=True)) == [small.pk]

    # Replace keeps the record but swaps the files.
    old_variants = dict(photo.variants)
    old_ref = photo.file_ref
    resp = desk.patch(
        f"/api/photos/{photo.pk}", {"file": upload("new.png", png_bytes((1000, 500)))}, format="multipart"
    )
    assert resp.status_code == 200
    photo.refresh_from_db()
    assert photo.file_ref != old_ref and not storages["private"].exists(old_ref)
    assert not any(default_storage.exists(p) for p in old_variants.values())

    # Deleting the cover promotes the next photo.
    assert desk.delete(f"/api/photos/{small.pk}").status_code == 204
    photo.refresh_from_db()
    assert photo.is_cover
    files = [photo.file_ref, *photo.variants.values()]
    assert desk.delete(f"/api/photos/{photo.pk}").status_code == 204
    assert not storages["private"].exists(files[0]) and not any(default_storage.exists(p) for p in files[1:])


def test_photo_must_be_an_image(manager, room_type):
    desk = client_for(manager)
    url = f"/api/room-types/{room_type.pk}/photos"
    assert desk.post(url, {"file": upload("a.pdf", PDF)}, format="multipart").status_code == 400
    assert desk.post(url, {"file": upload("a.png", b"\x89PNG\r\n\x1a\nbroken")}, format="multipart").status_code == 400
    assert desk.post(url, {}, format="multipart").status_code == 400
    assert not RoomPhoto.objects.exists()


def test_room_type_price_follows_effective_date(room_type):
    from datetime import date

    from apps.rooms.models import Tariff

    Tariff.objects.create(room_type=room_type, price_per_night=1200, valid_from=date(2026, 6, 1))
    rt = RoomType.objects.get(pk=room_type.pk)
    assert rt.price_on(date(2026, 5, 31)) == 1000
    assert rt.price_on(date(2026, 6, 1)) == 1200
    assert rt.price_on(date(2019, 1, 1)) is None
