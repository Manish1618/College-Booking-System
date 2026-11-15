"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button, Field, inputClass, Loading, Notice, PageTitle } from "@/components/ui";
import { api, fmtDateTime, inrExact } from "@/lib/api";
import { isManager, useMe } from "@/lib/hooks";
import type { Page, RegisterEntry } from "@/lib/types";

const exportLink =
  "inline-flex min-h-11 items-center rounded-md border border-slate-300 bg-card px-4 text-sm font-medium text-slate-800 hover:bg-slate-50";

type Filters = { search: string; from: string; to: string };
const noFilters: Filters = { search: "", from: "", to: "" };

function queryString(filters: Filters, page = 1) {
  const query = new URLSearchParams();
  if (filters.search.trim()) query.set("search", filters.search.trim());
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  if (page > 1) query.set("page", String(page));
  const text = query.toString();
  return text ? `?${text}` : "";
}

/** The guest register: everyone who has checked in, searchable, printable and exportable. */
export default function RegisterPage() {
  const { data: me, isLoading } = useMe();
  const allowed = isManager(me);
  // The form holds what is being typed; the search runs on what was last submitted, so the access log
  // records one search per press of the button and not one per keystroke.
  const [form, setForm] = useState(noFilters);
  const [filters, setFilters] = useState(noFilters);
  const [page, setPage] = useState(1);
  const entries = useQuery({
    queryKey: ["register", filters, page],
    queryFn: () => api<Page<RegisterEntry>>(`/register${queryString(filters, page)}`),
    enabled: allowed,
  });

  if (isLoading) return <Loading />;
  if (!allowed) return <Notice tone="error">The guest register is for the guesthouse desk.</Notice>;

  const apply = (next: Filters) => {
    setFilters(next);
    setPage(1);
  };

  return (
    <div className="space-y-6">
      <PageTitle title="Guest register">
        Everyone who has checked in. Each search, export and print of this register is logged.
      </PageTitle>

      <form
        className="grid gap-4 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-start print:hidden"
        onSubmit={(e) => {
          e.preventDefault();
          apply(form);
        }}
      >
        <Field label="Search" hint="Guest name, phone, booking ID or room number">
          <input value={form.search} onChange={(e) => setForm({ ...form, search: e.target.value })} className={inputClass} />
        </Field>
        <Field label="Arrived from">
          <input type="date" value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} className={inputClass} />
        </Field>
        <Field label="Arrived up to">
          <input type="date" value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} className={inputClass} />
        </Field>
        <div className="flex gap-3 sm:pt-6">
          <Button type="submit">Search</Button>
          <Button
            variant="secondary"
            onClick={() => {
              setForm(noFilters);
              apply(noFilters);
            }}
          >
            Clear
          </Button>
        </div>
      </form>

      <div className="flex flex-wrap items-center gap-3 print:hidden">
        <a href={`/api/register.csv${queryString(filters)}`} className={exportLink}>
          Download CSV
        </a>
        <a href={`/api/register.pdf${queryString(filters)}`} target="_blank" rel="noreferrer" className={exportLink}>
          Open as PDF
        </a>
        <Button variant="secondary" onClick={() => window.print()}>
          Print this page
        </Button>
        {entries.data && (
          <p className="text-sm text-slate-600" aria-live="polite">
            {entries.data.count} {entries.data.count === 1 ? "entry" : "entries"}
          </p>
        )}
      </div>

      {entries.isLoading && <Loading />}
      {entries.error && <Notice tone="error">{entries.error.message}</Notice>}
      {entries.data?.results.length === 0 && <Notice>No register entries match.</Notice>}
      {entries.data && entries.data.results.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-card print:overflow-visible print:border-0">
          <table className="w-full min-w-[60rem] text-left text-sm print:min-w-0 print:text-xs">
            <thead className="bg-slate-50 text-slate-700">
              <tr>
                {["No.", "Guest", "ID type", "Room", "Arrival", "Departure", "Purpose", "Paid", "Booking"].map((title) => (
                  <th key={title} scope="col" className="px-3 py-2 font-medium">
                    {title}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {entries.data.results.map((entry) => (
                <tr key={entry.id} className="align-top">
                  <td className="px-3 py-2">{entry.serial_number}</td>
                  <td className="px-3 py-2">
                    <span className="font-medium">{entry.guest_name}</span>
                    <span className="block text-slate-600">{entry.guest_phone}</span>
                    <span className="block text-slate-600">{entry.guest_address}</span>
                  </td>
                  <td className="px-3 py-2">{entry.id_type}</td>
                  <td className="px-3 py-2">{entry.room_number}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{fmtDateTime(entry.arrival_at)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {entry.departure_at ? fmtDateTime(entry.departure_at) : "In house"}
                  </td>
                  <td className="px-3 py-2">{entry.purpose}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {Number(entry.amount_paid) > 0 ? inrExact(entry.amount_paid) : "—"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <Link href={`/bookings/${entry.booking}`} className="text-brand-700 underline print:no-underline">
                      {entry.booking_reference}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {entries.data && (entries.data.previous || entries.data.next) && (
        <nav aria-label="Pages" className="flex items-center justify-between gap-3 print:hidden">
          <Button variant="secondary" disabled={!entries.data.previous} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <p className="text-sm text-slate-600">Page {page}</p>
          <Button variant="secondary" disabled={!entries.data.next} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </nav>
      )}
    </div>
  );
}
