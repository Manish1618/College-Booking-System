import pytest
from django.db import DatabaseError, transaction

from apps.audit import services as audit
from apps.audit.models import AuditLog

from .conftest import client_for

pytestmark = pytest.mark.django_db


def test_audit_log_is_append_only(requester):
    entry = audit.log("test.action", requester, actor=requester, after={"a": 1})
    entry.action = "tampered"
    with pytest.raises(RuntimeError):
        entry.save()
    with pytest.raises(RuntimeError):
        entry.delete()
    # The database refuses too, whatever the application does.
    for attempt in (
        lambda: AuditLog.objects.filter(pk=entry.pk).update(action="tampered"),
        lambda: AuditLog.objects.filter(pk=entry.pk).delete(),
    ):
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            attempt()
    assert AuditLog.objects.get(pk=entry.pk).action == "test.action"


def test_admin_reads_and_filters_the_log(admin, requester):
    audit.log("thing.done", requester, actor=requester, before={"x": 1}, after={"x": 2})
    client = client_for(admin)
    rows = client.get("/api/audit-logs?action=thing.done").data["results"]
    assert len(rows) == 1
    assert (rows[0]["actor_name"], rows[0]["before"], rows[0]["after"]) == ("Requester", {"x": 1}, {"x": 2})
    assert client.post("/api/audit-logs", {}, format="json").status_code == 405
    assert client.delete(f"/api/audit-logs/{rows[0]['id']}").status_code == 405


def test_request_ip_is_recorded(requester, settings):
    settings.TRUSTED_PROXY_COUNT = 1
    client = client_for(requester)
    client.patch("/api/auth/me", {"name": "x"}, format="json")
    client.post("/api/auth/logout", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9")
    from apps.audit.middleware import client_ip

    class Req:
        META = {"HTTP_X_FORWARDED_FOR": "6.6.6.6, 203.0.113.9", "REMOTE_ADDR": "10.0.0.1"}

    assert client_ip(Req) == "203.0.113.9"  # the spoofable left-hand entry is ignored
    settings.TRUSTED_PROXY_COUNT = 0
    assert client_ip(Req) == "10.0.0.1"
