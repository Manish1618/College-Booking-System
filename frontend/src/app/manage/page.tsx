"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Card, Field, Input, inputClass, Loading, Notice, PageTitle } from "@/components/ui";
import { api, fmtDate, inr, isoDate } from "@/lib/api";
import { isManager, useMe, useRefresh } from "@/lib/hooks";
import type { Room, RoomType, Tariff } from "@/lib/types";

/** Runs a change, then refetches. Returns the error message to show, if any. */
function useAction() {
  const refresh = useRefresh();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>) {
    setError("");
    setBusy(true);
    try {
      await action();
      await refresh();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { run, error, busy };
}

export default function ManagePage() {
  const { data: me, isLoading } = useMe();
  const allowed = isManager(me);
  const roomTypes = useQuery({ queryKey: ["room-types", "manage"], queryFn: () => api<RoomType[]>("/room-types"), enabled: allowed });
  const rooms = useQuery({ queryKey: ["rooms"], queryFn: () => api<Room[]>("/rooms"), enabled: allowed });
  const [open, setOpen] = useState<string | null>(null);

  if (isLoading) return <Loading />;
  if (!allowed) return <Notice tone="error">This page is for guesthouse managers.</Notice>;

  return (
    <>
      <PageTitle title="Rooms and prices">Changes here go live straight away.</PageTitle>
      <div className="space-y-4">
        {roomTypes.isLoading && <Loading />}
        {roomTypes.data?.map((type) => (
          <Card key={type.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">
                  {type.name}
                  {!type.is_active && <span className="ml-2 text-sm font-normal text-red-700">Hidden from guests</span>}
                </h2>
                <p className="text-sm text-slate-600">
                  Sleeps {type.capacity} · {inr(type.price_per_night)} per night · {type.room_count} active room(s) ·{" "}
                  {type.photos.length} photo(s)
                </p>
              </div>
              <Button variant="secondary" aria-expanded={open === type.id} onClick={() => setOpen(open === type.id ? null : type.id)}>
                {open === type.id ? "Close" : "Edit"}
              </Button>
            </div>
            {open === type.id && (
              <div className="mt-5 space-y-8 border-t border-slate-200 pt-5">
                <TypeForm type={type} />
                <Prices type={type} />
                <Photos type={type} />
                <Rooms type={type} rooms={rooms.data?.filter((r) => r.room_type === type.id) ?? []} />
              </div>
            )}
          </Card>
        ))}
        <Card>
          <h2 className="mb-4 text-lg font-semibold">Add a room type</h2>
          <TypeForm />
        </Card>
      </div>
    </>
  );
}

function TypeForm({ type }: { type?: RoomType }) {
  const { run, error, busy } = useAction();
  const [name, setName] = useState(type?.name ?? "");
  const [capacity, setCapacity] = useState(String(type?.capacity ?? 2));
  const [amenities, setAmenities] = useState(type?.amenities.join(", ") ?? "");
  const [description, setDescription] = useState(type?.description ?? "");
  const [active, setActive] = useState(type?.is_active ?? true);

  return (
    <form
      className="space-y-4"
      onSubmit={async (e) => {
        e.preventDefault();
        const body = {
          name,
          capacity: Number(capacity),
          description,
          is_active: active,
          amenities: amenities.split(",").map((a) => a.trim()).filter(Boolean),
        };
        const ok = await run(() => api(type ? `/room-types/${type.id}` : "/room-types", { method: type ? "PATCH" : "POST", body }));
        if (ok && !type) {
          setName("");
          setAmenities("");
          setDescription("");
        }
      }}
    >
      {type && <h3 className="font-semibold">Details</h3>}
      {error && <Notice tone="error">{error}</Notice>}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <Input required value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Guests per room">
          <Input required type="number" min={1} max={10} value={capacity} onChange={(e) => setCapacity(e.target.value)} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="Amenities" hint="Separate with commas, for example: Wi-Fi, AC, Attached bath">
            <Input value={amenities} onChange={(e) => setAmenities(e.target.value)} />
          </Field>
        </div>
        <div className="sm:col-span-2">
          <Field label="Description">
            <textarea rows={2} value={description} onChange={(e) => setDescription(e.target.value)} className={`${inputClass} py-2`} />
          </Field>
        </div>
      </div>
      {type && (
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="size-4" />
          Open for booking
        </label>
      )}
      <Button type="submit" disabled={busy}>
        {type ? "Save details" : "Add room type"}
      </Button>
    </form>
  );
}

function Prices({ type }: { type: RoomType }) {
  const { run, error, busy } = useAction();
  const tariffs = useQuery({ queryKey: ["tariffs", type.id], queryFn: () => api<Tariff[]>(`/room-types/${type.id}/tariffs`) });
  const [price, setPrice] = useState("");
  const [from, setFrom] = useState(isoDate(new Date()));
  return (
    <div className="space-y-3">
      <h3 className="font-semibold">Price per night</h3>
      <p className="text-sm text-slate-600">
        A new price applies to stays that start on or after its date. Existing bookings keep the price they were booked at.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      <ul className="text-sm">
        {tariffs.data?.map((tariff) => (
          <li key={tariff.id} className="flex justify-between border-b border-slate-100 py-1.5">
            <span>From {fmtDate(tariff.valid_from)}</span>
            <span className="font-medium">{inr(tariff.price_per_night)}</span>
          </li>
        ))}
        {tariffs.data?.length === 0 && <li className="text-red-700">No price set yet, so guests cannot book this type.</li>}
      </ul>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api(`/room-types/${type.id}/tariffs`, { body: { price_per_night: price, valid_from: from } }))) setPrice("");
        }}
      >
        <Field label="New price (₹)">
          <Input required type="number" min={0} step="1" value={price} onChange={(e) => setPrice(e.target.value)} />
        </Field>
        <Field label="Effective from">
          <Input required type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Button type="submit" variant="secondary" disabled={busy}>
          Set price
        </Button>
      </form>
    </div>
  );
}

function Photos({ type }: { type: RoomType }) {
  const { run, error, busy } = useAction();
  const ids = type.photos.map((p) => p.id);

  function move(index: number, by: number) {
    const order = [...ids];
    [order[index], order[index + by]] = [order[index + by], order[index]];
    run(() => api(`/room-types/${type.id}/photos/reorder`, { body: { order } }));
  }
  function send(path: string, method: string) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file) return;
      const body = new FormData();
      body.append("file", file);
      run(() => api(path, { method, body }));
    };
  }

  return (
    <div className="space-y-3">
      <h3 className="font-semibold">Photos</h3>
      {error && <Notice tone="error">{error}</Notice>}
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {type.photos.map((photo, index) => (
          <li key={photo.id} className="rounded-md border border-slate-200 p-2 text-sm">
            {photo.urls["480"] ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={photo.urls["480"]} alt={photo.caption || `Photo ${index + 1}`} className="h-36 w-full rounded object-cover" />
            ) : (
              <div className="flex h-36 items-center justify-center rounded bg-slate-100 text-slate-500">Processing…</div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
              {photo.is_cover ? (
                <span className="font-medium text-brand-700">Cover photo</span>
              ) : (
                <button type="button" disabled={busy} className="py-1 text-brand-700 hover:underline" onClick={() => run(() => api(`/photos/${photo.id}`, { method: "PATCH", body: { is_cover: true } }))}>
                  Make cover
                </button>
              )}
              <button type="button" disabled={busy || index === 0} className="py-1 hover:underline disabled:opacity-40" onClick={() => move(index, -1)}>
                Move earlier
              </button>
              <button type="button" disabled={busy || index === ids.length - 1} className="py-1 hover:underline disabled:opacity-40" onClick={() => move(index, 1)}>
                Move later
              </button>
              <label className="cursor-pointer py-1 hover:underline">
                Replace
                <input type="file" accept=".jpg,.jpeg,.png" className="sr-only" onChange={send(`/photos/${photo.id}`, "PATCH")} />
              </label>
              <button
                type="button"
                disabled={busy}
                className="py-1 text-red-700 hover:underline"
                onClick={() => window.confirm("Delete this photo?") && run(() => api(`/photos/${photo.id}`, { method: "DELETE" }))}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
      <Field label="Add a photo" hint="JPG or PNG, up to 5 MB. It is resized automatically.">
        <input type="file" accept=".jpg,.jpeg,.png" disabled={busy} onChange={send(`/room-types/${type.id}/photos`, "POST")} className="block w-full text-sm" />
      </Field>
    </div>
  );
}

function Rooms({ type, rooms }: { type: RoomType; rooms: Room[] }) {
  const { run, error, busy } = useAction();
  const [number, setNumber] = useState("");
  const [floor, setFloor] = useState("0");
  return (
    <div className="space-y-3">
      <h3 className="font-semibold">Rooms</h3>
      {error && <Notice tone="error">{error}</Notice>}
      <ul className="flex flex-wrap gap-2 text-sm">
        {rooms.map((room) => (
          <li key={room.id} className={`flex items-center gap-2 rounded-md border px-3 py-1.5 ${room.is_active ? "border-slate-300" : "border-slate-200 bg-slate-50 text-slate-500"}`}>
            Room {room.number} · floor {room.floor}
            <button
              type="button"
              disabled={busy}
              className="py-1 text-brand-700 hover:underline"
              onClick={() => run(() => api(`/rooms/${room.id}`, { method: "PATCH", body: { is_active: !room.is_active } }))}
            >
              {room.is_active ? "Take out of use" : "Put back in use"}
            </button>
          </li>
        ))}
        {rooms.length === 0 && <li className="text-slate-600">No rooms yet.</li>}
      </ul>
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          if (await run(() => api("/rooms", { body: { number, floor: Number(floor), room_type: type.id } }))) setNumber("");
        }}
      >
        <Field label="Room number">
          <Input required value={number} onChange={(e) => setNumber(e.target.value)} />
        </Field>
        <Field label="Floor">
          <Input required type="number" value={floor} onChange={(e) => setFloor(e.target.value)} />
        </Field>
        <Button type="submit" variant="secondary" disabled={busy}>
          Add room
        </Button>
      </form>
    </div>
  );
}
