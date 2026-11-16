"use client";

import { ArrowRight } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useState } from "react";

import { SectionHead } from "@/components/section-head";
import { primaryLink } from "@/components/ui";
import { inr } from "@/lib/api";
import type { Availability, RoomType } from "@/lib/types";

// three.js is large and browser-only: load the room after the page, never on the server.
const RoomScene = dynamic(() => import("@/components/room-scene"), { ssr: false });

type Slot = Availability["results"][number];

export interface RoomShowcaseProps {
  types: RoomType[];
  /** Availability for the chosen dates by room type id; empty until dates are picked. */
  slots: Map<string, Slot>;
  /** Called by "Book this room". */
  onBook: (type: RoomType) => void;
}

/** Tier 1 to 5 by where the nightly price sits among the room types; it decides how richly the 3D room is furnished. */
export function tierOf(type: RoomType, types: RoomType[]) {
  const prices = [...new Set(types.map((t) => Number(t.price_per_night)).filter((p) => p > 0))].sort((a, b) => a - b);
  const index = prices.indexOf(Number(type.price_per_night));
  if (index < 0) return 1;
  return prices.length === 1 ? 3 : 1 + Math.round((index * 4) / (prices.length - 1));
}

export function RoomShowcase({ types, slots, onBook }: RoomShowcaseProps) {
  const reduce = useReducedMotion();
  const [selected, setSelected] = useState(0);
  const index = Math.min(selected, types.length - 1);
  const type = types[index];

  if (!type) return null;
  const slot = slots.get(type.id);
  const cover = type.photos.find((p) => p.is_cover) ?? type.photos[0];
  const photo = cover?.urls["1600"] ?? cover?.urls["960"] ?? cover?.urls["480"];
  const tier = tierOf(type, types);
  const facts = [`Sleeps ${type.capacity}`, ...type.amenities];

  return (
    <section
      aria-labelledby="showcase-heading"
      id="showcase" className="relative mx-auto w-full max-w-[88rem] scroll-mt-16 px-4 pt-20 md:px-8 md:pt-28"
    >
      <SectionHead
        no="02"
        kicker="Rooms"
        id="showcase-heading"
        title="Step inside before you book"
        aside={<>Each room, as you will find it.<span className="hidden md:inline"> Move your mouse over the room to look around.</span></>}
      />

      <div className="mt-10 grid border border-border lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        {/* Stage */}
        <div className="relative min-h-[300px] min-w-0 overflow-hidden bg-[#12100d] sm:min-h-[420px] lg:min-h-[580px]">
          {photo ? (
            <AnimatePresence mode="popLayout" initial={false}>
              <motion.img
                key={type.id}
                src={photo}
                alt={cover?.caption || `${type.name} room`}
                className="absolute inset-0 size-full object-cover"
                initial={reduce ? false : { opacity: 0, scale: 1.08 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.9, ease: [0.22, 0.85, 0.3, 1] }}
              />
            </AnimatePresence>
          ) : (
            <RoomScene capacity={type.capacity} tier={tier} label={`3D view of the ${type.name} room`} className="absolute inset-0" />
          )}
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-black/70 to-transparent" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 p-5 md:p-7">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={type.id}
                initial={reduce ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.35 }}
              >
                <p className="label tabular-nums text-gold">
                  {String(index + 1).padStart(2, "0")} / {String(types.length).padStart(2, "0")}
                </p>
                <p className="mt-1 font-display text-4xl leading-none text-foreground md:text-6xl">{type.name}</p>
              </motion.div>
            </AnimatePresence>
            {!photo && <p className="label hidden text-muted-foreground sm:block">Illustrative 3D view</p>}
          </div>
        </div>

        {/* Details */}
        <div className="flex min-w-0 flex-col border-t border-border lg:border-l lg:border-t-0">
          <div role="tablist" aria-label="Room types" className="flex overflow-x-auto border-b border-border lg:flex-col lg:overflow-visible">
            {types.map((t, i) => {
              const active = i === index;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  id={`room-tab-${t.id}`}
                  aria-selected={active}
                  aria-controls="room-panel"
                  onClick={() => setSelected(i)}
                  className={`group relative flex shrink-0 items-baseline gap-4 border-border px-5 py-4 text-left transition-colors lg:border-b lg:last:border-b-0 ${active ? "bg-card" : "hover:bg-card/60"}`}
                >
                  {active && <motion.span layoutId="room-tab-mark" aria-hidden="true" className="absolute inset-y-0 left-0 hidden w-0.5 bg-gold lg:block" />}
                  <span aria-hidden="true" className={`label tabular-nums ${active ? "text-gold" : "text-muted-foreground"}`}>{String(i + 1).padStart(2, "0")}</span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate font-display text-2xl leading-tight ${active ? "text-foreground" : "text-muted-foreground group-hover:text-foreground"}`}>{t.name}</span>
                    <span className="block text-xs text-muted-foreground lg:hidden">Sleeps {t.capacity}</span>
                  </span>
                  <span className="hidden text-right text-sm tabular-nums text-muted-foreground lg:block">
                    {inr(t.price_per_night)}
                  </span>
                </button>
              );
            })}
          </div>

          <div id="room-panel" role="tabpanel" aria-labelledby={`room-tab-${type.id}`} className="flex flex-1 flex-col p-5 md:p-8">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={type.id}
                className="flex flex-1 flex-col"
                initial={reduce ? false : { opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3 }}
              >
                <p className="text-base leading-relaxed text-foreground/85">
                  {type.description || `A comfortable ${type.capacity > 1 ? `room for ${type.capacity}` : "single room"} at the college guesthouse.`}
                </p>
                <ul className="mt-6 border-t border-border text-sm">
                  {facts.map((fact) => (
                    <li key={fact} className="border-b border-border py-2.5 text-muted-foreground">
                      {fact}
                    </li>
                  ))}
                </ul>

                <Link href={`/rooms/${type.id}`} className="label mt-5 inline-flex items-center gap-2 self-start border-b border-gold pb-1 text-foreground transition-colors hover:text-gold">
                  See this room in full
                </Link>

                <div className="mt-auto pt-7">
                  <div className="flex flex-wrap items-end justify-between gap-4">
                    <div>
                      <p className="font-display text-5xl leading-none text-foreground">
                        {inr(slot?.price_per_night ?? type.price_per_night)}
                        <span className="ml-1.5 font-sans text-xs text-muted-foreground">/ night</span>
                      </p>
                      <p className={`mt-1 text-sm ${!slot ? "text-muted-foreground" : slot.available ? "text-emerald-700" : "text-red-700"}`} aria-live="polite">
                        {!slot
                          ? "Pick dates to see what is free"
                          : slot.available
                            ? `${slot.available} free · ${inr(slot.amount)} for your stay`
                            : "Full for your dates"}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => onBook(type)}
                      disabled={!!slot && slot.available === 0}
                      className={`${primaryLink} min-h-12 whitespace-nowrap enabled:hover:bg-gold-soft`}
                    >
                      Book this room
                      <ArrowRight aria-hidden="true" className="size-3.5" />
                    </button>
                  </div>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}
