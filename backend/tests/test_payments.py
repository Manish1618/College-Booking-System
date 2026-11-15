import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
import requests
from django.core import mail
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.bookings.models import Booking, Status
from apps.payments import gateways, services
from apps.payments.models import Payment, Refund, WebhookEvent

from .conftest import client_for, make_booking, pay

pytestmark = pytest.mark.django_db


def sign(secret, message):
    return hmac.new(
        secret.encode(), message if isinstance(message, bytes) else message.encode(), hashlib.sha256
    ).hexdigest()


class FakeHTTP:
    """Stands in for the gateways' HTTPS APIs: records each call and plays back a canned answer."""

    def __init__(self):
        self.calls = []
        self.routes = {}

    def on(self, method, suffix, data, status=200):
        self.routes[(method, suffix)] = (status, data)

    def __call__(self, method, url, **kwargs):
        self.calls.append(SimpleNamespace(method=method, url=url, **kwargs))
        for (wanted, suffix), (status, data) in self.routes.items():
            if wanted == method and url.endswith(suffix):
                if isinstance(data, Exception):
                    raise data
                return SimpleNamespace(status_code=status, json=lambda data=data: data)
        raise AssertionError(f"Unexpected gateway call: {method} {url}")

    def last(self, suffix):
        return next(call for call in reversed(self.calls) if call.url.endswith(suffix))


@pytest.fixture
def http(monkeypatch):
    fake = FakeHTTP()
    monkeypatch.setattr("apps.payments.gateways.requests.request", fake)
    return fake


@pytest.fixture
def approved(requester, room_type, stay):
    return make_booking(
        requester, room_type, stay, Status.APPROVED, hold_expires_at=timezone.now() + timedelta(hours=24)
    )


def dev_webhook(client, payment, outcome="paid", **changes):
    """Posts the simulated gateway's webhook, optionally tampered with after signing."""
    body, headers = gateways.adapter("dev").webhook_for(payment, outcome)
    if changes:
        body = json.dumps({**json.loads(body), **changes}).encode()
        if changes.pop("resign", True):
            headers = {"X-Dev-Signature": sign(gateways.adapter("dev")._secret(), body)}
    return client.post(
        "/api/payments/webhooks/dev",
        body,
        content_type="application/json",
        HTTP_X_DEV_SIGNATURE=headers["X-Dev-Signature"],
    )


def open_order(client, booking, gateway="dev"):
    resp = client.post(f"/api/bookings/{booking.pk}/pay", {"gateway": gateway}, format="json")
    assert resp.status_code == 200, resp.data
    return Payment.objects.get(pk=resp.data["payment"]["id"]), resp.data["checkout"]


# --- Paying -------------------------------------------------------------------
def test_booking_is_confirmed_by_the_webhook_not_by_the_browser(requester, approved):
    client = client_for(requester)
    payment, checkout = open_order(client, approved)
    assert checkout == {"mode": "dev", "order_id": payment.order_id}
    # Opening an order moves nothing: the booking waits for the gateway's word.
    assert (payment.status, Booking.objects.get(pk=approved.pk).status) == ("CREATED", "APPROVED")
    # Pressing Pay again reuses the open order instead of opening a second one.
    assert open_order(client, approved)[0].pk == payment.pk

    booking = pay(client, approved.pk)
    assert booking["status"] == "CONFIRMED" and booking["hold_expires_at"] is None
    payment.refresh_from_db()
    assert (payment.status, payment.amount) == ("PAID", Decimal("2000.00"))
    assert payment.gateway_payment_id.startswith("devpay_") and payment.paid_at
    assert booking["payment"]["paid"] == "2000.00" and booking["actions"]["receipt"] is True

    confirmation = next(m for m in mail.outbox if m.subject.endswith("Confirmed"))
    name, content, kind = confirmation.attachments[0]
    assert name == f"receipt-{approved.reference}.pdf" and kind == "application/pdf" and content[:5] == b"%PDF-"


def test_webhook_with_a_wrong_signature_changes_nothing(requester, approved):
    client = client_for(requester)
    payment, _ = open_order(client, approved)
    body, _ = gateways.adapter("dev").webhook_for(payment, "paid")
    resp = client.post(
        "/api/payments/webhooks/dev", body, content_type="application/json", HTTP_X_DEV_SIGNATURE="0" * 64
    )
    assert resp.status_code == 400
    assert client.post("/api/payments/webhooks/dev", body, content_type="application/json").status_code == 400
    payment.refresh_from_db()
    assert (payment.status, Booking.objects.get(pk=approved.pk).status) == ("CREATED", "APPROVED")


def test_webhook_needs_no_session_and_a_repeat_delivery_is_ignored(requester, approved):
    payment, _ = open_order(client_for(requester), approved)
    from rest_framework.test import APIClient

    gateway = APIClient(enforce_csrf_checks=True)  # the gateway has no cookie and no CSRF token
    body, headers = gateways.adapter("dev").webhook_for(payment, "paid")
    send = lambda: gateway.post(  # noqa: E731
        "/api/payments/webhooks/dev",
        body,
        content_type="application/json",
        HTTP_X_DEV_SIGNATURE=headers["X-Dev-Signature"],
    )
    first = send()
    assert (first.status_code, first.content) == (200, b"SUCCESS")
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED
    emails = len(mail.outbox)
    assert send().status_code == 200
    assert WebhookEvent.objects.count() == 1
    assert AuditLog.objects.filter(action="payment.paid").count() == 1
    assert AuditLog.objects.filter(action="booking.confirmed").count() == 1
    assert len(mail.outbox) == emails


def test_unknown_gateway_webhook_is_not_found(client, settings):
    assert client.post("/api/payments/webhooks/paytm", b"{}", content_type="application/json").status_code == 404
    # No secret configured means no endpoint: an empty secret would accept anyone's signature.
    for name in ("razorpay", "mobikwik"):
        resp = client.post(f"/api/payments/webhooks/{name}", b"{}", content_type="application/json")
        assert resp.status_code == 404, name
    settings.PAYMENT_GATEWAYS = []
    assert client.post("/api/payments/webhooks/dev", b"{}", content_type="application/json").status_code == 404


def test_wrong_amount_never_confirms(requester, approved):
    client = client_for(requester)
    payment, _ = open_order(client, approved)
    assert dev_webhook(client, payment, amount=100).status_code == 200
    payment.refresh_from_db()
    assert payment.status == "FAILED" and "not the Rs 2000.00" in payment.failure_reason
    assert Booking.objects.get(pk=approved.pk).status == Status.APPROVED
    assert AuditLog.objects.filter(action="payment.amount_mismatch").count() == 1


def test_failed_payment_leaves_the_booking_payable(requester, approved):
    client = client_for(requester)
    booking = pay(client, approved.pk, outcome="failed")
    assert booking["status"] == "APPROVED" and booking["actions"]["pay"] is True
    assert booking["payment"]["payments"] == []  # guests are not shown failed attempts
    first = Payment.objects.get()
    assert first.status == "FAILED" and first.failure_reason
    assert pay(client, approved.pk)["status"] == "CONFIRMED"
    assert Payment.objects.count() == 2


def test_only_the_owner_can_complete_a_simulated_payment(requester, other_requester, approved, settings):
    payment, _ = open_order(client_for(requester), approved)
    stranger = client_for(other_requester)
    assert stranger.post("/api/payments/dev/complete", {"order_id": payment.order_id}, format="json").status_code == 404
    settings.PAYMENT_GATEWAYS = []
    owner = client_for(requester)
    assert owner.post("/api/payments/dev/complete", {"order_id": payment.order_id}, format="json").status_code == 404
    assert Booking.objects.get(pk=approved.pk).status == Status.APPROVED


def test_payment_after_expiry_becomes_a_refund_due(requester, manager, approved):
    client = client_for(requester)
    payment, _ = open_order(client, approved)
    Booking.objects.filter(pk=approved.pk).update(status=Status.EXPIRED, hold_expires_at=None)
    assert dev_webhook(client, payment).status_code == 200
    payment.refresh_from_db()
    assert payment.status == "PAID"
    assert Booking.objects.get(pk=approved.pk).status == Status.EXPIRED
    refund = Refund.objects.get()
    assert (refund.status, refund.amount) == ("DUE", Decimal("2000.00")) and "expired" in refund.reason
    assert any("refund due" in m.subject for m in mail.outbox)
    assert client_for(manager).get("/api/desk").data["refunds_due"] == 1


def test_payment_just_after_the_window_is_honoured_while_the_room_is_free(
    requester, other_requester, room_type, approved
):
    client = client_for(requester)
    payment, _ = open_order(client, approved)
    Booking.objects.filter(pk=approved.pk).update(hold_expires_at=timezone.now() - timedelta(minutes=1))
    assert dev_webhook(client, payment).status_code == 200
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED


def test_payment_after_the_window_is_refunded_when_the_room_has_gone(
    requester, other_requester, room_type, stay, approved
):
    client = client_for(requester)
    payment, _ = open_order(client, approved)
    Booking.objects.filter(pk=approved.pk).update(hold_expires_at=timezone.now() - timedelta(minutes=1))
    for _ in room_type.rooms.all():
        make_booking(other_requester, room_type, stay, Status.CONFIRMED)
    assert dev_webhook(client, payment).status_code == 200
    assert Booking.objects.get(pk=approved.pk).status == Status.APPROVED
    assert Refund.objects.get().amount == Decimal("2000.00")


def test_second_payment_for_a_confirmed_booking_is_refunded(requester, approved):
    client = client_for(requester)
    pay(client, approved.pk)
    stray = Payment.objects.create(booking=approved, gateway="dev", order_id="dev_second", amount=approved.amount)
    assert dev_webhook(client, stray).status_code == 200
    stray.refresh_from_db()
    assert stray.status == "PAID"
    refund = Refund.objects.get()
    assert (refund.payment_id, refund.amount, refund.status) == (stray.pk, Decimal("2000.00"), "DUE")


# --- Razorpay -----------------------------------------------------------------
@pytest.fixture
def razorpay(settings, http):
    settings.PAYMENT_GATEWAYS = ["razorpay"]
    settings.RAZORPAY_KEY_ID = "rzp_test_key"
    settings.RAZORPAY_KEY_SECRET = "key-secret"
    settings.RAZORPAY_WEBHOOK_SECRET = "hook-secret"
    http.on("POST", "/v1/orders", {"id": "order_ABC", "status": "created"})
    return http


def razorpay_webhook(client, event, payload, event_id="evt_1", secret="hook-secret"):
    body = json.dumps({"entity": "event", "event": event, "payload": payload}).encode()
    return client.post(
        "/api/payments/webhooks/razorpay",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(secret, body),
        HTTP_X_RAZORPAY_EVENT_ID=event_id,
    )


def captured(order_id="order_ABC", amount=200000, status="captured", **extra):
    return {"payment": {"entity": {"id": "pay_XYZ", "order_id": order_id, "amount": amount, "status": status, **extra}}}


def test_razorpay_order_checkout_and_signed_webhook(client, requester, approved, razorpay):
    payment, checkout = open_order(client_for(requester), approved, "razorpay")
    order = razorpay.last("/v1/orders")
    assert order.auth == ("rzp_test_key", "key-secret") and order.timeout
    assert order.json["amount"] == 200000 and order.json["currency"] == "INR"  # paise
    assert order.json["receipt"] == payment.pk.hex
    assert payment.order_id == "order_ABC"
    assert checkout["mode"] == "razorpay" and checkout["script"].startswith("https://checkout.razorpay.com/")
    assert checkout["options"]["key"] == "rzp_test_key" and checkout["options"]["order_id"] == "order_ABC"
    assert "key-secret" not in json.dumps(checkout) and "hook-secret" not in json.dumps(checkout)

    # A forged webhook (signed with the wrong secret) is refused.
    assert razorpay_webhook(client, "payment.captured", captured(), secret="guess").status_code == 400
    assert Booking.objects.get(pk=approved.pk).status == Status.APPROVED

    assert razorpay_webhook(client, "payment.captured", captured()).status_code == 200
    payment.refresh_from_db()
    assert (payment.status, payment.gateway_payment_id) == ("PAID", "pay_XYZ")
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED
    # order.paid reports the same payment under another event id. Nothing happens twice.
    assert razorpay_webhook(client, "order.paid", captured(), event_id="evt_2").status_code == 200
    assert AuditLog.objects.filter(action="payment.paid").count() == 1
    assert Refund.objects.count() == 0
    # Events this system does not act on are acknowledged, so the gateway stops resending them.
    authorized = captured(status="authorized")
    assert razorpay_webhook(client, "payment.authorized", authorized, event_id="evt_3").status_code == 200


def test_razorpay_failure_then_success_on_the_same_order(client, requester, approved, razorpay):
    payment, _ = open_order(client_for(requester), approved, "razorpay")
    failed = captured(status="failed", error_description="Payment was declined by the bank")
    assert razorpay_webhook(client, "payment.failed", failed).status_code == 200
    payment.refresh_from_db()
    assert (payment.status, payment.failure_reason) == ("FAILED", "Payment was declined by the bank")
    assert razorpay_webhook(client, "payment.captured", captured(), event_id="evt_2").status_code == 200
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED


def test_razorpay_refusal_is_reported_and_nothing_is_stored(requester, approved, razorpay):
    razorpay.on("POST", "/v1/orders", {"error": {"description": "Authentication failed"}}, status=401)
    resp = client_for(requester).post(f"/api/bookings/{approved.pk}/pay", {"gateway": "razorpay"}, format="json")
    assert resp.status_code == 409 and "Authentication failed" in str(resp.data)
    razorpay.on("POST", "/v1/orders", requests.ConnectionError("boom"))
    resp = client_for(requester).post(f"/api/bookings/{approved.pk}/pay", {"gateway": "razorpay"}, format="json")
    assert resp.status_code == 409 and "could not be reached" in str(resp.data)
    assert Payment.objects.count() == 0


def test_status_check_confirms_when_the_webhook_is_late(requester, other_requester, approved, razorpay):
    client = client_for(requester)
    open_order(client, approved, "razorpay")
    razorpay.on("GET", "/orders/order_ABC/payments", {"items": [{"id": "pay_1", "status": "failed", "amount": 200000}]})
    assert client.post(f"/api/bookings/{approved.pk}/payment-status").data["status"] == "APPROVED"
    assert client_for(other_requester).post(f"/api/bookings/{approved.pk}/payment-status").status_code == 404
    items = [
        {"id": "pay_1", "status": "failed", "amount": 200000},
        {"id": "pay_2", "order_id": "order_ABC", "status": "captured", "amount": 200000},
    ]
    razorpay.on("GET", "/orders/order_ABC/payments", {"items": items})
    assert client.post(f"/api/bookings/{approved.pk}/payment-status").data["status"] == "CONFIRMED"
    assert Payment.objects.get().gateway_payment_id == "pay_2"


def test_reconcile_picks_up_orders_whose_webhook_never_came(requester, approved, razorpay):
    payment, _ = open_order(client_for(requester), approved, "razorpay")
    razorpay.on(
        "GET",
        "/orders/order_ABC/payments",
        {"items": [{"id": "pay_9", "order_id": "order_ABC", "status": "captured", "amount": 200000}]},
    )
    assert services.reconcile() == 0  # too fresh: the guest may still be paying
    Payment.objects.filter(pk=payment.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    assert services.reconcile() == 1
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED
    assert services.reconcile() == 0


def test_nightly_check_reports_payments_the_gateway_disagrees_with(requester, manager, approved, razorpay):
    from apps.payments.tasks import verify_recent

    payment, _ = open_order(client_for(requester), approved, "razorpay")
    razorpay.on(
        "GET",
        "/orders/order_ABC/payments",
        {"items": [{"id": "pay_9", "order_id": "order_ABC", "status": "captured", "amount": 200000}]},
    )
    services.check(payment)
    assert verify_recent() == 0
    razorpay.on("GET", "/orders/order_ABC/payments", {"items": []})
    mail.outbox.clear()
    assert verify_recent() == 1
    assert AuditLog.objects.filter(action="payment.reconcile_mismatch").count() == 1
    assert mail.outbox[0].to == [manager.email] and "order_ABC" in mail.outbox[0].body


# --- MobiKwik -----------------------------------------------------------------
@pytest.fixture
def mobikwik(settings, http):
    settings.PAYMENT_GATEWAYS = ["mobikwik"]
    settings.MOBIKWIK_MERCHANT_ID = "merchant-1"
    settings.MOBIKWIK_SECRET_KEY = "zaak-secret"
    settings.MOBIKWIK_BASE_URL = "https://zaakstaging.zaakpay.com"
    settings.SITE_URL = "https://guesthouse.example"
    return http


def zaakpay_status(payment, txn_status, amount="200000", refunds=()):
    order = {
        "orderDetail": {"orderId": payment.order_id, "txnId": "ZP123", "amount": amount},
        "txnStatus": txn_status,
        "responseDescription": "Declined by the bank",
        "refundDetails": list(refunds),
    }
    return {"status": True, "data": {"success": True, "orders": [order]}}


def test_mobikwik_checkout_form_is_signed(requester, approved, mobikwik):
    payment, checkout = open_order(client_for(requester), approved, "mobikwik")
    assert mobikwik.calls == []  # the order is opened by the form itself
    fields = checkout["fields"]
    assert checkout["mode"] == "redirect"
    assert checkout["action"] == "https://zaakstaging.zaakpay.com/api/paymentTransact/V13"
    assert fields["amount"] == "200000" and fields["orderId"] == payment.order_id == f"GH{payment.pk.hex}"
    assert fields["returnUrl"] == "https://guesthouse.example/api/payments/mobikwik/return"
    signed = {k: v for k, v in fields.items() if k != "checksum"}
    assert list(sorted(signed))[:3] == ["amount", "buyerEmail", "currency"]
    message = "".join(f"{name}={signed[name]}&" for name in sorted(signed))
    assert fields["checksum"] == sign("zaak-secret", message)
    # A second attempt gets a fresh order id: the gateway refuses a reused one.
    assert open_order(client_for(requester), approved, "mobikwik")[0].pk != payment.pk


def test_mobikwik_return_is_believed_only_after_a_status_lookup(client, requester, approved, mobikwik):
    payment, _ = open_order(client_for(requester), approved, "mobikwik")
    # The browser comes back claiming success while the gateway still says pending.
    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(payment, "2"))
    claim = {"orderId": payment.order_id, "responseCode": "100", "checksum": "anything"}
    resp = client.post("/api/payments/mobikwik/return", claim)
    assert resp.status_code == 302
    assert resp["Location"] == f"https://guesthouse.example/bookings/{approved.pk}?returned=1"
    assert Booking.objects.get(pk=approved.pk).status == Status.APPROVED

    lookup = mobikwik.last("/api/payments/v1/status")
    assert json.loads(lookup.data) == {"merchantIdentifier": "merchant-1", "orderId": payment.order_id}
    assert lookup.headers["checksum"] == sign("zaak-secret", lookup.data)

    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(payment, "0"))
    client.post("/api/payments/mobikwik/return", claim)
    payment.refresh_from_db()
    assert (payment.status, payment.gateway_payment_id) == ("PAID", "ZP123")
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED
    assert client.post("/api/payments/mobikwik/return", {"orderId": "nope"})["Location"].endswith("/bookings")


def test_mobikwik_failed_lookup_and_wrong_amount(client, requester, approved, mobikwik):
    payment, _ = open_order(client_for(requester), approved, "mobikwik")
    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(payment, "0", amount="100"))
    client.post("/api/payments/mobikwik/return", {"orderId": payment.order_id})
    payment.refresh_from_db()
    assert payment.status == "FAILED" and Booking.objects.get(pk=approved.pk).status == Status.APPROVED

    second, _ = open_order(client_for(requester), approved, "mobikwik")
    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(second, "1"))
    client.post("/api/payments/mobikwik/return", {"orderId": second.order_id})
    second.refresh_from_db()
    assert (second.status, second.failure_reason) == ("FAILED", "Declined by the bank")


def test_mobikwik_webhook_checks_the_checksum_then_looks_the_order_up(client, requester, approved, mobikwik):
    payment, _ = open_order(client_for(requester), approved, "mobikwik")
    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(payment, "0"))
    txn_data = json.dumps(
        {"merchantIdentifier": "merchant-1", "txns": [{"orderid": payment.order_id, "responseCode": 100}]}
    )
    url = "/api/payments/webhooks/mobikwik?realtime=true"

    def form(secret):
        body = urlencode({"txnData": txn_data, "checksum": sign(secret, txn_data)})
        return client.post(url, body, content_type="application/x-www-form-urlencoded")

    assert form("wrong").status_code == 400
    assert mobikwik.calls == [] and Booking.objects.get(pk=approved.pk).status == Status.APPROVED
    resp = form("zaak-secret")
    assert (resp.status_code, resp.content) == (200, b"SUCCESS")
    assert Booking.objects.get(pk=approved.pk).status == Status.CONFIRMED
    # The JSON form of the same webhook works too, and a repeat changes nothing.
    body = json.dumps({"txnData": txn_data, "checksum": sign("zaak-secret", txn_data)})
    assert client.post(url, body, content_type="application/json").status_code == 200
    assert AuditLog.objects.filter(action="payment.paid").count() == 1
    # If the lookup cannot be made, the gateway is asked to deliver again.
    mobikwik.on("POST", "/api/payments/v1/status", requests.Timeout())
    assert form("zaak-secret").status_code == 503


# --- Refunds ------------------------------------------------------------------
@pytest.fixture
def paid(requester, approved):
    pay(client_for(requester), approved.pk)
    mail.outbox.clear()
    return Booking.objects.get(pk=approved.pk)


def test_refund_rules_by_time_before_arrival(requester, room_type, stay, settings):
    booking = make_booking(requester, room_type, stay, Status.CONFIRMED)
    arrival = timezone.make_aware(timezone.datetime.combine(stay[0], timezone.datetime.min.time())) + timedelta(
        hours=12
    )
    percent = lambda hours: services.cancellation_percent(booking, now=arrival - timedelta(hours=hours))  # noqa: E731
    assert [percent(h) for h in (72, 48, 47, 24, 23, 0, -5)] == [100, 100, 50, 50, 0, 0, 0]
    settings.REFUND_FULL_HOURS, settings.REFUND_PARTIAL_HOURS, settings.REFUND_PARTIAL_PERCENT = 24, 6, 80
    assert [percent(h) for h in (30, 10, 2)] == [100, 80, 0]


def test_guest_cancellation_proposes_the_refund_the_rules_allow(requester, manager, paid, settings):
    client = client_for(requester)
    assert client.get(f"/api/bookings/{paid.pk}").data["payment"]["refund_on_cancel"] == {
        "percent": 100, "amount": "2000.00", "full": "2000.00"
    }  # fmt: skip
    settings.REFUND_FULL_HOURS = 24 * 60  # ten days ahead now falls in the partial band
    assert client.get(f"/api/bookings/{paid.pk}").data["payment"]["refund_on_cancel"]["amount"] == "1000.00"
    # A guest cannot award themselves the full refund.
    booking = client.post(f"/api/bookings/{paid.pk}/cancel", {"full_refund": True}, format="json").data
    assert booking["status"] == "CANCELLED"
    refund = booking["payment"]["refunds"][0]
    assert (refund["amount"], refund["status"], refund["limit"]) == ("1000.00", "DUE", "2000.00")
    assert "50%" in refund["reason"]
    assert booking["payment"]["refund_on_cancel"] is None
    assert [m.subject.rsplit("– ", 1)[1] for m in mail.outbox] == ["Cancelled", "refund due"]


def test_late_cancellation_refunds_nothing_and_the_desk_can_refund_in_full(
    requester, other_requester, manager, room_type, stay, settings
):
    settings.REFUND_FULL_HOURS, settings.REFUND_PARTIAL_HOURS = 24 * 90, 24 * 60
    late = make_booking(
        requester, room_type, stay, Status.APPROVED, hold_expires_at=timezone.now() + timedelta(hours=1)
    )
    pay(client_for(requester), late.pk)
    assert client_for(requester).post(f"/api/bookings/{late.pk}/cancel").data["payment"]["refunds"] == []
    assert Refund.objects.count() == 0

    other = make_booking(
        other_requester, room_type, stay, Status.APPROVED, hold_expires_at=timezone.now() + timedelta(hours=1)
    )
    pay(client_for(other_requester), other.pk)
    desk = client_for(manager)
    booking = desk.post(
        f"/api/bookings/{other.pk}/cancel", {"full_refund": True, "reason": "Room under repair"}, format="json"
    ).data
    assert booking["payment"]["refunds"][0]["amount"] == "2000.00"
    assert "guesthouse" in booking["payment"]["refunds"][0]["reason"]
    assert (
        AuditLog.objects.get(action="booking.cancelled", entity_id=str(other.pk)).after["comment"]
        == "Room under repair"
    )


def test_manager_issues_a_refund_through_the_gateway(clients, requester, paid):
    clients["requester"].post(f"/api/bookings/{paid.pk}/cancel")
    refund = Refund.objects.get()
    url = f"/api/refunds/{refund.pk}/issue"
    for name in ("requester", "approver", "manager_no_mfa", "external"):
        assert clients[name].post(url).status_code == 403, name
        assert clients[name].get("/api/refunds").status_code == 403, name
    listed = clients["manager"].get("/api/refunds?status=DUE").data["results"]
    assert [(r["reference"], r["amount"]) for r in listed] == [(paid.reference, "2000.00")]

    mail.outbox.clear()
    assert clients["manager"].post(url, {"amount": "2500"}, format="json").status_code == 400
    result = clients["manager"].post(url, {"amount": "1500.00"}, format="json")
    assert result.status_code == 200 and (result.data["status"], result.data["amount"]) == ("PROCESSED", "1500.00")
    refund.refresh_from_db()
    payment = refund.payment
    assert refund.gateway_refund_id.startswith("devrfnd_") and refund.processed_at
    assert (payment.refunded_amount, payment.status) == (Decimal("1500.00"), "PAID")
    assert [m.subject.rsplit("– ", 1)[1] for m in mail.outbox] == ["refund issued"]
    assert clients["manager"].post(url).status_code == 409  # never twice

    summary = clients["requester"].get(f"/api/bookings/{paid.pk}").data["payment"]
    assert (summary["paid"], summary["refunded"], summary["refundable"]) == ("2000.00", "1500.00", "500.00")


def test_goodwill_refund_manual_settlement_and_withdrawal(clients, paid):
    desk = clients["manager"]
    url = f"/api/bookings/{paid.pk}/refunds"
    assert clients["requester"].post(url, {"amount": "100", "reason": "x"}, format="json").status_code == 403
    assert desk.post(url, {"amount": "100"}, format="json").status_code == 400  # a reason is required
    assert desk.post(url, {"amount": "2000.01", "reason": "Hot water was off"}, format="json").status_code == 400
    assert desk.post(url, {"amount": "abc", "reason": "Hot water was off"}, format="json").status_code == 400
    booking = desk.post(url, {"amount": "300", "reason": "Hot water was off"}, format="json").data
    first = booking["payment"]["refunds"][0]
    assert (first["amount"], first["status"]) == ("300.00", "DUE") and booking["payment"]["refundable"] == "1700.00"
    # What is promised cannot be promised again.
    assert desk.post(url, {"amount": "1800", "reason": "More"}, format="json").status_code == 400

    assert desk.post(f"/api/refunds/{first['id']}/issue", {"manual": True}, format="json").status_code == 400
    done = desk.post(
        f"/api/refunds/{first['id']}/issue", {"manual": True, "note": "Cash at the desk"}, format="json"
    ).data
    assert (done["status"], done["manual"], done["note"]) == ("PROCESSED", True, "Cash at the desk")
    assert Payment.objects.get().refunded_amount == Decimal("300.00")

    second = desk.post(url, {"amount": "1700", "reason": "Mistake"}, format="json").data["payment"]["refunds"][1]
    assert desk.post(f"/api/refunds/{second['id']}/withdraw", {}, format="json").status_code == 400
    assert (
        desk.post(f"/api/refunds/{second['id']}/withdraw", {"note": "Entered twice"}, format="json").status_code == 204
    )
    assert Refund.objects.count() == 1 and AuditLog.objects.filter(action="refund.withdrawn").count() == 1
    assert desk.post(f"/api/refunds/{first['id']}/withdraw", {"note": "x"}, format="json").status_code == 409

    full = desk.post(url, {"amount": "1700", "reason": "Rest"}, format="json").data["payment"]["refunds"][1]
    desk.post(f"/api/refunds/{full['id']}/issue")
    assert Payment.objects.get().status == "REFUNDED"


def razorpay_paid(requester, approved, razorpay):
    payment, _ = open_order(client_for(requester), approved, "razorpay")
    razorpay.on(
        "GET",
        "/orders/order_ABC/payments",
        {"items": [{"id": "pay_XYZ", "order_id": "order_ABC", "status": "captured", "amount": 200000}]},
    )
    assert services.check(payment)
    return Payment.objects.get(pk=payment.pk)


def test_razorpay_refund_is_settled_by_the_webhook(client, requester, manager, approved, razorpay):
    payment = razorpay_paid(requester, approved, razorpay)
    desk = client_for(manager)
    desk.post(f"/api/bookings/{approved.pk}/cancel", {"full_refund": True}, format="json")
    refund = Refund.objects.get()
    razorpay.on("POST", "/payments/pay_XYZ/refund", {"id": "rfnd_1", "status": "pending"})
    assert desk.post(f"/api/refunds/{refund.pk}/issue").data["status"] == "PROCESSING"
    call = razorpay.last("/payments/pay_XYZ/refund")
    assert call.json == {"amount": 200000, "notes": {"refund": str(refund.pk)}}
    payment.refresh_from_db()
    assert payment.refunded_amount == 0

    # A refund made in Razorpay's own dashboard is not ours and is ignored.
    foreign = {"refund": {"entity": {"id": "rfnd_other", "payment_id": "pay_XYZ", "amount": 5000, "notes": []}}}
    assert razorpay_webhook(client, "refund.processed", foreign, event_id="evt_r0").status_code == 200
    payload = {
        "refund": {
            "entity": {
                "id": "rfnd_1",
                "payment_id": "pay_XYZ",
                "amount": 200000,
                "status": "processed",
                "notes": {"refund": str(refund.pk)},
            }
        }
    }
    assert razorpay_webhook(client, "refund.processed", payload, event_id="evt_r1").status_code == 200
    assert razorpay_webhook(client, "refund.processed", payload, event_id="evt_r2").status_code == 200
    refund.refresh_from_db()
    payment.refresh_from_db()
    assert (refund.status, refund.gateway_refund_id) == ("PROCESSED", "rfnd_1")
    assert (payment.refunded_amount, payment.status) == (Decimal("2000.00"), "REFUNDED")


def test_refund_refused_by_the_gateway_can_be_retried(requester, manager, approved, razorpay):
    razorpay_paid(requester, approved, razorpay)
    desk = client_for(manager)
    desk.post(f"/api/bookings/{approved.pk}/cancel", {"full_refund": True}, format="json")
    refund = Refund.objects.get()
    razorpay.on("POST", "/payments/pay_XYZ/refund", {"error": {"description": "Insufficient balance"}}, status=400)
    result = desk.post(f"/api/refunds/{refund.pk}/issue").data
    assert (result["status"], result["failure_reason"]) == ("FAILED", "Insufficient balance")
    assert desk.get("/api/desk").data["refunds_due"] == 1
    razorpay.on("POST", "/payments/pay_XYZ/refund", {"id": "rfnd_2", "status": "processed"})
    assert desk.post(f"/api/refunds/{refund.pk}/issue").data["status"] == "PROCESSED"


def test_refund_with_no_answer_is_never_assumed_to_have_failed(requester, manager, approved, razorpay):
    razorpay_paid(requester, approved, razorpay)
    desk = client_for(manager)
    desk.post(f"/api/bookings/{approved.pk}/cancel", {"full_refund": True}, format="json")
    refund = Refund.objects.get()
    razorpay.on("POST", "/payments/pay_XYZ/refund", requests.Timeout())
    result = desk.post(f"/api/refunds/{refund.pk}/issue").data
    assert result["status"] == "PROCESSING" and "could not be reached" in result["failure_reason"]
    assert desk.post(f"/api/refunds/{refund.pk}/issue").status_code == 409  # no second attempt while unknown

    Refund.objects.filter(pk=refund.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    # The gateway did receive it: the scheduled check finds it by the note and settles it.
    found = {"items": [{"id": "rfnd_7", "status": "processed", "notes": {"refund": str(refund.pk)}}]}
    razorpay.on("GET", "/payments/pay_XYZ/refunds", found)
    assert services.reconcile() == 1
    refund.refresh_from_db()
    assert (refund.status, refund.gateway_refund_id) == ("PROCESSED", "rfnd_7")


def test_refund_the_gateway_never_received_becomes_retryable(requester, manager, approved, razorpay):
    razorpay_paid(requester, approved, razorpay)
    desk = client_for(manager)
    desk.post(f"/api/bookings/{approved.pk}/cancel", {"full_refund": True}, format="json")
    refund = Refund.objects.get()
    razorpay.on("POST", "/payments/pay_XYZ/refund", requests.ConnectionError())
    desk.post(f"/api/refunds/{refund.pk}/issue")
    Refund.objects.filter(pk=refund.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    razorpay.on("GET", "/payments/pay_XYZ/refunds", {"items": []})
    assert services.reconcile() == 1
    refund.refresh_from_db()
    assert refund.status == "FAILED" and "Issue it again" in refund.failure_reason
    assert Payment.objects.get().refunded_amount == 0


def test_mobikwik_refund_request_and_status(client, requester, manager, approved, mobikwik):
    payment, _ = open_order(client_for(requester), approved, "mobikwik")
    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(payment, "0"))
    assert services.check(payment)
    desk = client_for(manager)
    desk.post(f"/api/bookings/{approved.pk}/refunds", {"amount": "500", "reason": "Left a day early"}, format="json")
    refund = Refund.objects.get()
    mobikwik.on(
        "POST",
        "/api/payments/v1/refund",
        {"status": True, "message": {"code": 100}, "data": {"refundStatus": "PENDING"}},
    )
    assert desk.post(f"/api/refunds/{refund.pk}/issue").data["status"] == "PROCESSING"
    call = mobikwik.last("/api/payments/v1/refund")
    assert json.loads(call.data) == {
        "merchantIdentifier": "merchant-1", "orderId": payment.order_id, "refundType": "P",
        "refundAmount": "50000", "merchantRefundId": refund.pk.hex,
    }  # fmt: skip
    assert call.headers["checksum"] == sign("zaak-secret", call.data)

    Refund.objects.filter(pk=refund.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    done = [{"merchantRefId": refund.pk.hex, "amount": "50000", "refundStatus": "SUCCESS"}]
    mobikwik.on("POST", "/api/payments/v1/status", zaakpay_status(payment, "4", refunds=done))
    assert services.reconcile() == 1
    refund.refresh_from_db()
    assert refund.status == "PROCESSED" and Payment.objects.get().refunded_amount == Decimal("500.00")

    refused = {"status": False, "message": {"code": 200, "text": "Already refunded"}}
    desk.post(f"/api/bookings/{approved.pk}/refunds", {"amount": "100", "reason": "Again"}, format="json")
    again = Refund.objects.exclude(pk=refund.pk).get()
    mobikwik.on("POST", "/api/payments/v1/refund", refused)
    assert desk.post(f"/api/refunds/{again.pk}/issue").data["failure_reason"] == "Already refunded"


# --- Receipts -----------------------------------------------------------------
def test_receipt_is_for_the_payer_and_the_desk(clients, requester, approved):
    url = f"/api/bookings/{approved.pk}/receipt.pdf"
    assert clients["requester"].get(url).status_code == 404  # nothing paid yet
    pay(clients["requester"], approved.pk)
    resp = clients["requester"].get(url)
    assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-" and "no-store" in resp["Cache-Control"]
    assert clients["manager"].get(url).status_code == 200
    for name in ("external", "approver"):
        assert clients[name].get(url).status_code == 404, name
    assert AuditLog.objects.filter(action="receipt.downloaded").count() == 2


def test_receipt_lists_booking_id_payment_reference_and_refunds(requester, manager, paid):
    from django.template.loader import render_to_string

    from apps.payments import receipts

    client_for(manager).post(f"/api/bookings/{paid.pk}/refunds", {"amount": "500", "reason": "Goodwill"}, format="json")
    client_for(manager).post(f"/api/refunds/{Refund.objects.get().pk}/issue")
    captured_context = {}
    original = receipts.render_pdf
    receipts.render_pdf = lambda template, context: captured_context.update(context) or original(template, context)
    try:
        assert receipts.receipt_pdf(Booking.objects.get(pk=paid.pk))[:5] == b"%PDF-"
    finally:
        receipts.render_pdf = original
    html = render_to_string("payments/receipt.html", captured_context)
    payment = Payment.objects.get()
    assert paid.reference in html and payment.gateway_payment_id in html
    assert "Rs 2000.00" in html and "- Rs 500.00" in html and "Rs 1500.00" in html


def test_pdfs_cannot_pull_in_outside_files():
    from config.pdf import _refuse

    with pytest.raises(ValueError):
        _refuse("file:///etc/passwd")
