"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, BedDouble, CalendarRange, Sparkles, Users } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState } from "react";
import { DayPicker, type DateRange } from "react-day-picker";

import dynamic from "next/dynamic";

import Endless, { type EndlessSlide } from "@/components/ui/endless";
import SushiConveyorMenu, { type ConveyorDish } from "@/components/ui/sushi-conveyor-menu";
import { TiltCard } from "@/components/tilt-card";
import { api, fmtDate, inr, isoDate } from "@/lib/api";
import { bedPlate, priceTiers } from "@/lib/room-plates";
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

const goldButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-gradient-to-b from-gold-soft to-gold px-5 text-sm font-semibold text-black shadow-[0_10px_30px_-12px_rgb(212_175_55/0.8)] transition-[translate,box-shadow] hover:-translate-y-px hover:shadow-[0_14px_36px_-12px_rgb(212_175_55/0.95)] motion-reduce:transition-none";
const ghostButton =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-gold/40 px-5 text-sm font-medium text-gold-soft transition-colors hover:border-gold hover:bg-gold/10";

const coverOf = (type: RoomType): Photo | undefined => type.photos.find((p) => p.is_cover) ?? type.photos[0];

export default function HomePage() {
  const router = useRouter();
  const reduce = useReducedMotion();
  const datesRef = useRef<HTMLDivElement>(null);
  const [range, setRange] = useState<DateRange | undefined>();
  const [wanted, setWanted] = useState<string | null>(null);
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

  const tiers = useMemo(() => priceTiers(types), [types]);
  const plates = useMemo<ConveyorDish[]>(
    () =>
      types.map((type) => {
        const slot = byType.get(type.id);
        const cover = coverOf(type);
        const photo = cover?.urls["480"];
        const details = [`Sleeps ${type.capacity}`, ...type.amenities];
        if (slot) details.push(slot.available ? `${slot.available} free for your dates` : "Full for your dates");
        return {
          id: type.id,
          name: type.name,
          price: `${inr(slot?.price_per_night ?? type.price_per_night)} / night`,
          tier: tiers.get(type.id),
          description: type.description || `A ${type.capacity > 1 ? "room for " + type.capacity : "single room"} at the college guesthouse.`,
          details,
          image: photo ?? bedPlate(type.capacity),
          crop: !!photo,
        };
      }),
    [types, byType, tiers],
  );
  const legend = useMemo(() => {
    const out: { [tier: number]: string } = {};
    for (const type of types) {
      const tier = tiers.get(type.id) ?? 1;
      if (!out[tier] && type.price_per_night) out[tier] = inr(type.price_per_night);
    }
    return out;
  }, [types, tiers]);
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
  const wantedType = types.find((t) => t.id === wanted);
  const wantedSlot = wanted ? byType.get(wanted) : undefined;

  function scrollToDates() {
    datesRef.current?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  }

  function chooseRoom(dish: ConveyorDish) {
    const slot = byType.get(dish.id);
    if (checkIn && checkOut && slot && slot.available > 0) {
      router.push(bookHref(dish.id));
      return;
    }
    setWanted(dish.id);
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
    <div className="dark relative -my-10 mx-[calc(50%-50vw)] bg-background pb-16 text-foreground">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 overflow-hidden"
        style={{
          background:
            "radial-gradient(60% 40% at 15% 55%, rgb(212 175 55 / 0.10), transparent 70%), radial-gradient(50% 35% at 90% 80%, rgb(212 175 55 / 0.08), transparent 70%)",
        }}
      />

      <section aria-labelledby="hero-heading" className="relative mx-auto grid w-full max-w-6xl items-center gap-6 px-4 pt-10 md:pt-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:gap-4">
        <motion.div
          className="relative z-10 order-2 lg:order-1"
          initial={reduce ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.9, ease: [0.22, 0.85, 0.3, 1] }}
        >
          <p className="flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.35em] text-gold">
            <span aria-hidden="true" className="h-px w-10 bg-gradient-to-r from-gold to-transparent" />
            College Guesthouse
          </p>
          <h1 id="hero-heading" className="mt-5 text-5xl font-semibold leading-[1.02] tracking-tight text-foreground md:text-6xl xl:text-7xl">
            Stay on campus,{" "}
            <span className="bg-gradient-to-b from-[#fff3cf] via-gold-soft to-gold bg-clip-text italic text-transparent">in quiet comfort.</span>
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-muted-foreground md:text-lg">
            Pick your dates and a room. The college approves your request, then you pay online and get your room on arrival.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <button type="button" onClick={scrollToDates} className={goldButton}>
              Check availability
              <ArrowDown aria-hidden="true" className="size-4" />
            </button>
            <a href="#rooms" className={ghostButton}>
              See the rooms
            </a>
          </div>
          {types.length > 0 && (
            <dl className="mt-10 grid max-w-md grid-cols-3 divide-x divide-gold/15 rounded-2xl border border-gold/15 bg-white/[0.02] py-4 backdrop-blur-sm">
              {[
                ["Room types", String(types.length)],
                ["Rooms", String(types.reduce((sum, t) => sum + t.room_count, 0))],
                ["From", fromPrice ? `${inr(fromPrice)}` : "—"],
              ].map(([label, value]) => (
                <div key={label} className="px-4">
                  <dt className="text-[10px] font-semibold uppercase tracking-[0.22em] text-muted-foreground">{label}</dt>
                  <dd className="mt-1 font-display text-2xl font-semibold text-gold-soft">{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </motion.div>
        <div className="relative order-1 -mx-4 h-[340px] sm:h-[420px] lg:order-2 lg:mx-0 lg:h-[560px]">
          <div aria-hidden="true" className="absolute inset-x-[10%] bottom-[8%] top-[20%] rounded-full bg-gold/10 blur-3xl" />
          <GuesthouseModel className="relative size-full" />
        </div>
      </section>

      <div className="relative mx-auto w-full max-w-6xl px-4">
        <motion.div
          ref={datesRef}
          {...rise()}
          className="glass mt-6 grid scroll-mt-6 gap-6 rounded-3xl p-5 md:grid-cols-[auto_1fr] md:p-7"
        >
          <div>
            <h2 className="mb-2 flex items-center gap-2 font-medium text-gold-soft">
              <CalendarRange aria-hidden="true" className="size-4 text-gold" />
              Your stay
            </h2>
            <DayPicker
              mode="range"
              selected={range}
              onSelect={setRange}
              disabled={{ before: new Date() }}
              min={1}
              max={14}
            />
          </div>
          <div className="flex flex-col justify-center gap-4">
            <p className="text-sm text-muted-foreground" aria-live="polite">
              {checkIn && checkOut ? (
                <>
                  <span className="block text-xl font-medium text-foreground">
                    {fmtDate(checkIn)} to {fmtDate(checkOut)}
                  </span>
                  {availability.data?.nights ?? "…"} night(s)
                </>
              ) : (
                "Choose a check-in and a check-out date to see which rooms are free."
              )}
            </p>
            <AnimatePresence mode="popLayout">
              {wantedType && (
                <motion.div
                  key={wantedType.id}
                  initial={reduce ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  className="rounded-2xl border border-gold/30 bg-gold/5 p-4 text-sm"
                  role="status"
                >
                  <p className="font-medium text-gold-soft">{wantedType.name}</p>
                  {!checkOut ? (
                    <p className="mt-1 text-muted-foreground">Pick your dates and we will check this room for you.</p>
                  ) : !wantedSlot ? (
                    <p className="mt-1 text-muted-foreground">Checking these dates…</p>
                  ) : wantedSlot.available > 0 ? (
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                      <span className="text-muted-foreground">
                        {wantedSlot.available} free · {inr(wantedSlot.amount)} total
                      </span>
                      <Link href={bookHref(wantedType.id)} className={goldButton}>
                        Request this room
                      </Link>
                    </div>
                  ) : (
                    <p className="mt-1 text-red-300">Not available for these dates. Try other dates or another room.</p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
            {availability.error && (
              <p role="alert" className="text-sm text-red-300">
                {availability.error.message}
              </p>
            )}
          </div>
        </motion.div>
      </div>

      {plates.length > 0 && (
        <motion.div {...rise()} className="relative mt-10">
          <SushiConveyorMenu
            className="bg-transparent"
            dialogClassName="dark"
            items={plates}
            legend={legend}
            eyebrow="Rooms at the guesthouse"
            heading="Choose your room"
            caption="Hover to stop the carousel, drag to spin it, pick a room to see it up close."
            autoplay
            onAdd={chooseRoom}
            labels={{ add: "Book this room", close: "Close", previous: "Previous room", next: "Next room", pause: "Pause carousel" }}
            action={
              <a href="#rooms" className={ghostButton}>
                Compare all rooms
              </a>
            }
          />
        </motion.div>
      )}

      <section id="rooms" aria-labelledby="rooms-heading" className="relative mx-auto mt-10 w-full max-w-6xl scroll-mt-6 px-4">
        <motion.h2 {...rise()} id="rooms-heading" className="mb-4 flex items-center gap-2 text-xl font-medium text-gold-soft">
          <Sparkles aria-hidden="true" className="size-4 text-gold" />
          All rooms
        </motion.h2>
        {roomTypes.isLoading && <p className="py-8 text-center text-muted-foreground">Loading…</p>}
        {roomTypes.error && (
          <p role="alert" className="text-sm text-red-300">
            {roomTypes.error.message}
          </p>
        )}
        {roomTypes.data?.length === 0 && <p className="text-muted-foreground">No rooms are open for booking yet.</p>}
        <div className="space-y-4">
          {types.map((type, index) => {
            const slot = byType.get(type.id);
            const cover = coverOf(type);
            return (
              <TiltCard
                key={type.id}
                {...rise(Math.min(index, 4) * 0.06)}
                className={cn(
                  "glass flex flex-col gap-4 rounded-3xl p-4 sm:flex-row sm:p-5",
                  wanted === type.id && "ring-1 ring-gold/60",
                )}
              >
                {cover?.urls["480"] ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={cover.urls["480"]}
                    srcSet={Object.entries(cover.urls).map(([w, url]) => `${url} ${w}w`).join(", ")}
                    sizes="(min-width: 640px) 14rem, 100vw"
                    alt={cover.caption || `${type.name} room`}
                    loading="lazy"
                    className="h-40 w-full rounded-2xl object-cover sm:w-56"
                  />
                ) : (
                  <div className="flex h-40 w-full flex-col items-center justify-center gap-2 rounded-2xl border border-gold/20 bg-gradient-to-br from-gold/15 to-transparent text-sm text-gold-soft sm:w-56">
                    <BedDouble aria-hidden="true" className="size-8 text-gold" />
                    No photo yet
                  </div>
                )}
                <div className="flex flex-1 flex-col">
                  <h3 className="text-lg font-medium text-foreground">{type.name}</h3>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
                    <Users aria-hidden="true" className="size-3.5 text-gold" />
                    Sleeps {type.capacity}
                    {type.amenities.length > 0 && ` · ${type.amenities.join(" · ")}`}
                  </p>
                  {type.description && <p className="mt-2 text-sm text-foreground/80">{type.description}</p>}
                  <div className="mt-auto flex flex-wrap items-end justify-between gap-3 pt-4">
                    <div>
                      <p className="text-lg font-semibold text-gold-soft">
                        {inr(slot?.price_per_night ?? type.price_per_night)}
                        <span className="text-sm font-normal text-muted-foreground"> / night</span>
                      </p>
                      {slot && (
                        <p className={`text-sm ${slot.available ? "text-emerald-300" : "text-red-300"}`}>
                          {slot.available
                            ? `${slot.available} free · ${inr(slot.amount)} total`
                            : "Not available for these dates"}
                        </p>
                      )}
                    </div>
                    {slot && slot.available > 0 ? (
                      <Link href={bookHref(type.id)} className={goldButton}>
                        Request this room
                      </Link>
                    ) : (
                      !slot && (
                        <button
                          type="button"
                          onClick={() => {
                            setWanted(type.id);
                            scrollToDates();
                          }}
                          className="text-sm text-muted-foreground underline-offset-4 hover:text-gold-soft hover:underline"
                        >
                          Pick dates to check
                        </button>
                      )
                    )}
                  </div>
                </div>
              </TiltCard>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="walk-heading" className="relative mt-20">
        <h2 id="walk-heading" className="sr-only">
          Walk through the rooms
        </h2>
        <Endless
          slides={slides}
          height="min(70svh, 640px)"
          aria-label="Rooms at the guesthouse"
          title={
            <span className="block rounded-[2rem] border border-gold/15 bg-black/55 px-6 py-8 backdrop-blur-md md:px-12">
              <span className="block text-[11px] font-semibold uppercase tracking-[0.35em] text-gold">Walk through</span>
              <span className="mt-3 block font-display text-4xl font-semibold text-gold-soft md:text-5xl">Every room, one request away</span>
            </span>
          }
        >
          <div className="absolute inset-x-0 bottom-10 flex justify-center px-4">
            <button type="button" onClick={scrollToDates} className={goldButton}>
              Check availability
            </button>
          </div>
        </Endless>
      </section>
    </div>
  );
}
