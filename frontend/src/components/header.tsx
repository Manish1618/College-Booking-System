"use client";

import Link from "next/link";

import { api } from "@/lib/api";
import { isAdmin, isApprover, isManager, useMe } from "@/lib/hooks";

export function Header() {
  const { data: me, isLoading } = useMe();

  const links = [
    { href: "/", label: "Book a room", show: true },
    { href: "/bookings", label: "My bookings", show: !!me },
    { href: "/bookings?view=approvals", label: "Approvals", show: isApprover(me) },
    { href: "/bookings?view=desk", label: "Desk", show: isManager(me) },
    { href: "/manage", label: "Rooms", show: isManager(me) },
    { href: "/admin", label: "Admin", show: isAdmin(me) },
  ].filter((link) => link.show);

  async function signOut() {
    await api("/auth/logout", { method: "POST" });
    // A full page load rather than a client-side move: it drops everything this tab holds in memory
    // for the person who just signed out (fetched bookings, half-filled forms, the sign-in form).
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- the reload is the point
    window.location.assign("/");
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="text-lg font-semibold text-brand-700">
          College Guesthouse
        </Link>
        <nav aria-label="Main" className="flex flex-1 flex-wrap gap-x-4 gap-y-1 text-sm">
          {links.map((link) => (
            <Link key={link.href} href={link.href} className="py-2 text-slate-700 hover:text-brand-700">
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-3 text-sm">
          {isLoading ? null : me ? (
            <>
              <span className="text-slate-600">{me.name || me.email || me.phone}</span>
              <button type="button" onClick={signOut} className="py-2 font-medium text-brand-700 hover:underline">
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="py-2 font-medium text-brand-700 hover:underline">
              Sign in
            </Link>
          )}
        </div>
      </div>
      {me?.mfa.required && !me.mfa.verified && (
        <div className="bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
          Staff screens are locked until you finish two-step verification.{" "}
          <Link href="/login" className="font-medium underline">
            Verify now
          </Link>
        </div>
      )}
    </header>
  );
}
