"use client";

import { useState } from "react";
import { Guard } from "@/components/shell";
import {
  Button,
  Card,
  Empty,
  ErrorNotice,
  fieldError,
  Loading,
  Notice,
  PageTitle,
  SectionTitle,
  Select,
  TextInput,
} from "@/components/ui";
import { patch, post, qs } from "@/lib/api";
import { useDepartments } from "@/lib/admin";
import { formatDateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { usePaged } from "@/lib/paged";
import type { Role, User } from "@/lib/types";

function NewOfficer({ onCreated }: { onCreated: () => void }) {
  const { t, name } = useI18n();
  const departments = useDepartments();
  const [form, setForm] = useState({ full_name: "", phone: "", department: "" });
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = (departments.rows ?? []).filter((d) => d.is_active);
  const department = form.department || active[0]?.code || "";

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await post<User>("admin/users", { ...form, department });
      setForm({ full_name: "", phone: "", department });
      setDone(true);
      onCreated();
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  return (
    <Card>
      <SectionTitle>{t("people.newOfficer")}</SectionTitle>
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-3" noValidate>
        <div className="sm:col-span-3">
          <p className="text-xs text-slate-500">{t("people.newOfficerHint")}</p>
        </div>
        {done && (
          <div className="sm:col-span-3">
            <Notice tone="success">{t("common.saved")}</Notice>
          </div>
        )}
        <div className="sm:col-span-3">
          <ErrorNotice error={error} />
        </div>
        <TextInput
          label={t("common.fullName")}
          value={form.full_name}
          onChange={(e) => setForm({ ...form, full_name: e.target.value })}
          error={fieldError(error, "full_name")}
        />
        <TextInput
          label={t("common.phone")}
          type="tel"
          inputMode="tel"
          value={form.phone}
          onChange={(e) => setForm({ ...form, phone: e.target.value })}
          error={fieldError(error, "phone")}
        />
        <Select
          label={t("common.department")}
          value={department}
          onChange={(e) => setForm({ ...form, department: e.target.value })}
          options={active.map((d) => ({ value: d.code, label: name(d) }))}
        />
        <div>
          <Button type="submit" busy={busy} disabled={!form.full_name || !form.phone || !department}>
            {t("common.add")}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function UserRow({ user, onChange }: { user: User; onChange: () => void }) {
  const { t, lang } = useI18n();
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={`font-medium ${user.is_active ? "" : "text-slate-400 line-through"}`}>{user.full_name}</p>
          <p className="text-xs text-slate-500">
            {user.phone}
            {user.department && ` · ${user.department}`}
            {" · "}
            {user.last_login ? t("people.lastLogin", { date: formatDateTime(user.last_login, lang) }) : t("people.never")}
            {!user.has_password && ` · ${t("people.noPassword")}`}
          </p>
        </div>
        {user.role !== "ADMIN" && (
          <div className="flex flex-wrap gap-2">
            {user.is_active && (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await post(`admin/users/${user.id}/reset-password`);
                    setSent(true);
                  })
                }
              >
                {t("people.resetPassword")}
              </Button>
            )}
            <Button
              variant={user.is_active ? "ghost" : "secondary"}
              className={user.is_active ? "text-red-700" : ""}
              disabled={busy}
              onClick={() => run(() => patch(`admin/users/${user.id}`, { is_active: !user.is_active }))}
            >
              {user.is_active ? t("people.deactivate") : t("people.activate")}
            </Button>
          </div>
        )}
      </div>
      {sent && <Notice tone="success">{t("people.resetSent")}</Notice>}
      <ErrorNotice error={error} />
    </li>
  );
}

function People() {
  const { t } = useI18n();
  const [role, setRole] = useState<Role>("OFFICER");
  const [phone, setPhone] = useState("");
  const [search, setSearch] = useState("");
  const list = usePaged<User>(`admin/users${qs({ role, phone: search })}`);

  return (
    <div className="space-y-4">
      <PageTitle>{t("people.title")}</PageTitle>
      <NewOfficer onCreated={list.reload} />
      <Card>
        <form
          className="grid gap-3 sm:grid-cols-3"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(phone.trim());
          }}
        >
          <Select
            label={t("people.role")}
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            options={(["OFFICER", "CITIZEN", "ADMIN"] as Role[]).map((r) => ({ value: r, label: t(`role.${r}`) }))}
          />
          <TextInput label={t("people.searchPhone")} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
          <div className="flex items-end">
            <Button type="submit" variant="secondary">
              {t("common.search")}
            </Button>
          </div>
        </form>
        <ErrorNotice error={list.error} />
        {!list.rows ? (
          <Loading />
        ) : list.rows.length === 0 ? (
          <Empty />
        ) : (
          <ul className="mt-2 divide-y divide-slate-100">
            {list.rows.map((u) => (
              <UserRow key={u.id} user={u} onChange={list.reload} />
            ))}
          </ul>
        )}
        {list.hasMore && (
          <Button variant="secondary" className="w-full" busy={list.busy} onClick={list.more}>
            {t("common.more")}
          </Button>
        )}
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["ADMIN"]}>
      <People />
    </Guard>
  );
}
