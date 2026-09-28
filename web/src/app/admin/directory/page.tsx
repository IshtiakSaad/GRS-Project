"use client";

// What the deadlines are computed from: departments, the services they offer with a target
// in working days, public holidays, and suspensions (days an office could not work).

import { useState } from "react";
import { Guard } from "@/components/shell";
import { Button, Card, Empty, ErrorNotice, fieldError, Loading, PageTitle, SectionTitle, Select, Tabs, TextInput } from "@/components/ui";
import { del, patch, post } from "@/lib/api";
import { useAdminCategories, useDepartments, useList } from "@/lib/admin";
import { formatDate } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { Holiday, Suspension } from "@/lib/types";

type Tab = "departments" | "categories" | "holidays" | "suspensions";

/** A small add form: fields in a grid, one Add button, the API's field errors under each. */
function AddForm({
  fields,
  submit,
}: {
  fields: { name: string; label: string; type?: string; options?: { value: string; label: string }[] }[];
  submit: (values: Record<string, string>) => Promise<unknown>;
}) {
  const { t } = useI18n();
  const blank = Object.fromEntries(fields.map((f) => [f.name, f.options?.[0]?.value ?? ""]));
  const [values, setValues] = useState<Record<string, string>>(blank);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function go(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    // A select shows its first option until touched; send that option, not "".
    const final = Object.fromEntries(
      fields.map((f) => [f.name, values[f.name] || (f.options?.[0]?.value ?? "")]),
    );
    try {
      await submit(final);
      setValues(blank);
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  return (
    <form onSubmit={go} className="mt-4 space-y-3 rounded-lg bg-slate-50 p-3" noValidate>
      <ErrorNotice error={error} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {fields.map((f) =>
          f.options ? (
            <Select
              key={f.name}
              label={f.label}
              value={values[f.name] || f.options[0]?.value || ""}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
              options={f.options}
            />
          ) : (
            <TextInput
              key={f.name}
              label={f.label}
              type={f.type ?? "text"}
              value={values[f.name]}
              onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
              error={fieldError(error, f.name)}
            />
          ),
        )}
      </div>
      <Button type="submit" busy={busy}>
        {t("common.add")}
      </Button>
    </form>
  );
}

function Departments() {
  const { t, name } = useI18n();
  const { rows, error, reload } = useDepartments();
  const [err, setErr] = useState<unknown>(null);
  const toggle = async (code: string, is_active: boolean) => {
    setErr(null);
    try {
      await patch(`admin/departments/${code}`, { is_active });
      reload();
    } catch (e) {
      setErr(e);
    }
  };
  return (
    <div>
      <ErrorNotice error={error ?? err} />
      {!rows ? (
        <Loading />
      ) : (
        <ul className="divide-y divide-slate-100">
          {rows.map((d) => (
            <li key={d.code} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <p className={`text-sm font-medium ${d.is_active ? "" : "text-slate-400"}`}>{name(d)}</p>
                <p className="text-xs text-slate-500">
                  {d.code} · {d.is_active ? t("common.active") : t("common.inactive")}
                </p>
              </div>
              <Button variant="ghost" onClick={() => toggle(d.code, !d.is_active)}>
                {d.is_active ? t("people.deactivate") : t("people.activate")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <AddForm
        fields={[
          { name: "code", label: t("common.code") },
          { name: "name_bn", label: t("common.nameBn") },
          { name: "name_en", label: t("common.nameEn") },
        ]}
        submit={async (v) => {
          await post("admin/departments", v);
          reload();
        }}
      />
    </div>
  );
}

function Categories() {
  const { t, name } = useI18n();
  const departments = useDepartments();
  const { rows, error, reload } = useAdminCategories();
  const [err, setErr] = useState<unknown>(null);
  const [days, setDays] = useState<Record<string, string>>({});

  const save = async (code: string, body: Record<string, unknown>) => {
    setErr(null);
    try {
      await patch(`admin/categories/${code}`, body);
      reload();
    } catch (e) {
      setErr(e);
    }
  };

  return (
    <div>
      <ErrorNotice error={error ?? err} />
      {!rows ? (
        <Loading />
      ) : (
        <ul className="divide-y divide-slate-100">
          {rows.map((c) => (
            <li key={c.code} className="flex flex-wrap items-end justify-between gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-medium ${c.is_active ? "" : "text-slate-400"}`}>{name(c)}</p>
                <p className="text-xs text-slate-500">
                  {c.code} · {c.department} · {t("common.days", { n: c.target_working_days })}
                </p>
              </div>
              <div className="flex items-end gap-2">
                <div className="w-24">
                  <TextInput
                    label={t("dir.targetDays")}
                    type="number"
                    min={1}
                    max={365}
                    value={days[c.code] ?? String(c.target_working_days)}
                    onChange={(e) => setDays({ ...days, [c.code]: e.target.value })}
                  />
                </div>
                <Button
                  variant="secondary"
                  disabled={!days[c.code] || Number(days[c.code]) === c.target_working_days}
                  onClick={() => save(c.code, { target_working_days: Number(days[c.code]) })}
                >
                  {t("common.save")}
                </Button>
                <Button variant="ghost" onClick={() => save(c.code, { is_active: !c.is_active })}>
                  {c.is_active ? t("people.deactivate") : t("people.activate")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <AddForm
        fields={[
          {
            name: "department",
            label: t("common.department"),
            options: (departments.rows ?? []).filter((d) => d.is_active).map((d) => ({ value: d.code, label: name(d) })),
          },
          { name: "code", label: t("common.code") },
          { name: "name_bn", label: t("common.nameBn") },
          { name: "name_en", label: t("common.nameEn") },
          { name: "target_working_days", label: t("dir.targetDays"), type: "number" },
        ]}
        submit={async (v) => {
          await post("admin/categories", { ...v, target_working_days: Number(v.target_working_days) });
          reload();
        }}
      />
    </div>
  );
}

function Holidays() {
  const { t, lang, name, num } = useI18n();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(String(thisYear));
  const { rows, error, reload } = useList<Holiday>(`admin/holidays?year=${year}`);
  const [err, setErr] = useState<unknown>(null);

  return (
    <div>
      <div className="w-40">
        <Select
          label={t("dir.year")}
          value={year}
          onChange={(e) => setYear(e.target.value)}
          options={[thisYear - 1, thisYear, thisYear + 1].map((y) => ({ value: String(y), label: num(y) }))}
        />
      </div>
      <ErrorNotice error={error ?? err} />
      {!rows ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty />
      ) : (
        <ul className="mt-2 divide-y divide-slate-100">
          {rows.map((h) => (
            <li key={h.date} className="flex items-center justify-between gap-2 py-2">
              <div>
                <p className="text-sm font-medium">{name(h)}</p>
                <p className="text-xs text-slate-500">{formatDate(h.date, lang)}</p>
              </div>
              <Button
                variant="ghost"
                className="text-red-700"
                onClick={async () => {
                  setErr(null);
                  try {
                    await del(`admin/holidays/${h.date}`);
                    reload();
                  } catch (e) {
                    setErr(e);
                  }
                }}
              >
                {t("common.remove")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <AddForm
        fields={[
          { name: "date", label: t("common.date"), type: "date" },
          { name: "name_bn", label: t("common.nameBn") },
          { name: "name_en", label: t("common.nameEn") },
        ]}
        submit={async (v) => {
          await post("admin/holidays", v);
          reload();
        }}
      />
    </div>
  );
}

function Suspensions() {
  const { t, lang, name } = useI18n();
  const departments = useDepartments();
  const { rows, error, reload } = useList<Suspension>("admin/sla-suspensions");
  const [err, setErr] = useState<unknown>(null);

  return (
    <div>
      <p className="text-sm text-slate-600">{t("dir.suspensionHint")}</p>
      <ErrorNotice error={error ?? err} />
      {!rows ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty />
      ) : (
        <ul className="mt-2 divide-y divide-slate-100">
          {rows.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-2 py-2">
              <div>
                <p className="text-sm font-medium">{s.reason}</p>
                <p className="text-xs text-slate-500">
                  {formatDate(s.starts_on, lang)} – {formatDate(s.ends_on, lang)} · {s.department ?? t("dir.allDepartments")}
                </p>
              </div>
              <Button
                variant="ghost"
                className="text-red-700"
                onClick={async () => {
                  setErr(null);
                  try {
                    await del(`admin/sla-suspensions/${s.id}`);
                    reload();
                  } catch (e) {
                    setErr(e);
                  }
                }}
              >
                {t("common.remove")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <AddForm
        fields={[
          {
            name: "department",
            label: t("common.department"),
            options: [
              { value: "", label: t("dir.allDepartments") },
              ...(departments.rows ?? []).map((d) => ({ value: d.code, label: name(d) })),
            ],
          },
          { name: "starts_on", label: t("dir.startsOn"), type: "date" },
          { name: "ends_on", label: t("dir.endsOn"), type: "date" },
          { name: "reason", label: t("common.reason") },
        ]}
        submit={async (v) => {
          await post("admin/sla-suspensions", { ...v, department: v.department || null });
          reload();
        }}
      />
    </div>
  );
}

function Directory() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("departments");
  return (
    <div className="space-y-4">
      <PageTitle>{t("dir.title")}</PageTitle>
      <Tabs
        value={tab}
        onChange={setTab}
        options={[
          { value: "departments", label: t("dir.departments") },
          { value: "categories", label: t("dir.categories") },
          { value: "holidays", label: t("dir.holidays") },
          { value: "suspensions", label: t("dir.suspensions") },
        ]}
      />
      <Card>
        <SectionTitle>
          {t(tab === "departments" ? "dir.departments" : tab === "categories" ? "dir.categories" : tab === "holidays" ? "dir.holidays" : "dir.suspensions")}
        </SectionTitle>
        {tab === "departments" && <Departments />}
        {tab === "categories" && <Categories />}
        {tab === "holidays" && <Holidays />}
        {tab === "suspensions" && <Suspensions />}
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["ADMIN"]}>
      <Directory />
    </Guard>
  );
}
