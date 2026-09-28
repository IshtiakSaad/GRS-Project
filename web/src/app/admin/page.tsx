"use client";

// Statistics, each headline beside the numbers that would show it being gamed
// (src/apps/admin_api/stats.py has the pairs and the reasons).

import { useEffect, useState } from "react";
import { Guard } from "@/components/shell";
import { Card, ErrorNotice, Loading, PageTitle, Select, TextInput } from "@/components/ui";
import { useAdminCategories, useDepartments } from "@/lib/admin";
import { get, qs } from "@/lib/api";
import { formatNumber, formatPercent, todayInDhaka } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import type { Metrics, Stats } from "@/lib/types";

type By = Stats["by"];

function Headline({
  label,
  value,
  checks,
}: {
  label: string;
  value: string;
  checks: [string, string][];
}) {
  return (
    <Card>
      <p className="text-sm text-slate-600">{label}</p>
      <p className="mt-1 text-3xl font-semibold text-slate-900">{value}</p>
      <dl className="mt-3 space-y-1 border-t border-slate-100 pt-3">
        {checks.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 text-xs">
            <dt className="text-slate-500">{k}</dt>
            <dd className="font-medium text-slate-800">{v}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function Headlines({ m }: { m: Metrics }) {
  const { t, lang } = useI18n();
  const pct = (x: number | null) => formatPercent(x, lang);
  const n = (x: number | null) => formatNumber(x, lang);
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Headline
        label={t("stats.onTime")}
        value={pct(m.primary.on_time_resolution_rate)}
        checks={[
          [t("stats.infoRate"), pct(m.counter.info_request_rate)],
          [t("stats.medianPaused"), n(m.counter.median_days_paused)],
          [t("stats.rejectionRate"), pct(m.counter.rejection_rate)],
          [t("stats.lateRejections"), n(m.counter.late_rejections)],
        ]}
      />
      <Headline
        label={t("stats.medianDays")}
        value={n(m.primary.median_days_to_resolve)}
        checks={[
          [t("stats.reopenAfterResolve"), pct(m.counter.reopen_rate_after_resolution)],
          [t("stats.reopenAfterReject"), pct(m.counter.reopen_rate_after_rejection)],
        ]}
      />
      <Headline
        label={t("stats.resolved")}
        value={n(m.primary.resolved)}
        checks={[[t("stats.reassignRate"), pct(m.counter.reassignment_rate)]]}
      />
      <Headline
        label={t("stats.resolutionRate")}
        value={pct(m.primary.resolution_rate)}
        checks={[[t("stats.withdrawnLate"), n(m.counter.withdrawn_after_deadline)]]}
      />
    </div>
  );
}

const COUNTS: [keyof Metrics["counts"], Key][] = [
  ["submitted", "stats.submitted"],
  ["open", "stats.open"],
  ["overdue", "stats.overdue"],
  ["resolved", "stats.resolved"],
  ["rejected", "stats.rejected"],
  ["withdrawn", "stats.withdrawn"],
];

function Dashboard() {
  const { t, lang, name } = useI18n();
  const departments = useDepartments();
  const categories = useAdminCategories();
  // The report names groups in English only; departments and services have both names.
  const groupName = (g: Stats["groups"][number]["group"]) => {
    const list = by === "department" ? departments.rows : by === "category" ? categories.rows : null;
    const found = list?.find((x) => x.code === g.code);
    return found ? name(found) : (g.name ?? t("req.unassigned"));
  };
  const [by, setBy] = useState<By>("department");
  const [from, setFrom] = useState(todayInDhaka(-30));
  const [to, setTo] = useState(todayInDhaka());
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
    get<Stats>(`admin/stats${qs({ by, date_from: from, date_to: to })}`).then(setStats, setError);
  }, [by, from, to]);

  const pct = (x: number | null) => formatPercent(x, lang);
  const n = (x: number | null) => formatNumber(x, lang);

  return (
    <div className="space-y-4">
      <PageTitle>{t("stats.title")}</PageTitle>
      <Card className="grid gap-3 sm:grid-cols-3">
        <Select
          label={t("stats.by")}
          value={by}
          onChange={(e) => setBy(e.target.value as By)}
          options={[
            { value: "department", label: t("common.department") },
            { value: "category", label: t("common.category") },
            { value: "officer", label: t("common.officer") },
          ]}
        />
        <TextInput label={t("common.from")} type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        <TextInput label={t("common.to")} type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
      </Card>
      <ErrorNotice error={error} />
      {!stats ? (
        <Loading />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
            {COUNTS.map(([k, label]) => (
              <div key={k} className="rounded-lg bg-white p-3 text-center ring-1 ring-slate-200">
                <p className={`text-xl font-semibold ${k === "overdue" && stats.totals.counts.overdue ? "text-red-700" : ""}`}>
                  {n(stats.totals.counts[k])}
                </p>
                <p className="text-xs text-slate-500">{t(label)}</p>
              </div>
            ))}
          </div>
          <p className="text-sm text-slate-600">{t("stats.checksHint")}</p>
          <Headlines m={stats.totals} />
          <Card className="overflow-x-auto p-0 sm:p-0">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">{t(`common.${by === "category" ? "category" : by}` as Key)}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.submitted")}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.overdue")}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.onTime")}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.rejectionRate")}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.lateRejections")}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.medianDays")}</th>
                  <th className="px-3 py-2 font-medium">{t("stats.reopenAfterResolve")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {stats.groups.map((g, i) => (
                  <tr key={g.group.code ?? `none-${i}`}>
                    <td className="px-3 py-2 font-medium">{groupName(g.group)}</td>
                    <td className="px-3 py-2">{n(g.counts.submitted)}</td>
                    <td className={`px-3 py-2 ${g.counts.overdue ? "text-red-700" : ""}`}>{n(g.counts.overdue)}</td>
                    <td className="px-3 py-2">{pct(g.primary.on_time_resolution_rate)}</td>
                    <td className="px-3 py-2">{pct(g.counter.rejection_rate)}</td>
                    <td className="px-3 py-2">{n(g.counter.late_rejections)}</td>
                    <td className="px-3 py-2">{n(g.primary.median_days_to_resolve)}</td>
                    <td className="px-3 py-2">{pct(g.counter.reopen_rate_after_resolution)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["ADMIN"]}>
      <Dashboard />
    </Guard>
  );
}
