"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card, Field, inputClass, Notice } from "@/components/ui";
import { api, fmtDate, fmtDateTime, inr } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { Availability, Booking } from "@/lib/types";

const PAID = ["CONFIRMED", "ALLOTTED"];

/** Where a change of dates on a paid booking stands, with a way to take it back while it is open. */
export function ChangeNotice({ booking }: { booking: Booking }) {
  const { run, error, busy } = useAction();
  const change = booking.date_change;
  if (!change || change.status === "WITHDRAWN") return null;
  const asked = `${fmtDate(change.check_in)} to ${fmtDate(change.check_out)}`;
  const was = `${fmtDate(change.old_check_in)} to ${fmtDate(change.old_check_out)}`;
  const withdraw = booking.actions.withdraw_change && (
    <Button
      variant="secondary"
      disabled={busy}
      onClick={() => run(() => api(`/bookings/${booking.id}/date-change`, { method: "DELETE" }))}
    >
      Keep the current dates
    </Button>
  );

  if (change.status === "PENDING") {
    return (
      <Card className="space-y-3 border-amber-300">
        <h2 className="font-semibold">Change of dates waiting for approval</h2>
        <p className="text-sm text-slate-700">
          New dates asked for: <strong>{asked}</strong> ({change.nights} night(s), {inr(change.amount)} in all). The
          booking keeps its current dates until the change is approved, and the new dates are held until{" "}
          {fmtDateTime(change.expires_at)}.
        </p>
        <p className="text-sm text-slate-700">{moneyLine(change)}</p>
        {error && <Notice tone="error">{error}</Notice>}
        {withdraw}
      </Card>
    );
  }
  if (change.status === "AWAITING_PAYMENT") {
    return (
      <Card className="space-y-3 border-amber-300">
        <h2 className="font-semibold">Change of dates approved</h2>
        <p className="text-sm text-slate-700">
          The stay moves to <strong>{asked}</strong> once the balance of {inr(change.balance)} is paid. Pay by{" "}
          {fmtDateTime(change.expires_at)}, or the booking keeps its current dates.
        </p>
        {error && <Notice tone="error">{error}</Notice>}
        {withdraw}
      </Card>
    );
  }
  if (change.status === "APPLIED") {
    return (
      <Notice tone="success">
        The dates were changed from {was} to {asked}.
        {Number(change.refund) > 0 && ` The difference of ${inr(change.refund)} goes back to the guest.`}
      </Notice>
    );
  }
  return (
    <Notice>
      {change.status === "REJECTED"
        ? `The change to ${asked} was not approved, so the booking keeps its dates.`
        : `The change to ${asked} lapsed, so the booking keeps its dates.`}
      {change.comment && ` “${change.comment}”`}
    </Notice>
  );
}

function moneyLine(change: { balance: string; refund: string }) {
  if (Number(change.balance) > 0) return `If it is approved, a balance of ${inr(change.balance)} is to be paid.`;
  if (Number(change.refund) > 0) return `If it is approved, ${inr(change.refund)} is refunded.`;
  return "The price stays the same.";
}

/** Ask for new dates. Shows what the new stay would cost before anything is sent. */
export function ChangeDatesPanel({ booking, staff }: { booking: Booking; staff: boolean }) {
  const { run, error, setError, busy } = useAction();
  const [open, setOpen] = useState(false);
  const [checkIn, setCheckIn] = useState(booking.check_in);
  const [checkOut, setCheckOut] = useState(booking.check_out);
  const paid = PAID.includes(booking.status);
  const moved = checkIn !== booking.check_in || checkOut !== booking.check_out;
  const sensible = !!checkIn && !!checkOut && checkOut > checkIn;

  const quote = useQuery({
    queryKey: ["availability", checkIn, checkOut],
    queryFn: () => api<Availability>(`/availability?check_in=${checkIn}&check_out=${checkOut}`),
    enabled: open && moved && sensible,
    retry: false,
  });
  // Only the price is taken from here. Whether the dates are free is for the server to say when the change
  // is sent, because this booking's own nights do not count against it.
  const amount = quote.data?.results.find((r) => r.room_type === booking.room_type)?.amount ?? null;
  const difference = amount === null ? 0 : Number(amount) - Number(booking.amount);

  if (!open) {
    return (
      <Card className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Need different dates?</h2>
          <p className="text-sm text-slate-600">
            {paid
              ? "Ask for new dates. The booking stays as it is until the change is approved."
              : "Change the dates. The request goes back for approval with the new dates."}
          </p>
        </div>
        <Button variant="secondary" onClick={() => setOpen(true)}>
          Change dates
        </Button>
      </Card>
    );
  }

  return (
    <Card className="space-y-4 border-brand-600">
      <h2 className="font-semibold">Change dates</h2>
      <p className="text-sm text-slate-600">
        {paid
          ? "The new dates need approval. Until then this booking keeps its dates and its room. If the new stay costs more, the difference is paid after approval; if it costs less, the difference is refunded."
          : "The request goes back for approval with the new dates, at the price in force on the new check-in date."}
        {staff && paid && " As the desk, you can ask for a change right up to check-in."}
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="New check-in">
          <input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} className={inputClass} />
        </Field>
        <Field label="New check-out">
          <input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} className={inputClass} />
        </Field>
      </div>
      {moved && sensible && quote.error && <p className="text-sm text-red-700">{quote.error.message}</p>}
      {moved && sensible && quote.data && (
        <p className="text-sm text-slate-700" role="status">
          {amount === null ? (
            "No price is set for those dates."
          ) : (
            <>
              {quote.data.nights} night(s) for <strong>{inr(amount)}</strong>.{" "}
              {difference > 0
                ? `That is ${inr(difference)} more than now.`
                : difference < 0
                  ? `That is ${inr(-difference)} less than now.`
                  : "The price stays the same."}
            </>
          )}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button
          disabled={busy || !moved || !sensible}
          onClick={async () => {
            const ok = await run(() =>
              api(`/bookings/${booking.id}/date-change`, { body: { check_in: checkIn, check_out: checkOut } }),
            );
            if (ok) setOpen(false);
          }}
        >
          {paid ? "Ask for these dates" : "Change dates"}
        </Button>
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => {
            setError("");
            setCheckIn(booking.check_in);
            setCheckOut(booking.check_out);
            setOpen(false);
          }}
        >
          Not now
        </Button>
      </div>
    </Card>
  );
}

/** The approver's answer to new dates on a paid booking. */
export function ChangeDecisionPanel({ booking }: { booking: Booking }) {
  const { run, error, busy } = useAction();
  const [comment, setComment] = useState("");
  const change = booking.date_change;
  if (!change) return null;
  const decide = (decision: "APPROVED" | "REJECTED") =>
    run(() => api(`/bookings/${booking.id}/date-change/decide`, { body: { decision, comment } }));

  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">Decide the change of dates</h2>
      <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
        <dt className="text-slate-600">Now</dt>
        <dd>
          {fmtDate(change.old_check_in)} to {fmtDate(change.old_check_out)} · {inr(change.old_amount)}
        </dd>
        <dt className="text-slate-600">Asked for</dt>
        <dd className="font-medium">
          {fmtDate(change.check_in)} to {fmtDate(change.check_out)} · {change.nights} night(s) · {inr(change.amount)}
        </dd>
        <dt className="text-slate-600">Money</dt>
        <dd>{moneyLine(change)}</dd>
      </dl>
      <p className="text-sm text-slate-600">
        This booking is already paid. If you reject the change, the guest keeps the current dates. A comment is
        required to reject.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <Field label="Comment for the guest">
        <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} className={`${inputClass} py-2`} />
      </Field>
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy} onClick={() => decide("APPROVED")}>
          Approve new dates
        </Button>
        <Button variant="danger" disabled={busy || !comment.trim()} onClick={() => decide("REJECTED")}>
          Reject change
        </Button>
      </div>
    </Card>
  );
}
