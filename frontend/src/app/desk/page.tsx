"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { Card, Loading, Notice, PageTitle, StatusBadge } from "@/components/ui";
import { api, fmtDate, inrExact } from "@/lib/api";
import { isManager, useMe } from "@/lib/hooks";
import type { Booking, DeskDay, Page, Refund } from "@/lib/types";

const linkClass = "font-medium text-brand-700 underline";

/** What the desk has to do today: who arrives, who leaves, who is in house, and refunds waiting to be sent. */
export default function DeskPage() {
  const { data: me, isLoading } = useMe();
  const allowed = isManager(me);
  const desk = useQuery({ queryKey: ["desk"], queryFn: () => api<DeskDay>("/desk"), enabled: allowed });
  const refunds = useQuery({
    queryKey: ["refunds", "open"],
    queryFn: () => api<Page<Refund>>("/refunds?status=DUE,FAILED"),
    enabled: allowed,
  });

  if (isLoading) return <Loading />;
  if (!allowed) return <Notice tone="error">This screen is for the guesthouse desk.</Notice>;
  if (desk.isLoading) return <Loading />;
  if (desk.error || !desk.data) return <Notice tone="error">{desk.error?.message ?? "Could not load the desk."}</Notice>;
  const day = desk.data;

  return (
    <div className="space-y-6">
      <PageTitle title="Desk">{fmtDate(day.date)}</PageTitle>
      {(day.to_allot > 0 || day.refunds_due > 0) && (
        <Notice>
          {day.to_allot > 0 && (
            <>
              <Link href="/bookings?view=desk&status=CONFIRMED" className={linkClass}>
                {day.to_allot} paid {day.to_allot === 1 ? "booking needs" : "bookings need"} a room
              </Link>
              .{" "}
            </>
          )}
          {day.refunds_due > 0 && (
            <>
              {day.refunds_due} {day.refunds_due === 1 ? "refund is" : "refunds are"} waiting to be sent (listed below).
            </>
          )}
        </Notice>
      )}

      <Section
        title="Arriving"
        empty="Nobody is due to arrive today."
        bookings={day.arrivals}
        hint={(b) => (b.status === "ALLOTTED" ? "Open to check in" : "Needs a room first")}
      />
      <Section
        title="Leaving today"
        empty="Nobody is due to leave today."
        bookings={day.departures}
        hint={() => "Open to check out"}
      />
      <Section
        title="In house"
        empty="No guests are staying at the moment."
        bookings={day.in_house}
        hint={(b) => `Leaves ${fmtDate(b.check_out)}`}
      />

      <section>
        <h2 className="mb-3 text-lg font-semibold">Refunds to send</h2>
        {refunds.data?.results.length === 0 && <p className="text-sm text-slate-600">No refunds are waiting.</p>}
        <ul className="space-y-3">
          {refunds.data?.results.map((refund) => (
            <li key={refund.id}>
              <Link href={`/bookings/${refund.booking}`} className="block rounded-lg hover:ring-2 hover:ring-brand-100">
                <Card className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium">
                      {inrExact(refund.amount)} to {refund.requester_name}
                    </p>
                    <p className="text-sm text-slate-600">
                      {refund.reference} · {refund.reason}
                    </p>
                    {refund.failure_reason && <p className="text-sm text-red-700">{refund.failure_reason}</p>}
                  </div>
                  <span className={`text-sm font-medium ${refund.status === "FAILED" ? "text-red-700" : "text-amber-800"}`}>
                    {refund.status === "FAILED" ? "Failed, try again" : "Open to send"}
                  </span>
                </Card>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Section({
  title,
  empty,
  bookings,
  hint,
}: {
  title: string;
  empty: string;
  bookings: Booking[];
  hint: (booking: Booking) => string;
}) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold">
        {title} <span className="font-normal text-slate-500">({bookings.length})</span>
      </h2>
      {bookings.length === 0 && <p className="text-sm text-slate-600">{empty}</p>}
      <ul className="space-y-3">
        {bookings.map((booking) => (
          <li key={booking.id}>
            <Link href={`/bookings/${booking.id}`} className="block rounded-lg hover:ring-2 hover:ring-brand-100">
              <Card className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium">
                    {booking.guests.map((guest) => guest.name).join(", ")}
                    {booking.room_number ? ` · Room ${booking.room_number}` : ` · ${booking.room_type_name}`}
                  </p>
                  <p className="text-sm text-slate-600">
                    {fmtDate(booking.check_in)} to {fmtDate(booking.check_out)} · {booking.reference} · {hint(booking)}
                  </p>
                </div>
                <StatusBadge status={booking.status} label={booking.status_label} />
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
