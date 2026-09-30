"use client";

// One form behind two doors. "Forgot password" asks for the number first and sends a code.
// "Set your password" is where a new officer lands from the welcome SMS: the code is already on
// their phone and the number is in the link, so it starts at the code.

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useCountdown } from "@/components/countdown";
import { DEMO } from "@/components/shell";
import { SmsPeek } from "@/components/sms";
import { Button, Card, ErrorNotice, fieldError, Notice, PageTitle, TextInput } from "@/components/ui";
import { post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Accepted } from "@/lib/types";

export function PasswordCode({ setup = false }: { setup?: boolean }) {
  const { t } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const fromLink = setup ? (params.get("phone") ?? "") : "";
  const [phone, setPhone] = useState(fromLink);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState(setup);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const { left, restart } = useCountdown(0);

  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await post<Accepted>("auth/password/reset/request", { phone }, { auth: false });
      restart(out.resend_after ?? 60);
      setSent(true);
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  async function confirm(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post(
        "auth/password/reset/confirm",
        { phone, code: code.trim(), new_password: password },
        { auth: false },
      );
      router.replace(`/login/?${setup ? "set" : "reset"}=1&phone=${encodeURIComponent(phone)}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const phoneInput = (
    <TextInput
      label={t("common.phone")}
      hint={t(DEMO ? "auth.phoneHintDemo" : "auth.phoneHint")}
      type="tel"
      inputMode="tel"
      autoComplete="username"
      required
      value={phone}
      onChange={(e) => setPhone(e.target.value)}
      error={fieldError(error, "phone")}
    />
  );

  return (
    <div className="mx-auto max-w-md space-y-4">
      <PageTitle>{t(setup ? "auth.setTitle" : "auth.resetTitle")}</PageTitle>
      <Card>
        {!sent ? (
          <form onSubmit={send} className="space-y-4" noValidate>
            <p className="text-sm text-slate-600">{t("auth.resetHint")}</p>
            {DEMO && <Notice>{t("auth.demoMode")}</Notice>}
            <ErrorNotice error={error} />
            {phoneInput}
            <Button type="submit" busy={busy} className="w-full">
              {t("auth.sendCode")}
            </Button>
          </form>
        ) : (
          <form onSubmit={confirm} className="space-y-4" noValidate>
            {setup ? (
              <p className="text-sm text-slate-600">{t("auth.setHint")}</p>
            ) : (
              <Notice tone="success">{t("auth.sent")}</Notice>
            )}
            <ErrorNotice error={error} />
            {setup && !fromLink && phoneInput}
            <TextInput
              label={t("auth.code")}
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              error={fieldError(error, "code")}
            />
            <TextInput
              label={t("auth.newPassword")}
              hint={t("auth.passwordHint")}
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              error={fieldError(error, "new_password")}
            />
            <Button type="submit" busy={busy} className="w-full">
              {t("common.save")}
            </Button>
            <Button variant="ghost" className="w-full" disabled={left > 0 || !phone} onClick={() => send()}>
              {left > 0 ? t("auth.resendIn", { n: left }) : t("auth.resend")}
            </Button>
          </form>
        )}
      </Card>
      {sent && <SmsPeek phone={phone} onUse={setCode} />}
    </div>
  );
}
