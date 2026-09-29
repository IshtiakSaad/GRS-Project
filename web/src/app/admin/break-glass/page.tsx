"use client";

import Link from "next/link";
import { useState } from "react";
import { viewHref } from "@/components/request-list";
import { Guard } from "@/components/shell";
import { Button, Card, Empty, ErrorNotice, Loading, PageTitle, Tabs } from "@/components/ui";
import { formatDateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import { usePaged } from "@/lib/paged";
import type { BreakGlassEntry } from "@/lib/types";

type Days = "7" | "30" | "90";

function Report() {
  const { t, lang, name, num } = useI18n();
  const [days, setDays] = useState<Days>("30");
  const list = usePaged<BreakGlassEntry>(`admin/break-glass?days=${days}`);

  return (
    <div className="space-y-4">
      <PageTitle>{t("bgrep.title")}</PageTitle>
      <p className="text-sm text-slate-600">{t("bgrep.hint")}</p>
      <Tabs value={days} onChange={setDays} options={(["7", "30", "90"] as Days[]).map((d) => ({ value: d, label: t("bgrep.days", { n: Number(d) }) }))} />
      <ErrorNotice error={list.error} />
      {!list.rows ? (
        <Loading />
      ) : list.rows.length === 0 ? (
        <Empty />
      ) : (
        <Card>
          <ul className="divide-y divide-slate-100">
            {list.rows.map((e, i) => (
              <li key={`${e.at}-${i}`} className="py-3 text-sm">
                <p>
                  <span className="font-medium">{e.actor.name}</span> · {name(e.office)} ·{" "}
                  <Link href={viewHref(e.request.id)} prefetch={false} className="whitespace-nowrap text-brand-700 underline">
                    {num(e.request.tracking_no)}
                  </Link>
                </p>
                <p className="text-xs text-slate-500">
                  {formatDateTime(e.at, lang)} · {t(`access.${e.kind}` as Key)}
                  {e.break_glass_reason ? ` · ${t(`bgr.${e.break_glass_reason}` as Key)}` : ""}
                </p>
                {e.break_glass_note && <p className="mt-1 text-slate-700">{e.break_glass_note}</p>}
              </li>
            ))}
          </ul>
          {list.hasMore && (
            <Button variant="secondary" className="w-full" busy={list.busy} onClick={list.more}>
              {t("common.more")}
            </Button>
          )}
        </Card>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["ADMIN"]}>
      <Report />
    </Guard>
  );
}
