"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button, Card, Field, Input, Loading, Notice, PageTitle } from "@/components/ui";
import { api, fmtDate, fmtDateTime, inr, isoDate } from "@/lib/api";
import { isManager, useMe } from "@/lib/hooks";
import type { Report } from "@/lib/types";

import { OccupancyChart, type Period } from "./occupancy-chart";

type Range = { from: string; to: string };

function presets(today = new Date()): { label: string; range: Range }[] {
  const y = today.getFullYear();
  const m = today.getMonth();
  const day = (date: Date) => isoDate(date);
  const ago = new Date(today);
  ago.setDate(ago.getDate() - 29);
  return [
    { label: "This month", range: { from: day(new Date(y, m, 1)), to: day(new Date(y, m + 1, 0)) } },
    { label: "Last month", range: { from: day(new Date(y, m - 1, 1)), to: day(new Date(y, m, 0)) } },
    { label: "Last 30 days", range: { from: day(ago), to: day(today) } },
    { label: "This year", range: { from: day(new Date(y, 0, 1)), to: day(new Date(y, 11, 31)) } },
  ];
}

const percent = (value: number | null) => (value === null ? "—" : `${value}%`);
const count = (value: number) => value.toLocaleString("en-IN");
const hours = (value: number | null) =>
  value === null ? "—" : value < 1 ? "Under an hour" : value < 48 ? `${value} hours` : `${Math.round(value / 24)} days`;

/** Days as they are for up to three months; longer ranges are summed by month so the columns stay readable. */
function periods(report: Report): { by: "day" | "month"; rows: Period[] } {
  if (report.daily.length <= 92) {
    return {
      by: "day",
      rows: report.daily.map((d) => ({
        key: d.date,
        label: fmtDate(d.date),
        tick: String(Number(d.date.slice(8))),
        available: d.available,
        sold: d.sold,
        percent: d.percent,
        received: Number(d.received),
        refunded: Number(d.refunded),
      })),
    };
  }
  const months = new Map<string, Period>();
  for (const d of report.daily) {
    const key = d.date.slice(0, 7);
    const start = new Date(`${key}-01T00:00:00`);
    const row = months.get(key) ?? {
      key,
      label: start.toLocaleDateString("en-IN", { month: "long", year: "numeric" }),
      tick: start.toLocaleDateString("en-IN", { month: "short" }),
      available: 0,
      sold: 0,
      percent: null,
      received: 0,
      refunded: 0,
    };
    row.available += d.available;
    row.sold += d.sold;
    row.received += Number(d.received);
    row.refunded += Number(d.refunded);
    row.percent = row.available ? Math.round((1000 * row.sold) / row.available) / 10 : null;
    months.set(key, row);
  }
  return { by: "month", rows: [...months.values()] };
}

/** The guesthouse at a glance: how full it was, what it took, what is waiting, and who did not turn up. */
export default function ReportsPage() {
  const { data: me, isLoading } = useMe();
  const allowed = isManager(me);
  const options = presets();
  const [range, setRange] = useState<Range>(options[0].range);
  const [draft, setDraft] = useState<Range>(options[0].range);
  const [view, setView] = useState<"chart" | "table">("chart");
  const query = `from=${range.from}&to=${range.to}`;
  const report = useQuery({
    queryKey: ["report", range.from, range.to],
    queryFn: () => api<Report>(`/reports/summary?${query}`),
    enabled: allowed,
    placeholderData: keepPreviousData,
  });

  if (isLoading) return <Loading />;
  if (!allowed) return <Notice tone="error">Reports are for the guesthouse office.</Notice>;

  const choose = (next: Range) => {
    setDraft(next);
    setRange(next);
  };
  const r = report.data;
  const grouped = r ? periods(r) : null;

  return (
    <div className="space-y-6">
      <PageTitle title="Reports">
        {r ? `${fmtDate(r.from)} to ${fmtDate(r.to)} · ${r.days} day(s)` : "Occupancy, money, approvals and no-shows."}
      </PageTitle>

      <Card className="space-y-4 print:hidden">
        <div className="flex flex-wrap gap-2">
          {options.map((option) => {
            const active = option.range.from === range.from && option.range.to === range.to;
            return (
              <Button
                key={option.label}
                variant={active ? "primary" : "secondary"}
                aria-pressed={active}
                onClick={() => choose(option.range)}
              >
                {option.label}
              </Button>
            );
          })}
        </div>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            setRange(draft);
          }}
        >
          <Field label="From">
            <Input required type="date" value={draft.from} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
          </Field>
          <Field label="To">
            <Input required type="date" min={draft.from} value={draft.to} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
          </Field>
          <Button type="submit" variant="secondary">
            Show
          </Button>
          <a
            href={`/api/reports/daily.csv?${query}`}
            className="inline-flex min-h-11 items-center text-sm font-medium text-brand-700 underline"
          >
            Download day by day (CSV)
          </a>
        </form>
      </Card>

      {report.error && <Notice tone="error">{report.error.message}</Notice>}
      {report.isLoading && <Loading />}

      {r && grouped && (
        <div className={`space-y-6 ${report.isPlaceholderData ? "opacity-60" : ""}`}>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Tile
              label="Occupancy"
              value={percent(r.occupancy.percent)}
              note={`${count(r.occupancy.room_nights_sold)} of ${count(r.occupancy.room_nights_available)} room-nights sold`}
            />
            <Tile
              label="Money kept"
              value={inr(r.revenue.net)}
              note={`${inr(r.revenue.received)} received, ${inr(r.revenue.refunded)} refunded`}
            />
            <Tile
              label="Waiting for approval"
              value={String(r.approvals.waiting)}
              note={
                r.approvals.oldest_waiting_since
                  ? `Oldest since ${fmtDateTime(r.approvals.oldest_waiting_since)}`
                  : "Nothing is waiting right now"
              }
            />
            <Tile
              label="No-shows"
              value={String(r.no_shows.count)}
              note={`${r.bookings.stays} paid stay(s), ${r.bookings.cancelled} cancelled`}
            />
          </div>

          <Card className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="font-semibold">Occupancy by {grouped.by}</h2>
                <p className="text-sm text-slate-600">Share of the rooms on offer that were sold each {grouped.by}.</p>
              </div>
              <div className="flex gap-2 print:hidden">
                {(["chart", "table"] as const).map((option) => (
                  <Button
                    key={option}
                    variant={view === option ? "primary" : "secondary"}
                    aria-pressed={view === option}
                    onClick={() => setView(option)}
                  >
                    {option === "chart" ? "Chart" : "Table"}
                  </Button>
                ))}
              </div>
            </div>
            {view === "chart" ? (
              <OccupancyChart rows={grouped.rows} />
            ) : (
              <div className="max-h-96 overflow-auto">
                <table className="w-full min-w-[36rem] text-right text-sm tabular-nums">
                  <thead className="sticky top-0 bg-card text-slate-600">
                    <tr className="border-b border-slate-200">
                      <th scope="col" className="py-2 text-left font-medium">
                        {grouped.by === "day" ? "Day" : "Month"}
                      </th>
                      <th scope="col" className="py-2 pl-3 font-medium">Rooms on offer</th>
                      <th scope="col" className="py-2 pl-3 font-medium">Sold</th>
                      <th scope="col" className="py-2 pl-3 font-medium">Occupancy</th>
                      <th scope="col" className="py-2 pl-3 font-medium">Received</th>
                      <th scope="col" className="py-2 pl-3 font-medium">Refunded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grouped.rows.map((row) => (
                      <tr key={row.key} className="border-b border-slate-100">
                        <th scope="row" className="py-1.5 text-left font-normal">{row.label}</th>
                        <td className="pl-3">{row.available}</td>
                        <td className="pl-3">{row.sold}</td>
                        <td className="pl-3">{percent(row.percent)}</td>
                        <td className="pl-3">{inr(row.received)}</td>
                        <td className="pl-3">{inr(row.refunded)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <div className="grid gap-6 *:min-w-0 md:grid-cols-2">
            <Card className="space-y-4">
              <h2 className="font-semibold">Occupancy by room type</h2>
              {r.occupancy.by_room_type.length === 0 && <p className="text-sm text-slate-600">No rooms are set up yet.</p>}
              <ul className="space-y-4">
                {r.occupancy.by_room_type.map((type) => (
                  <li key={type.room_type} className="text-sm">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="font-medium">{type.name}</span>
                      <span className="tabular-nums text-slate-900">{percent(type.percent)}</span>
                    </div>
                    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true">
                      <div className="h-full rounded-full bg-chart" style={{ width: `${Math.min(type.percent ?? 0, 100)}%` }} />
                    </div>
                    <p className="mt-1 text-slate-600">
                      {type.sold} of {type.available} room-nights · {type.rooms} room(s)
                    </p>
                  </li>
                ))}
              </ul>
            </Card>

            <Card className="space-y-4">
              <h2 className="font-semibold">Money</h2>
              {r.revenue.by_gateway.length === 0 ? (
                <p className="text-sm text-slate-600">No payments or refunds in this period.</p>
              ) : (
                <table className="w-full text-right text-sm tabular-nums">
                  <thead className="text-slate-600">
                    <tr className="border-b border-slate-200">
                      <th scope="col" className="py-2 text-left font-medium">Paid through</th>
                      <th scope="col" className="py-2 pl-3 font-medium">Received</th>
                      <th scope="col" className="py-2 pl-3 font-medium">Refunded</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.revenue.by_gateway.map((gateway) => (
                      <tr key={gateway.gateway} className="border-b border-slate-100">
                        <th scope="row" className="py-1.5 text-left font-normal">{gateway.label}</th>
                        <td className="pl-3">{inr(gateway.received)}</td>
                        <td className="pl-3">{inr(gateway.refunded)}</td>
                      </tr>
                    ))}
                    <tr className="font-medium">
                      <th scope="row" className="py-1.5 text-left font-medium">Total</th>
                      <td className="pl-3">{inr(r.revenue.received)}</td>
                      <td className="pl-3">{inr(r.revenue.refunded)}</td>
                    </tr>
                  </tbody>
                </table>
              )}
              <p className="text-sm text-slate-600">
                Money counts on the day it moved, not on the day of the stay.
                {Number(r.revenue.refunds_outstanding) > 0 && (
                  <>
                    {" "}
                    <Link href="/desk" className="font-medium text-brand-700 underline">
                      {inr(r.revenue.refunds_outstanding)} in refunds is still to be sent
                    </Link>
                    .
                  </>
                )}
              </p>
            </Card>

            <Card className="space-y-3">
              <h2 className="font-semibold">Approvals</h2>
              <dl className="grid grid-cols-[1fr_auto] gap-y-2 text-sm tabular-nums">
                <dt className="text-slate-600">Waiting now</dt>
                <dd>{r.approvals.waiting}</dd>
                <dt className="text-slate-600">Approved in this period</dt>
                <dd>{r.approvals.decided.approved}</dd>
                <dt className="text-slate-600">Sent back</dt>
                <dd>{r.approvals.decided.sent_back}</dd>
                <dt className="text-slate-600">Rejected</dt>
                <dd>{r.approvals.decided.rejected}</dd>
                <dt className="text-slate-600">Typical time to decide</dt>
                <dd>{hours(r.approvals.median_hours)}</dd>
                <dt className="text-slate-600">Requests submitted</dt>
                <dd>{r.bookings.requested}</dd>
              </dl>
              {r.approvals.waiting > 0 && (
                <Link href="/bookings?view=approvals" className="text-sm font-medium text-brand-700 underline">
                  Open the approvals list
                </Link>
              )}
            </Card>

            <Card className="space-y-3">
              <h2 className="font-semibold">No-shows</h2>
              {r.no_shows.count === 0 ? (
                <p className="text-sm text-slate-600">Every guest due in this period arrived or cancelled.</p>
              ) : (
                <ul className="divide-y divide-slate-100 text-sm">
                  {r.no_shows.bookings.map((booking) => (
                    <li key={booking.id} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
                      <span>
                        <Link href={`/bookings/${booking.id}`} className="font-medium text-brand-700 underline">
                          {booking.reference}
                        </Link>{" "}
                        · {booking.requester_name} · {booking.room_type_name}
                        <span className="block text-slate-600">
                          Due {fmtDate(booking.check_in)} for {booking.nights} night(s)
                        </span>
                      </span>
                      <span className="tabular-nums text-slate-700">{inr(booking.kept)} kept</span>
                    </li>
                  ))}
                </ul>
              )}
              {r.no_shows.count > r.no_shows.bookings.length && (
                <p className="text-sm text-slate-600">Showing the first {r.no_shows.bookings.length}.</p>
              )}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <Card>
      <p className="text-sm text-slate-600">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-slate-900">{value}</p>
      <p className="mt-1 text-sm text-slate-600">{note}</p>
    </Card>
  );
}
