import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

import type { BookingStatus } from "@/lib/types";

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(" ");

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary:
      "bg-gradient-to-b from-gold-soft to-gold text-black shadow-[0_10px_28px_-14px_rgb(212_175_55/0.9)] enabled:hover:-translate-y-px enabled:hover:shadow-[0_14px_34px_-14px_rgb(212_175_55/1)] print:bg-none print:border print:border-black",
    secondary: "border border-slate-300 bg-transparent text-slate-800 hover:border-gold/60 hover:bg-gold/10",
    danger: "border border-red-300 bg-transparent text-red-700 hover:bg-red-50",
  }[variant];
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-semibold tracking-wide transition-[color,background-color,border-color,translate,box-shadow] duration-200 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none",
        styles,
        className,
      )}
    />
  );
}

export const inputClass =
  "block min-h-11 w-full rounded-xl border border-slate-300 bg-white/[0.03] px-3.5 text-base text-slate-900 shadow-[inset_0_1px_2px_rgb(0_0_0/0.25)] transition-colors placeholder:text-slate-400 hover:border-gold/40 focus:border-gold/70 print:bg-transparent";

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
        <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
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
  return <section className={cx("glass rounded-2xl p-5 md:p-6 print:border print:border-slate-300 print:shadow-none", className)}>{children}</section>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success"; children: ReactNode }) {
  const styles = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    error: "border-red-200 bg-red-50 text-red-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("rounded-xl border px-4 py-3 text-sm backdrop-blur-sm", styles)}>
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
    <span className={cx("inline-block rounded-full px-2.5 py-0.5 text-xs font-medium", STATUS_TONES[status])}>
      {label}
    </span>
  );
}

export function PageTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-8">
      <span aria-hidden="true" className="mb-3 block h-px w-12 bg-gradient-to-r from-gold to-transparent print:hidden" />
      <h1 className="text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">{title}</h1>
      {children && <p className="mt-2 max-w-2xl text-slate-600">{children}</p>}
    </div>
  );
}

export function Loading() {
  return <p className="py-8 text-center text-slate-500">Loading…</p>;
}
