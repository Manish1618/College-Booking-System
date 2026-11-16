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
    <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur-md print:hidden">
      <div className="mx-auto flex max-w-[88rem] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-4 md:px-8">
        <Link href="/" className="font-display text-2xl leading-none text-foreground">
          College <span className="italic text-gold">Guesthouse</span>
        </Link>
        <nav aria-label="Main" className="order-last flex basis-full flex-wrap gap-x-6 gap-y-1 sm:order-none sm:flex-1 sm:basis-auto">
          {links.map((link) => {
            const active = link.href === here;
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`label whitespace-nowrap border-b py-2 transition-colors ${active ? "border-gold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-3 text-sm">
          {isLoading ? null : me ? (
            <>
              <span className="text-slate-600">{me.name || me.email || me.phone}</span>
              <button type="button" onClick={signOut} className="label border-b border-transparent py-2 text-muted-foreground transition-colors hover:border-foreground hover:text-foreground">
                Sign out
              </button>
            </>
          ) : (
            <Link href="/login" className="label rounded-[2px] border border-input px-4 py-2.5 text-foreground transition-colors hover:border-foreground">
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
