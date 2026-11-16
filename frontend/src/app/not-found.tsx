import Link from "next/link";

import { primaryLink } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="grid gap-8 py-16 md:grid-cols-12 md:py-24">
      <p className="label text-gold md:col-span-3">Page not found</p>
      <div className="md:col-span-9">
        <h1 className="text-6xl leading-[0.95] tracking-[-0.02em] md:text-8xl">
          Nobody is staying <em className="text-gold">here.</em>
        </h1>
        <p className="mt-6 max-w-md text-base leading-relaxed text-muted-foreground">
          The page you were looking for has moved or never existed. The rooms are where they have always been.
        </p>
        <Link href="/" className={`${primaryLink} mt-8`}>
          Back to the rooms
        </Link>
      </div>
    </div>
  );
}
