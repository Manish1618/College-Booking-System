"""Payment gateways behind one interface.

The rest of the code never talks to a gateway directly. It asks an adapter to open an order, to say what
the browser needs for checkout, to turn a webhook into verified events, to look a payment up, and to
refund. Three adapters exist: "dev" simulates a gateway so the whole flow runs without keys, "razorpay"
and "mobikwik" (MobiKwik's gateway, Zaakpay) call the real services over HTTPS.

Nothing here changes a booking. Adapters return Event objects and apps.payments.services acts on them.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import parse_qs

import requests
from django.conf import settings
from django.utils.encoding import force_bytes

from .models import Payment

TIMEOUT = 15  # seconds, for every call to a gateway

PAID = "payment.paid"
FAILED = "payment.failed"
REFUND_PROCESSED = "refund.processed"
REFUND_FAILED = "refund.failed"

# What a refund call or lookup can say.
PROCESSED, PENDING, REJECTED, UNKNOWN = "processed", "pending", "failed", "unknown"


class GatewayError(Exception):
    """The gateway answered and refused. The message is safe to show to staff."""


class GatewayUnreachable(GatewayError):
    """No usable answer, so the outcome is not known. Never treat this as a refusal."""


class BadSignature(Exception):
    """A webhook whose signature does not match. Nothing in it can be trusted."""


@dataclass(frozen=True)
class Event:
    kind: str
    event_id: str = ""  # the gateway's id for this delivery, when it gives one
    order_id: str = ""
    payment_id: str = ""
    amount: Decimal | None = None
    refund_ref: str = ""  # our reference for one refund attempt, echoed back by the gateway
    refund_id: str = ""  # the gateway's refund id
    reason: str = ""


def to_paise(amount):
    return int((Decimal(amount) * 100).to_integral_value())


def from_paise(paise):
    return (Decimal(str(paise)) / 100).quantize(Decimal("0.01"))


def _hmac_hex(secret, message):
    return hmac.new(force_bytes(secret), force_bytes(message), hashlib.sha256).hexdigest()


def _same(a, b):
    return hmac.compare_digest(force_bytes(a or ""), force_bytes(b or ""))


class Gateway:
    name = ""
    # False when the gateway refuses a second attempt on the same order id.
    reuse_orders = True
    # True when the guest can try again inside the same order after an attempt fails. A failed attempt
    # then says nothing final about the order, which must stay open and keep being looked up.
    retries_within_order = False

    def create_order(self, payment, booking):
        """Opens an order for payment.amount and returns the id to store as Payment.order_id."""
        raise NotImplementedError

    def checkout(self, payment, booking):
        """What the browser needs to let the guest pay this order."""
        raise NotImplementedError

    def parse_webhook(self, body, headers):
        """Verified events from a webhook delivery. Raises BadSignature if it is not genuine."""
        raise NotImplementedError

    def payment_status(self, payment):
        """Asks the gateway about an order. Returns a PAID or FAILED event, or None while undecided."""
        return None

    def refund(self, payment, refund):
        """Asks for a refund. Returns (gateway refund id, PROCESSED | PENDING | REJECTED)."""
        raise NotImplementedError

    def refund_status(self, payment, refund):
        """PROCESSED, PENDING, REJECTED, or UNKNOWN when the gateway has no record of the refund."""
        return PENDING

    def _request(self, method, url, **kwargs):
        try:
            response = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise GatewayUnreachable(f"{self.label} could not be reached. Please try again.") from exc
        if response.status_code >= 500:
            raise GatewayUnreachable(f"{self.label} is having trouble. Please try again.")
        try:
            data = response.json()
        except ValueError as exc:
            raise GatewayUnreachable(f"{self.label} sent an answer that could not be read.") from exc
        return response.status_code, data

    @property
    def label(self):
        return self.name.title()


# --- Simulated gateway ------------------------------------------------------
class DevGateway(Gateway):
    """A stand-in for a real gateway. It signs its own webhooks, so the real verification path runs.

    Listed in PAYMENT_GATEWAYS only for development and demos: anyone signed in can "pay" with it.
    """

    name = "dev"
    label = "The test gateway"
    signature_header = "X-Dev-Signature"

    def _secret(self):
        return _hmac_hex(settings.SECRET_KEY, "dev-payment-gateway")

    def create_order(self, payment, booking):
        return f"dev_{uuid.uuid4().hex}"

    def checkout(self, payment, booking):
        return {"mode": "dev", "order_id": payment.order_id}

    def webhook_for(self, payment, outcome):
        """The (body, headers) a gateway would send for this order. Used by the simulate endpoint and tests."""
        paid = outcome == "paid"
        body = json.dumps(
            {
                "id": f"devevt_{uuid.uuid4().hex}",
                "event": PAID if paid else FAILED,
                "order_id": payment.order_id,
                "payment_id": f"devpay_{uuid.uuid4().hex[:16]}",
                "amount": to_paise(payment.amount),
                "reason": "" if paid else "The simulated payment was declined.",
            }
        ).encode()
        return body, {self.signature_header: _hmac_hex(self._secret(), body)}

    def parse_webhook(self, body, headers):
        if not _same(headers.get(self.signature_header), _hmac_hex(self._secret(), body)):
            raise BadSignature
        data = json.loads(body)
        if data.get("event") not in (PAID, FAILED):
            return []
        return [
            Event(
                kind=data["event"],
                event_id=str(data.get("id", "")),
                order_id=str(data.get("order_id", "")),
                payment_id=str(data.get("payment_id", "")),
                amount=from_paise(data.get("amount", 0)),
                reason=str(data.get("reason", "")),
            )
        ]

    def refund(self, payment, refund):
        return f"devrfnd_{uuid.uuid4().hex[:16]}", PROCESSED

    def refund_status(self, payment, refund):
        return PROCESSED if refund.gateway_refund_id else UNKNOWN


# --- Razorpay ---------------------------------------------------------------
class RazorpayGateway(Gateway):
    """Razorpay Orders, Standard Checkout, webhooks and refunds, called directly over HTTPS."""

    name = "razorpay"
    api = "https://api.razorpay.com/v1"
    retries_within_order = True

    def _call(self, method, path, payload=None, params=None):
        status, data = self._request(
            method,
            f"{self.api}{path}",
            json=payload,
            params=params,
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
        )
        if status >= 400:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            raise GatewayError(error.get("description") or "Razorpay refused the request.")
        return data

    def create_order(self, payment, booking):
        order = self._call(
            "POST",
            "/orders",
            {
                "amount": to_paise(payment.amount),
                "currency": "INR",
                # Unique per order, so a repeated request cannot open a second order for the same payment.
                "receipt": payment.pk.hex,
                "notes": {"booking": booking.reference},
            },
        )
        return order["id"]

    def checkout(self, payment, booking):
        user = booking.requester
        return {
            "mode": "razorpay",
            "script": "https://checkout.razorpay.com/v1/checkout.js",
            "options": {
                "key": settings.RAZORPAY_KEY_ID,
                "order_id": payment.order_id,
                "amount": to_paise(payment.amount),
                "currency": "INR",
                "name": settings.SITE_NAME,
                "description": f"Booking {booking.reference}",
                "prefill": {"name": user.name, "email": user.email or "", "contact": user.phone or ""},
            },
        }

    def parse_webhook(self, body, headers):
        # The signature covers the bytes exactly as they arrived, so it is checked before any parsing.
        expected = _hmac_hex(settings.RAZORPAY_WEBHOOK_SECRET, body)
        if not _same(headers.get("X-Razorpay-Signature"), expected):
            raise BadSignature
        data = json.loads(body)
        kind = data.get("event", "")
        event_id = headers.get("X-Razorpay-Event-Id") or hashlib.sha256(body).hexdigest()
        payload = data.get("payload", {})
        payment = payload.get("payment", {}).get("entity", {})
        if kind in ("payment.captured", "order.paid") and payment.get("status") == "captured":
            return [self._payment_event(PAID, payment, event_id)]
        if kind == "payment.failed":
            return [self._payment_event(FAILED, payment, event_id)]
        if kind in ("refund.processed", "refund.failed"):
            refund = payload.get("refund", {}).get("entity", {})
            return [
                Event(
                    kind=REFUND_PROCESSED if kind == "refund.processed" else REFUND_FAILED,
                    event_id=event_id,
                    refund_id=str(refund.get("id", "")),
                    refund_ref=str((refund.get("notes") or {}).get("refund", "")),
                    payment_id=str(refund.get("payment_id", "")),
                    amount=from_paise(refund.get("amount", 0)),
                    reason="Razorpay could not complete the refund." if kind == "refund.failed" else "",
                )
            ]
        return []

    def _payment_event(self, kind, entity, event_id=""):
        return Event(
            kind=kind,
            event_id=event_id,
            order_id=str(entity.get("order_id", "")),
            payment_id=str(entity.get("id", "")),
            amount=from_paise(entity.get("amount", 0)),
            reason=str(entity.get("error_description") or "")[:255] if kind == FAILED else "",
        )

    def payment_status(self, payment):
        items = self._call("GET", f"/orders/{payment.order_id}/payments").get("items", [])
        for item in items:
            if item.get("status") == "captured":
                return self._payment_event(PAID, item)
        return None  # a failed attempt can still be followed by a successful one on the same order

    def refund(self, payment, refund):
        result = self._call(
            "POST",
            f"/payments/{payment.gateway_payment_id}/refund",
            # The note lets a webhook or a later lookup find this attempt even if this answer is lost.
            {"amount": to_paise(refund.amount), "notes": {"refund": refund.reference}},
        )
        return result["id"], self._refund_state(result)

    def refund_status(self, payment, refund):
        if refund.gateway_refund_id:
            return self._refund_state(self._call("GET", f"/refunds/{refund.gateway_refund_id}"))
        for item in self._every("GET", f"/payments/{payment.gateway_payment_id}/refunds"):
            if (item.get("notes") or {}).get("refund") == refund.reference:
                refund.gateway_refund_id = item["id"]
                return self._refund_state(item)
        return UNKNOWN  # safe to say only because every page was read

    PAGE = 100  # the most Razorpay returns in one list call; without `count` it returns 10

    def _every(self, method, path):
        """Every item of a list. Stopping at the first page could miss a refund that exists."""
        skip = 0
        while True:
            items = self._call(method, path, params={"count": self.PAGE, "skip": skip}).get("items") or []
            yield from items
            if len(items) < self.PAGE:
                return
            skip += len(items)

    @staticmethod
    def _refund_state(data):
        return {"processed": PROCESSED, "failed": REJECTED}.get(data.get("status"), PENDING)


# --- MobiKwik (Zaakpay) -----------------------------------------------------
class MobikwikGateway(Gateway):
    """MobiKwik's payment gateway, Zaakpay: redirect checkout, status lookup, webhook and refunds.

    The guest's browser is sent to Zaakpay and comes back to our return URL. What the browser brings back
    is never believed. The return, the webhook and the scheduled check all end in the same place: a
    server-to-server status lookup, and only its answer can mark a payment paid.
    """

    name = "mobikwik"
    label = "MobiKwik"
    reuse_orders = False
    SUCCESS, FAILURE = "0", "1"  # txnStatus values in the status lookup

    def _signed_json(self, path, payload):
        body = json.dumps(payload, separators=(",", ":"))
        status, data = self._request(
            "POST",
            f"{settings.MOBIKWIK_BASE_URL}{path}",
            data=body,  # sent exactly as signed
            headers={"Content-Type": "application/json", "checksum": _hmac_hex(settings.MOBIKWIK_SECRET_KEY, body)},
        )
        if status >= 400 or not isinstance(data, dict):
            raise GatewayError("MobiKwik refused the request.")
        return data

    def create_order(self, payment, booking):
        return f"GH{payment.pk.hex}"  # the order is opened by the checkout form itself

    def checkout(self, payment, booking):
        fields = {
            "amount": str(to_paise(payment.amount)),
            "buyerEmail": booking.requester.email or settings.MOBIKWIK_FALLBACK_EMAIL,
            "currency": "INR",
            "merchantIdentifier": settings.MOBIKWIK_MERCHANT_ID,
            "mode": "0",
            "orderId": payment.order_id,
            "productDescription": f"Guesthouse booking {booking.reference}",
            "returnUrl": f"{settings.SITE_URL}/api/payments/mobikwik/return",
            "txnType": "1",
        }
        # Every non-empty field, in alphabetical order, each as name=value followed by "&".
        message = "".join(f"{name}={fields[name]}&" for name in sorted(fields) if fields[name])
        fields["checksum"] = _hmac_hex(settings.MOBIKWIK_SECRET_KEY, message)
        return {
            "mode": "redirect",
            "action": f"{settings.MOBIKWIK_BASE_URL}/api/paymentTransact/V13",
            "fields": fields,
        }

    def _lookup(self, order_id):
        data = self._signed_json(
            "/api/payments/v1/status", {"merchantIdentifier": settings.MOBIKWIK_MERCHANT_ID, "orderId": order_id}
        )
        for order in (data.get("data") or {}).get("orders") or []:
            if (order.get("orderDetail") or {}).get("orderId") == order_id:
                return order
        return None

    def payment_status(self, payment):
        order = self._lookup(payment.order_id)
        return None if order is None else self._payment_event_from(payment, order)

    def parse_webhook(self, body, headers):
        """The webhook proves it is genuine and names orders. Their state then comes from a lookup."""
        text = body.decode("utf-8", "replace")
        if text.lstrip().startswith("{"):
            posted = json.loads(text)
            txn_data, checksum = posted.get("txnData"), posted.get("checksum")
            if not isinstance(txn_data, str):
                raise BadSignature  # the checksum covers the exact string, which a parsed object has lost
        else:
            form = parse_qs(text, keep_blank_values=True)
            txn_data, checksum = form.get("txnData", [""])[0], form.get("checksum", [""])[0]
        if not txn_data or not _same(checksum, _hmac_hex(settings.MOBIKWIK_SECRET_KEY, txn_data)):
            raise BadSignature
        data = json.loads(txn_data)
        events = []
        rows = [*(data.get("txns") or []), *(data.get("refunds") or [])]
        order_ids = {str(row.get("orderId") or row.get("orderid") or "") for row in rows} - {""}
        for payment in Payment.objects.filter(gateway=self.name, order_id__in=order_ids):
            order = self._lookup(payment.order_id)
            if order is None:
                continue
            if event := self._payment_event_from(payment, order):
                events.append(event)
            events.extend(self._refund_events_from(order))
        return events

    def _payment_event_from(self, payment, order):
        detail = order.get("orderDetail") or {}
        status = str(order.get("txnStatus", ""))
        if status == self.SUCCESS and detail.get("amount") is not None:
            return Event(
                kind=PAID,
                order_id=payment.order_id,
                payment_id=str(detail.get("txnId", "")),
                amount=from_paise(detail["amount"]),
            )
        if status == self.FAILURE:
            reason = str(order.get("responseDescription") or "The payment did not go through.")[:255]
            return Event(kind=FAILED, order_id=payment.order_id, reason=reason)
        return None  # pending, or a later state such as refunded that this lookup does not act on

    def _refund_states(self, order):
        """The state of each refund on an order, by our reference.

        One refund can be listed more than once, for example as pending and again as successful. The
        records are read together: money returned outweighs everything, and a refund still in progress
        outweighs a failure.
        """
        states = {}
        for detail in (order or {}).get("refundDetails") or []:
            reference, state = str(detail.get("merchantRefId", "")), self._refund_state(detail)
            if reference not in states or self.WEIGHT[state] > self.WEIGHT[states[reference]]:
                states[reference] = state
        return states

    WEIGHT = {REJECTED: 0, PENDING: 1, PROCESSED: 2}

    def _refund_events_from(self, order):
        return [
            Event(
                kind=REFUND_PROCESSED if state == PROCESSED else REFUND_FAILED,
                refund_ref=reference,
                refund_id=reference,
                reason="MobiKwik could not complete the refund." if state == REJECTED else "",
            )
            for reference, state in self._refund_states(order).items()
            if state in (PROCESSED, REJECTED)
        ]

    def refund(self, payment, refund):
        reference = refund.reference  # new for every attempt: the gateway refuses a reused one
        data = self._signed_json(
            "/api/payments/v1/refund",
            {
                "merchantIdentifier": settings.MOBIKWIK_MERCHANT_ID,
                "orderId": payment.order_id,
                "refundType": "F" if refund.amount == payment.amount else "P",
                "refundAmount": str(to_paise(refund.amount)),
                "merchantRefundId": reference,
            },
        )
        message = data.get("message") or {}
        code = str(message.get("code", ""))
        if code == "1036":  # "something went wrong": the docs say the refund may or may not exist
            raise GatewayUnreachable("MobiKwik could not say whether the refund went through.")
        if not data.get("status") or code != "100":
            raise GatewayError(message.get("text") or "MobiKwik refused the refund.")
        return reference, self._refund_state(data.get("data") or {})

    def refund_status(self, payment, refund):
        state = self._refund_states(self._lookup(payment.order_id)).get(refund.reference)
        if state is None:
            return UNKNOWN
        refund.gateway_refund_id = refund.reference
        return state

    @staticmethod
    def _refund_state(detail):
        # The docs show this both as words and as numbers (1 success, 2 pending, 3 failed).
        status = str(detail.get("refundStatus", "")).upper()
        if status in ("SUCCESS", "1"):
            return PROCESSED
        if status in ("FAILED", "3"):
            return REJECTED
        return PENDING


ADAPTERS = {gateway.name: gateway for gateway in (DevGateway, RazorpayGateway, MobikwikGateway)}


def enabled():
    """Gateway names a guest may pay with, in the configured order."""
    return [name for name in settings.PAYMENT_GATEWAYS if name in ADAPTERS]


def adapter(name):
    """The adapter for a gateway that has taken money before, whether or not it is still offered."""
    return ADAPTERS[name]()
