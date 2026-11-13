/** Thin fetch wrapper: same-origin session cookie, CSRF header, JSON or multipart bodies. */

import type { Page } from "./types";

export class ApiError extends Error {
  status: number;
  fields: Record<string, string[]>;

  constructor(status: number, body: unknown) {
    const fields: Record<string, string[]> = {};
    const messages: string[] = [];
    if (body && typeof body === "object") {
      for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
        const list = (Array.isArray(value) ? value : [value]).map((v) =>
          typeof v === "string" ? v : JSON.stringify(v),
        );
        if (key === "detail" || key === "non_field_errors") messages.push(...list);
        else fields[key] = list;
      }
    }
    if (!messages.length) {
      messages.push(...Object.entries(fields).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v.join(" ")}`));
    }
    super(messages.join(" ") || defaultMessage(status));
    this.status = status;
    this.fields = fields;
  }
}

function defaultMessage(status: number) {
  if (status === 401 || status === 403) return "You do not have access to this.";
  if (status === 404) return "Not found.";
  if (status === 429) return "Too many attempts. Please wait and try again.";
  return "Something went wrong. Please try again.";
}

function csrfToken() {
  return document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] ?? "";
}

async function ensureCsrf() {
  if (!csrfToken()) await fetch("/api/auth/csrf", { credentials: "same-origin" });
}

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? (options.body === undefined ? "GET" : "POST");
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (method !== "GET") {
    await ensureCsrf();
    headers["X-CSRFToken"] = csrfToken();
    if (options.body instanceof FormData) body = options.body;
    else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
  }
  const response = await fetch(`/api${path}`, { method, headers, body, credentials: "same-origin" });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data);
  return data as T;
}

/** Every page of a paginated list, for short lists that feed a selector. Long lists are paged on screen. */
export async function apiAll<T>(path: string): Promise<T[]> {
  const items: T[] = [];
  for (let page = 1; ; page++) {
    const data = await api<Page<T>>(`${path}${path.includes("?") ? "&" : "?"}page=${page}`);
    items.push(...data.results);
    if (!data.next) return items;
  }
}

export const inr = (amount: string | number | null | undefined) =>
  amount == null
    ? "—"
    : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(
        Number(amount),
      );

export const fmtDate = (iso: string) =>
  new Date(iso + (iso.length === 10 ? "T00:00:00" : "")).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export const isoDate = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
