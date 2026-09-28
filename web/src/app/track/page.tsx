"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { viewHref } from "@/components/request-list";
import { Guard } from "@/components/shell";
import { Button, Card, ErrorNotice, PageTitle, TextInput } from "@/components/ui";
import { get } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ServiceRequest } from "@/lib/types";

function Track() {
  const { t } = useI18n();
  const router = useRouter();
  const [number, setNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function find(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const req = await get<ServiceRequest>(`requests/by-tracking/${encodeURIComponent(number.trim())}`);
      router.push(viewHref(req.id));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("track.title")}</PageTitle>
      <Card>
        <form onSubmit={find} className="space-y-4" noValidate>
          <ErrorNotice error={error} />
          <TextInput
            label={t("req.tracking")}
            hint={t("track.hint")}
            inputMode="numeric"
            autoComplete="off"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
          />
          <Button type="submit" busy={busy} disabled={!number.trim()} className="w-full">
            {t("common.search")}
          </Button>
        </form>
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Guard>
      <Track />
    </Guard>
  );
}
