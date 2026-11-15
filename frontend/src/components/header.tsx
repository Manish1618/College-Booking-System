"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { api } from "@/lib/api";
import { isAdmin, isApprover, isManager, useMe } from "@/lib/hooks";

export function Header() {
  const { data: me, isLoading } = useMe();
  const pathname = usePathname();
  const view = useSearchParams().get("view");
  const here = view ? `${pathname}?view=${view}` : pathname;

  const links = [
    { href: "/", label: "Book a room", show: true },
    { href: "/bookings", label: "My bookings", show: !!me },
    { href: "/bookings?view=approvals", label: "Approvals", show: isApprover(me) },
    { href: "/desk", label: "Desk", show: isManager(me) },
    { href: "/bookings?view=desk", label: "All bookings", show: isManager(me) },
    { href: "/register", label: "Register", show: isManager(me) },
    { href: "/manage", label: "Rooms", show: isManager(me) },
    { href: "/reports", label: "Reports", show: isManager(me) },
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
    <header className="sticky top-0 z-40 border-b border-gold/15 bg-background/70 shadow-[0_10px_30px_-20px_rgb(0_0_0/0.9)] backdrop-blur-xl backdrop-saturate-150 print:hidden">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="group flex items-center gap-3">
          <span
            aria-hidden="true"
            className="grid size-9 place-items-center rounded-full border border-gold/50 bg-gradient-to-b from-[#2a2417] to-black font-display text-lg font-semibold text-gold shadow-[inset_0_1px_0_rgb(255_255_255/0.12),0_6px_18px_-8px_rgb(212_175_55/0.6)] transition-transform group-hover:rotate-[-8deg] motion-reduce:transition-none"
          >
            G
          </span>
          <span className="flex flex-col leading-none">
            <span className="font-display text-xl font-semibold tracking-wide text-gold-soft">College Guesthouse</span>
            <span className="mt-1 hidden text-[10px] font-medium uppercase sm:block tracking-[0.3em] text-slate-500">On campus stays</span>
          </span>
        </Link>
        <nav aria-label="Main" className="flex flex-1 flex-wrap gap-1 text-sm">
          {links.map((link) => {
            const active = link.href === here;
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-full px-3 py-2 transition-colors ${active ? "bg-gold/12 text-gold-soft ring-1 ring-gold/30" : "text-slate-600 hover:bg-white/5 hover:text-gold-soft"}`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-3 text-sm">
          {isLoading ? null : me ? (
            <>
              <span className="text-slate-600">{me.name || me.email || me.phone}</span>
              <button type="button" onClick={signOut} className="rounded-full border border-gold/30 px-4 py-2 font-medium text-gold-soft transition-colors hover:border-gold hover:bg-gold/10">
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="rounded-full bg-gradient-to-b from-gold-soft to-gold px-4 py-2 font-semibold text-black shadow-[0_8px_22px_-12px_rgb(212_175_55/0.9)]">
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
