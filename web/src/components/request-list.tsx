"use client";

import Link from "next/link";
import { formatDate, isOverdue } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { OPEN_STATUSES, type Category, type RequestRow } from "@/lib/types";
import { Button, Empty, ErrorNotice, Loading, PriorityLabel, StatusBadge } from "./ui";

export function viewHref(id: string) {
  return `/requests/view/?id=${id}`;
}

/** Requests as tappable cards: works at 360 px, no table to scroll sideways. */
export function RequestList({
  rows,
  staff,
  categories,
  empty,
  hasMore,
  more,
  busy,
  error,
}: {
  rows: RequestRow[] | null;
  staff?: boolean;
  categories?: Category[];
  empty?: string;
  hasMore?: boolean;
  more?: () => void;
  busy?: boolean;
  error?: unknown;
}) {
  const { t, lang, name, num } = useI18n();
  if (error && !rows) return <ErrorNotice error={error} />;
  if (!rows) return <Loading />;
  if (rows.length === 0) return <Empty>{empty}</Empty>;
  const categoryName = (code: string) => {
    const c = categories?.find((x) => x.code === code);
    return c ? name(c) : code;
  };

  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {rows.map((r) => {
          const late = isOverdue(r.due_at, OPEN_STATUSES.includes(r.status));
          return (
            <li key={r.id}>
              {/* No prefetch: a list of 50 would fetch 50 pages up front, costing a 2G phone
                  its data and a shared carrier address its request budget. */}
              <Link
                href={viewHref(r.id)}
                prefetch={false}
                className="block rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 transition hover:ring-brand-600"
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900">
                      {r.title ?? categoryName(r.category)}
                    </p>
                    <p className="text-xs text-slate-500">
                      {r.tracking_no ? num(r.tracking_no) : t("status.DRAFT")}
                      {r.title && ` · ${categoryName(r.category)}`}
                      {staff && r.owner_initials && ` · ${r.owner_initials}`}
                    </p>
                  </div>
                  <StatusBadge status={r.status} staff={staff} />
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-600">
                  {r.submitted_at && <span>{t("common.submittedOn", { date: formatDate(r.submitted_at, lang) })}</span>}
                  {r.due_at && OPEN_STATUSES.includes(r.status) && (
                    <span className={late ? "font-semibold text-red-700" : ""}>
                      {late ? t("common.overdue") : t("common.due", { date: formatDate(r.due_at, lang) })}
                    </span>
                  )}
                  {staff && r.priority && <PriorityLabel priority={r.priority} />}
                  {staff && r.citizen_urgent && <span className="text-red-700">!</span>}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
      {error ? <ErrorNotice error={error} /> : null}
      {hasMore && more && (
        <Button variant="secondary" className="w-full" busy={busy} onClick={more}>
          {t("common.more")}
        </Button>
      )}
    </div>
  );
}
