"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { Card, Loading, Notice, PageTitle, StatusBadge } from "@/components/ui";
import { api, fmtDate, inr } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import type { Booking, Page } from "@/lib/types";

const VIEWS = {
  mine: { title: "My bookings", query: "?scope=mine", empty: "You have no bookings yet." },
  approvals: { title: "Waiting for your decision", query: "?scope=approvals", empty: "Nothing is waiting for you." },
  desk: { title: "Guesthouse desk", query: "?scope=desk", empty: "No bookings yet." },
} as const;

const DESK_FILTERS = [
  ["", "All"],
  ["CONFIRMED", "To allot"],
  ["ALLOTTED", "Allotted"],
  ["PENDING,APPROVED", "In progress"],
] as const;

const pagerLink =
  "inline-flex min-h-11 items-center rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-800 hover:bg-slate-50";

export default function BookingsPage() {
  const params = useSearchParams();
  const { data: me, isLoading } = useMe();
  const viewKey = (params.get("view") ?? "mine") as keyof typeof VIEWS;
  const view = VIEWS[viewKey] ?? VIEWS.mine;
  const status = viewKey === "desk" ? (params.get("status") ?? "") : "";

  const page = Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1);

  const bookings = useQuery({
    queryKey: ["bookings", viewKey, status, page],
    queryFn: () =>
      api<Page<Booking>>(`/bookings${view.query}${status ? `&status=${status}` : ""}${page > 1 ? `&page=${page}` : ""}`),
    enabled: !!me,
  });

  // Links to other pages keep the current view and filter. Changing the filter starts again at page 1.
  const pageHref = (target: number) => {
    const next = new URLSearchParams();
    if (viewKey !== "mine") next.set("view", viewKey);
    if (status) next.set("status", status);
    if (target > 1) next.set("page", String(target));
    const query = next.toString();
    return query ? `/bookings?${query}` : "/bookings";
  };

  if (isLoading) return <Loading />;
  if (!me) {
    return (
      <Notice>
        Please <Link href="/login" className="font-medium underline">sign in</Link> to see your bookings.
      </Notice>
    );
  }

  return (
    <>
      <PageTitle title={view.title} />
      {viewKey === "desk" && (
        <nav aria-label="Filter" className="mb-4 flex flex-wrap gap-2">
          {DESK_FILTERS.map(([value, label]) => (
            <Link
              key={value}
              href={`/bookings?view=desk${value ? `&status=${value}` : ""}`}
              aria-current={status === value ? "page" : undefined}
              className={`rounded-full border px-3 py-1.5 text-sm ${
                status === value ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 bg-white"
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>
      )}
      {bookings.isLoading && <Loading />}
      {bookings.error && (
        <Notice tone="error">
          {bookings.error.message}{" "}
          {page > 1 && (
            <Link href={pageHref(1)} className="font-medium underline">
              Back to the first page
            </Link>
          )}
        </Notice>
      )}
      {bookings.data?.results.length === 0 && (
        <Notice>
          {view.empty}{" "}
          {viewKey === "mine" && (
            <Link href="/" className="font-medium underline">
              Book a room
            </Link>
          )}
        </Notice>
      )}
      <ul className="space-y-3">
        {bookings.data?.results.map((booking) => (
          <li key={booking.id}>
            <Link href={`/bookings/${booking.id}`} className="block rounded-lg hover:ring-2 hover:ring-brand-100">
              <Card className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium">
                    {booking.room_type_name}
                    {booking.room_number && ` · Room ${booking.room_number}`}
                  </p>
                  <p className="text-sm text-slate-600">
                    {fmtDate(booking.check_in)} to {fmtDate(booking.check_out)} · {booking.reference}
                    {viewKey !== "mine" && ` · ${booking.requester.name || booking.requester.email || booking.requester.phone}`}
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-slate-700">{inr(booking.amount)}</span>
                  <StatusBadge status={booking.status} label={booking.status_label} />
                </div>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
      {bookings.data && (bookings.data.previous || bookings.data.next) && (
        <nav aria-label="Pages" className="mt-6 flex items-center justify-between gap-3">
          {bookings.data.previous ? (
            <Link href={pageHref(page - 1)} rel="prev" className={pagerLink}>
              Previous
            </Link>
          ) : (
            <span />
          )}
          <p className="text-sm text-slate-600" aria-live="polite">
            Page {page} · {bookings.data.count} bookings
          </p>
          {bookings.data.next ? (
            <Link href={pageHref(page + 1)} rel="next" className={pagerLink}>
              Next
            </Link>
          ) : (
            <span />
          )}
        </nav>
      )}
    </>
  );
}
