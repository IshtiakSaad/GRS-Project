"use client";

import { ButtonLink, Card, PageTitle } from "@/components/ui";
import { useI18n } from "@/lib/i18n";

export default function NotFound() {
  const { t } = useI18n();
  return (
    <div className="mx-auto max-w-md">
      <PageTitle>404</PageTitle>
      <Card className="space-y-4">
        <p className="text-sm text-slate-600">{t("app.notFound")}</p>
        <ButtonLink href="/">{t("app.home")}</ButtonLink>
      </Card>
    </div>
  );
}
