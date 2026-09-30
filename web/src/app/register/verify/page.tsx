"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useCountdown } from "@/components/countdown";
import { SmsPeek } from "@/components/sms";
import { Button, Card, Checkbox, ErrorNotice, Loading, Notice, PageTitle, TextInput } from "@/components/ui";
import { deviceToken, post, rememberDevice, type TrustMode } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { Accepted, LoginOut, Tokens } from "@/lib/types";

function Verify() {
  const { t } = useI18n();
  const { me, signIn, reload } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [phone, setPhone] = useState(params.get("phone") ?? "");
  const [code, setCode] = useState("");
  const [personal, setPersonal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const { left, restart } = useCountdown(Number(params.get("wait") ?? 60) || 60);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const mode: TrustMode = personal ? "PERSONAL" : "SHARED";
    try {
      if (me) {
        // Confirming from the profile: already logged in, so no second session.
        await post("auth/otp/verify", { phone, code: code.trim(), start_session: false }, { auth: false });
        await reload();
        router.replace("/profile/");
        return;
      }
      // A correct code logs the new citizen in: they chose the password a minute ago.
      const out = await post<LoginOut>(
        "auth/otp/verify",
        { phone, code: code.trim(), trust_mode: mode, device_token: deviceToken() },
        { auth: false },
      );
      rememberDevice(out.device_token);
      const user = await signIn(out as Tokens, mode);
      router.replace(homeFor(user.role));
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
          {!me && (
            <Checkbox
              label={t("auth.trustPersonal")}
              hint={t("auth.trustHint")}
              checked={personal}
              onChange={(e) => setPersonal(e.target.checked)}
            />
          )}
          <Button type="submit" busy={busy} className="w-full">
            {t("auth.verify")}
          </Button>
          <Button variant="ghost" className="w-full" disabled={left > 0 || !phone} onClick={resend}>
            {left > 0 ? t("auth.resendIn", { n: left }) : t("auth.resend")}
          </Button>
        </form>
      </Card>
      <SmsPeek phone={phone} onUse={setCode} />
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
