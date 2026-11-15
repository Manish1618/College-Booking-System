"""Role and ownership checks (IDOR): every role against every protected endpoint."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.audit.models import AuditLog
from apps.bookings.models import ApprovalRule, Category, Document, Status

from .conftest import booking_payload, client_for, make_booking, make_user, submitted_booking, upload

pytestmark = pytest.mark.django_db


@pytest.fixture
def clients(requester, external, approver, manager, admin):
    return {
        "anon": APIClient(),
        "requester": client_for(requester),
        "external": client_for(external),
        "approver": client_for(approver),
        "manager": client_for(manager),
        "manager_no_mfa": client_for(make_user(Role.MANAGER, "mgr2"), mfa=False),
        "admin": client_for(admin),
        "admin_no_mfa": client_for(make_user(Role.ADMIN, "adm2"), mfa=False),
    }


MANAGER_ONLY = {"manager", "admin"}
ADMIN_ONLY = {"admin"}


@pytest.mark.parametrize(
    "method,path,allowed",
    [
        ("get", "/api/rooms", MANAGER_ONLY),
        ("post", "/api/rooms", MANAGER_ONLY),
        ("post", "/api/room-types", MANAGER_ONLY),
        ("get", "/api/users", ADMIN_ONLY),
        ("post", "/api/users", ADMIN_ONLY),
        ("get", "/api/audit-logs", ADMIN_ONLY),
        ("get", "/api/approval-rules", ADMIN_ONLY),
        ("post", "/api/approval-rules", ADMIN_ONLY),
    ],
)
def test_staff_endpoints_by_role(clients, method, path, allowed):
    for name, client in clients.items():
        code = getattr(client, method)(path, {}, format="json").status_code
        if name in allowed:
            assert code in (200, 201, 400), f"{name} {method} {path} -> {code}"
        else:
            assert code == 403, f"{name} {method} {path} -> {code}"


def test_room_type_writes_by_role(clients, room_type):
    for name, client in clients.items():
        base = f"/api/room-types/{room_type.pk}"
        codes = [
            client.patch(base, {"description": "x"}, format="json").status_code,
            client.get(f"{base}/tariffs").status_code,
            client.post(f"{base}/tariffs", {}, format="json").status_code,
            client.post(f"{base}/photos", {}, format="multipart").status_code,
        ]
        if name in MANAGER_ONLY:
            assert codes == [200, 200, 400, 400], name
        else:
            assert codes == [403] * 4, name


def test_public_endpoints_are_open(clients, room_type, stay):
    anon = clients["anon"]
    assert anon.get("/api/room-types").status_code == 200
    assert anon.get(f"/api/availability?check_in={stay[0]}&check_out={stay[1]}").status_code == 200
    assert anon.get("/api/bookings").status_code == 403
    assert anon.post("/api/bookings", {}, format="json").status_code == 403


def test_booking_is_invisible_to_other_guests(clients, requester, other_requester, room_type, stay):
    booking = make_booking(requester, room_type, stay, Status.PENDING)
    other = client_for(other_requester)
    base = f"/api/bookings/{booking.pk}"
    assert other.get(base).status_code == 404
    assert other.patch(base, {"purpose": "hijack"}, format="json").status_code == 404
    for act in ("submit", "cancel", "decide", "allot", "pay", "documents"):
        assert other.post(f"{base}/{act}", {}, format="json").status_code in (403, 404), act
    assert other.get(f"{base}/free-rooms").status_code == 403
    assert clients["external"].get(base).status_code == 404
    assert [b["id"] for b in other.get("/api/bookings").data["results"]] == []
    assert clients["requester"].get(base).status_code == 200


def test_list_scopes_by_role(clients, requester, other_requester, room_type, stay):
    mine = make_booking(requester, room_type, stay, Status.PENDING)
    draft = make_booking(other_requester, room_type, stay, Status.DRAFT)
    ids = lambda c, q="": {b["id"] for b in c.get(f"/api/bookings{q}").data["results"]}  # noqa: E731
    assert ids(clients["requester"]) == {str(mine.pk)}
    assert ids(clients["approver"]) == {str(mine.pk)}  # drafts are never routed
    assert ids(clients["manager"]) == {str(mine.pk), str(draft.pk)}
    assert ids(clients["manager"], "?scope=desk") == {str(mine.pk)}
    assert ids(clients["manager_no_mfa"]) == set()
    assert ids(clients["admin_no_mfa"]) == set()
    assert ids(clients["approver"], "?scope=approvals") == {str(mine.pk)}
    assert ids(clients["approver"], "?scope=mine") == set()


def test_only_approvers_decide(clients, requester, room_type, stay):
    booking = make_booking(requester, room_type, stay, Status.PENDING)
    url = f"/api/bookings/{booking.pk}/decide"
    body = {"decision": "APPROVED"}
    assert clients["requester"].post(url, body, format="json").status_code == 403  # own request
    assert clients["manager"].post(url, body, format="json").status_code == 403
    assert clients["external"].post(url, body, format="json").status_code == 404
    assert clients["admin_no_mfa"].post(url, body, format="json").status_code == 404
    assert clients["approver"].post(url, body, format="json").status_code == 200


def test_approver_cannot_approve_own_request(approver, room_type, stay):
    booking = make_booking(approver, room_type, stay, Status.PENDING)
    resp = client_for(approver).post(f"/api/bookings/{booking.pk}/decide", {"decision": "APPROVED"}, format="json")
    assert resp.status_code == 403


def test_routing_rules_limit_approvers(clients, requester, approver, room_type, stay):
    hod = make_user(Role.APPROVER, "hod")
    ApprovalRule.objects.create(category=Category.OFFICIAL, approver=hod)
    official = make_booking(requester, room_type, stay, Status.PENDING, Category.OFFICIAL)
    personal = make_booking(requester, room_type, stay, Status.PENDING, Category.PERSONAL)
    # `approver` has no rule for official stays, so cannot even see that request.
    assert clients["approver"].get(f"/api/bookings/{official.pk}").status_code == 404
    assert (
        clients["approver"]
        .post(f"/api/bookings/{official.pk}/decide", {"decision": "APPROVED"}, format="json")
        .status_code
        == 404
    )
    assert (
        client_for(hod).post(f"/api/bookings/{official.pk}/decide", {"decision": "APPROVED"}, format="json").status_code
        == 200
    )
    # Personal stays have no rule, so any approver may decide.
    assert (
        clients["approver"]
        .post(f"/api/bookings/{personal.pk}/decide", {"decision": "APPROVED"}, format="json")
        .status_code
        == 200
    )


def test_only_managers_allot(clients, requester, room_type, stay):
    booking = make_booking(requester, room_type, stay, Status.CONFIRMED)
    room = room_type.rooms.first()
    url = f"/api/bookings/{booking.pk}/allot"
    for name in ("requester", "approver", "manager_no_mfa", "admin_no_mfa", "external"):
        assert clients[name].post(url, {"room": str(room.pk)}, format="json").status_code == 403, name
    assert clients["manager"].post(url, {"room": str(room.pk)}, format="json").status_code == 200


def test_only_owner_pays(clients, requester, room_type, stay):
    booking = make_booking(requester, room_type, stay, Status.APPROVED)
    url = f"/api/bookings/{booking.pk}/pay"
    for name in ("external", "approver", "manager"):
        assert clients[name].post(url, {"gateway": "dev"}, format="json").status_code == 403, name
    assert clients["requester"].post(url, {"gateway": "dev"}, format="json").status_code == 200


def test_document_access(clients, requester, other_requester, room_type, stay):
    booking = submitted_booking(clients["requester"], room_type, stay)
    letter = next(d for d in booking["documents"] if d["type"] == "RECOMMENDATION_LETTER")
    id_copy = next(d for d in booking["documents"] if d["type"] == "GUEST_ID")
    get = lambda name, doc: clients[name].get(f"/api/documents/{doc['id']}/download").status_code  # noqa: E731

    # Letter: requester, routed approver, manager, admin.
    assert {n: get(n, letter) for n in ("requester", "approver", "manager", "admin")} == dict.fromkeys(
        ("requester", "approver", "manager", "admin"), 200
    )
    assert client_for(other_requester).get(f"/api/documents/{letter['id']}/download").status_code == 404
    assert get("external", letter) == 404
    assert get("anon", letter) == 403
    # ID copies: manager and admin only, and only after TOTP.
    assert get("manager", id_copy) == 200
    assert get("admin", id_copy) == 200
    for name in ("requester", "approver", "external", "manager_no_mfa", "admin_no_mfa"):
        assert get(name, id_copy) == 404, name
    # Every successful view is logged; refused ones are not counted as views.
    assert AuditLog.objects.filter(action="document.viewed", entity_id=id_copy["id"]).count() == 2


def test_approver_sees_no_guest_contact_details(clients, room_type, stay):
    booking = submitted_booking(clients["requester"], room_type, stay)
    seen = clients["approver"].get(f"/api/bookings/{booking['id']}").data
    assert seen["guests"] == [{"id": booking["guests"][0]["id"], "name": "Prof. Visitor"}]
    assert "phone" in clients["manager"].get(f"/api/bookings/{booking['id']}").data["guests"][0]


def test_cannot_upload_to_or_edit_submitted_booking(clients, room_type, stay):
    booking = submitted_booking(clients["requester"], room_type, stay)
    base = f"/api/bookings/{booking['id']}"
    assert clients["requester"].patch(base, {"purpose": "changed"}, format="json").status_code == 400
    resp = clients["requester"].post(
        f"{base}/documents", {"type": "RECOMMENDATION_LETTER", "file": upload()}, format="multipart"
    )
    assert resp.status_code == 400
    assert Document.objects.filter(booking_id=booking["id"]).count() == 2


def test_requester_cannot_set_protected_fields(clients, room_type, stay):
    payload = booking_payload(
        room_type, stay, status="CONFIRMED", amount="1", price_per_night="1", room=str(room_type.rooms.first().pk)
    )
    data = clients["requester"].post("/api/bookings", payload, format="json").data
    assert (data["status"], data["amount"], data["room"]) == ("DRAFT", "2000.00", None)


def test_admin_manages_users(clients, requester):
    admin = clients["admin"]
    resp = admin.post(
        "/api/users", {"email": "HoD@college.example.edu", "name": "HoD", "role": "APPROVER"}, format="json"
    )
    assert resp.status_code == 201 and resp.data["email"] == "hod@college.example.edu"
    assert admin.patch(f"/api/users/{requester.pk}", {"role": "MANAGER"}, format="json").status_code == 200
    requester.refresh_from_db()
    assert requester.role == Role.MANAGER
    assert AuditLog.objects.filter(action="user.updated", entity_id=str(requester.pk)).exists()
    me = admin.get("/api/auth/me").data["id"]
    assert admin.patch(f"/api/users/{me}", {"role": "EXTERNAL"}, format="json").status_code == 400


@pytest.mark.django_db
def test_django_admin_sign_in_returns_to_the_requested_page(admin, requester):
    """The admin's own login URL only redirects, so it must never be the place sign-in returns to."""
    login = "/django-admin/login/"
    anon = APIClient()
    resp = anon.get("/django-admin/")
    assert resp.status_code == 302 and resp["Location"] == f"{login}?next=/django-admin/"
    assert anon.get(resp["Location"])["Location"] == "/login?next=/django-admin/"
    assert anon.get(login, {"next": "/django-admin/audit/"})["Location"] == "/login?next=/django-admin/audit/"
    for bad in ("https://evil.example/", "//evil.example/", f"{login}?next=/django-admin/", ""):
        assert anon.get(login, {"next": bad})["Location"] == "/login?next=/django-admin/"

    # Signed in with TOTP: straight through, no second trip to the portal.
    signed_in = client_for(admin)
    assert signed_in.get(login, {"next": "/django-admin/"})["Location"] == "/django-admin/"
    assert signed_in.get("/django-admin/").status_code == 200
    # Staff without TOTP in this session go to the portal, which asks for the authenticator code.
    no_totp = client_for(admin, mfa=False)
    assert no_totp.get(login, {"next": "/django-admin/"})["Location"] == "/login?next=/django-admin/"
    # An account with no admin access is sent home instead of bouncing between the two sign-in pages.
    assert client_for(requester).get(login, {"next": "/django-admin/"})["Location"] == "/"


def test_health_probe_answers_when_only_the_public_domain_is_allowed(settings):
    """The container probe calls localhost; production allows only the real domain."""
    settings.ALLOWED_HOSTS = ["guesthouse.example.edu"]
    settings.SECURE_SSL_REDIRECT = True
    client = APIClient()
    resp = client.get("/api/healthz", HTTP_HOST="localhost:8000")
    assert resp.status_code == 200 and resp.json() == {"status": "ok"}
    # Everything else is still refused for an unknown host.
    assert client.get("/api/auth/csrf", HTTP_HOST="localhost:8000").status_code == 400


@pytest.mark.django_db
def test_admin_set_phone_is_stored_the_way_sign_in_looks_it_up(admin, requester):
    from apps.accounts import otp

    client = client_for(admin)
    resp = client.post("/api/users", {"name": "Desk", "phone": "98765 43210", "role": "MANAGER"}, format="json")
    assert resp.status_code == 201 and resp.data["phone"] == "+919876543210"
    # Signing in with the same number, however it is typed, reaches that staff account.
    kind, number = otp.normalise_identifier("9876543210")
    user, created = otp.get_or_create_user(kind, number)
    assert (str(user.pk), created, user.role) == (resp.data["id"], False, Role.MANAGER)

    # The same number or address in another form is a duplicate, not a second account or a server error.
    again = client.post("/api/users", {"name": "Copy", "phone": "+91 98765 43210"}, format="json")
    assert again.status_code == 400 and "phone" in again.data
    assert client.patch(f"/api/users/{requester.pk}", {"phone": "9876543210"}, format="json").status_code == 400
    taken = client.post("/api/users", {"name": "Copy", "email": requester.email.upper()}, format="json")
    assert taken.status_code == 400 and "email" in taken.data
    assert client.post("/api/users", {"name": "Bad", "phone": "12345"}, format="json").status_code == 400

    # Saving a user's own number again is fine, and updates are normalised too.
    assert client.patch(f"/api/users/{user.pk}", {"phone": "98765 43210"}, format="json").status_code == 200
    resp = client.patch(f"/api/users/{requester.pk}", {"phone": "9123456780"}, format="json")
    assert resp.status_code == 200 and resp.data["phone"] == "+919123456780"


@pytest.mark.django_db
def test_profile_edit_does_not_restore_access_removed_meanwhile(manager, admin, requester, monkeypatch):
    """A name change that started before an admin revoked the account must not undo the revocation."""
    from apps.accounts.models import User
    from apps.accounts.serializers import MeSerializer

    real_is_valid = MeSerializer.is_valid

    def revoked_while_the_request_was_running(serializer, **kwargs):
        valid = real_is_valid(serializer, **kwargs)
        User.objects.filter(pk=manager.pk).update(role=Role.EXTERNAL, is_superuser=False, is_active=False)
        return valid

    client = client_for(manager)
    monkeypatch.setattr(MeSerializer, "is_valid", revoked_while_the_request_was_running)
    assert client.patch("/api/auth/me", {"name": "New Name"}, format="json").status_code == 200
    manager.refresh_from_db()
    assert (manager.name, manager.role, manager.is_active) == ("New Name", Role.EXTERNAL, False)
    monkeypatch.undo()

    # A role change through the admin screen still keeps the superuser flag in step with the role.
    desk = client_for(admin)
    assert desk.patch(f"/api/users/{requester.pk}", {"role": "ADMIN"}, format="json").status_code == 200
    requester.refresh_from_db()
    assert (requester.role, requester.is_superuser) == (Role.ADMIN, True)
    assert desk.patch(f"/api/users/{requester.pk}", {"role": "REQUESTER"}, format="json").status_code == 200
    requester.refresh_from_db()
    assert (requester.role, requester.is_superuser) == (Role.REQUESTER, False)
