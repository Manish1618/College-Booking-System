"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useFieldArray, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button, Card, Field, inputClass, Loading, Notice, PageTitle } from "@/components/ui";
import { api, ApiError, fmtDate, inr } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import { ID_TYPES, type Availability, type Booking, type RoomType } from "@/lib/types";

const MAX_FILE = 5 * 1024 * 1024;
const FILE_TYPES = ["application/pdf", "image/jpeg", "image/png"];

const guestSchema = z.object({
  name: z.string().trim().min(2, "Enter the guest's full name."),
  phone: z.string().trim().regex(/^\+?[0-9]{10,14}$/, "Enter a valid mobile number."),
  address: z.string().trim().min(5, "Enter the guest's address."),
  id_type: z.enum(ID_TYPES.map(([value]) => value)),
});

const schema = z
  .object({
    category: z.enum(["OFFICIAL", "PERSONAL"]),
    purpose: z.string().trim().min(5, "Say briefly why the guests are visiting."),
    guests: z.array(guestSchema).min(1),
    student_name: z.string().trim(),
    roll_number: z.string().trim(),
    programme: z.string().trim(),
    year: z.string().trim(),
    relationship: z.string().trim(),
  })
  .superRefine((data, ctx) => {
    if (data.category !== "PERSONAL") return;
    for (const key of ["student_name", "roll_number", "programme", "relationship"] as const) {
      if (!data[key]) ctx.addIssue({ code: "custom", path: [key], message: "This is required for a personal stay." });
    }
    if (!/^[1-8]$/.test(data.year)) {
      ctx.addIssue({ code: "custom", path: ["year"], message: "Enter the student's year of study (1 to 8)." });
    }
  });

type FormValues = z.infer<typeof schema>;
const emptyGuest = { name: "", phone: "", address: "", id_type: "AADHAAR" as const };

function checkFile(file: File | undefined, label: string) {
  if (!file) return `${label}: choose a file.`;
  if (!FILE_TYPES.includes(file.type)) return `${label}: only PDF, JPG or PNG files are accepted.`;
  if (file.size > MAX_FILE) return `${label}: the file is larger than 5 MB.`;
  return null;
}

export default function BookPage() {
  const params = useSearchParams();
  const router = useRouter();
  const typeId = params.get("type");
  const checkIn = params.get("check_in");
  const checkOut = params.get("check_out");
  const { data: me, isLoading: meLoading } = useMe();

  const roomType = useQuery({
    queryKey: ["room-type", typeId],
    queryFn: () => api<RoomType>(`/room-types/${typeId}`),
    enabled: !!typeId,
  });
  const quote = useQuery({
    queryKey: ["availability", checkIn, checkOut],
    queryFn: () => api<Availability>(`/availability?check_in=${checkIn}&check_out=${checkOut}`),
    enabled: !!checkIn && !!checkOut,
  });
  const slot = quote.data?.results.find((r) => r.room_type === typeId);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      category: "OFFICIAL",
      purpose: "",
      guests: [emptyGuest],
      student_name: "",
      roll_number: "",
      programme: "",
      year: "",
      relationship: "",
    },
  });
  const guests = useFieldArray({ control: form.control, name: "guests" });
  const category = useWatch({ control: form.control, name: "category" });
  const errors = form.formState.errors;

  const [letter, setLetter] = useState<File>();
  const [ids, setIds] = useState<Record<string, File | undefined>>({});
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  if (!typeId || !checkIn || !checkOut) {
    return (
      <Notice>
        Pick your dates and a room first. <Link href="/" className="underline">Go to rooms</Link>
      </Notice>
    );
  }
  if (meLoading || roomType.isLoading) return <Loading />;
  if (!me) {
    const here = `/book?${params.toString()}`;
    return (
      <Notice>
        Please <Link href={`/login?next=${encodeURIComponent(here)}`} className="font-medium underline">sign in</Link>{" "}
        to request this room. External guests can sign up with an email address or mobile number.
      </Notice>
    );
  }
  if (roomType.error || !roomType.data) return <Notice tone="error">This room type is not available.</Notice>;
  const capacity = roomType.data.capacity;

  async function onSubmit(values: FormValues) {
    setProblem("");
    const fileProblems = [
      values.category === "OFFICIAL" ? checkFile(letter, "Recommendation letter") : null,
      ...guests.fields.map((field, i) => checkFile(ids[field.id], `ID for guest ${i + 1}`)),
    ].filter(Boolean);
    if (fileProblems.length) {
      setProblem(fileProblems.join(" "));
      return;
    }
    setBusy(true);
    let booking: Booking | undefined;
    try {
      // 1. Save the request as a draft. 2. Attach the documents. 3. Submit it for approval.
      booking = await api<Booking>("/bookings", {
        body: {
          room_type: typeId,
          check_in: checkIn,
          check_out: checkOut,
          category: values.category,
          purpose: values.purpose,
          guests: values.guests,
          student_link:
            values.category === "PERSONAL"
              ? {
                  student_name: values.student_name,
                  roll_number: values.roll_number,
                  programme: values.programme,
                  year: Number(values.year),
                  relationship: values.relationship,
                }
              : null,
        },
      });
      const unmatched = [...booking.guests];
      const uploads: [string, File, string | null][] = guests.fields.map((field, i) => {
        // The server returns guests sorted by name, so match each form row by name, not by position.
        const at = Math.max(unmatched.findIndex((g) => g.name === values.guests[i].name.trim()), 0);
        const [guest] = unmatched.splice(at, 1);
        return ["GUEST_ID", ids[field.id]!, guest.id];
      });
      if (values.category === "OFFICIAL") uploads.push(["RECOMMENDATION_LETTER", letter!, null]);
      for (const [type, file, guest] of uploads) {
        const body = new FormData();
        body.append("type", type);
        body.append("file", file);
        if (guest) body.append("guest", guest);
        await api(`/bookings/${booking.id}/documents`, { body });
      }
      await api(`/bookings/${booking.id}/submit`, { method: "POST" });
      router.push(`/bookings/${booking.id}`);
    } catch (e) {
      if (booking) {
        // The draft is saved; let the guest finish it from the booking page.
        router.push(`/bookings/${booking.id}?problem=${encodeURIComponent(e instanceof Error ? e.message : "")}`);
        return;
      }
      if (e instanceof ApiError) setProblem(e.message);
      else setProblem("Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <>
      <PageTitle title={`Request: ${roomType.data.name}`}>
        {fmtDate(checkIn)} to {fmtDate(checkOut)}
        {slot && ` · ${quote.data?.nights} night(s) · ${inr(slot.amount)} total`}
      </PageTitle>
      {slot && slot.available < 1 && (
        <div className="mb-4">
          <Notice tone="error">This room type is no longer free for these dates.</Notice>
        </div>
      )}
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-6">
        <Card className="space-y-4">
          <h2 className="font-semibold">About the stay</h2>
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-slate-700">Type of stay</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {(
                [
                  ["OFFICIAL", "Official stay", "College business. Needs a recommendation letter from a college authority."],
                  ["PERSONAL", "Personal stay", "For guardians visiting a student. Needs the student's details."],
                ] as const
              ).map(([value, title, help]) => (
                <label
                  key={value}
                  className={`flex cursor-pointer gap-3 rounded-md border p-3 ${
                    category === value ? "border-brand-600 bg-brand-50" : "border-slate-300"
                  }`}
                >
                  <input type="radio" value={value} {...form.register("category")} className="mt-1" />
                  <span>
                    <span className="block font-medium">{title}</span>
                    <span className="block text-sm text-slate-600">{help}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Purpose of visit" error={errors.purpose?.message}>
            <textarea rows={2} {...form.register("purpose")} className={`${inputClass} py-2`} />
          </Field>

          {category === "OFFICIAL" ? (
            <Field label="Recommendation letter" hint="PDF, JPG or PNG, up to 5 MB.">
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png"
                onChange={(e) => setLetter(e.target.files?.[0])}
                className="block w-full text-sm"
              />
            </Field>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Student's name" error={errors.student_name?.message}>
                <input {...form.register("student_name")} className={inputClass} />
              </Field>
              <Field label="Roll number" error={errors.roll_number?.message}>
                <input {...form.register("roll_number")} className={inputClass} />
              </Field>
              <Field label="Programme" error={errors.programme?.message} hint="For example, B.Tech CSE">
                <input {...form.register("programme")} className={inputClass} />
              </Field>
              <Field label="Year of study" error={errors.year?.message}>
                <input inputMode="numeric" {...form.register("year")} className={inputClass} />
              </Field>
              <Field label="Your relationship to the student" error={errors.relationship?.message}>
                <input {...form.register("relationship")} className={inputClass} placeholder="Mother, father, guardian…" />
              </Field>
            </div>
          )}
        </Card>

        {guests.fields.map((field, index) => {
          const guestErrors = errors.guests?.[index];
          return (
            <Card key={field.id} className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Guest {index + 1}</h2>
                {guests.fields.length > 1 && (
                  <button type="button" onClick={() => guests.remove(index)} className="py-2 text-sm text-red-700 hover:underline">
                    Remove
                  </button>
                )}
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Full name" error={guestErrors?.name?.message}>
                  <input autoComplete="off" {...form.register(`guests.${index}.name`)} className={inputClass} />
                </Field>
                <Field label="Mobile number" error={guestErrors?.phone?.message}>
                  <input inputMode="tel" {...form.register(`guests.${index}.phone`)} className={inputClass} />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Address" error={guestErrors?.address?.message}>
                    <input {...form.register(`guests.${index}.address`)} className={inputClass} />
                  </Field>
                </div>
                <Field label="Government ID type">
                  <select {...form.register(`guests.${index}.id_type`)} className={inputClass}>
                    {ID_TYPES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Copy of the ID" hint="PDF, JPG or PNG, up to 5 MB. Only guesthouse staff can view it.">
                  <input
                    type="file"
                    accept=".pdf,.jpg,.jpeg,.png"
                    onChange={(e) => setIds((prev) => ({ ...prev, [field.id]: e.target.files?.[0] }))}
                    className="block w-full text-sm"
                  />
                </Field>
              </div>
            </Card>
          );
        })}
        {guests.fields.length < capacity && (
          <Button variant="secondary" onClick={() => guests.append(emptyGuest)}>
            Add another guest
          </Button>
        )}

        {problem && <Notice tone="error">{problem}</Notice>}
        <div className="flex flex-wrap items-center gap-4">
          <Button type="submit" disabled={busy}>
            {busy ? "Submitting…" : "Submit request"}
          </Button>
          <p className="text-sm text-slate-600">
            Your dates are held for 48 hours while the request is reviewed. You pay only after approval.
          </p>
        </div>
      </form>
    </>
  );
}
