"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button, Card, Field, inputClass, Loading, Notice, StatusBadge } from "@/components/ui";
import { api, fmtDate, fmtDateTime, inr } from "@/lib/api";
import { useRefresh } from "@/lib/hooks";
import type { Booking, Room } from "@/lib/types";

const DECISIONS = { APPROVED: "Approved", REJECTED: "Rejected", SENT_BACK: "Sent back" } as Record<string, string>;

export default function BookingPage() {
  const { id } = useParams<{ id: string }>();
  const carried = useSearchParams().get("problem");
  const refresh = useRefresh();
  const booking = useQuery({ queryKey: ["booking", id], queryFn: () => api<Booking>(`/bookings/${id}`) });
  const [error, setError] = useState(carried ?? "");
  const [busy, setBusy] = useState(false);

  async function act(path: string, body?: unknown) {
    setError("");
    setBusy(true);
    try {
      await api(`/bookings/${id}/${path}`, body === undefined ? { method: "POST" } : { body });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (booking.isLoading) return <Loading />;
  if (booking.error || !booking.data) return <Notice tone="error">This booking was not found.</Notice>;
  const b = booking.data;
  const letter = b.documents.find((d) => d.type === "RECOMMENDATION_LETTER");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-slate-600">Booking {b.reference}</p>
          <h1 className="text-2xl font-semibold">
            {b.room_type_name}
            {b.room_number && ` · Room ${b.room_number}`}
          </h1>
          <p className="text-slate-700">
            {fmtDate(b.check_in)} to {fmtDate(b.check_out)} · {b.nights} night(s)
          </p>
        </div>
        <StatusBadge status={b.status} label={b.status_label} />
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      <NextStep booking={b} />

      {b.actions.decide && <DecisionPanel busy={busy} onDecide={(body) => act("decide", body)} />}
      {b.actions.allot && <AllotPanel booking={b} busy={busy} onAllot={(room) => act("allot", { room })} />}
      {b.actions.pay && <PayPanel booking={b} busy={busy} onPay={(gateway) => act("pay", { gateway })} />}
      {b.actions.edit && <FixPanel booking={b} onError={setError} />}

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <h2 className="mb-3 font-semibold">Stay</h2>
          <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
            <dt className="text-slate-600">Type</dt>
            <dd>{b.category === "OFFICIAL" ? "Official stay" : "Personal stay"}</dd>
            <dt className="text-slate-600">Purpose</dt>
            <dd>{b.purpose}</dd>
            <dt className="text-slate-600">Rate</dt>
            <dd>{inr(b.price_per_night)} per night</dd>
            <dt className="text-slate-600">Total</dt>
            <dd className="font-medium">{inr(b.amount)}</dd>
            <dt className="text-slate-600">Requested by</dt>
            <dd>
              {b.requester.name || "—"}
              <span className="block text-slate-600">{b.requester.email ?? b.requester.phone}</span>
              {b.requester.department && <span className="block text-slate-600">{b.requester.department}</span>}
            </dd>
          </dl>
        </Card>

        <Card>
          <h2 className="mb-3 font-semibold">{b.category === "OFFICIAL" ? "Recommendation letter" : "Student"}</h2>
          {b.category === "OFFICIAL" ? (
            letter ? (
              <a
                href={`/api/documents/${letter.id}/download`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex min-h-11 items-center font-medium text-brand-700 underline"
              >
                View the letter ({letter.content_type === "application/pdf" ? "PDF" : "image"})
              </a>
            ) : (
              <p className="text-sm text-slate-600">Not uploaded yet.</p>
            )
          ) : b.student_link ? (
            <dl className="grid grid-cols-[8rem_1fr] gap-y-2 text-sm">
              <dt className="text-slate-600">Name</dt>
              <dd>{b.student_link.student_name}</dd>
              <dt className="text-slate-600">Roll number</dt>
              <dd>{b.student_link.roll_number}</dd>
              <dt className="text-slate-600">Programme</dt>
              <dd>
                {b.student_link.programme}, year {b.student_link.year}
              </dd>
              <dt className="text-slate-600">Relationship</dt>
              <dd>{b.student_link.relationship}</dd>
              <dt className="text-slate-600">Records check</dt>
              <dd>
                {b.student_link.record_check === "MATCHED"
                  ? "Matches student records"
                  : b.student_link.record_check === "MISMATCH"
                    ? "Does not match student records"
                    : "Student records are not connected yet; please check by hand"}
              </dd>
            </dl>
          ) : (
            <p className="text-sm text-slate-600">Not entered yet.</p>
          )}
        </Card>

        <Card>
          <h2 className="mb-3 font-semibold">Guests</h2>
          <ul className="space-y-3 text-sm">
            {b.guests.map((guest) => (
              <li key={guest.id}>
                <p className="font-medium">{guest.name}</p>
                {guest.phone && (
                  <p className="text-slate-600">
                    {guest.phone} · {guest.address}
                  </p>
                )}
                {guest.has_id_document !== undefined &&
                  (guest.id_document && b.actions.allot ? (
                    <a
                      href={`/api/documents/${guest.id_document}/download`}
                      target="_blank"
                      rel="noreferrer"
                      className="text-brand-700 underline"
                    >
                      View ID copy (this view is logged)
                    </a>
                  ) : (
                    <p className={guest.has_id_document ? "text-emerald-700" : "text-red-700"}>
                      {guest.has_id_document ? "ID uploaded" : "ID not uploaded"}
                    </p>
                  ))}
              </li>
            ))}
          </ul>
        </Card>

        <Card>
          <h2 className="mb-3 font-semibold">Decisions</h2>
          {b.approvals.length === 0 ? (
            <p className="text-sm text-slate-600">No decision yet.</p>
          ) : (
            <ul className="space-y-3 text-sm">
              {b.approvals.map((approval) => (
                <li key={approval.id}>
                  <p className="font-medium">
                    {DECISIONS[approval.decision]} by {approval.approver_name}
                  </p>
                  <p className="text-slate-600">{fmtDateTime(approval.decided_at)}</p>
                  {approval.comment && <p className="mt-1">“{approval.comment}”</p>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {b.actions.cancel && (
        <Button
          variant="danger"
          disabled={busy}
          onClick={() => window.confirm("Cancel this booking? The room will be released.") && act("cancel")}
        >
          Cancel booking
        </Button>
      )}
      <p>
        <Link href="/bookings" className="text-sm text-brand-700 hover:underline">
          Back to bookings
        </Link>
      </p>
    </div>
  );
}

function NextStep({ booking: b }: { booking: Booking }) {
  const deadline = b.hold_expires_at ? fmtDateTime(b.hold_expires_at) : "";
  const text: Partial<Record<Booking["status"], string>> = {
    DRAFT: "This request is saved but not submitted. Add anything missing below, then submit it.",
    PENDING: `Waiting for approval. The dates are held until ${deadline}.`,
    SENT_BACK: "The approver sent this back. Read the comment, fix the request below and submit again.",
    APPROVED: `Approved. Payment is due by ${deadline}, or the dates are released.`,
    CONFIRMED: "Paid and confirmed. The guesthouse office will allot a room.",
    ALLOTTED: `Room ${b.room_number} is allotted. Bring the original ID at check-in.`,
    EXPIRED: "This request expired and the dates were released.",
  };
  return text[b.status] ? <Notice>{text[b.status]}</Notice> : null;
}

function DecisionPanel({ busy, onDecide }: { busy: boolean; onDecide: (body: object) => void }) {
  const [comment, setComment] = useState("");
  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">Your decision</h2>
      <p className="text-sm text-slate-600">
        Check the letter or the student details below first. A comment is required to reject or send back.
      </p>
      <Field label="Comment for the guest">
        <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} className={`${inputClass} py-2`} />
      </Field>
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy} onClick={() => onDecide({ decision: "APPROVED", comment })}>
          Approve
        </Button>
        <Button variant="secondary" disabled={busy || !comment.trim()} onClick={() => onDecide({ decision: "SENT_BACK", comment })}>
          Send back
        </Button>
        <Button variant="danger" disabled={busy || !comment.trim()} onClick={() => onDecide({ decision: "REJECTED", comment })}>
          Reject
        </Button>
      </div>
    </Card>
  );
}

function AllotPanel({ booking, busy, onAllot }: { booking: Booking; busy: boolean; onAllot: (room: string) => void }) {
  const rooms = useQuery({
    queryKey: ["free-rooms", booking.id, booking.room],
    queryFn: () => api<Room[]>(`/bookings/${booking.id}/free-rooms`),
  });
  const [room, setRoom] = useState("");
  const options = rooms.data?.filter((r) => r.id !== booking.room) ?? [];
  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">{booking.room ? "Change room" : "Allot a room"}</h2>
      {rooms.data && options.length === 0 ? (
        <Notice tone="error">No other {booking.room_type_name} room is free for these dates.</Notice>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <Field label={`Free ${booking.room_type_name} rooms`}>
            <select value={room} onChange={(e) => setRoom(e.target.value)} className={inputClass}>
              <option value="">Choose a room</option>
              {options.map((r) => (
                <option key={r.id} value={r.id}>
                  Room {r.number} (floor {r.floor})
                </option>
              ))}
            </select>
          </Field>
          <Button disabled={busy || !room} onClick={() => onAllot(room)}>
            {booking.room ? "Move guest" : "Allot room"}
          </Button>
        </div>
      )}
    </Card>
  );
}

function PayPanel({ booking, busy, onPay }: { booking: Booking; busy: boolean; onPay: (gateway: string) => void }) {
  const gateways = useQuery({
    queryKey: ["gateways"],
    queryFn: () => api<{ id: string; label: string }[]>("/payments/gateways"),
  });
  return (
    <Card className="space-y-3 border-brand-600">
      <h2 className="font-semibold">Pay {inr(booking.amount)}</h2>
      {gateways.data?.length === 0 && (
        <Notice>Online payment is not switched on yet. Please contact the guesthouse office.</Notice>
      )}
      <div className="flex flex-wrap gap-3">
        {gateways.data?.map((gateway) => (
          <Button key={gateway.id} disabled={busy} onClick={() => onPay(gateway.id)}>
            {gateway.label}
          </Button>
        ))}
      </div>
    </Card>
  );
}

/** For drafts and sent-back requests: fix dates or purpose, add missing documents, then submit. */
function FixPanel({ booking, onError }: { booking: Booking; onError: (message: string) => void }) {
  const refresh = useRefresh();
  const [purpose, setPurpose] = useState(booking.purpose);
  const [checkIn, setCheckIn] = useState(booking.check_in);
  const [checkOut, setCheckOut] = useState(booking.check_out);
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>) {
    onError("");
    setBusy(true);
    try {
      await action();
      await refresh();
    } catch (e) {
      onError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  function upload(type: string, guest?: string) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const body = new FormData();
      body.append("type", type);
      body.append("file", file);
      if (guest) body.append("guest", guest);
      run(() => api(`/bookings/${booking.id}/documents`, { body }));
    };
  }

  const changed = purpose !== booking.purpose || checkIn !== booking.check_in || checkOut !== booking.check_out;
  const hasLetter = booking.documents.some((d) => d.type === "RECOMMENDATION_LETTER");

  return (
    <Card className="space-y-4 border-brand-600">
      <h2 className="font-semibold">Finish your request</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Check-in">
          <input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} className={inputClass} />
        </Field>
        <Field label="Check-out">
          <input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} className={inputClass} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Purpose of visit">
            <textarea rows={2} value={purpose} onChange={(e) => setPurpose(e.target.value)} className={`${inputClass} py-2`} />
          </Field>
        </div>
        {booking.category === "OFFICIAL" && (
          <Field label={hasLetter ? "Replace the recommendation letter" : "Recommendation letter (missing)"}>
            <input type="file" accept=".pdf,.jpg,.jpeg,.png" disabled={busy} onChange={upload("RECOMMENDATION_LETTER")} className="block w-full text-sm" />
          </Field>
        )}
        {booking.guests.map((guest) => (
          <Field key={guest.id} label={`${guest.has_id_document ? "Replace ID" : "ID (missing)"} for ${guest.name}`}>
            <input type="file" accept=".pdf,.jpg,.jpeg,.png" disabled={busy} onChange={upload("GUEST_ID", guest.id)} className="block w-full text-sm" />
          </Field>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        {changed && (
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => run(() => api(`/bookings/${booking.id}`, { method: "PATCH", body: { purpose, check_in: checkIn, check_out: checkOut } }))}
          >
            Save changes
          </Button>
        )}
        <Button disabled={busy || changed} onClick={() => run(() => api(`/bookings/${booking.id}/submit`, { method: "POST" }))}>
          Submit for approval
        </Button>
      </div>
    </Card>
  );
}
