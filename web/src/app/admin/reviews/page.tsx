"use client";

import Link from "next/link";
import { useState } from "react";
import { viewHref } from "@/components/request-list";
import { Guard } from "@/components/shell";
import { Button, Card, Empty, ErrorNotice, Loading, Notice, PageTitle, StatusBadge, Tabs, TextArea } from "@/components/ui";
import { post, qs } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import { usePaged } from "@/lib/paged";
import type { Review } from "@/lib/types";

type Filter = Review["status"];

function ReviewCard({ review, onDecided }: { review: Review; onDecided: () => void }) {
  const { t, lang, num } = useI18n();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"" | "UPHOLD" | "OVERTURN">("");
  const [error, setError] = useState<unknown>(null);
  const r = review.request;

  async function decide(decision: "UPHOLD" | "OVERTURN") {
    setBusy(decision);
    setError(null);
    try {
      await post(`admin/reviews/${review.id}/decision`, note ? { decision, note } : { decision });
      onDecided();
    } catch (err) {
      setError(err);
      setBusy("");
    }
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Link href={viewHref(r.id)} prefetch={false} className="font-medium text-brand-700 underline">
            {num(r.tracking_no)}
          </Link>
          <p className="text-xs text-slate-500">
            {t(`rev.${review.reason}` as Key)} · {r.department} · {r.category} · {formatDateTime(review.created_at, lang)}
          </p>
        </div>
        <StatusBadge status={review.decided_status} staff />
      </div>
      <p className="text-sm text-slate-600">{t("rev.decidedBy", { name: review.officer.full_name })}</p>
      {review.decided_status === "REJECTED" ? (
        <div className="rounded-lg bg-red-50 p-3 text-sm">
          {r.rejection_reason_code && <p className="font-medium">{t(`reject.${r.rejection_reason_code}` as Key)}</p>}
          {r.rejection_note && <p className="whitespace-pre-wrap">{r.rejection_note}</p>}
        </div>
      ) : (
        r.resolution_note && <div className="whitespace-pre-wrap rounded-lg bg-brand-50 p-3 text-sm">{r.resolution_note}</div>
      )}
      {review.status === "PENDING" ? (
        <div className="space-y-2">
          <ErrorNotice error={error} />
          <TextArea label={`${t("common.note")} (${t("common.optional")})`} rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <Button busy={busy === "UPHOLD"} disabled={!!busy} onClick={() => decide("UPHOLD")}>
              {t("rev.uphold")}
            </Button>
            <Button variant="danger" busy={busy === "OVERTURN"} disabled={!!busy} onClick={() => decide("OVERTURN")}>
              {t("rev.overturn")}
            </Button>
          </div>
        </div>
      ) : (
        <Notice tone={review.status === "OVERTURNED" ? "warning" : "success"}>
          {t(`rev.${review.status}` as Key)}
          {review.reviewer && ` · ${t("rev.reviewedBy", { name: review.reviewer.full_name })}`}
          {review.note && <span className="mt-1 block">{review.note}</span>}
        </Notice>
      )}
    </Card>
  );
}

function Reviews() {
  const { t } = useI18n();
  const [status, setStatus] = useState<Filter>("PENDING");
  const list = usePaged<Review>(`admin/reviews${qs({ status })}`);

  return (
    <div className="space-y-4">
      <PageTitle>{t("rev.title")}</PageTitle>
      <p className="text-sm text-slate-600">{t("rev.hint")}</p>
      <Tabs
        value={status}
        onChange={setStatus}
        options={(["PENDING", "UPHELD", "OVERTURNED"] as Filter[]).map((s) => ({ value: s, label: t(`rev.${s}`) }))}
      />
      <ErrorNotice error={list.error} />
      {!list.rows ? (
        <Loading />
      ) : list.rows.length === 0 ? (
        <Empty />
      ) : (
        <div className="space-y-3">
          {list.rows.map((r) => (
            <ReviewCard key={r.id} review={r} onDecided={list.reload} />
          ))}
          {list.hasMore && (
            <Button variant="secondary" className="w-full" busy={list.busy} onClick={list.more}>
              {t("common.more")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["ADMIN"]}>
      <Reviews />
    </Guard>
  );
}
