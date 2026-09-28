// Dates are shown in Dhaka time whatever the device's clock says: deadlines are Dhaka dates.

import type { Lang } from "./types";

const TZ = "Asia/Dhaka";

function locale(lang: Lang) {
  return lang === "bn" ? "bn-BD" : "en-GB";
}

export function formatDate(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale(lang), {
    timeZone: TZ,
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(iso));
}

export function formatDateTime(iso: string | null | undefined, lang: Lang): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat(locale(lang), {
    timeZone: TZ,
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    // bn-BD would print a Latin "PM" after Bangla digits; a 24-hour clock reads cleanly.
    hourCycle: lang === "bn" ? "h23" : "h12",
  }).format(new Date(iso));
}

export function formatSize(bytes: number, lang: Lang): string {
  const n = new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 1 });
  if (bytes < 1024) return `${n.format(bytes)} B`;
  if (bytes < 1024 * 1024) return `${n.format(bytes / 1024)} KB`;
  return `${n.format(bytes / (1024 * 1024))} MB`;
}

export function formatPercent(ratio: number | null | undefined, lang: Lang): string {
  if (ratio === null || ratio === undefined) return "—";
  return new Intl.NumberFormat(locale(lang), { style: "percent", maximumFractionDigits: 1 }).format(
    ratio,
  );
}

export function formatNumber(n: number | null | undefined, lang: Lang): string {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat(locale(lang), { maximumFractionDigits: 2 }).format(n);
}

export function isOverdue(dueAt: string | null | undefined, open: boolean): boolean {
  return open && !!dueAt && new Date(dueAt).getTime() < Date.now();
}

/** Today's date in Dhaka, as YYYY-MM-DD. */
export function todayInDhaka(offsetDays = 0): string {
  const d = new Date(Date.now() + offsetDays * 86_400_000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(d);
}
