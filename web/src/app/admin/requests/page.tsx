"use client";

import { useState } from "react";
import { RequestList } from "@/components/request-list";
import { Guard } from "@/components/shell";
import { Card, Checkbox, PageTitle, Select } from "@/components/ui";
import { qs } from "@/lib/api";
import { useDepartments } from "@/lib/admin";
import { useCategories } from "@/lib/directory";
import { useI18n } from "@/lib/i18n";
import { usePaged } from "@/lib/paged";
import type { RequestRow, Status } from "@/lib/types";

const STATUSES: Status[] = ["SUBMITTED", "ASSIGNED", "IN_PROGRESS", "AWAITING_CITIZEN", "RESOLVED", "REJECTED", "WITHDRAWN"];

function AllRequests() {
  const { t, name } = useI18n();
  const categories = useCategories();
  const departments = useDepartments();
  const [filters, setFilters] = useState({ status: "", department: "", category: "", overdue: false });
  const list = usePaged<RequestRow>(
    `requests${qs({ ...filters, overdue: filters.overdue || undefined })}`,
  );
  const set = (k: keyof typeof filters) => (e: React.ChangeEvent<HTMLSelectElement>) =>
    setFilters({ ...filters, [k]: e.target.value });

  return (
    <div className="space-y-4">
      <PageTitle>{t("all.title")}</PageTitle>
      <Card className="grid gap-3 sm:grid-cols-3">
        <Select
          label={t("common.status")}
          value={filters.status}
          onChange={set("status")}
          options={[{ value: "", label: t("common.all") }, ...STATUSES.map((s) => ({ value: s, label: t(`status.${s}`) }))]}
        />
        <Select
          label={t("common.department")}
          value={filters.department}
          onChange={set("department")}
          options={[
            { value: "", label: t("common.all") },
            ...(departments.rows ?? []).map((d) => ({ value: d.code, label: name(d) })),
          ]}
        />
        <Select
          label={t("common.category")}
          value={filters.category}
          onChange={set("category")}
          options={[
            { value: "", label: t("common.all") },
            ...categories
              .filter((c) => !filters.department || c.department === filters.department)
              .map((c) => ({ value: c.code, label: name(c) })),
          ]}
        />
        <Checkbox
          label={t("all.overdueOnly")}
          checked={filters.overdue}
          onChange={(e) => setFilters({ ...filters, overdue: e.target.checked })}
        />
      </Card>
      <RequestList {...list} staff categories={categories} />
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["ADMIN"]}>
      <AllRequests />
    </Guard>
  );
}
