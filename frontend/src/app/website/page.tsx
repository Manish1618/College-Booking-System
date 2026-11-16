"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Button, Card, Field, Input, inputClass, Loading, Notice, PageTitle } from "@/components/ui";
import { api } from "@/lib/api";
import { isManager, useAction, useMe } from "@/lib/hooks";
import type { SiteContent } from "@/lib/types";

type Key = Exclude<keyof SiteContent, "updated_at">;
type FieldSpec = { key: Key; label: string; hint?: string; max: number; long?: boolean; optional?: boolean; type?: string; rows?: number };

/** The screen is generated from this list: each group is a panel, each entry a box to type in. */
const GROUPS: { title: string; about: string; fields: FieldSpec[] }[] = [
  {
    title: "Name",
    about: "Shown in the top bar, the footer and at the top of the home page.",
    fields: [
      { key: "name", label: "Guesthouse name", hint: "The last word is set in gold italics.", max: 60 },
      { key: "tagline", label: "Short line beside the name", max: 80 },
    ],
  },
  {
    title: "Home page opening",
    about: "The large headline guests see first, and the sentence under it.",
    fields: [
      { key: "headline", label: "Headline", max: 80 },
      { key: "headline_accent", label: "Last word or words, in gold italics", hint: "Leave empty for a plain headline.", max: 40, optional: true },
      { key: "intro", label: "Sentence under the headline", max: 400, long: true },
    ],
  },
  {
    title: "How a stay is arranged",
    about: "The three steps on the home page.",
    fields: [
      { key: "step1_title", label: "First step", max: 60 },
      { key: "step1_body", label: "First step, in a sentence", max: 300, long: true },
      { key: "step2_title", label: "Second step", max: 60 },
      { key: "step2_body", label: "Second step, in a sentence", max: 300, long: true },
      { key: "step3_title", label: "Last step", max: 60 },
      { key: "step3_body", label: "Last step, in a sentence", max: 300, long: true },
    ],
  },
  {
    title: "Visiting",
    about: "The section near the bottom of the home page, and the notes on each room's page. Empty boxes are left out.",
    fields: [
      { key: "about", label: "About the guesthouse", max: 600, long: true, optional: true },
      { key: "checkin_time", label: "Check-in time", max: 40, optional: true },
      { key: "checkout_time", label: "Check-out time", max: 40, optional: true },
      { key: "facilities", label: "Shared facilities", hint: "One per line, for example: Dining hall, Wi-Fi, Power backup", max: 600, long: true, optional: true, rows: 4 },
      { key: "house_rules", label: "House rules", hint: "One per line.", max: 800, long: true, optional: true, rows: 4 },
      { key: "directions", label: "How to reach us", hint: "Nearest gate, parking, landmarks.", max: 400, long: true, optional: true },
      { key: "map_url", label: "Map link", hint: "Paste a Google Maps link starting with https://", max: 200, optional: true, type: "url" },
    ],
  },
  {
    title: "Footer and contact",
    about: "Shown at the bottom of every page. Contact details appear only when filled in.",
    fields: [
      { key: "footer_about", label: "About the guesthouse", max: 300, long: true },
      { key: "address", label: "Address", max: 200, optional: true },
      { key: "contact_phone", label: "Phone", max: 40, optional: true, type: "tel" },
      { key: "contact_email", label: "Email", max: 254, optional: true, type: "email" },
    ],
  },
];

export default function WebsitePage() {
  const { data: me, isLoading } = useMe();
  const allowed = isManager(me);
  const content = useQuery({ queryKey: ["site-content"], queryFn: () => api<SiteContent>("/site-content"), enabled: allowed });

  if (isLoading) return <Loading />;
  if (!allowed) return <Notice tone="error">This page is for guesthouse managers.</Notice>;

  return (
    <>
      <PageTitle title="Website">
        Change the wording guests see. It goes live when you save. Room photos, prices and details are on the{" "}
        <Link href="/manage" className="text-gold underline underline-offset-4">
          Rooms
        </Link>{" "}
        screen.
      </PageTitle>
      {content.isLoading && <Loading />}
      {content.error && <Notice tone="error">{content.error.message}</Notice>}
      {content.data && <WebsiteForm saved={content.data} />}
    </>
  );
}

function WebsiteForm({ saved }: { saved: SiteContent }) {
  const { run, error, busy } = useAction();
  // Only the boxes this manager has typed in are kept here. Every other box follows the saved wording,
  // so a colleague's change that arrives with a refresh is shown, not queued to be overwritten.
  const [edits, setEdits] = useState<Partial<Record<Key, string>>>({});
  const [done, setDone] = useState(false);
  const valueOf = (key: Key) => edits[key] ?? saved[key];
  const changed = GROUPS.flatMap((g) => g.fields).filter((f) => valueOf(f.key).trim() !== saved[f.key]);

  return (
    <form
      className="space-y-6"
      onSubmit={async (e) => {
        e.preventDefault();
        setDone(false);
        const body = Object.fromEntries(changed.map((f) => [f.key, valueOf(f.key).trim()]));
        // The boxes are locked while this runs, so no edit can be typed under the save.
        if (await run(() => api("/site-content", { method: "PATCH", body }))) {
          setEdits({});
          setDone(true);
        }
      }}
    >
      <fieldset disabled={busy} className="space-y-6 disabled:opacity-60">
      {GROUPS.map((group) => (
        <Card key={group.title}>
          <h2 className="text-2xl">{group.title}</h2>
          <p className="mb-5 mt-1 text-sm text-slate-600">{group.about}</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {group.fields.map((f) => {
              const props = {
                value: valueOf(f.key),
                maxLength: f.max,
                required: !f.optional,
                onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
                  setDone(false);
                  setEdits((current) => ({ ...current, [f.key]: e.target.value }));
                },
              };
              return (
                <div key={f.key} className={f.long ? "sm:col-span-2" : undefined}>
                  <Field label={f.label} hint={f.hint}>
                    {f.long ? <textarea rows={f.rows ?? 2} {...props} className={`${inputClass} py-2`} /> : <Input type={f.type ?? "text"} {...props} />}
                  </Field>
                </div>
              );
            })}
          </div>
        </Card>
      ))}
      </fieldset>
      {error && <Notice tone="error">{error}</Notice>}
      {done && (
        <Notice tone="success">
          Saved. The new wording is live.{" "}
          <Link href="/" className="underline underline-offset-4">
            See the home page
          </Link>
        </Notice>
      )}
      <div className="sticky bottom-0 -mx-4 flex flex-wrap items-center gap-3 border-t border-border bg-background/95 px-4 py-4 backdrop-blur-md">
        <Button type="submit" disabled={busy || changed.length === 0}>
          {busy ? "Saving…" : "Save changes"}
        </Button>
        <Button variant="secondary" disabled={busy || changed.length === 0} onClick={() => setEdits({})}>
          Undo edits
        </Button>
        <span className="text-sm text-slate-600" aria-live="polite">
          {changed.length === 0 ? "No unsaved changes" : `${changed.length} unsaved ${changed.length === 1 ? "change" : "changes"}`}
        </span>
      </div>
    </form>
  );
}
