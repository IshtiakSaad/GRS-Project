"use client";

// The officer's day: what is theirs, and one button that takes the next request. Officers
// do not choose from the queue (decision 3); they see its order so it is not a black box.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RequestList, viewHref } from "@/components/request-list";
import { Guard } from "@/components/shell";
import { Button, Card, ErrorNotice, Notice, PageTitle, SectionTitle } from "@/components/ui";
import { call, get, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useCategories } from "@/lib/directory";
import { useI18n } from "@/lib/i18n";
import { OPEN_STATUSES, type Page, type Queue, type RequestRow, type ServiceRequest } from "@/lib/types";

function OfficerHome() {
  const { t } = useI18n();
  const { me } = useAuth();
  const router = useRouter();
  const categories = useCategories();
  const [queue, setQueue] = useState<Queue | null>(null);
  const [busy, setBusy] = useState(false);
  const [empty, setEmpty] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [mine, setMine] = useState<RequestRow[] | null>(null);

  const loadQueue = useCallback(async () => {
    try {
      setQueue(await get<Queue>("queue"));
    } catch (err) {
      setError(err);
    }
  }, []);

  // Only the open ones, asked of the API per status: filtering a page here would hide open
  // requests behind a page of closed ones. Soonest deadline first.
  const loadMine = useCallback(async () => {
    if (!me) return;
    try {
      const pages = await Promise.all(
        OPEN_STATUSES.map((status) => get<Page<RequestRow>>(`requests${qs({ officer: me.id, status, page_size: 50 })}`)),
      );
      const rows = pages.flatMap((p) => p.results);
      rows.sort((a, b) => (a.due_at ?? "9").localeCompare(b.due_at ?? "9"));
      setMine(rows);
    } catch (err) {
      setError(err);
    }
  }, [me]);

  useEffect(() => {
    loadQueue();
    loadMine();
  }, [loadQueue, loadMine]);

  async function takeNext() {
    setBusy(true);
    setError(null);
    setEmpty(false);
    try {
      const { data, status } = await call<ServiceRequest>("queue/claim-next", { method: "POST" });
      if (status === 204) {
        setEmpty(true);
        await loadQueue();
        setBusy(false);
        return;
      }
      router.push(viewHref(data.id));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageTitle>{t("queue.title")}</PageTitle>
      <Card className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-lg font-semibold">{queue ? t("queue.waiting", { n: queue.waiting }) : "…"}</p>
          <p className="text-sm text-slate-600">{t("queue.hint")}</p>
        </div>
        <Button onClick={takeNext} busy={busy} disabled={queue?.waiting === 0} className="w-full sm:w-auto">
          {t("queue.takeNext")}
        </Button>
      </Card>
      <ErrorNotice error={error} />
      {empty && <Notice>{t("queue.empty")}</Notice>}

      <section>
        <SectionTitle>{t("queue.mine")}</SectionTitle>
        <RequestList rows={mine} staff categories={categories} />
      </section>

      {queue && queue.requests.length > 0 && (
        <section>
          <SectionTitle>{t("queue.upNext")}</SectionTitle>
          <RequestList rows={queue.requests} staff categories={categories} />
        </section>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["OFFICER"]}>
      <OfficerHome />
    </Guard>
  );
}
