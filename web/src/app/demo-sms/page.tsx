"use client";

import { useState } from "react";
import { SmsList, useDemoSms } from "@/components/sms";
import { Button, Card, PageTitle, TextInput } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

export default function DemoSmsPage() {
  const { t } = useI18n();
  const { me } = useAuth();
  const [draft, setDraft] = useState("");
  const [phone, setPhone] = useState("");
  const shown = phone || me?.phone || "";
  const { messages, reload } = useDemoSms(shown);

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("sms.title")}</PageTitle>
      <Card className="space-y-4">
        <p className="text-sm text-slate-600">{t("sms.hint")}</p>
        <form
          className="flex items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPhone(draft);
            if (draft === phone) reload();
          }}
        >
          <div className="flex-1">
            <TextInput
              label={t("common.phone")}
              type="tel"
              inputMode="tel"
              placeholder={me?.phone ?? "01000000101"}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </div>
          <Button type="submit">{t("sms.show")}</Button>
        </form>
        {shown && <p className="text-sm font-medium text-slate-700">{shown}</p>}
        <SmsList messages={messages} />
      </Card>
    </div>
  );
}
