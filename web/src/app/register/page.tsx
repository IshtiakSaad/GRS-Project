"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button, Card, ErrorNotice, fieldError, Notice, PageTitle, Select, TextInput } from "@/components/ui";
import { DEMO } from "@/components/shell";
import { post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Accepted } from "@/lib/types";

export default function Register() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", phone: "", password: "", preferred_language: lang });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await post<Accepted>("auth/register", form, { auth: false });
      const q = new URLSearchParams({ phone: form.phone, wait: String(out.resend_after ?? 60) });
      router.push(`/register/verify/?${q}`);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>{t("auth.registerTitle")}</PageTitle>
      <Card>
        <form onSubmit={submit} className="space-y-4" noValidate>
          <p className="text-sm text-slate-600">{t("auth.registerHint")}</p>
          {DEMO && <Notice>{t("auth.demoCodes")}</Notice>}
          <ErrorNotice error={error} />
          <TextInput
            label={t("common.fullName")}
            name="full_name"
            autoComplete="name"
            required
            value={form.full_name}
            onChange={set("full_name")}
            error={fieldError(error, "full_name")}
          />
          <TextInput
            label={t("common.phone")}
            hint={t("auth.phoneHint")}
            name="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            required
            value={form.phone}
            onChange={set("phone")}
            error={fieldError(error, "phone")}
          />
          <TextInput
            label={t("common.password")}
            hint={t("auth.passwordHint")}
            name="password"
            type="password"
            autoComplete="new-password"
            required
            value={form.password}
            onChange={set("password")}
            error={fieldError(error, "password")}
          />
          <Select
            label={t("auth.smsLanguage")}
            name="preferred_language"
            value={form.preferred_language}
            onChange={set("preferred_language")}
            options={[
              { value: "bn", label: "বাংলা" },
              { value: "en", label: "English" },
            ]}
          />
          <Button type="submit" busy={busy} className="w-full">
            {t("common.continue")}
          </Button>
        </form>
        <Link href="/login/" className="mt-4 block text-sm text-brand-700 underline">
          {t("auth.haveAccount")}
        </Link>
      </Card>
    </div>
  );
}
