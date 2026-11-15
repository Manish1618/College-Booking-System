"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { DayPicker, type DateRange } from "react-day-picker";

import { Card, Loading, Notice, PageTitle } from "@/components/ui";
import { api, fmtDate, inr, isoDate } from "@/lib/api";
import type { Availability, RoomType } from "@/lib/types";

export default function HomePage() {
  const [range, setRange] = useState<DateRange | undefined>();
  const checkIn = range?.from ? isoDate(range.from) : null;
  const checkOut = range?.to && range.from && range.to > range.from ? isoDate(range.to) : null;

  const roomTypes = useQuery({ queryKey: ["room-types"], queryFn: () => api<RoomType[]>("/room-types") });
  const availability = useQuery({
    queryKey: ["availability", checkIn, checkOut],
    queryFn: () => api<Availability>(`/availability?check_in=${checkIn}&check_out=${checkOut}`),
    enabled: !!checkIn && !!checkOut,
  });
  const byType = new Map(availability.data?.results.map((r) => [r.room_type, r]));

  return (
    <>
      <PageTitle title="Book a guesthouse room">
        Pick your dates to see which rooms are free. Requests are approved by the college before payment.
      </PageTitle>
      <div className="grid gap-6 lg:grid-cols-[auto_1fr]">
        <Card className="self-start">
          <h2 className="mb-2 font-medium">Your stay</h2>
          <DayPicker
            mode="range"
            selected={range}
            onSelect={setRange}
            disabled={{ before: new Date() }}
            min={1}
            max={14}
          />
          <p className="mt-2 text-sm text-slate-600" aria-live="polite">
            {checkIn && checkOut
              ? `${fmtDate(checkIn)} to ${fmtDate(checkOut)} · ${availability.data?.nights ?? "…"} night(s)`
              : "Choose a check-in and a check-out date."}
          </p>
        </Card>

        <div className="space-y-4">
          {roomTypes.isLoading && <Loading />}
          {availability.error && <Notice tone="error">{availability.error.message}</Notice>}
          {roomTypes.data?.length === 0 && <Notice>No rooms are open for booking yet.</Notice>}
          {roomTypes.data?.map((type) => {
            const slot = byType.get(type.id);
            const cover = type.photos.find((p) => p.is_cover) ?? type.photos[0];
            return (
              <Card key={type.id} className="flex flex-col gap-4 sm:flex-row">
                {cover?.urls["480"] ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={cover.urls["480"]}
                    srcSet={Object.entries(cover.urls).map(([w, url]) => `${url} ${w}w`).join(", ")}
                    sizes="(min-width: 640px) 14rem, 100vw"
                    alt={cover.caption || `${type.name} room`}
                    loading="lazy"
                    className="h-40 w-full rounded-md object-cover sm:w-56"
                  />
                ) : (
                  <div className="flex h-40 w-full items-center justify-center rounded-md bg-brand-50 text-sm text-brand-700 sm:w-56">
                    No photo yet
                  </div>
                )}
                <div className="flex flex-1 flex-col">
                  <h2 className="text-lg font-semibold">{type.name}</h2>
                  <p className="text-sm text-slate-600">
                    Sleeps {type.capacity}
                    {type.amenities.length > 0 && ` · ${type.amenities.join(" · ")}`}
                  </p>
                  {type.description && <p className="mt-2 text-sm text-slate-700">{type.description}</p>}
                  <div className="mt-auto flex flex-wrap items-end justify-between gap-3 pt-4">
                    <div>
                      <p className="text-lg font-semibold">
                        {inr(slot?.price_per_night ?? type.price_per_night)}
                        <span className="text-sm font-normal text-slate-600"> / night</span>
                      </p>
                      {slot && (
                        <p className={`text-sm ${slot.available ? "text-emerald-700" : "text-red-700"}`}>
                          {slot.available
                            ? `${slot.available} free · ${inr(slot.amount)} total`
                            : "Not available for these dates"}
                        </p>
                      )}
                    </div>
                    {slot && slot.available > 0 ? (
                      <Link
                        href={`/book?type=${type.id}&check_in=${checkIn}&check_out=${checkOut}`}
                        className="inline-flex min-h-11 items-center rounded-md bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
                      >
                        Request this room
                      </Link>
                    ) : (
                      !slot && <span className="text-sm text-slate-500">Pick dates to check</span>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </>
  );
}
