"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card, Field, Input, inputClass, Notice } from "@/components/ui";
import { api, ApiError, fmtDate, isoDate } from "@/lib/api";
import { useRefresh } from "@/lib/hooks";
import type { Room, RoomBlock } from "@/lib/types";

type Problem = { message: string; overbooked: boolean };

/** Runs a change to a block. An "overbooked" answer is a warning the manager may override, not a dead end. */
function useBlockAction() {
  const refresh = useRefresh();
  const [problem, setProblem] = useState<Problem | null>(null);
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>) {
    setProblem(null);
    setBusy(true);
    try {
      await action();
      await refresh();
      return true;
    } catch (e) {
      // Field errors read as sentences on their own here, so they are shown without the field's name in front.
      const fields = e instanceof ApiError ? Object.entries(e.fields).filter(([key]) => key !== "code") : [];
      setProblem({
        message: fields.length
          ? fields.flatMap(([, texts]) => texts).join(" ")
          : e instanceof Error
            ? e.message
            : "Something went wrong.",
        overbooked: e instanceof ApiError && e.fields.code?.[0] === "overbooked",
      });
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { run, problem, setProblem, busy };
}

function addDays(iso: string, days: number) {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

/** Rooms out of service for repairs: the current and coming blocks, and a form to add one. */
export function RoomBlocks({ rooms }: { rooms: Room[] }) {
  const blocks = useQuery({ queryKey: ["room-blocks"], queryFn: () => api<RoomBlock[]>("/room-blocks") });
  const { run, problem, setProblem, busy } = useBlockAction();
  const today = isoDate(new Date());
  const [room, setRoom] = useState("");
  const [from, setFrom] = useState(today);
  const [back, setBack] = useState(addDays(today, 1));
  const [reason, setReason] = useState("");

  async function add(force: boolean) {
    const body = { room, starts_on: from, ends_on: back, reason, force };
    if (await run(() => api("/room-blocks", { body }))) {
      setRoom("");
      setReason("");
    }
  }

  return (
    <Card className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Rooms out of service</h2>
        <p className="text-sm text-slate-600">
          Block a room for repairs or cleaning. A blocked room is not sold or offered for allotment on those nights.
        </p>
      </div>

      {blocks.error && <Notice tone="error">Could not load the blocks. Reload the page to try again.</Notice>}
      {blocks.data?.length === 0 && <p className="text-sm text-slate-600">Every room is in service.</p>}
      <ul className="divide-y divide-slate-100">
        {blocks.data?.map((block) => (
          <BlockRow key={block.id} block={block} today={today} />
        ))}
      </ul>

      <form
        className="space-y-4 border-t border-slate-200 pt-4"
        onSubmit={(e) => {
          e.preventDefault();
          add(false);
        }}
      >
        <h3 className="font-semibold">Block a room</h3>
        {problem && (
          <Notice tone="error">
            {problem.message}
            {problem.overbooked && (
              <span className="mt-3 flex flex-wrap gap-3">
                <Button variant="danger" disabled={busy} onClick={() => add(true)}>
                  Block the room anyway
                </Button>
                <Button variant="secondary" disabled={busy} onClick={() => setProblem(null)}>
                  Leave it in service
                </Button>
              </span>
            )}
          </Notice>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Room">
            <select required value={room} onChange={(e) => setRoom(e.target.value)} className={inputClass}>
              <option value="">Choose a room</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  Room {r.number} · {r.room_type_name}
                  {r.is_active ? "" : " (out of use)"}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Out of service from">
            <Input
              required
              type="date"
              value={from}
              onChange={(e) => {
                setFrom(e.target.value);
                if (e.target.value && back <= e.target.value) setBack(addDays(e.target.value, 1));
              }}
            />
          </Field>
          <Field label="Back in service on" hint="The first day the room can be used again.">
            <Input required type="date" min={from ? addDays(from, 1) : undefined} value={back} onChange={(e) => setBack(e.target.value)} />
          </Field>
          <div className="sm:col-span-3">
            <Field label="Reason">
              <Input required maxLength={200} placeholder="For example: plumbing repair" value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
        </div>
        <Button type="submit" variant="secondary" disabled={busy}>
          Block room
        </Button>
      </form>
    </Card>
  );
}

function BlockRow({ block, today }: { block: RoomBlock; today: string }) {
  const { run, problem, setProblem, busy } = useBlockAction();
  const [editing, setEditing] = useState(false);
  const [back, setBack] = useState(block.ends_on);
  const [reason, setReason] = useState(block.reason);
  const started = block.starts_on <= today;
  const url = `/room-blocks/${block.id}`;

  async function save(force: boolean) {
    if (await run(() => api(url, { method: "PATCH", body: { ends_on: back, reason, force } }))) setEditing(false);
  }

  return (
    <li className="space-y-3 py-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium">
            Room {block.room_number} · {block.room_type_name}
            {started && <span className="label ml-2 rounded-[2px] bg-amber-100 px-2 py-0.5 text-amber-900">Out now</span>}
          </p>
          <p className="text-slate-700">
            {fmtDate(block.starts_on)} until {fmtDate(block.ends_on)} ({block.nights} night(s)) · {block.reason}
          </p>
          {block.created_by_name && <p className="text-slate-500">Blocked by {block.created_by_name}</p>}
        </div>
        {!editing && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => setEditing(true)}>
              Change
            </Button>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() =>
                window.confirm(`Put room ${block.room_number} back into service?`) &&
                run(() => api(url, { method: "DELETE" }))
              }
            >
              Back in service
            </Button>
          </div>
        )}
      </div>
      {problem && (
        <Notice tone="error">
          {problem.message}
          {problem.overbooked && editing && (
            <span className="mt-3 flex flex-wrap gap-3">
              <Button variant="danger" disabled={busy} onClick={() => save(true)}>
                Extend the block anyway
              </Button>
            </span>
          )}
        </Notice>
      )}
      {editing && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save(false);
          }}
        >
          <Field label="Back in service on">
            <Input required type="date" value={back} onChange={(e) => setBack(e.target.value)} />
          </Field>
          <div className="min-w-48 flex-1">
            <Field label="Reason">
              <Input required maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          </div>
          <Button type="submit" disabled={busy}>
            Save
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => {
              setProblem(null);
              setBack(block.ends_on);
              setReason(block.reason);
              setEditing(false);
            }}
          >
            Cancel
          </Button>
        </form>
      )}
    </li>
  );
}
