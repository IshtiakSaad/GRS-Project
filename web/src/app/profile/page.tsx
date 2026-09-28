"use client";

import { useCallback, useEffect, useState } from "react";
import { Guard } from "@/components/shell";
import {
  Button,
  ButtonLink,
  Card,
  ErrorNotice,
  fieldError,
  Notice,
  PageTitle,
  SectionTitle,
  Select,
  TextInput,
} from "@/components/ui";
import { del, get, hasSession, patch, post, startSession, trustMode } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import type { Me, Session, Tokens } from "@/lib/types";

function Details({ me }: { me: Me }) {
  const { t } = useI18n();
  const { reload } = useAuth();
  const [form, setForm] = useState({
    full_name: me.full_name,
    email: me.email ?? "",
    preferred_language: me.preferred_language,
  });
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await patch<Me>("me", { ...form, email: form.email || null });
      await reload();
      setSaved(true);
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  return (
    <Card>
      <SectionTitle>{t("profile.details")}</SectionTitle>
      <form onSubmit={save} className="space-y-4" noValidate>
        {saved && <Notice tone="success">{t("common.saved")}</Notice>}
        <ErrorNotice error={error} />
        <p className="text-sm text-slate-600">
          {t("profile.role")}: {t(`role.${me.role}` as Key)}
          {me.department ? ` · ${me.department}` : ""} · {me.phone}
        </p>
        {me.two_step_login && <p className="text-sm text-slate-600">{t("profile.twoStep")}</p>}
        <TextInput
          label={t("common.fullName")}
          value={form.full_name}
          onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          error={fieldError(error, "full_name")}
        />
        <TextInput
          label={t("profile.email")}
          hint={
            form.email && form.email === me.email
              ? me.email_verified
                ? t("profile.emailVerified")
                : t("profile.emailPending")
              : t("profile.emailHint")
          }
          type="email"
          autoComplete="email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          error={fieldError(error, "email")}
        />
        <Select
          label={t("auth.smsLanguage")}
          value={form.preferred_language}
          onChange={(e) => setForm({ ...form, preferred_language: e.target.value as Me["preferred_language"] })}
          options={[
            { value: "bn", label: "বাংলা" },
            { value: "en", label: "English" },
          ]}
        />
        <Button type="submit" busy={busy}>
          {t("common.save")}
        </Button>
      </form>
    </Card>
  );
}

function Password() {
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      // Every other session ends; this one continues on the tokens that come back.
      const tokens = await post<Tokens>("me/password", { current_password: current, new_password: next });
      if (hasSession()) startSession(tokens, trustMode());
      setCurrent("");
      setNext("");
      setDone(true);
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  return (
    <Card>
      <SectionTitle>{t("profile.password")}</SectionTitle>
      <form onSubmit={save} className="space-y-4" noValidate>
        {done && <Notice tone="success">{t("profile.passwordChanged")}</Notice>}
        <ErrorNotice error={error} />
        <TextInput
          label={t("profile.currentPassword")}
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          error={fieldError(error, "current_password")}
        />
        <TextInput
          label={t("auth.newPassword")}
          hint={t("auth.passwordHint")}
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          error={fieldError(error, "new_password")}
        />
        <Button type="submit" busy={busy} disabled={!current || !next}>
          {t("common.save")}
        </Button>
      </form>
    </Card>
  );
}

function Sessions() {
  const { t, lang } = useI18n();
  const [rows, setRows] = useState<Session[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  const load = useCallback(async () => {
    try {
      setRows(await get<Session[]>("me/sessions"));
    } catch (err) {
      setError(err);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function revoke(id: string) {
    setError(null);
    try {
      await del(`me/sessions/${id}`);
      await load();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Card>
      <SectionTitle>{t("profile.sessions")}</SectionTitle>
      <ErrorNotice error={error} />
      <ul className="divide-y divide-slate-100">
        {rows?.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{s.user_agent || "—"}</p>
              <p className="text-xs text-slate-500">
                {s.current ? t("profile.thisDevice") : t("profile.lastUsed", { date: formatDateTime(s.last_used_at, lang) })}
                {" · "}
                {s.trust_mode === "PERSONAL" ? t("profile.personal") : t("profile.shared")}
              </p>
            </div>
            {!s.current && (
              <Button variant="secondary" onClick={() => revoke(s.id)}>
                {t("profile.logoutDevice")}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Profile() {
  const { t } = useI18n();
  const { me } = useAuth();
  if (!me) return null;
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <PageTitle>{t("profile.title")}</PageTitle>
      {!me.phone_verified && (
        <Notice tone="warning">
          <p>{t("profile.phoneUnverified")}</p>
          <ButtonLink href={`/register/verify/?phone=${encodeURIComponent(me.phone)}&wait=0`} variant="secondary" className="mt-2">
            {t("profile.confirmNumber")}
          </ButtonLink>
        </Notice>
      )}
      <Details me={me} />
      <Password />
      <Sessions />
    </div>
  );
}

export default function Page() {
  return (
    <Guard>
      <Profile />
    </Guard>
  );
}
