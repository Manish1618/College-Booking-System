"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowRight } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState, useSyncExternalStore } from "react";
import { DayPicker, type DateRange } from "react-day-picker";

import dynamic from "next/dynamic";

import Endless, { type EndlessSlide } from "@/components/ui/endless";
import { RoomShowcase } from "@/components/room-showcase";
import { SectionHead } from "@/components/section-head";
import { primaryLink, secondaryLink } from "@/components/ui";
import { api, fmtDate, inr, isoDate } from "@/lib/api";
import { useSiteContent } from "@/lib/hooks";
import type { Availability, Photo, RoomType } from "@/lib/types";
import { cn } from "@/lib/utils";

// three.js is large and browser-only: load the model after the page, never on the server.
const GuesthouseModel = dynamic(() => import("@/components/guesthouse-model"), { ssr: false });

/** Shown in the corridor while room types load, or if none are open yet. */
const PLACEHOLDER_SLIDES: EndlessSlide[] = [
  { label: "Quiet rooms on campus", sublabel: "College Guesthouse" },
  { label: "Approved by the college", sublabel: "Before you pay" },
  { label: "Book in minutes", sublabel: "Online" },
];

const WIDE = "(min-width: 768px)";
function subscribeWide(notify: () => void) {
  const media = window.matchMedia(WIDE);
  media.addEventListener("change", notify);
  return () => media.removeEventListener("change", notify);
}

const coverOf = (type: RoomType): Photo | undefined => type.photos.find((p) => p.is_cover) ?? type.photos[0];

export default function HomePage() {
  const router = useRouter();
  const reduce = useReducedMotion();
  const site = useSiteContent();
  const datesRef = useRef<HTMLElement>(null);
  const [range, setRange] = useState<DateRange | undefined>();
  const [wanted, setWanted] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const twoMonths = useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => false);
  const checkIn = range?.from ? isoDate(range.from) : null;
  const checkOut = range?.to && range.from && range.to > range.from ? isoDate(range.to) : null;

  const roomTypes = useQuery({ queryKey: ["room-types"], queryFn: () => api<RoomType[]>("/room-types") });
  const availability = useQuery({
    queryKey: ["availability", checkIn, checkOut],
    queryFn: () => api<Availability>(`/availability?check_in=${checkIn}&check_out=${checkOut}`),
    enabled: !!checkIn && !!checkOut,
  });
  const byType = useMemo(() => new Map(availability.data?.results.map((r) => [r.room_type, r])), [availability.data]);
  const types = useMemo(() => roomTypes.data ?? [], [roomTypes.data]);
  const bookHref = (typeId: string) => `/book?type=${typeId}&check_in=${checkIn}&check_out=${checkOut}`;

  const slides = useMemo<EndlessSlide[]>(() => {
    const fromTypes = types.map((type) => {
      const cover = coverOf(type);
      return {
        src: cover?.urls["960"] ?? cover?.urls["480"],
        label: type.name,
        sublabel: `${inr(type.price_per_night)} / night`,
      };
    });
    return fromTypes.length ? fromTypes : PLACEHOLDER_SLIDES;
  }, [types]);

  const fromPrice = types.reduce<number | null>((min, t) => {
    const price = Number(t.price_per_night);
    return t.price_per_night && (min === null || price < min) ? price : min;
  }, null);
  const nights = availability.data?.nights ?? (range?.from && range.to && checkOut ? Math.round((range.to.getTime() - range.from.getTime()) / 86_400_000) : null);
  const wantedType = types.find((t) => t.id === wanted);
  const wantedSlot = wanted ? byType.get(wanted) : undefined;

  function scrollToDates() {
    setOpen(true);
    datesRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  function chooseRoom(typeId: string) {
    const slot = byType.get(typeId);
    if (checkIn && checkOut && slot && slot.available > 0) {
      router.push(bookHref(typeId));
      return;
    }
    setWanted(typeId);
    scrollToDates();
  }

  const rise = (delay = 0) =>
    reduce
      ? {}
      : {
          initial: { opacity: 0, y: 24 },
          whileInView: { opacity: 1, y: 0 },
          viewport: { once: true, margin: "-60px" },
          transition: { duration: 0.6, delay, ease: [0.22, 0.85, 0.3, 1] as const },
        };

  return (
    <div className="relative -my-10 mx-[calc(50%-50vw)] bg-background text-foreground">
      <section aria-labelledby="hero-heading" className="relative overflow-hidden border-b border-border">
        <div className="relative mx-auto w-full max-w-[88rem] px-4 md:px-8">
          <div className="relative -mx-4 h-[300px] sm:h-[380px] md:-mx-8 lg:absolute lg:inset-y-0 lg:right-0 lg:mx-0 lg:h-auto lg:w-[56%]">
            <GuesthouseModel className="size-full" />
          </div>
          <motion.div
            className="pointer-events-none relative z-10 pb-12 lg:pb-20 lg:pt-24"
            initial={reduce ? false : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: [0.22, 0.85, 0.3, 1] }}
          >
            <p className="label text-muted-foreground">
              {site.name} <span aria-hidden="true" className="mx-2 text-gold">/</span> {site.tagline}
            </p>
            <h1 id="hero-heading" className="mt-6 max-w-[11ch] text-[clamp(3.5rem,10.5vw,9.5rem)] leading-[0.88] tracking-[-0.03em] text-foreground">
              {site.headline} {site.headline_accent && <em className="text-gold">{site.headline_accent}</em>}
            </h1>
            <div className="pointer-events-auto mt-10 grid max-w-xl gap-8 sm:grid-cols-[1fr_auto] sm:items-end">
              <p className="text-base leading-relaxed text-muted-foreground">
                {site.intro}
              </p>
              <div className="flex flex-wrap gap-3">
                <button type="button" onClick={scrollToDates} className={primaryLink}>
                  Check availability
                  <ArrowDown aria-hidden="true" className="size-3.5" />
                </button>
              </div>
            </div>
          </motion.div>
        </div>
        {types.length > 0 && (
          <dl className="relative z-10 mx-auto grid w-full max-w-[88rem] grid-cols-2 border-t border-border bg-background md:grid-cols-4">
            {[
              ["Room types", String(types.length)],
              ["Rooms", String(types.reduce((sum, t) => sum + t.room_count, 0))],
              ["From, per night", fromPrice ? inr(fromPrice) : "—"],
              ["Longest stay", "14 nights"],
            ].map(([label, value], i) => (
              <div key={label} className={cn("border-border px-4 py-5 md:px-8", i % 2 === 1 && "border-l", i >= 2 && "border-t md:border-t-0", i === 2 && "md:border-l")}>
                <dt className="label text-muted-foreground">{label}</dt>
                <dd className="mt-2 font-display text-3xl leading-none text-foreground md:text-4xl">{value}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section ref={datesRef} aria-labelledby="dates-heading" className="mx-auto w-full max-w-[88rem] scroll-mt-20 px-4 pt-20 md:px-8 md:pt-28">
        <SectionHead no="01" kicker="Dates" id="dates-heading" title="When are you staying?" aside="Rooms show what is free as soon as both dates are in." />
        <div className="mt-10 grid border border-border sm:grid-cols-2 lg:grid-cols-[1fr_1fr_minmax(8rem,auto)_auto]">
          {([["Arrival", checkIn], ["Departure", checkOut]] as const).map(([label, value], i) => (
            <button
              key={label}
              type="button"
              aria-expanded={open}
              aria-controls="stay-calendar"
              onClick={() => setOpen((o) => !o)}
              className={cn("border-border px-5 py-5 text-left transition-colors hover:bg-card md:px-7", i === 1 && "border-t sm:border-l sm:border-t-0")}
            >
              <span className="label block text-muted-foreground">{label}</span>
              <span className={cn("mt-2 block font-display text-3xl leading-none md:text-4xl", value ? "text-foreground" : "text-muted-foreground/60")}>
                {value ? fmtDate(value) : "Add date"}
              </span>
            </button>
          ))}
          <div className="border-t border-border px-5 py-5 md:px-7 lg:border-l lg:border-t-0" aria-live="polite">
            <span className="label block text-muted-foreground">Nights</span>
            <span className="mt-2 block font-display text-3xl leading-none text-foreground md:text-4xl">{nights ?? "—"}</span>
          </div>
          <button
            type="button"
            onClick={() => {
              if (checkIn && checkOut) document.getElementById("showcase")?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
              else setOpen(true);
            }}
            className={cn(primaryLink, "min-h-16 rounded-none border-t border-border px-8 lg:border-t-0")}
          >
            {checkIn && checkOut ? "See free rooms" : "Check availability"}
            <ArrowRight aria-hidden="true" className="size-3.5" />
          </button>
        </div>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              id="stay-calendar"
              initial={reduce ? false : { opacity: 0, y: -6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2 }}
              className="flex flex-wrap items-start justify-between gap-6 border border-t-0 border-border p-4 md:p-7"
            >
              <DayPicker
                mode="range"
                numberOfMonths={twoMonths ? 2 : 1}
                selected={range}
                onSelect={(next) => {
                  setRange(next);
                  if (next?.from && next.to && next.to > next.from) setOpen(false);
                }}
                disabled={{ before: new Date() }}
                min={1}
                max={14}
              />
              <p className="max-w-[16rem] text-sm leading-relaxed text-muted-foreground">
                Pick the day you arrive, then the day you leave. Stays run from one to fourteen nights.
              </p>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="mt-8 flex max-w-2xl flex-col gap-6">
            <AnimatePresence mode="popLayout">
              {wantedType && (
                <motion.div
                  key={wantedType.id}
                  initial={reduce ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  className="border-l-2 border-gold pl-5 text-sm"
                  role="status"
                >
                  <p className="label text-gold">Your room</p>
                  <p className="mt-1.5 font-display text-2xl text-foreground">{wantedType.name}</p>
                  {!checkOut ? (
                    <p className="mt-1 text-muted-foreground">Pick your dates and we will check this room for you.</p>
                  ) : !wantedSlot ? (
                    <p className="mt-1 text-muted-foreground">Checking these dates…</p>
                  ) : wantedSlot.available > 0 ? (
                    <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-3">
                      <span className="text-muted-foreground">
                        {wantedSlot.available} free · {inr(wantedSlot.amount)} total
                      </span>
                      <Link href={bookHref(wantedType.id)} className={primaryLink}>
                        Request this room
                        <ArrowRight aria-hidden="true" className="size-3.5" />
                      </Link>
                    </div>
                  ) : (
                    <p className="mt-1 text-red-700">Not available for these dates. Try other dates or another room.</p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
            {availability.error && (
              <p role="alert" className="text-sm text-red-700">
                {availability.error.message}
              </p>
            )}
        </div>
      </section>

      <RoomShowcase types={types} slots={byType} onBook={(type) => chooseRoom(type.id)} />

      <section id="rooms" aria-labelledby="rooms-heading" className="paper mt-20 scroll-mt-16 bg-background text-foreground md:mt-28">
        <div className="mx-auto w-full max-w-[88rem] px-4 py-20 md:px-8 md:py-28">
          <SectionHead no="03" kicker="Index" id="rooms-heading" title="Every room, side by side" aside="Prices are per room, per night. Availability appears once you have picked dates." />
          {roomTypes.isLoading && <p className="py-10 text-muted-foreground">Loading…</p>}
          {roomTypes.error && (
            <p role="alert" className="mt-8 text-sm text-red-700">
              {roomTypes.error.message}
            </p>
          )}
          {roomTypes.data?.length === 0 && <p className="mt-8 text-muted-foreground">No rooms are open for booking yet.</p>}
          <ol className="mt-12 border-b border-border">
            {types.map((type, index) => {
              const slot = byType.get(type.id);
              const cover = coverOf(type);
              return (
                <motion.li
                  key={type.id}
                  {...rise(Math.min(index, 4) * 0.05)}
                  className={cn(
                    "group grid gap-x-8 gap-y-4 border-t border-border py-7 transition-colors md:grid-cols-12 md:items-center md:py-8",
                    wanted === type.id && "bg-card",
                  )}
                >
                  <p className="font-display text-2xl leading-none text-gold tabular-nums md:col-span-1 md:text-3xl">{String(index + 1).padStart(2, "0")}</p>
                  <div className="md:col-span-5">
                    <h3 className="text-3xl leading-none text-foreground md:text-4xl">{type.name}</h3>
                    {type.description && <p className="mt-3 max-w-md text-sm leading-relaxed text-muted-foreground">{type.description}</p>}
                  </div>
                  <div className="md:col-span-3">
                    {cover?.urls["480"] ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={cover.urls["480"]}
                        srcSet={Object.entries(cover.urls).map(([w, url]) => `${url} ${w}w`).join(", ")}
                        sizes="(min-width: 768px) 16rem, 100vw"
                        alt={cover.caption || `${type.name} room`}
                        loading="lazy"
                        className="mb-3 aspect-[3/2] w-full object-cover grayscale-[0.35] transition-[filter] duration-500 group-hover:grayscale-0 md:max-w-64"
                      />
                    ) : null}
                    <p className="label text-muted-foreground">Sleeps {type.capacity}</p>
                    {type.amenities.length > 0 && <p className="mt-1.5 text-sm leading-relaxed text-foreground">{type.amenities.join(", ")}</p>}
                  </div>
                  <div className="flex flex-wrap items-end justify-between gap-4 md:col-span-3 md:flex-col md:items-end md:text-right">
                    <div>
                      <p className="font-display text-3xl leading-none text-foreground">
                        {inr(slot?.price_per_night ?? type.price_per_night)}
                        <span className="ml-1.5 font-sans text-xs text-muted-foreground">/ night</span>
                      </p>
                      {slot && (
                        <p className={`mt-2 text-sm ${slot.available ? "text-emerald-700" : "text-red-700"}`}>
                          {slot.available ? `${slot.available} free · ${inr(slot.amount)} total` : "Not available for these dates"}
                        </p>
                      )}
                    </div>
                    {slot && slot.available > 0 ? (
                      <Link href={bookHref(type.id)} className={primaryLink}>
                        Request
                        <ArrowRight aria-hidden="true" className="size-3.5" />
                      </Link>
                    ) : (
                      !slot && (
                        <button
                          type="button"
                          onClick={() => {
                            setWanted(type.id);
                            scrollToDates();
                          }}
                          className={secondaryLink}
                        >
                          Check dates
                        </button>
                      )
                    )}
                  </div>
                </motion.li>
              );
            })}
          </ol>
        </div>
      </section>

      <section aria-labelledby="how-heading" className="mx-auto w-full max-w-[88rem] px-4 py-20 md:px-8 md:py-28">
        <SectionHead no="04" kicker="Booking" id="how-heading" title="How a stay is arranged" />
        <ol className="mt-12 grid border-y border-border md:grid-cols-3">
          {[
            ["First", site.step1_title, site.step1_body],
            ["Then", site.step2_title, site.step2_body],
            ["Last", site.step3_title, site.step3_body],
          ].map(([when, title, body], i) => (
            <li key={when} className={cn("border-border py-8 md:px-8 md:py-10", i > 0 && "border-t md:border-l md:border-t-0", i === 0 && "md:pl-0")}>
              <p className="label text-gold">{when}</p>
              <h3 className="mt-4 text-3xl leading-tight text-foreground">{title}</h3>
              <p className="mt-3 max-w-sm text-sm leading-relaxed text-muted-foreground">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="walk-heading" className="relative border-t border-border">
        <h2 id="walk-heading" className="sr-only">
          Walk through the rooms
        </h2>
        <Endless
          slides={slides}
          height="min(70svh, 640px)"
          aria-label="Rooms at the guesthouse"
          title={
            <span className="block border border-border bg-background px-8 py-9 md:px-14 md:py-12">
              <span className="label block text-muted-foreground">The corridor</span>
              <span className="mt-4 block font-display text-4xl leading-none text-foreground md:text-6xl">
                Every room, one <em className="text-gold">request</em> away
              </span>
            </span>
          }
        >
          <div className="absolute inset-x-0 bottom-10 flex justify-center px-4">
            <button type="button" onClick={scrollToDates} className={primaryLink}>
              Check availability
            </button>
          </div>
        </Endless>
      </section>
    </div>
  );
}
