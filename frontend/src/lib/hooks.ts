"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "./api";
import type { Me, SiteContent } from "./types";

/** The signed-in user, or null when signed out. */
export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (error) {
        if (error instanceof ApiError && (error.status === 403 || error.status === 401)) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export const isManager = (me: Me | null | undefined) =>
  !!me && (me.role === "MANAGER" || me.role === "ADMIN") && (!me.mfa.required || me.mfa.verified);
export const isAdmin = (me: Me | null | undefined) => isManager(me) && me?.role === "ADMIN";
export const isApprover = (me: Me | null | undefined) => me?.role === "APPROVER" || isAdmin(me);

/** Refetch everything after a change, so every screen shows the new state. */
export function useRefresh() {
  const client = useQueryClient();
  return () => client.invalidateQueries();
}

/** Runs a change, then refetches. Gives back the error message to show, if any. */
export function useAction() {
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
  return { run, error, setError, busy };
}

/** The wording shown until the saved wording loads, and if it cannot be loaded. Matches the server's defaults. */
export const DEFAULT_SITE: SiteContent = {
  name: "College Guesthouse",
  tagline: "Rooms on campus",
  headline: "Stay on campus,",
  headline_accent: "quietly.",
  intro: "Pick your dates and a room. The college approves your request, then you pay online and your room is ready when you arrive.",
  step1_title: "You send a request",
  step1_body: "Choose dates and a room, and tell us who is staying and why you are visiting.",
  step2_title: "The college approves it",
  step2_body: "Your request goes to the college for approval. You hear back by email, and nothing is charged until then.",
  step3_title: "You pay, and arrive",
  step3_body: "Pay online once approved. Your room is allotted and waiting at the desk when you check in.",
  footer_about: "Rooms on campus for visiting faculty, families of students and guests of the college.",
  contact_phone: "",
  contact_email: "",
  address: "",
};

/** The site's wording as managers last saved it. */
export function useSiteContent(): SiteContent {
  const { data } = useQuery({ queryKey: ["site-content"], queryFn: () => api<SiteContent>("/site-content"), staleTime: 60_000 });
  return data ?? DEFAULT_SITE;
}

/** Splits a name so its last word can be set in italics: "College Guesthouse" gives ["College", "Guesthouse"]. */
export function splitName(name: string): [string, string] {
  const words = name.trim().split(/\s+/);
  return words.length < 2 ? [name.trim(), ""] : [words.slice(0, -1).join(" "), words[words.length - 1]];
}
