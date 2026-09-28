"use client";

// Opening a request outside one's department: a stated reason, read-only, reported, and
// shown in the citizen's access log. The answer is the request itself; it cannot be
// reopened by id later, because it is still out of scope.

import { useState } from "react";
import { Summary } from "@/components/request-detail";
import { Guard } from "@/components/shell";
import { Button, Card, ErrorNotice, fieldError, Notice, PageTitle, Select, TextArea, TextInput } from "@/components/ui";
import { post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { BreakGlassReason, ServiceRequest } from "@/lib/types";

const REASONS: BreakGlassReason[] = ["CITIZEN_COMPLAINT", "SUPERVISOR_REVIEW", "AUDIT", "DATA_CORRECTION", "OTHER"];

function BreakGlass() {
  const { t } = useI18n();
  const [trackingNo, setTrackingNo] = useState("");
  const [reason, setReason] = useState<BreakGlassReason>("CITIZEN_COMPLAINT");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [req, setReq] = useState<ServiceRequest | null>(null);

  async function open(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setReq(await post<ServiceRequest>("requests/break-glass", { tracking_no: trackingNo.trim(), reason, note }));
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <PageTitle>{t("bg.title")}</PageTitle>
      <Card>
        <form onSubmit={open} className="space-y-4" noValidate>
          <Notice tone="warning">{t("bg.hint")}</Notice>
          <ErrorNotice error={error} />
          <TextInput
            label={t("req.tracking")}
            value={trackingNo}
            onChange={(e) => setTrackingNo(e.target.value)}
            error={fieldError(error, "tracking_no")}
          />
          <Select
            label={t("common.reason")}
            value={reason}
            onChange={(e) => setReason(e.target.value as BreakGlassReason)}
            options={REASONS.map((r) => ({ value: r, label: t(`bgr.${r}`) }))}
          />
          <TextArea label={t("bg.note")} rows={3} value={note} onChange={(e) => setNote(e.target.value)} error={fieldError(error, "note")} />
          <Button type="submit" busy={busy} disabled={!trackingNo.trim()}>
            {t("bg.open")}
          </Button>
        </form>
      </Card>
      {req && <Summary req={req} staff />}
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["OFFICER"]}>
      <BreakGlass />
    </Guard>
  );
}
