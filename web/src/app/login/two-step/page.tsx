"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { safeNext } from "@/components/shell";
import { Button, Card, ErrorNotice, Loading, PageTitle, TextInput } from "@/components/ui";
import { ApiError, post, type TrustMode } from "@/lib/api";
import { homeFor, MFA_KEY, useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { Tokens } from "@/lib/types";

function TwoStep() {
  const { t } = useI18n();
  const { signIn } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [pending, setPending] = useState<{ token: string; mode: TrustMode } | null>(null);
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(MFA_KEY);
      if (raw) {
        setPending(JSON.parse(raw));
        return;
      }
    } catch {}
    router.replace("/login/");
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!pending) return;
    setBusy(true);
    setError(null);
    try {
      const tokens = await post<Tokens>(
        recovery ? "auth/2fa/recovery" : "auth/2fa/verify",
        { mfa_token: pending.token, code: code.trim() },
        { auth: false },
      );
      sessionStorage.removeItem(MFA_KEY);
      const me = await signIn(tokens, pending.mode);
      router.replace(safeNext(params.get("next"), homeFor(me.role)));
    } catch (err) {
      // The first step expired: start again rather than retrying a dead token.
      if (err instanceof ApiError && err.code === "MFA_TOKEN_INVALID") {
        sessionStorage.removeItem(MFA_KEY);
      }
      setError(err);
      setBusy(false);
    }
  }

  if (!pending) return <Loading />;

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("auth.twoStepTitle")}</PageTitle>
      <Card>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <ErrorNotice error={error} />
          <TextInput
            label={recovery ? t("auth.recoveryCode") : t("auth.code")}
            hint={recovery ? undefined : t("auth.twoStepHint")}
            name="code"
            inputMode={recovery ? "text" : "numeric"}
            autoComplete="one-time-code"
            autoFocus
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" busy={busy} className="w-full">
            {t("auth.verify")}
          </Button>
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => {
              setRecovery(!recovery);
              setCode("");
              setError(null);
            }}
          >
            {recovery ? t("auth.useApp") : t("auth.useRecovery")}
          </Button>
        </form>
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <TwoStep />
    </Suspense>
  );
}
