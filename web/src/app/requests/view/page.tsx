"use client";

// One request, for whoever may see it: the citizen who owns it, officers of its department,
// administrators. What is shown and what can be done follow the viewer's role.

import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Actions } from "@/components/request-actions";
import { AccessLog, Files, Messages, Summary, Timeline } from "@/components/request-detail";
import { Guard } from "@/components/shell";
import { Card, ErrorNotice, Loading, Notice, Tabs } from "@/components/ui";
import { call } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { ServiceRequest } from "@/lib/types";

type Tab = "timeline" | "messages" | "files" | "access";

function View() {
  const { t, num } = useI18n();
  const { me } = useAuth();
  const params = useSearchParams();
  const id = params.get("id") ?? "";
  const [req, setReq] = useState<ServiceRequest | null>(null);
  const [etag, setEtag] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [stale, setStale] = useState(false);
  const [tab, setTab] = useState<Tab>("timeline");

  const load = useCallback(async () => {
    try {
      const { data, etag } = await call<ServiceRequest>(`requests/${id}`);
      setReq(data);
      setEtag(etag ?? `"${data.version}"`);
    } catch (err) {
      setError(err);
    }
  }, [id]);

  useEffect(() => {
    if (id) load();
  }, [id, load]);

  if (error && !req) return <ErrorNotice error={error} />;
  if (!req || !me) return <Loading />;

  const staff = me.role !== "CITIZEN";
  const tabs: { value: Tab; label: string }[] = [
    { value: "timeline", label: t("req.timeline") },
    { value: "messages", label: t("req.messages") },
    { value: "files", label: t("req.attachments") },
  ];
  // The access log is the citizen's and the auditors'; officers are refused it.
  if (me.role !== "OFFICER" && req.status !== "DRAFT") tabs.push({ value: "access", label: t("req.accessLog") });

  const actions = (
    <Actions
      req={req}
      etag={etag}
      onChange={(r) => {
        setReq(r);
        setEtag(`"${r.version}"`);
        setStale(false);
      }}
      onStale={() => {
        setStale(true);
        load();
      }}
    />
  );

  // One actions panel: under the summary on phones, in the right column on wide screens.
  return (
    <div className="grid items-start gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        {params.get("submitted") && req.tracking_no && (
          <Notice tone="success">{t("req.submitted", { no: num(req.tracking_no) })}</Notice>
        )}
        {stale && <Notice tone="warning">{t("act.staleVersion")}</Notice>}
        <Summary req={req} staff={staff} />
      </div>
      <aside className="lg:sticky lg:top-4 lg:col-start-3 lg:row-span-2 lg:row-start-1">{actions}</aside>
      <Card className="lg:col-span-2">
        <Tabs value={tab} onChange={setTab} options={tabs} />
        {tab === "timeline" && <Timeline id={req.id} version={req.version} />}
        {tab === "messages" && <Messages req={req} staff={staff} onChange={load} />}
        {tab === "files" && <Files req={req} />}
        {tab === "access" && <AccessLog id={req.id} admin={me.role === "ADMIN"} />}
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Guard>
      <Suspense fallback={<Loading />}>
        <View />
      </Suspense>
    </Guard>
  );
}
