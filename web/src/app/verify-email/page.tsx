"use client";

// The link in the verification email: /verify-email#token=…  The token is in the fragment,
// so it never reaches a server log; only the API call below sends it.

import { useEffect, useState } from "react";
import { ButtonLink, Card, ErrorNotice, Loading, Notice, PageTitle } from "@/components/ui";
import { post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

export default function VerifyEmail() {
  const { t } = useI18n();
  const [state, setState] = useState<"working" | "done" | unknown>("working");

  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) {
      setState(new Error("missing token"));
      return;
    }
    post("auth/email/verify", { token }, { auth: false }).then(
      () => setState("done"),
      (err) => setState(err),
    );
  }, []);

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("profile.verifyEmailTitle")}</PageTitle>
      <Card className="space-y-4">
        {state === "working" ? (
          <Loading />
        ) : state === "done" ? (
          <Notice tone="success">{t("profile.emailConfirmed")}</Notice>
        ) : (
          <ErrorNotice error={state} />
        )}
        <ButtonLink href={state === "done" ? "/profile/" : "/"}>
          {state === "done" ? t("profile.backToProfile") : t("app.home")}
        </ButtonLink>
      </Card>
    </div>
  );
}
