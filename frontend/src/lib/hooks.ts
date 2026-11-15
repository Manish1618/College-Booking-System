"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "./api";
import type { Me } from "./types";

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
