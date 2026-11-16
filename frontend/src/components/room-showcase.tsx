"use client";

import { ArrowRight, BedDouble, BedSingle, Check, Users } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

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
function tierOf(type: RoomType, types: RoomType[]) {
  const prices = [...new Set(types.map((t) => Number(t.price_per_night)).filter((p) => p > 0))].sort((a, b) => a - b);
  const index = prices.indexOf(Number(type.price_per_night));
  if (index < 0) return 1;
  return prices.length === 1 ? 3 : 1 + Math.round((index * 4) / (prices.length - 1));
}

const AUTOPLAY_MS = 6000;

export function RoomShowcase({ types, slots, onBook }: RoomShowcaseProps) {
  const reduce = useReducedMotion();
  const [selected, setSelected] = useState(0);
  const [touched, setTouched] = useState(false);
  const index = Math.min(selected, types.length - 1);
  const type = types[index];

  // Walk through the rooms until the visitor takes over.
  useEffect(() => {
    if (touched || reduce || types.length < 2) return;
    const timer = window.setInterval(() => setSelected((i) => (i + 1) % types.length), AUTOPLAY_MS);
    return () => window.clearInterval(timer);
  }, [touched, reduce, types.length]);

  if (!type) return null;
  const slot = slots.get(type.id);
  const cover = type.photos.find((p) => p.is_cover) ?? type.photos[0];
  const photo = cover?.urls["1600"] ?? cover?.urls["960"] ?? cover?.urls["480"];
  const tier = tierOf(type, types);
  const facts = [`Sleeps ${type.capacity}`, ...type.amenities];
  const pick = (i: number) => {
    setTouched(true);
    setSelected(i);
  };

  return (
    <section
      aria-labelledby="showcase-heading"
      className="relative mx-auto mt-16 w-full max-w-6xl px-4"
      onPointerDown={() => setTouched(true)}
      onFocusCapture={() => setTouched(true)}
    >
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.35em] text-gold">
            <span aria-hidden="true" className="h-px w-10 bg-gradient-to-r from-gold to-transparent" />
            Rooms at the guesthouse
          </p>
          <h2 id="showcase-heading" className="mt-3 text-4xl font-semibold tracking-tight text-foreground md:text-5xl">
            Choose your room
          </h2>
        </div>
        <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
          Step inside each room before you book.<span className="hidden md:inline"> Move your mouse over the room to look around.</span>
        </p>
      </div>

      <div className="glass grid overflow-hidden rounded-[2rem] lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        {/* Stage */}
        <div className="relative min-h-[300px] min-w-0 overflow-hidden bg-[radial-gradient(90%_70%_at_50%_35%,#2b2114,#0c0a07_75%)] sm:min-h-[420px] lg:min-h-[540px]">
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-32 bg-gradient-to-b from-gold/10 to-transparent" />
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
          <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-black/80 to-transparent" />
          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 p-5 md:p-7">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={type.id}
                initial={reduce ? false : { opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.35 }}
              >
                <p className="font-mono text-[11px] tracking-[0.25em] text-gold">
                  {String(index + 1).padStart(2, "0")} / {String(types.length).padStart(2, "0")}
                </p>
                <p className="mt-1 font-display text-3xl font-semibold text-foreground md:text-4xl">{type.name}</p>
              </motion.div>
            </AnimatePresence>
            {!photo && <p className="hidden text-[11px] uppercase tracking-[0.2em] text-muted-foreground sm:block">Illustrative 3D view</p>}
          </div>
        </div>

        {/* Details */}
        <div className="flex min-w-0 flex-col border-t border-gold/15 lg:border-l lg:border-t-0">
          <div role="tablist" aria-label="Room types" className="flex gap-1 overflow-x-auto border-b border-gold/15 p-2 lg:flex-col lg:overflow-visible">
            {types.map((t, i) => {
              const active = i === index;
              const Icon = t.capacity > 1 ? BedDouble : BedSingle;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  id={`room-tab-${t.id}`}
                  aria-selected={active}
                  aria-controls="room-panel"
                  onClick={() => pick(i)}
                  className={`group relative flex shrink-0 items-center gap-3 rounded-2xl px-4 py-3 text-left transition-colors ${active ? "bg-gold/10" : "hover:bg-white/[0.04]"}`}
                >
                  {active && <motion.span layoutId="room-tab-mark" aria-hidden="true" className="absolute inset-y-3 left-0 hidden w-0.5 rounded-full bg-gold lg:block" />}
                  <Icon aria-hidden="true" className={`size-5 shrink-0 ${active ? "text-gold" : "text-muted-foreground"}`} />
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate font-display text-lg font-semibold ${active ? "text-gold-soft" : "text-foreground"}`}>{t.name}</span>
                    <span className="block text-xs text-muted-foreground">Sleeps {t.capacity}</span>
                  </span>
                  <span className="hidden text-right text-sm tabular-nums text-foreground lg:block">
                    {inr(t.price_per_night)}
                    <span className="block text-[11px] text-muted-foreground">per night</span>
                  </span>
                </button>
              );
            })}
          </div>

          <div id="room-panel" role="tabpanel" aria-labelledby={`room-tab-${type.id}`} className="flex flex-1 flex-col p-5 md:p-7">
            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={type.id}
                className="flex flex-1 flex-col"
                initial={reduce ? false : { opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.3 }}
              >
                <p className="text-sm leading-relaxed text-foreground/85">
                  {type.description || `A comfortable ${type.capacity > 1 ? `room for ${type.capacity}` : "single room"} at the college guesthouse.`}
                </p>
                <ul className="mt-5 grid grid-cols-2 gap-x-4 gap-y-2 text-sm text-muted-foreground">
                  {facts.map((fact, i) => (
                    <li key={fact} className="flex items-center gap-2">
                      {i === 0 ? <Users aria-hidden="true" className="size-4 text-gold" /> : <Check aria-hidden="true" className="size-4 text-gold" />}
                      {fact}
                    </li>
                  ))}
                </ul>

                <div className="mt-auto pt-7">
                  <div className="flex flex-wrap items-end justify-between gap-4 border-t border-gold/15 pt-5">
                    <div>
                      <p className="font-display text-4xl font-semibold text-gold-soft">
                        {inr(slot?.price_per_night ?? type.price_per_night)}
                        <span className="font-sans text-sm font-normal text-muted-foreground"> / night</span>
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
                      className="inline-flex min-h-12 items-center gap-2 whitespace-nowrap rounded-full bg-gradient-to-b from-gold-soft to-gold px-6 text-sm font-semibold text-black shadow-[0_10px_30px_-12px_rgb(212_175_55/0.8)] transition-[translate,box-shadow] enabled:hover:-translate-y-px enabled:hover:shadow-[0_14px_36px_-12px_rgb(212_175_55/0.95)] disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
                    >
                      Book this room
                      <ArrowRight aria-hidden="true" className="size-4" />
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
