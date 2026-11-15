"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button, Card, Field, inputClass, Notice } from "@/components/ui";
import { api, fmtDateTime, inr, inrExact } from "@/lib/api";
import { useAction, useRefresh } from "@/lib/hooks";
import type { Booking, Checkout, Refund } from "@/lib/types";

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve();
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("The payment window could not be loaded. Check your connection."));
    document.body.appendChild(script);
  });
}

/** Sends the browser to a gateway's own payment page, carrying the signed order as form fields. */
function leaveForGateway(action: string, fields: Record<string, string>) {
  const form = document.createElement("form");
  form.method = "POST";
  form.action = action;
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
}

const CHECKS = 10; // how many times to ask whether the gateway has confirmed, a few seconds apart

/**
 * Paying. The gateway tells our server directly when money arrives, and only that confirms the booking.
 * After the guest pays, this panel just waits and asks the server whether it has heard yet.
 */
export function PayPanel({ booking, justReturned }: { booking: Booking; justReturned: boolean }) {
  const refresh = useRefresh();
  const gateways = useQuery({
    queryKey: ["gateways"],
    queryFn: () => api<{ id: string; label: string }[]>("/payments/gateways"),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [testOrder, setTestOrder] = useState<string | null>(null);
  // "waiting": the guest has paid (or come back from the gateway) and the server has not confirmed yet.
  const [phase, setPhase] = useState<"choose" | "waiting" | "unconfirmed">(justReturned ? "waiting" : "choose");

  useEffect(() => {
    if (phase !== "waiting") return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    let tries = 0;
    const ask = async () => {
      tries += 1;
      try {
        const latest = await api<Booking>(`/bookings/${booking.id}/payment-status`, { method: "POST" });
        if (stopped) return;
        if (latest.status !== "APPROVED") return void refresh();
        if (latest.payment && !latest.payment.pending) {
          // The gateway has answered and it was not a success.
          setError("The payment did not go through. No money was taken. You can try again.");
          return setPhase("choose");
        }
      } catch {
        // A failed check is not a failed payment. Keep waiting.
      }
      if (stopped) return;
      if (tries < CHECKS) timer = setTimeout(ask, 3000);
      else setPhase("unconfirmed");
    };
    timer = setTimeout(ask, 1500);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
    // refresh is a new function on every render; the wait must not restart because of that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, booking.id]);

  async function start(gateway: string) {
    setError("");
    setBusy(true);
    try {
      const { checkout } = await api<{ checkout: Checkout }>(`/bookings/${booking.id}/pay`, { body: { gateway } });
      if (checkout.mode === "dev") {
        setTestOrder(checkout.order_id);
      } else if (checkout.mode === "redirect") {
        leaveForGateway(checkout.action, checkout.fields);
        return; // the page is on its way out; keep the buttons disabled
      } else {
        await loadScript(checkout.script);
        if (!window.Razorpay) throw new Error("The payment window could not be loaded.");
        new window.Razorpay({
          ...checkout.options,
          // Called when the guest finishes paying. What it carries is not used: our server hears from Razorpay itself.
          handler: () => setPhase("waiting"),
        }).open();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
    setBusy(false);
  }

  async function finishTest(outcome: "paid" | "failed") {
    setError("");
    setBusy(true);
    try {
      await api("/payments/dev/complete", { body: { order_id: testOrder, outcome } });
      setTestOrder(null);
      if (outcome === "failed") setError("The payment did not go through. You can try again.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
    setBusy(false);
  }

  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">Pay {inr(booking.amount)}</h2>
      {error && <Notice tone="error">{error}</Notice>}
      {phase === "waiting" ? (
        <Notice>Checking with the payment gateway. This usually takes a few seconds. Please keep this page open.</Notice>
      ) : (
        <>
          {phase === "unconfirmed" && (
            <Notice>
              The payment gateway has not confirmed a payment yet. If money left your account, this booking will be
              confirmed on its own within a few minutes and you do not need to pay again. Otherwise, choose a payment
              option below.{" "}
              <button type="button" className="font-medium underline" onClick={() => setPhase("waiting")}>
                Check again
              </button>
            </Notice>
          )}
          {gateways.data?.length === 0 && (
            <Notice>Online payment is not switched on yet. Please contact the guesthouse office.</Notice>
          )}
          {testOrder ? (
            <div className="space-y-3">
              <p className="text-sm text-slate-600">
                This is the test gateway. No money moves. Choose how the pretend payment ends.
              </p>
              <div className="flex flex-wrap gap-3">
                <Button disabled={busy} onClick={() => finishTest("paid")}>
                  Payment succeeds
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => finishTest("failed")}>
                  Payment fails
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-3">
              {gateways.data?.map((gateway) => (
                <Button key={gateway.id} disabled={busy} onClick={() => start(gateway.id)}>
                  Pay with {gateway.label}
                </Button>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

const REFUND_TONES: Record<Refund["status"], string> = {
  DUE: "text-amber-800",
  PROCESSING: "text-sky-800",
  PROCESSED: "text-emerald-700",
  FAILED: "text-red-700",
};

/** What was paid and what went back, with the receipt. The desk also gets the refund controls. */
export function PaymentCard({ booking }: { booking: Booking }) {
  const money = booking.payment;
  if (!money || (money.payments.length === 0 && money.refunds.length === 0)) return null;
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">Payment</h2>
        {booking.actions.receipt && (
          <a
            href={`/api/bookings/${booking.id}/receipt.pdf`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-h-11 items-center font-medium text-brand-700 underline"
          >
            Download receipt (PDF)
          </a>
        )}
      </div>
      <ul className="space-y-2 text-sm">
        {money.payments.map((payment) => (
          <li key={payment.id} className="flex flex-wrap justify-between gap-x-4">
            <span>
              {payment.status === "FAILED" ? "Failed attempt" : payment.status === "CREATED" ? "Not completed" : "Paid"}{" "}
              through {payment.gateway_label}
              <span className="block text-slate-600">
                {payment.paid_at ? fmtDateTime(payment.paid_at) : fmtDateTime(payment.created_at)} · Reference{" "}
                {payment.gateway_payment_id || payment.order_id}
              </span>
              {payment.failure_reason && <span className="block text-red-700">{payment.failure_reason}</span>}
            </span>
            <span className={payment.status === "PAID" || payment.status === "REFUNDED" ? "font-medium" : "text-slate-500"}>
              {inrExact(payment.amount)}
            </span>
          </li>
        ))}
      </ul>
      {money.refunds.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-medium text-slate-700">Refunds</h3>
          <ul className="space-y-4 text-sm">
            {money.refunds.map((refund) => (
              <li key={refund.id}>
                <div className="flex flex-wrap justify-between gap-x-4">
                  <span>
                    <span className={`font-medium ${REFUND_TONES[refund.status]}`}>{refund.status_label}</span>
                    {refund.manual && refund.status === "PROCESSED" && " (returned by the office)"}
                    <span className="block text-slate-600">{refund.reason}</span>
                    {refund.note && <span className="block text-slate-600">Note: {refund.note}</span>}
                    {refund.failure_reason && <span className="block text-red-700">{refund.failure_reason}</span>}
                  </span>
                  <span className="font-medium">{inrExact(refund.amount)}</span>
                </div>
                {booking.actions.refund && refund.limit !== null && <IssueRefund refund={refund} />}
              </li>
            ))}
          </ul>
        </div>
      )}
      {booking.actions.refund && Number(money.refundable) > 0 && <NewRefund booking={booking} />}
    </Card>
  );
}

/** Desk: send a refund that is due (or failed), record one paid back by hand, or withdraw it. */
function IssueRefund({ refund }: { refund: Refund }) {
  const { run, error, setError, busy } = useAction();
  const [amount, setAmount] = useState(refund.amount);
  const [note, setNote] = useState("");

  const needNote = (why: string) => {
    if (note.trim()) return true;
    setError(why);
    return false;
  };

  return (
    <div className="mt-2 space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Amount to refund (₹)" hint={`Up to ${inrExact(refund.limit ?? 0)}`}>
          <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Note" hint="Needed to record a refund made by hand, or to withdraw">
          <input value={note} onChange={(e) => setNote(e.target.value)} className={inputClass} />
        </Field>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy} onClick={() => run(() => api(`/refunds/${refund.id}/issue`, { body: { amount } }))}>
          Refund through {refund.gateway_label}
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() =>
            needNote("Say in the note how the money was returned.") &&
            run(() => api(`/refunds/${refund.id}/issue`, { body: { amount, manual: true, note } }))
          }
        >
          Record as returned by hand
        </Button>
        <Button
          variant="danger"
          disabled={busy}
          onClick={() =>
            needNote("Say in the note why this refund is withdrawn.") &&
            run(() => api(`/refunds/${refund.id}/withdraw`, { body: { note } }))
          }
        >
          Withdraw
        </Button>
      </div>
    </div>
  );
}

/** Desk: a refund outside the cancellation rules. It appears above as due and is issued from there. */
function NewRefund({ booking }: { booking: Booking }) {
  const { run, error, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Give a refund
      </Button>
    );
  }
  return (
    <div className="space-y-3 border-t border-slate-200 pt-4">
      <h3 className="text-sm font-medium">Give a refund</h3>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Amount (₹)" hint={`Up to ${inrExact(booking.payment?.refundable ?? 0)}`}>
          <input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Reason (the guest sees this)">
          <input value={reason} onChange={(e) => setReason(e.target.value)} className={inputClass} />
        </Field>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button
          disabled={busy || !amount.trim() || !reason.trim()}
          onClick={async () => {
            const done = await run(() => api(`/bookings/${booking.id}/refunds`, { body: { amount, reason } }));
            if (done) {
              setOpen(false);
              setAmount("");
              setReason("");
            }
          }}
        >
          Add the refund
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
    </div>
  );
}

/** Cancelling, with what it means for money said before the button is pressed. */
export function CancelPanel({ booking, staff }: { booking: Booking; staff: boolean }) {
  const { run, error, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState(false);
  const [reason, setReason] = useState("");
  const terms = booking.payment?.refund_on_cancel ?? null;

  if (!open) {
    return (
      <Button variant="danger" onClick={() => setOpen(true)}>
        Cancel booking
      </Button>
    );
  }
  const amount = terms ? (full ? terms.full : terms.amount) : null;
  return (
    <Card className="space-y-3 border-red-300">
      <h2 className="font-semibold">Cancel this booking?</h2>
      {error && <Notice tone="error">{error}</Notice>}
      <p className="text-sm text-slate-700">
        The room will be released.{" "}
        {terms === null
          ? "Nothing has been paid, so there is nothing to refund."
          : Number(amount) > 0
            ? `${inrExact(amount ?? 0)} will be refunded${full ? "" : ` (${terms.percent}% under the cancellation rules)`}. The guesthouse office issues the refund.`
            : "This close to arrival, the cancellation rules give no refund."}
      </p>
      {staff && (
        <>
          {terms && terms.full !== terms.amount && (
            <label className="flex min-h-11 items-center gap-3 text-sm">
              <input type="checkbox" checked={full} onChange={(e) => setFull(e.target.checked)} className="size-5" />
              The guesthouse is cancelling, so refund in full ({inrExact(terms.full)})
            </label>
          )}
          <Field label="Reason (the guest sees this)">
            <input value={reason} onChange={(e) => setReason(e.target.value)} className={inputClass} />
          </Field>
        </>
      )}
      <div className="flex flex-wrap gap-3">
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => run(() => api(`/bookings/${booking.id}/cancel`, { body: { full_refund: full, reason } }))}
        >
          Yes, cancel the booking
        </Button>
        <Button variant="secondary" disabled={busy} onClick={() => setOpen(false)}>
          Keep the booking
        </Button>
      </div>
    </Card>
  );
}

/** Desk: tick each arriving guest once their ID has been compared with the uploaded copy, then check in. */
export function CheckInPanel({ booking }: { booking: Booking }) {
  const { run, error, busy } = useAction();
  const [checked, setChecked] = useState<string[]>([]);
  const toggle = (id: string) =>
    setChecked((list) => (list.includes(id) ? list.filter((g) => g !== id) : [...list, id]));
  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">Check in</h2>
      <p className="text-sm text-slate-600">
        Compare each guest&apos;s original ID with the uploaded copy, then tick the guests who have arrived. They are
        entered in the guest register.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <ul className="space-y-2">
        {booking.guests.map((guest) => (
          <li key={guest.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
            <label className="flex min-h-11 items-center gap-3">
              <input
                type="checkbox"
                className="size-5"
                checked={checked.includes(guest.id)}
                disabled={!guest.id_document}
                onChange={() => toggle(guest.id)}
              />
              <span>
                {guest.name}
                <span className="block text-sm text-slate-600">ID matches the uploaded copy</span>
              </span>
            </label>
            {guest.id_document ? (
              <a
                href={`/api/documents/${guest.id_document}/download`}
                target="_blank"
                rel="noreferrer"
                className="text-sm text-brand-700 underline"
              >
                View ID copy (this view is logged)
              </a>
            ) : (
              <span className="text-sm text-red-700">No ID copy was uploaded</span>
            )}
          </li>
        ))}
      </ul>
      <Button
        disabled={busy || checked.length === 0}
        onClick={() => run(() => api(`/bookings/${booking.id}/check-in`, { body: { guests: checked } }))}
      >
        {checked.length > 1 ? `Check in ${checked.length} guests` : "Check in"}
      </Button>
    </Card>
  );
}

export function CheckOutPanel({ booking }: { booking: Booking }) {
  const { run, error, busy } = useAction();
  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">Check out</h2>
      <p className="text-sm text-slate-600">
        Records the departure time in the guest register and frees room {booking.room_number}.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <Button disabled={busy} onClick={() => run(() => api(`/bookings/${booking.id}/check-out`, { method: "POST" }))}>
        Check out
      </Button>
    </Card>
  );
}
