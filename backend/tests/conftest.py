import io
from datetime import date, timedelta

import pytest
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.bookings.models import Booking, Category, Document, Guest, Status
from apps.rooms.models import Room, RoomType, Tariff

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def png_bytes(size=(1200, 800)):
    buf = io.BytesIO()
    Image.new("RGB", size, (40, 90, 160)).save(buf, "PNG")
    return buf.getvalue()


def upload(name="file.pdf", content=PDF):
    f = io.BytesIO(content)
    f.name = name
    return f


def make_user(role, local=None, **extra):
    local = local or role.lower()
    return User.objects.create_user(email=f"{local}@college.example.edu", name=local.title(), role=role, **extra)


def client_for(user, mfa=None):
    """A signed-in client. Staff get a verified TOTP session unless mfa=False."""
    client = APIClient()
    client.force_login(user)
    if mfa if mfa is not None else user.role in (Role.MANAGER, Role.ADMIN):
        device = TOTPDevice.objects.create(user=user, name="test", confirmed=True)
        session = client.session
        session["otp_device_id"] = device.persistent_id
        session.save()
    return client


@pytest.fixture(autouse=True)
def run_on_commit_hooks(request, monkeypatch):
    """Ordinary tests never commit, so run on_commit hooks (emails, photo jobs) straight away."""
    marker = request.node.get_closest_marker("django_db")
    if not (marker and marker.kwargs.get("transaction")):
        monkeypatch.setattr("django.db.transaction.on_commit", lambda func, *a, **k: func())


@pytest.fixture
def requester(db):
    return make_user(Role.REQUESTER)


@pytest.fixture
def other_requester(db):
    return make_user(Role.REQUESTER, "other")


@pytest.fixture
def external(db):
    return User.objects.create_user(email="guardian@example.com", name="Guardian", role=Role.EXTERNAL)


@pytest.fixture
def approver(db):
    return make_user(Role.APPROVER)


@pytest.fixture
def manager(db):
    return make_user(Role.MANAGER)


@pytest.fixture
def admin(db):
    return make_user(Role.ADMIN)


@pytest.fixture
def room_type(db):
    rt = RoomType.objects.create(name="Double", capacity=2, amenities=["Wi-Fi"])
    Tariff.objects.create(room_type=rt, price_per_night=1000, valid_from=date(2020, 1, 1))
    Room.objects.create(number="101", room_type=rt, floor=1)
    Room.objects.create(number="102", room_type=rt, floor=1)
    return rt


@pytest.fixture
def stay():
    start = date.today() + timedelta(days=10)
    return start, start + timedelta(days=2)


def booking_payload(room_type, stay, category="OFFICIAL", **extra):
    data = {
        "room_type": str(room_type.pk),
        "check_in": stay[0].isoformat(),
        "check_out": stay[1].isoformat(),
        "category": category,
        "purpose": "Guest lecture",
        "guests": [
            {"name": "Prof. Visitor", "phone": "+919800000001", "address": "12 MG Road, Pune", "id_type": "AADHAAR"}
        ],
    }
    if category == "PERSONAL":
        data["student_link"] = {
            "student_name": "Riya Sen",
            "roll_number": "CS22B014",
            "programme": "B.Tech CSE",
            "year": 3,
            "relationship": "Mother",
        }
    data.update(extra)
    return data


def make_booking(user, room_type, stay, status=Status.DRAFT, category=Category.OFFICIAL, room=None, **extra):
    """Creates a booking directly in a given state, for tests that start mid-flow."""
    booking = Booking.objects.create(
        requester=user, room_type=room_type, room=room, check_in=stay[0], check_out=stay[1], category=category,
        purpose="Visit", status=status, price_per_night=1000, amount=1000 * (stay[1] - stay[0]).days, **extra,
    )  # fmt: skip
    doc = Document.objects.create(
        booking=booking,
        type=Document.Type.GUEST_ID,
        file_ref="x/id.pdf",
        content_type="application/pdf",
        size=10,
        uploaded_by=user,
    )
    Guest.objects.create(
        booking=booking, name="Guest One", phone="+919800000002", address="Addr", id_type="PASSPORT", id_document=doc
    )
    return booking


def submitted_booking(client, room_type, stay, category="OFFICIAL"):
    """Drives the real API: draft, uploads, submit. Returns the booking JSON."""
    resp = client.post("/api/bookings", booking_payload(room_type, stay, category), format="json")
    assert resp.status_code == 201, resp.data
    booking = resp.data
    guest_id = booking["guests"][0]["id"]
    resp = client.post(
        f"/api/bookings/{booking['id']}/documents",
        {"type": "GUEST_ID", "guest": guest_id, "file": upload()},
        format="multipart",
    )
    assert resp.status_code == 201, resp.data
    if category == "OFFICIAL":
        resp = client.post(
            f"/api/bookings/{booking['id']}/documents",
            {"type": "RECOMMENDATION_LETTER", "file": upload()},
            format="multipart",
        )
        assert resp.status_code == 201, resp.data
    resp = client.post(f"/api/bookings/{booking['id']}/submit")
    assert resp.status_code == 200, resp.data
    return resp.data
