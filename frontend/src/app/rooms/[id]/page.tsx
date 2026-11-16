"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { DayPicker, type DateRange } from "react-day-picker";

import { tierOf } from "@/components/room-showcase";
import { Loading, Notice, primaryLink } from "@/components/ui";
import { api, ApiError, fmtDate, inr, isoDate } from "@/lib/api";
import { lines, useSiteContent } from "@/lib/hooks";
import type { Availability, RoomType } from "@/lib/types";

// three.js is large and browser-only: load the room after the page, never on the server.
const RoomScene = dynamic(() => import("@/components/room-scene"), { ssr: false });

export default function RoomPage() {
  const { id } = useParams<{ id: string }>();
  const site = useSiteContent();
  const roomTypes = useQuery({ queryKey: ["room-types"], queryFn: () => api<RoomType[]>("/room-types") });
  const [shown, setShown] = useState(0);
  const [range, setRange] = useState<DateRange | undefined>();
  const checkIn = range?.from ? isoDate(range.from) : null;
  const checkOut = range?.to && range.from && range.to > range.from ? isoDate(range.to) : null;
  const availability = useQuery({
    queryKey: ["availability", checkIn, checkOut],
    queryFn: () => api<Availability>(`/availability?check_in=${checkIn}&check_out=${checkOut}`),
    enabled: !!checkIn && !!checkOut,
  });

  if (roomTypes.isLoading) return <Loading />;
  if (roomTypes.error) return <Notice tone="error">{roomTypes.error instanceof ApiError ? roomTypes.error.message : "This page could not be loaded."}</Notice>;
  const types = roomTypes.data ?? [];
  const index = types.findIndex((t) => t.id === id);
  const type = types[index];
  if (!type) {
    return (
      <div className="py-16">
        <p className="label text-gold">Room not found</p>
        <h1 className="mt-4 text-5xl">This room is not open for booking.</h1>
        <Link href="/#rooms" className={`${primaryLink} mt-8`}>
          See all rooms
        </Link>
      </div>
    );
  }

  const photos = [...type.photos].sort((a, b) => Number(b.is_cover) - Number(a.is_cover));
  const photo = photos[Math.min(shown, photos.length - 1)];
  const slot = availability.data?.results.find((r) => r.room_type === type.id);
  const others = types.filter((t) => t.id !== type.id);
  const notes = [
    site.checkin_time && `Check-in: ${site.checkin_time}`,
    site.checkout_time && `Check-out: ${site.checkout_time}`,
    ...lines(site.house_rules),
  ].filter((note): note is string => !!note);

  return (
    <div className="-my-10 mx-[calc(50%-50vw)]">
      <div className="mx-auto w-full max-w-[88rem] px-4 pb-20 pt-8 md:px-8 md:pb-28">
        <Link href="/#rooms" className="label inline-flex items-center gap-2 text-muted-foreground transition-colors hover:text-foreground">
          <ArrowLeft aria-hidden="true" className="size-3.5" />
          All rooms
        </Link>
        <header className="mt-8 grid gap-6 border-b border-border pb-10 md:grid-cols-12 md:items-end">
          <div className="md:col-span-8">
            <p className="label text-gold tabular-nums">
              Room {String(index + 1).padStart(2, "0")} / {String(types.length).padStart(2, "0")}
            </p>
            <h1 className="mt-4 text-[clamp(3rem,8vw,7.5rem)] leading-[0.9] tracking-[-0.03em] text-foreground">{type.name}</h1>
          </div>
          <p className="text-base leading-relaxed text-muted-foreground md:col-span-4">
            {type.description || `A comfortable ${type.capacity > 1 ? `room for ${type.capacity}` : "single room"} at the guesthouse.`}
          </p>
        </header>

        <div className="mt-10 grid gap-10 lg:grid-cols-12">
          <div className="min-w-0 lg:col-span-8">
            <div className="relative aspect-[3/2] w-full overflow-hidden border border-border bg-[#12100d]">
              {photo ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  key={photo.id}
                  src={photo.urls["1600"] ?? photo.urls["960"] ?? photo.urls["480"]}
                  alt={photo.caption || `${type.name} room`}
                  className="absolute inset-0 size-full object-cover"
                />
              ) : (
                <>
                  <RoomScene capacity={type.capacity} tier={tierOf(type, types)} label={`3D view of the ${type.name} room`} className="absolute inset-0" />
                  <p className="label pointer-events-none absolute bottom-4 right-5 text-muted-foreground">Illustrative 3D view</p>
                </>
              )}
            </div>
            {photo?.caption && <p className="mt-3 text-sm text-muted-foreground">{photo.caption}</p>}
            {photos.length > 1 && (
              <ul className="mt-3 grid grid-cols-4 gap-3 sm:grid-cols-6">
                {photos.map((p, i) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      aria-label={`Show photo ${i + 1}${p.caption ? `: ${p.caption}` : ""}`}
                      aria-pressed={i === shown}
                      onClick={() => setShown(i)}
                      className={`block aspect-[3/2] w-full overflow-hidden border transition-opacity ${i === shown ? "border-gold" : "border-border opacity-60 hover:opacity-100"}`}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={p.urls["480"]} alt="" loading="lazy" className="size-full object-cover" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-14 grid gap-x-10 gap-y-12 sm:grid-cols-2">
              <section aria-labelledby="in-room">
                <h2 id="in-room" className="label font-sans text-gold">
                  In the room
                </h2>
                <ul className="mt-4 border-t border-border text-sm">
                  {[`Sleeps ${type.capacity}`, ...type.amenities].map((item) => (
                    <li key={item} className="border-b border-border py-3 text-foreground/85">
                      {item}
                    </li>
                  ))}
                </ul>
              </section>
              {notes.length > 0 && (
                <section aria-labelledby="good-to-know">
                  <h2 id="good-to-know" className="label font-sans text-gold">
                    Good to know
                  </h2>
                  <ul className="mt-4 border-t border-border text-sm">
                    {notes.map((note) => (
                      <li key={note} className="border-b border-border py-3 leading-relaxed text-foreground/85">
                        {note}
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </div>

          <aside aria-label="Request this room" className="lg:col-span-4">
            <div className="border border-border lg:sticky lg:top-24">
              <div className="border-b border-border p-6">
                <p className="font-display text-5xl leading-none text-foreground">
                  {inr(slot?.price_per_night ?? type.price_per_night)}
                  <span className="ml-1.5 font-sans text-xs text-muted-foreground">/ night</span>
                </p>
                <p className="mt-2 text-sm text-muted-foreground">Per room. Nothing is charged until the college approves.</p>
              </div>
              <div className="flex justify-center border-b border-border p-3">
                <DayPicker mode="range" selected={range} onSelect={setRange} disabled={{ before: new Date() }} min={1} max={14} />
              </div>
              <div className="p-6" aria-live="polite">
                {!checkIn || !checkOut ? (
                  <p className="text-sm text-muted-foreground">Pick the day you arrive, then the day you leave.</p>
                ) : availability.error ? (
                  <p role="alert" className="text-sm text-red-700">
                    {availability.error.message}
                  </p>
                ) : !slot ? (
                  <p className="text-sm text-muted-foreground">Checking these dates…</p>
                ) : (
                  <>
                    <p className="text-sm text-foreground">
                      {fmtDate(checkIn)} to {fmtDate(checkOut)}
                    </p>
                    <p className={`mt-1 text-sm ${slot.available ? "text-emerald-700" : "text-red-700"}`}>
                      {slot.available ? `${slot.available} free · ${inr(slot.amount)} for ${availability.data?.nights} night(s)` : "Full for these dates. Try other dates."}
                    </p>
                  </>
                )}
                {checkIn && checkOut && slot && slot.available > 0 ? (
                  <Link href={`/book?type=${type.id}&check_in=${checkIn}&check_out=${checkOut}`} className={`${primaryLink} mt-5 min-h-12 w-full`}>
                    Request this room
                    <ArrowRight aria-hidden="true" className="size-3.5" />
                  </Link>
                ) : (
                  <span aria-disabled="true" className={`${primaryLink} mt-5 min-h-12 w-full cursor-not-allowed opacity-40 hover:bg-primary`}>
                    Request this room
                  </span>
                )}
              </div>
            </div>
          </aside>
        </div>

        {others.length > 0 && (
          <nav aria-labelledby="other-rooms" className="mt-20 border-t border-border pt-5 md:mt-28">
            <h2 id="other-rooms" className="label font-sans text-muted-foreground">
              Other rooms
            </h2>
            <ul className="mt-6 grid border-b border-border sm:grid-cols-2 lg:grid-cols-3">
              {others.map((other) => (
                <li key={other.id} className="border-t border-border sm:odd:border-r lg:border-r lg:last:border-r-0">
                  <Link href={`/rooms/${other.id}`} className="group flex items-baseline justify-between gap-4 px-1 py-6 transition-colors hover:bg-card sm:px-5">
                    <span className="font-display text-3xl leading-none text-foreground">{other.name}</span>
                    <span className="text-sm tabular-nums text-muted-foreground">{inr(other.price_per_night)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </div>
    </div>
  );
}
