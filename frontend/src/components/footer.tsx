import Link from "next/link";

/** Site footer: the wordmark set large, and the few places a guest or a member of staff needs. */
export function Footer() {
  return (
    <footer className="mt-auto border-t border-border print:hidden">
      <div className="mx-auto grid w-full max-w-[88rem] gap-10 px-4 py-14 md:px-8 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <p className="font-display text-4xl leading-none text-foreground md:text-5xl">
            College <span className="italic text-gold">Guesthouse</span>
          </p>
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted-foreground">
            Rooms on campus for visiting faculty, families of students and guests of the college.
          </p>
        </div>
        <nav aria-label="Guests" className="text-sm">
          <p className="label text-muted-foreground">Guests</p>
          <ul className="mt-4 space-y-2.5">
            <li><Link href="/" className="text-foreground underline-offset-4 hover:underline">Rooms and availability</Link></li>
            <li><Link href="/bookings" className="text-foreground underline-offset-4 hover:underline">My bookings</Link></li>
            <li><Link href="/login" className="text-foreground underline-offset-4 hover:underline">Sign in</Link></li>
          </ul>
        </nav>
        <div className="text-sm">
          <p className="label text-muted-foreground">How it works</p>
          <p className="mt-4 leading-relaxed text-muted-foreground">
            Every request is approved by the college before payment. You pay online once it is approved, and your room is allotted for your arrival.
          </p>
        </div>
      </div>
      <div className="border-t border-border">
        <p className="label mx-auto w-full max-w-[88rem] px-4 py-5 md:px-8 text-muted-foreground">College Guesthouse · Booking desk</p>
      </div>
    </footer>
  );
}
