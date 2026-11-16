import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

import type { BookingStatus } from "@/lib/types";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

/** Shared shape of every button and button-like link: squared, upper-case, letter-spaced. */
export const buttonBase =
  "inline-flex min-h-11 items-center justify-center gap-2.5 rounded-[2px] px-5 text-[12px] font-semibold uppercase tracking-[0.14em] transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-40 motion-reduce:transition-none";
/** For links that should look like the primary and secondary buttons. */
export const primaryLink = `${buttonBase} bg-primary text-primary-foreground hover:bg-gold-soft`;
export const secondaryLink = `${buttonBase} border border-input text-foreground hover:border-foreground`;

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary: "bg-primary text-primary-foreground enabled:hover:bg-gold-soft print:border print:border-black",
    secondary: "border border-slate-300 bg-transparent text-slate-800 enabled:hover:border-slate-800",
    danger: "border border-red-300 bg-transparent text-red-700 enabled:hover:bg-red-50",
  }[variant];
  return (
    <button
      type="button"
      {...props}
      className={cx(
        buttonBase,
        styles,
        className,
      )}
    />
  );
}

export const inputClass =
  "block min-h-11 w-full rounded-[2px] border border-slate-300 bg-transparent px-3.5 text-base text-slate-900 transition-colors placeholder:text-slate-400 hover:border-slate-500 focus:border-gold print:bg-transparent";

export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
}) {
  // Hint and error sit outside the label so the control's accessible name stays short and stable.
  return (
    <div>
      <label className="block">
        <span className="label mb-1.5 block text-slate-600">{label}</span>
        {children}
      </label>
      {hint && !error && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
      {error && (
        <p role="alert" className="mt-1 text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputClass, props.className)} />;
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cx("glass rounded-[3px] p-5 md:p-7 print:border print:border-slate-300", className)}>{children}</section>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success"; children: ReactNode }) {
  const styles = {
    info: "border-slate-200 bg-card text-slate-800",
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("rounded-[2px] border px-4 py-3 text-sm", styles)}>
      {children}
    </div>
  );
}

const STATUS_TONES: Record<BookingStatus, string> = {
  DRAFT: "bg-slate-100 text-slate-700",
  PENDING: "bg-amber-100 text-amber-900",
  SENT_BACK: "bg-orange-100 text-orange-900",
  APPROVED: "bg-sky-100 text-sky-900",
  CONFIRMED: "bg-emerald-100 text-emerald-900",
  ALLOTTED: "bg-emerald-100 text-emerald-900",
  CHECKED_IN: "bg-brand-100 text-brand-900",
  CHECKED_OUT: "bg-slate-100 text-slate-700",
  REJECTED: "bg-red-100 text-red-800",
  CANCELLED: "bg-slate-100 text-slate-600",
  EXPIRED: "bg-slate-100 text-slate-600",
  NO_SHOW: "bg-red-100 text-red-800",
};

export function StatusBadge({ status, label }: { status: BookingStatus; label: string }) {
  return (
    <span className={cx("inline-block rounded-[2px] px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.08em]", STATUS_TONES[status])}>
      {label}
    </span>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-10 border-b border-slate-200 pb-7 print:border-0">
      <h1 className="text-4xl leading-[1.05] text-slate-900 md:text-5xl">{title}</h1>
      {children && <p className="mt-3 max-w-2xl text-slate-600">{children}</p>}
    </div>
  );
}

/** A quiet placeholder while a page's data loads: a few hairline bars that breathe. */
export function Loading() {
  return (
    <div role="status" className="space-y-4 py-10">
      <span className="sr-only">Loading…</span>
      {["w-1/3 h-9", "w-2/3 h-4", "w-1/2 h-4", "w-full h-28"].map((shape) => (
        <div key={shape} aria-hidden="true" className={`skeleton ${shape}`} />
      ))}
    </div>
  );
}
