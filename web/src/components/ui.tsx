"use client";

// Small building blocks. Tap targets are at least 44 px high: the app is meant for phones.

import Link from "next/link";
import { useId } from "react";
import { ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import type { Priority, Status } from "@/lib/types";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  busy?: boolean;
};

const VARIANTS = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50 disabled:opacity-50",
  danger: "bg-accent-600 text-white hover:bg-red-700 disabled:opacity-50",
  ghost: "text-brand-700 hover:bg-brand-50 disabled:opacity-50",
};

export function Button({ variant = "primary", busy, className = "", children, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || busy}
      aria-busy={busy || undefined}
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-medium transition ${VARIANTS[variant]} ${className}`}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  );
}

export function ButtonLink({
  href,
  variant = "primary",
  className = "",
  children,
}: {
  href: string;
  variant?: keyof typeof VARIANTS;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center justify-center rounded-lg px-4 text-sm font-medium transition ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

export function Spinner({ small }: { small?: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${small ? "h-4 w-4" : "h-6 w-6"}`}
    />
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-3 py-10 text-slate-500" role="status">
      <Spinner /> {t("app.loading")}
    </div>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 sm:p-6 ${className}`}>{children}</section>;
}

export function PageTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-semibold text-slate-900 sm:text-2xl">{children}</h1>
      {action}
    </div>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-3 text-base font-semibold text-slate-900">{children}</h2>;
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "success" | "warning" | "error";
  children: React.ReactNode;
}) {
  const tones = {
    info: "bg-sky-50 text-sky-900 ring-sky-200",
    success: "bg-brand-50 text-brand-800 ring-brand-100",
    warning: "bg-amber-50 text-amber-900 ring-amber-200",
    error: "bg-red-50 text-red-900 ring-red-200",
  };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-lg px-4 py-3 text-sm ring-1 ${tones[tone]}`}>
      {children}
    </div>
  );
}

/** An API error in the user's language, with the request id to quote to support. */
export function ErrorNotice({ error }: { error: unknown }) {
  const { t } = useI18n();
  if (!error) return null;
  let text = t("error.generic");
  let ref = "";
  if (error instanceof ApiError) {
    if (error.code === "NETWORK") text = t("error.network");
    else if (error.message) text = error.message;
    // The API's own message usually says when to retry; add it only when there is none.
    if (error.retryAfter && !error.message) text += ` ${t("error.retryIn", { n: error.retryAfter })}`;
    ref = error.requestId;
  }
  return (
    <Notice tone="error">
      {text}
      {ref && <span className="mt-1 block text-xs opacity-70">{t("error.reference", { id: ref })}</span>}
    </Notice>
  );
}

/** The field's own message from an API validation error. */
export function fieldError(error: unknown, name: string): string | undefined {
  return error instanceof ApiError ? error.field(name) : undefined;
}

type FieldProps = {
  label: string;
  hint?: string;
  error?: string;
  children: (id: string, describedBy: string | undefined) => React.ReactNode;
};

export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errId = error ? `${id}-err` : undefined;
  const describedBy = [hintId, errId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-slate-800">
        {label}
      </label>
      {children(id, describedBy)}
      {hint && (
        <p id={hintId} className="text-xs text-slate-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={errId} className="text-sm text-red-700">
          {error}
        </p>
      )}
    </div>
  );
}

const INPUT =
  "block w-full min-h-11 rounded-lg border-0 bg-white px-3 py-2 text-base ring-1 ring-slate-300 placeholder:text-slate-400 focus:ring-2 focus:ring-brand-600 aria-[invalid=true]:ring-red-500";

export function TextInput({
  label,
  hint,
  error,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string; error?: string }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <input id={id} aria-describedby={describedBy} aria-invalid={!!error || undefined} className={INPUT} {...rest} />
      )}
    </Field>
  );
}

export function TextArea({
  label,
  hint,
  error,
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string; error?: string }) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <textarea
          id={id}
          rows={4}
          aria-describedby={describedBy}
          aria-invalid={!!error || undefined}
          className={INPUT}
          {...rest}
        />
      )}
    </Field>
  );
}

export function Select({
  label,
  hint,
  error,
  options,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  label: string;
  hint?: string;
  error?: string;
  options: { value: string; label: string }[];
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      {(id, describedBy) => (
        <select id={id} aria-describedby={describedBy} aria-invalid={!!error || undefined} className={INPUT} {...rest}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

export function Checkbox({
  label,
  hint,
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <input id={id} type="checkbox" className="mt-1 h-5 w-5 rounded border-slate-300 accent-brand-600" {...rest} />
      <label htmlFor={id} className="text-sm text-slate-800">
        {label}
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </label>
    </div>
  );
}

const STATUS_TONE: Record<Status, string> = {
  DRAFT: "bg-slate-100 text-slate-700",
  SUBMITTED: "bg-sky-100 text-sky-800",
  ASSIGNED: "bg-indigo-100 text-indigo-800",
  IN_PROGRESS: "bg-amber-100 text-amber-900",
  AWAITING_CITIZEN: "bg-orange-100 text-orange-900",
  RESOLVED: "bg-brand-100 text-brand-800",
  REJECTED: "bg-red-100 text-red-800",
  WITHDRAWN: "bg-slate-100 text-slate-600",
};

export function StatusBadge({ status, staff }: { status: Status; staff?: boolean }) {
  const { t } = useI18n();
  const key = (staff && status === "AWAITING_CITIZEN" ? "status.AWAITING_CITIZEN.staff" : `status.${status}`) as Key;
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}>
      {t(key)}
    </span>
  );
}

const PRIORITY_TONE: Record<Priority, string> = {
  LOW: "text-slate-500",
  NORMAL: "text-slate-700",
  HIGH: "text-amber-700 font-medium",
  URGENT: "text-red-700 font-semibold",
};

export function PriorityLabel({ priority }: { priority: Priority }) {
  const { t } = useI18n();
  return <span className={`text-xs ${PRIORITY_TONE[priority]}`}>{t(`priority.${priority}` as Key)}</span>;
}

export function Empty({ children }: { children?: React.ReactNode }) {
  const { t } = useI18n();
  return <p className="py-8 text-center text-sm text-slate-500">{children ?? t("common.none")}</p>;
}

/** A definition list row: label on the left, value on the right (stacked on phones). */
export function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-0.5 py-2 sm:grid-cols-3 sm:gap-4">
      <dt className="text-sm text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-900 sm:col-span-2">{children}</dd>
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div role="tablist" className="mb-4 flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          type="button"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={`min-h-10 shrink-0 rounded-md px-3 text-sm font-medium ${
            o.value === value ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
