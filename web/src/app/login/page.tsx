"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { safeNext } from "@/components/shell";
import { Button, Card, Checkbox, ErrorNotice, Loading, Notice, PageTitle, TextInput } from "@/components/ui";
import { deviceToken, post, rememberDevice, type TrustMode } from "@/lib/api";
import { homeFor, MFA_KEY, useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { LoginOut, Tokens } from "@/lib/types";

function Login() {
  const { t } = useI18n();
  const { signIn } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [phone, setPhone] = useState(params.get("phone") ?? "");
  const [password, setPassword] = useState("");
  const [personal, setPersonal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const mode: TrustMode = personal ? "PERSONAL" : "SHARED";
    try {
      const out = await post<LoginOut>(
        "auth/login",
        { phone, password, trust_mode: mode, device_token: deviceToken() },
        { auth: false },
      );
      rememberDevice(out.device_token);
      const next = params.get("next");
      if (out.mfa_required) {
        sessionStorage.setItem(MFA_KEY, JSON.stringify({ token: out.mfa_token, mode }));
        router.push(`/login/two-step/${next ? `?next=${encodeURIComponent(next)}` : ""}`);
        return;
      }
      const me = await signIn(out as Tokens, mode);
      router.replace(safeNext(next, homeFor(me.role)));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("auth.loginTitle")}</PageTitle>
      <Card>
        <form onSubmit={submit} className="space-y-4" noValidate>
          {params.get("verified") && <Notice tone="success">{t("auth.verified")}</Notice>}
          {params.get("reset") && <Notice tone="success">{t("auth.resetDone")}</Notice>}
          <ErrorNotice error={error} />
          <TextInput
            label={t("common.phone")}
            hint={t("auth.phoneHint")}
            name="phone"
            type="tel"
            inputMode="tel"
            autoComplete="username"
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
          <TextInput
            label={t("common.password")}
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Checkbox
            label={t("auth.trustPersonal")}
            hint={t("auth.trustHint")}
            checked={personal}
            onChange={(e) => setPersonal(e.target.checked)}
          />
          <Button type="submit" busy={busy} className="w-full">
            {t("nav.login")}
          </Button>
        </form>
        <div className="mt-4 flex flex-col gap-2 text-sm">
          <Link href="/forgot/" className="text-brand-700 underline">
            {t("auth.forgot")}
          </Link>
          <Link href="/register/" className="text-brand-700 underline">
            {t("auth.noAccount")}
          </Link>
        </div>
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <Login />
    </Suspense>
  );
}
