"use client";

import { useState } from "react";

import { inr } from "@/lib/api";

export interface Period {
  key: string;
  /** In full, for the tooltip and the table. */
  label: string;
  /** Short, for the axis. */
  tick: string;
  available: number;
  sold: number;
  percent: number | null;
  received: number;
  refunded: number;
}

const GRID = [100, 75, 50, 25, 0];

/**
 * One column per day or month: the share of rooms on offer that were sold. Hover, tap or use the arrow
 * keys to read a column; the table view beside it carries the same figures for screen readers.
 */
export function OccupancyChart({ rows }: { rows: Period[] }) {
  const [active, setActive] = useState<number | null>(null);
  // Enough axis labels to place a column, few enough that they never run into each other.
  const every = Math.max(1, Math.ceil(rows.length / 12));
  const current = active === null ? null : rows[active];
  const place = active === null ? 0 : ((active + 0.5) / rows.length) * 100;

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const step = e.key === "ArrowRight" ? 1 : -1;
    setActive((index) => Math.min(Math.max((index ?? (step > 0 ? -1 : rows.length)) + step, 0), rows.length - 1));
  }

  return (
    <div className="flex gap-2 text-xs text-slate-500">
      <div className="relative h-52 w-9 shrink-0" aria-hidden="true">
        {GRID.map((line) => (
          <span key={line} className="absolute right-0 -translate-y-1/2 tabular-nums" style={{ top: `${100 - line}%` }}>
            {line}%
          </span>
        ))}
      </div>
      <div className="min-w-0 flex-1">
        <div
          role="group"
          tabIndex={0}
          aria-label="Occupancy chart. Use the left and right arrow keys to read each column."
          onKeyDown={onKeyDown}
          onBlur={() => setActive(null)}
          onMouseLeave={() => setActive(null)}
          className="relative h-52 rounded-sm outline-offset-4 focus-visible:outline-2 focus-visible:outline-brand-600"
        >
          {GRID.map((line) => (
            <span
              key={line}
              aria-hidden="true"
              className={`absolute inset-x-0 border-t ${line === 0 ? "border-slate-300" : "border-slate-100"}`}
              style={{ top: `${100 - line}%` }}
            />
          ))}
          <div className="absolute inset-0 flex">
            {rows.map((row, index) => (
              <div
                key={row.key}
                onMouseEnter={() => setActive(index)}
                onClick={() => setActive(index)}
                className={`flex h-full min-w-0 flex-1 items-end justify-center ${active === index ? "bg-slate-100" : ""}`}
              >
                {row.percent !== null && row.percent > 0 && (
                  <div
                    className={`w-[calc(100%-2px)] max-w-6 rounded-t ${active === index ? "bg-brand-600" : "bg-chart"}`}
                    style={{ height: `${Math.min(row.percent, 100)}%`, minHeight: 2 }}
                  />
                )}
              </div>
            ))}
          </div>
          {current && (
            <div
              role="status"
              className="pointer-events-none absolute top-1 z-10 w-max max-w-56 rounded-md border border-slate-200 bg-card px-3 py-2 text-sm text-slate-700 shadow-md"
              style={{
                left: `${place}%`,
                transform: `translateX(${place < 20 ? "0" : place > 80 ? "-100%" : "-50%"})`,
              }}
            >
              <p className="font-medium text-slate-900">{current.label}</p>
              {current.available === 0 ? (
                <p>No rooms on offer</p>
              ) : (
                <p>
                  <span className="font-medium text-slate-900">{current.percent}%</span> · {current.sold} of{" "}
                  {current.available} {current.tick.length > 2 ? "room-nights" : "rooms"} sold
                </p>
              )}
              {(current.received > 0 || current.refunded > 0) && (
                <p>
                  {inr(current.received)} received
                  {current.refunded > 0 && `, ${inr(current.refunded)} refunded`}
                </p>
              )}
            </div>
          )}
        </div>
        <div className="mt-1 flex" aria-hidden="true">
          {rows.map((row, index) => (
            <span key={row.key} className="min-w-0 flex-1 text-center tabular-nums">
              {index % every === 0 ? <span className="inline-block whitespace-nowrap">{row.tick}</span> : null}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
