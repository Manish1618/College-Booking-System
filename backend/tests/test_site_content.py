"""The public site's wording: anyone reads it, only managers change it, and changes are audited."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.audit.models import AuditLog

from .conftest import client_for, make_user

pytestmark = pytest.mark.django_db


def test_anyone_can_read_the_defaults():
    response = APIClient().get("/api/site-content")
    assert response.status_code == 200
    assert response.data["name"] == "College Guesthouse"
    assert response.data["headline"] == "Stay on campus,"
    assert "id" not in response.data


def test_manager_changes_wording_and_it_is_audited():
    manager = make_user(Role.MANAGER)
    response = client_for(manager).patch(
        "/api/site-content", {"name": "Tagore Guest House", "contact_phone": "0674 555 0100"}, format="json"
    )
    assert response.status_code == 200
    assert APIClient().get("/api/site-content").data["name"] == "Tagore Guest House"
    entry = AuditLog.objects.get(action="sitecontent.updated")
    assert entry.actor == manager
    assert entry.before["name"] == "College Guesthouse"
    assert entry.after["name"] == "Tagore Guest House"


@pytest.mark.parametrize("role", [None, Role.REQUESTER, Role.APPROVER])
def test_others_cannot_change_wording(role):
    client = client_for(make_user(role)) if role else APIClient()
    assert client.patch("/api/site-content", {"name": "Hacked"}, format="json").status_code == 403
    assert APIClient().get("/api/site-content").data["name"] == "College Guesthouse"


def test_required_wording_cannot_be_emptied():
    response = client_for(make_user(Role.MANAGER)).patch(
        "/api/site-content", {"name": "", "headline_accent": ""}, format="json"
    )
    assert response.status_code == 400
    assert "name" in response.data and "headline_accent" not in response.data


def test_saving_one_field_keeps_another_managers_change():
    """Two managers edit different fields at once: the second save must not put back the first one's old value."""
    from apps.rooms.models import SiteContent
    from apps.rooms.serializers import SiteContentSerializer

    stale = SiteContent.load()
    SiteContent.objects.filter(pk=stale.pk).update(name="Tagore Guest House")
    serializer = SiteContentSerializer(stale, data={"tagline": "On the north lawn"}, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    fresh = SiteContent.load()
    assert (fresh.name, fresh.tagline) == ("Tagore Guest House", "On the north lawn")


def test_map_link_must_be_https():
    client = client_for(make_user(Role.MANAGER))
    assert client.patch("/api/site-content", {"map_url": "javascript:alert(1)"}, format="json").status_code == 400
    assert client.patch("/api/site-content", {"map_url": "http://maps.example.com/x"}, format="json").status_code == 400
    assert (
        client.patch("/api/site-content", {"map_url": "https://maps.example.com/x"}, format="json").status_code == 200
    )
