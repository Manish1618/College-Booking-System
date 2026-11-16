import type { ReactNode } from "react";

/** The numbered heading that opens each section of the home page: a hairline, a numeral, a serif title. */
export function SectionHead({
  no,
  kicker,
  title,
  id,
  aside,
}: {
  no: string;
  kicker: string;
  title: ReactNode;
  id: string;
  aside?: ReactNode;
}) {
  return (
    <header className="grid gap-x-10 gap-y-4 border-t border-border pt-5 md:grid-cols-12">
      <p className="label flex gap-4 text-muted-foreground md:col-span-3">
        <span className="tabular-nums text-gold">{no}</span>
        {kicker}
      </p>
      <h2 id={id} className="text-4xl leading-[1.02] text-foreground md:col-span-6 md:text-6xl">
        {title}
      </h2>
      {aside && <p className="max-w-xs self-end text-sm leading-relaxed text-muted-foreground md:col-span-3">{aside}</p>}
    </header>
  );
}
