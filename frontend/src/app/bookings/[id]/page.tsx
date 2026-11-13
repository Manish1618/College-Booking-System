"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button, Card, Field, inputClass, Loading, Notice, StatusBadge } from "@/components/ui";
import { api, fmtDate, fmtDateTime, inr } from "@/lib/api";
import { useRefresh } from "@/lib/hooks";
import { ID_TYPES, type Booking, type Room } from "@/lib/types";

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
      {b.actions.edit && (
        // The key remounts the panel after each save, so its fields start again from what the server stored.
        <FixPanel
          key={JSON.stringify([b.purpose, b.check_in, b.check_out, b.guests, b.student_link])}
          booking={b}
          onError={setError}
        />
      )}

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

type GuestDraft = { id?: string; name: string; phone: string; address: string; id_type: string };
type LinkDraft = { student_name: string; roll_number: string; programme: string; year: string; relationship: string };
const emptyLink: LinkDraft = { student_name: "", roll_number: "", programme: "", year: "", relationship: "" };

/** The first problem with the corrected details, in words for the requester, or null when they are complete. */
function problemWith(purpose: string, guests: GuestDraft[], link: LinkDraft | null) {
  if (purpose.trim().length < 5) return "Say briefly why the guests are visiting.";
  if (!guests.length) return "Add at least one guest.";
  for (const [index, guest] of guests.entries()) {
    const who = `Guest ${index + 1}`;
    if (guest.name.trim().length < 2) return `${who}: enter the guest's full name.`;
    if (!/^\+?[0-9]{10,14}$/.test(guest.phone.trim())) return `${who}: enter a valid mobile number.`;
    if (guest.address.trim().length < 5) return `${who}: enter the guest's address.`;
  }
  if (link) {
    if (!link.student_name.trim() || !link.roll_number.trim() || !link.programme.trim() || !link.relationship.trim()) {
      return "Fill in all of the student's details.";
    }
    if (!/^[1-8]$/.test(link.year.trim())) return "Enter the student's year of study (1 to 8).";
  }
  return null;
}

/** For drafts and sent-back requests: correct the stay, the guests or the student's details, add documents, then submit. */
function FixPanel({ booking, onError }: { booking: Booking; onError: (message: string) => void }) {
  const refresh = useRefresh();
  const personal = booking.category === "PERSONAL";
  const savedGuests: GuestDraft[] = booking.guests.map((g) => ({
    id: g.id,
    name: g.name,
    phone: g.phone ?? "",
    address: g.address ?? "",
    id_type: g.id_type ?? "AADHAAR",
  }));
  const savedLink: LinkDraft | null = !personal
    ? null
    : booking.student_link
      ? {
          student_name: booking.student_link.student_name,
          roll_number: booking.student_link.roll_number,
          programme: booking.student_link.programme,
          year: String(booking.student_link.year),
          relationship: booking.student_link.relationship,
        }
      : emptyLink;

  const [purpose, setPurpose] = useState(booking.purpose);
  const [checkIn, setCheckIn] = useState(booking.check_in);
  const [checkOut, setCheckOut] = useState(booking.check_out);
  const [guests, setGuests] = useState(savedGuests);
  const [link, setLink] = useState(savedLink);
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

  function save() {
    const problem = problemWith(purpose, guests, link);
    if (problem) return onError(problem);
    const body = {
      purpose: purpose.trim(),
      check_in: checkIn,
      check_out: checkOut,
      guests: guests.map((g) => ({ ...g, name: g.name.trim(), phone: g.phone.trim(), address: g.address.trim() })),
      ...(link && { student_link: { ...link, year: Number(link.year) } }),
    };
    run(() => api(`/bookings/${booking.id}`, { method: "PATCH", body }));
  }

  const setGuest = (index: number, change: Partial<GuestDraft>) =>
    setGuests((list) => list.map((g, i) => (i === index ? { ...g, ...change } : g)));
  const setLinkField = (change: Partial<LinkDraft>) => setLink((current) => current && { ...current, ...change });

  const changed =
    purpose !== booking.purpose ||
    checkIn !== booking.check_in ||
    checkOut !== booking.check_out ||
    JSON.stringify(guests) !== JSON.stringify(savedGuests) ||
    JSON.stringify(link) !== JSON.stringify(savedLink);
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
      </div>

      {link && (
        <fieldset className="grid gap-4 border-t border-slate-200 pt-4 sm:grid-cols-2">
          <legend className="sr-only">Student&apos;s details</legend>
          <h3 className="font-medium sm:col-span-2">Student&apos;s details</h3>
          <Field label="Student's name">
            <input value={link.student_name} onChange={(e) => setLinkField({ student_name: e.target.value })} className={inputClass} />
          </Field>
          <Field label="Roll number">
            <input value={link.roll_number} onChange={(e) => setLinkField({ roll_number: e.target.value })} className={inputClass} />
          </Field>
          <Field label="Programme">
            <input value={link.programme} onChange={(e) => setLinkField({ programme: e.target.value })} className={inputClass} />
          </Field>
          <Field label="Year of study">
            <input inputMode="numeric" value={link.year} onChange={(e) => setLinkField({ year: e.target.value })} className={inputClass} />
          </Field>
          <Field label="Your relationship to the student">
            <input value={link.relationship} onChange={(e) => setLinkField({ relationship: e.target.value })} className={inputClass} />
          </Field>
        </fieldset>
      )}

      {guests.map((guest, index) => {
        const saved = booking.guests.find((g) => g.id === guest.id);
        return (
          <fieldset key={guest.id ?? `new-${index}`} className="grid gap-4 border-t border-slate-200 pt-4 sm:grid-cols-2">
            <legend className="sr-only">Guest {index + 1}</legend>
            <div className="flex items-center justify-between sm:col-span-2">
              <h3 className="font-medium">Guest {index + 1}</h3>
              {guests.length > 1 && (
                <button
                  type="button"
                  onClick={() => setGuests((list) => list.filter((_, i) => i !== index))}
                  className="py-2 text-sm text-red-700 hover:underline"
                >
                  Remove
                </button>
              )}
            </div>
            <Field label="Full name">
              <input autoComplete="off" value={guest.name} onChange={(e) => setGuest(index, { name: e.target.value })} className={inputClass} />
            </Field>
            <Field label="Mobile number">
              <input inputMode="tel" value={guest.phone} onChange={(e) => setGuest(index, { phone: e.target.value })} className={inputClass} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="Address">
                <input value={guest.address} onChange={(e) => setGuest(index, { address: e.target.value })} className={inputClass} />
              </Field>
            </div>
            <Field label="Government ID type">
              <select value={guest.id_type} onChange={(e) => setGuest(index, { id_type: e.target.value })} className={inputClass}>
                {ID_TYPES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            {saved ? (
              <Field label={saved.has_id_document ? "Replace the ID copy" : "ID copy (missing)"}>
                <input type="file" accept=".pdf,.jpg,.jpeg,.png" disabled={busy} onChange={upload("GUEST_ID", saved.id)} className="block w-full text-sm" />
              </Field>
            ) : (
              <p className="self-end text-sm text-slate-600">Save the changes, then upload this guest&apos;s ID copy.</p>
            )}
          </fieldset>
        );
      })}

      <div className="flex flex-wrap gap-3 border-t border-slate-200 pt-4">
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => setGuests((list) => [...list, { name: "", phone: "", address: "", id_type: "AADHAAR" }])}
        >
          Add a guest
        </Button>
        {changed && (
          <Button variant="secondary" disabled={busy} onClick={save}>
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
