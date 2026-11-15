import re

import pytest
import requests
from django.core import mail
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.test import APIClient

from apps.accounts import otp
from apps.accounts.models import OneTimeCode, Role, User
from apps.audit.models import AuditLog

from .conftest import client_for

pytestmark = pytest.mark.django_db


def request_code(client, identifier):
    resp = client.post("/api/auth/otp/request", {"identifier": identifier}, format="json")
    assert resp.status_code == 200
    assert "debug_code" not in resp.data
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def test_college_email_signs_in_as_requester():
    client = APIClient()
    code = request_code(client, "Asha@College.Example.edu")
    resp = client.post(
        "/api/auth/otp/verify", {"identifier": "asha@college.example.edu", "code": code, "name": "Asha"}, format="json"
    )
    assert resp.status_code == 200
    assert resp.data["role"] == Role.REQUESTER
    assert client.get("/api/auth/me").data["email"] == "asha@college.example.edu"
    assert AuditLog.objects.filter(action="user.signed_in").count() == 1


def test_other_email_signs_up_as_external_guest():
    client = APIClient()
    code = request_code(client, "parent@gmail.com")
    resp = client.post("/api/auth/otp/verify", {"identifier": "parent@gmail.com", "code": code}, format="json")
    assert resp.data["role"] == Role.EXTERNAL


def test_phone_signup_uses_sms(caplog):
    client = APIClient()
    with caplog.at_level("INFO", logger="apps.notifications.sms"):
        assert client.post("/api/auth/otp/request", {"identifier": "98765 43210"}, format="json").status_code == 200
    code = re.search(r"\b(\d{6})\b", caplog.text).group(1)
    resp = client.post("/api/auth/otp/verify", {"identifier": "9876543210", "code": code}, format="json")
    assert resp.status_code == 200
    assert resp.data["phone"] == "+919876543210"
    assert resp.data["role"] == Role.EXTERNAL


def test_code_is_stored_hashed_and_single_use():
    client = APIClient()
    code = request_code(client, "a@example.com")
    assert code not in OneTimeCode.objects.get().code_hash
    assert (
        client.post("/api/auth/otp/verify", {"identifier": "a@example.com", "code": code}, format="json").status_code
        == 200
    )
    assert (
        APIClient()
        .post("/api/auth/otp/verify", {"identifier": "a@example.com", "code": code}, format="json")
        .status_code
        == 400
    )


def test_wrong_code_attempts_are_capped(settings):
    settings.OTP_MAX_ATTEMPTS = 3
    client = APIClient()
    code = request_code(client, "a@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(3):
        assert (
            client.post(
                "/api/auth/otp/verify", {"identifier": "a@example.com", "code": wrong}, format="json"
            ).status_code
            == 400
        )
    # The right code no longer works once the cap is hit.
    assert (
        client.post("/api/auth/otp/verify", {"identifier": "a@example.com", "code": code}, format="json").status_code
        == 400
    )
    assert not User.objects.filter(email="a@example.com").exists()


def test_new_code_invalidates_the_old_one():
    client = APIClient()
    first = request_code(client, "a@example.com")
    second = request_code(client, "a@example.com")
    if first != second:
        assert (
            client.post(
                "/api/auth/otp/verify", {"identifier": "a@example.com", "code": first}, format="json"
            ).status_code
            == 400
        )
    assert (
        client.post("/api/auth/otp/verify", {"identifier": "a@example.com", "code": second}, format="json").status_code
        == 200
    )


def test_expired_code_is_rejected():
    code = otp.issue_code("a@example.com")
    OneTimeCode.objects.update(expires_at="2020-01-01T00:00:00Z")
    assert (
        APIClient()
        .post("/api/auth/otp/verify", {"identifier": "a@example.com", "code": code}, format="json")
        .status_code
        == 400
    )


def test_invalid_identifier():
    assert APIClient().post("/api/auth/otp/request", {"identifier": "nonsense"}, format="json").status_code == 400


def test_otp_requests_are_rate_limited(settings):
    settings.RATELIMIT_ENABLE = True
    settings.OTP_REQUEST_RATE_PER_IDENTIFIER = "2/h"
    client = APIClient()
    codes = [
        client.post("/api/auth/otp/request", {"identifier": "rl@example.com"}, format="json").status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_disabled_account_cannot_sign_in():
    User.objects.create_user(email="gone@example.com", is_active=False)
    client = APIClient()
    code = request_code(client, "gone@example.com")
    assert (
        client.post("/api/auth/otp/verify", {"identifier": "gone@example.com", "code": code}, format="json").status_code
        == 403
    )


def test_post_requires_csrf_token():
    client = APIClient(enforce_csrf_checks=True)
    assert client.post("/api/auth/otp/request", {"identifier": "a@example.com"}, format="json").status_code == 403
    token = client.get("/api/auth/csrf").cookies["csrftoken"].value
    resp = client.post("/api/auth/otp/request", {"identifier": "a@example.com"}, format="json", HTTP_X_CSRFTOKEN=token)
    assert resp.status_code == 200


def test_logout_and_anonymous_me(requester):
    client = client_for(requester)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 403


def test_user_can_edit_name_but_not_role(requester):
    client = client_for(requester)
    resp = client.patch("/api/auth/me", {"name": "New Name", "role": "ADMIN"}, format="json")
    assert resp.data["name"] == "New Name"
    requester.refresh_from_db()
    assert requester.role == Role.REQUESTER


def test_staff_totp_enrol_and_verify(manager):
    client = client_for(manager, mfa=False)
    me = client.get("/api/auth/me").data
    assert me["mfa"] == {"required": True, "enrolled": False, "verified": False}
    assert client.get("/api/rooms").status_code == 403  # manager screens are locked until TOTP passes

    assert client.post("/api/auth/totp/verify", {"code": "123456"}, format="json").status_code == 400
    assert client.post("/api/auth/totp/setup").data["otpauth_url"].startswith("otpauth://totp/")
    device = TOTPDevice.objects.get(user=manager)
    assert client.post("/api/auth/totp/verify", {"code": "000000"}, format="json").status_code == 400

    token = f"{TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift).token():06d}"
    device.throttle_reset()
    resp = client.post("/api/auth/totp/verify", {"code": token}, format="json")
    assert resp.status_code == 200, resp.data
    assert resp.data["mfa"] == {"required": True, "enrolled": True, "verified": True}
    assert client.get("/api/rooms").status_code == 200
    # Enrolment cannot be silently replaced.
    assert client.post("/api/auth/totp/setup").status_code == 400


def test_totp_is_for_staff_only(requester):
    assert client_for(requester).post("/api/auth/totp/setup").status_code == 403


class FakeTurnstile:
    def __init__(self, success):
        self.success = success
        self.calls = []

    def __call__(self, url, data, timeout):
        self.calls.append(data)
        if self.success is None:
            raise requests.ConnectionError("down")

        class Response:
            json = staticmethod(lambda: {"success": self.success})

        return Response()


def test_turnstile_guards_code_requests_when_configured(settings, monkeypatch):
    settings.TURNSTILE_SITE_KEY, settings.TURNSTILE_SECRET_KEY = "site-key", "secret-key"
    client = APIClient()
    assert client.get("/api/auth/csrf").data["turnstile_site_key"] == "site-key"

    passing = FakeTurnstile(True)
    monkeypatch.setattr(requests, "post", passing)
    body = {"identifier": "a@example.com"}
    assert client.post("/api/auth/otp/request", body, format="json").status_code == 400  # no token
    assert passing.calls == []
    assert client.post("/api/auth/otp/request", {**body, "turnstile_token": "tok"}, format="json").status_code == 200
    assert passing.calls[0]["secret"] == "secret-key" and passing.calls[0]["response"] == "tok"

    for outcome in (False, None):  # challenge failed, or Cloudflare unreachable: fail closed
        monkeypatch.setattr(requests, "post", FakeTurnstile(outcome))
        assert (
            client.post("/api/auth/otp/request", {**body, "turnstile_token": "tok"}, format="json").status_code == 400
        )
    assert len(mail.outbox) == 1


def test_turnstile_is_off_by_default():
    assert APIClient().get("/api/auth/csrf").data["turnstile_site_key"] == ""
