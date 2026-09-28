"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useCountdown } from "@/components/countdown";
import { SmsPeek } from "@/components/sms";
import { Button, Card, ErrorNotice, Loading, Notice, PageTitle, TextInput } from "@/components/ui";
import { post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Accepted } from "@/lib/types";

function Verify() {
  const { t } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const [phone, setPhone] = useState(params.get("phone") ?? "");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const { left, restart } = useCountdown(Number(params.get("wait") ?? 60) || 60);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("auth/otp/verify", { phone, code: code.trim() }, { auth: false });
      router.replace(`/login/?verified=1&phone=${encodeURIComponent(phone)}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      const out = await post<Accepted>("auth/otp/resend", { phone }, { auth: false });
      restart(out.resend_after ?? 60);
      setSent(true);
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-4">
      <PageTitle>{t("auth.verifyTitle")}</PageTitle>
      <Card>
        <form onSubmit={submit} className="space-y-4" noValidate>
          {params.get("phone") ? (
            <p className="text-sm text-slate-600">{t("auth.verifyHint", { phone })}</p>
          ) : (
            <TextInput
              label={t("common.phone")}
              type="tel"
              inputMode="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
            />
          )}
          {sent && <Notice tone="success">{t("auth.sent")}</Notice>}
          <ErrorNotice error={error} />
          <TextInput
            label={t("auth.code")}
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            autoFocus
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" busy={busy} className="w-full">
            {t("auth.verify")}
          </Button>
          <Button variant="ghost" className="w-full" disabled={left > 0 || !phone} onClick={resend}>
            {left > 0 ? t("auth.resendIn", { n: left }) : t("auth.resend")}
          </Button>
        </form>
      </Card>
      <SmsPeek phone={phone} />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Verify />
    </Suspense>
  );
}
