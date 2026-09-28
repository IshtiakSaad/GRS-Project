"use client";

import { useState } from "react";
import { RequestList } from "@/components/request-list";
import { Guard } from "@/components/shell";
import { ButtonLink, PageTitle, Tabs } from "@/components/ui";
import { qs } from "@/lib/api";
import { useCategories } from "@/lib/directory";
import { useI18n } from "@/lib/i18n";
import { usePaged } from "@/lib/paged";
import type { RequestRow, Status } from "@/lib/types";

type Filter = "" | Status;

function MyRequests() {
  const { t } = useI18n();
  const categories = useCategories();
  const [status, setStatus] = useState<Filter>("");
  const list = usePaged<RequestRow>(`requests${qs({ status })}`);

  const filters: { value: Filter; label: string }[] = [
    { value: "", label: t("common.all") },
    { value: "AWAITING_CITIZEN", label: t("status.AWAITING_CITIZEN") },
    { value: "DRAFT", label: t("status.DRAFT") },
    { value: "IN_PROGRESS", label: t("status.IN_PROGRESS") },
    { value: "RESOLVED", label: t("status.RESOLVED") },
    { value: "REJECTED", label: t("status.REJECTED") },
  ];

  return (
    <div>
      <PageTitle action={<ButtonLink href="/requests/new/">{t("nav.newRequest")}</ButtonLink>}>
        {t("req.myTitle")}
      </PageTitle>
      <Tabs value={status} onChange={setStatus} options={filters} />
      <RequestList {...list} categories={categories} empty={t("req.none")} />
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["CITIZEN"]}>
      <MyRequests />
    </Guard>
  );
}
