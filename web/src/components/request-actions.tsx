"use client";

// What the viewer may do next, from the same rules the API enforces (transitions.RULES).
// The API still decides: a button shown here that the API refuses shows its error.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, call, get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import {
  OPEN_STATUSES,
  type Me,
  type Page,
  type PauseReason,
  type Priority,
  type RejectionReason,
  type ServiceRequest,
  type User,
} from "@/lib/types";
import { Button, Card, ErrorNotice, Notice, SectionTitle, Select, TextArea, TextInput } from "./ui";

const PAUSE: PauseReason[] = ["MISSING_DOCUMENT", "UNCLEAR_REQUEST", "VERIFICATION", "OTHER"];
const REJECT: RejectionReason[] = ["INCOMPLETE", "NOT_ELIGIBLE", "DUPLICATE", "WRONG_OFFICE", "OTHER"];
const PRIORITIES: Priority[] = ["LOW", "NORMAL", "HIGH", "URGENT"];

type Field =
  | { name: string; kind: "text" | "textarea"; label: Key; optional?: boolean }
  | { name: string; kind: "select"; label: Key; options: { value: string; label: Key }[] }
  | { name: string; kind: "officer"; label: Key };

interface Spec {
  action: string;
  label: Key;
  hint?: Key;
  fields: Field[];
  tone?: "primary" | "secondary" | "danger";
}

const note = (name: string, label: Key, optional = false): Field => ({ name, kind: "textarea", label, optional });

function available(req: ServiceRequest, me: Me): Spec[] {
  const s = req.status;
  const open = OPEN_STATUSES.includes(s);
  const specs: Spec[] = [];

  if (me.role === "CITIZEN") {
    if (s === "AWAITING_CITIZEN")
      specs.push({ action: "respond", label: "act.respond", hint: "act.respondHint", fields: [note("message", "act.message")] });
    const reopenable =
      (s === "RESOLVED" || s === "REJECTED") && (!req.reopen_deadline || new Date(req.reopen_deadline) > new Date());
    if (reopenable)
      specs.push({ action: "reopen", label: "act.reopen", hint: "act.reopenHint", fields: [note("reason", "common.reason")] });
    if (open)
      specs.push({
        action: "withdraw",
        label: "act.withdraw",
        hint: "act.withdrawHint",
        tone: "danger",
        fields: [note("reason", "common.reason", true)],
      });
  }

  if (me.role === "OFFICER" && req.assigned_officer?.id === me.id) {
    if (s === "ASSIGNED") specs.push({ action: "start", label: "act.start", fields: [] });
    if (s === "IN_PROGRESS") {
      specs.push({ action: "resolve", label: "act.resolve", hint: "act.resolveHint", fields: [note("note", "common.note")] });
      specs.push({
        action: "request_info",
        label: "act.requestInfo",
        hint: "act.requestInfoHint",
        tone: "secondary",
        fields: [
          { name: "reason_code", kind: "select", label: "common.reason", options: PAUSE.map((p) => ({ value: p, label: `pause.${p}` as Key })) },
          note("message", "act.message"),
        ],
      });
    }
    if (s === "AWAITING_CITIZEN")
      specs.push({ action: "resume", label: "act.resume", tone: "secondary", fields: [note("reason", "common.reason")] });
  }

  if (me.role === "ADMIN") {
    if (s === "SUBMITTED") specs.push({ action: "assign", label: "act.assign", fields: [{ name: "officer", kind: "officer", label: "common.officer" }] });
    if (s === "ASSIGNED" || s === "IN_PROGRESS")
      specs.push({
        action: "reassign",
        label: "act.reassign",
        tone: "secondary",
        fields: [{ name: "officer", kind: "officer", label: "common.officer" }, note("reason", "common.reason")],
      });
  }

  const mayReject = (me.role === "OFFICER" && req.assigned_officer?.id === me.id) || me.role === "ADMIN";
  if (open && mayReject)
    specs.push({
      action: "reject",
      label: "act.reject",
      hint: "act.rejectHint",
      tone: "danger",
      fields: [
        { name: "reason_code", kind: "select", label: "common.reason", options: REJECT.map((r) => ({ value: r, label: `reject.${r}` as Key })) },
        note("note", "common.note"),
      ],
    });
  return specs;
}

function OfficerSelect({ department, value, onChange }: { department: string; value: string; onChange: (v: string) => void }) {
  const { t } = useI18n();
  const [officers, setOfficers] = useState<User[]>([]);
  useEffect(() => {
    get<Page<User>>(`admin/users?role=OFFICER&is_active=true&department=${department}&page_size=50`).then(
      (p) => {
        setOfficers(p.results);
        if (!value && p.results[0]) onChange(p.results[0].id);
      },
      () => setOfficers([]),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [department]);
  return (
    <Select
      label={t("common.officer")}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      options={officers.map((o) => ({ value: o.id, label: `${o.full_name} · ${o.phone}` }))}
    />
  );
}

function ActionForm({ req, spec, onDone, onCancel }: { req: ServiceRequest; spec: Spec; onDone: (r: ServiceRequest) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const initial = Object.fromEntries(
    spec.fields.map((f) => [f.name, f.kind === "select" ? f.options[0].value : ""]),
  ) as Record<string, string>;
  const [values, setValues] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    // Optional fields left empty are not sent at all.
    const optional = (name: string) =>
      spec.fields.some((f) => f.name === name && (f.kind === "text" || f.kind === "textarea") && f.optional);
    const body = Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== "" || !optional(k)));
    try {
      onDone(await post<ServiceRequest>(`requests/${req.id}/actions/${spec.action}`, body));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  // No input needed (start): act on the first tap.
  if (spec.fields.length === 0) {
    return (
      <div className="space-y-2">
        <ErrorNotice error={error} />
        <Button busy={busy} onClick={() => submit()}>
          {t(spec.label)}
        </Button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3 rounded-lg bg-slate-50 p-3" noValidate>
      <p className="text-sm font-medium">{t(spec.label)}</p>
      {spec.hint && <p className="text-xs text-slate-600">{t(spec.hint)}</p>}
      <ErrorNotice error={error} />
      {spec.fields.map((f) => {
        const set = (v: string) => setValues((x) => ({ ...x, [f.name]: v }));
        const err = error instanceof ApiError ? error.field(f.name) : undefined;
        if (f.kind === "officer")
          return <OfficerSelect key={f.name} department={req.handled_by?.department.code ?? ""} value={values[f.name]} onChange={set} />;
        if (f.kind === "select")
          return (
            <Select
              key={f.name}
              label={t(f.label)}
              value={values[f.name]}
              onChange={(e) => set(e.target.value)}
              options={f.options.map((o) => ({ value: o.value, label: t(o.label) }))}
              error={err}
            />
          );
        const label = f.optional ? `${t(f.label)} (${t("common.optional")})` : t(f.label);
        return f.kind === "textarea" ? (
          <TextArea key={f.name} label={label} rows={3} value={values[f.name]} onChange={(e) => set(e.target.value)} error={err} />
        ) : (
          <TextInput key={f.name} label={label} value={values[f.name]} onChange={(e) => set(e.target.value)} error={err} />
        );
      })}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" busy={busy} variant={spec.tone === "danger" ? "danger" : "primary"}>
          {t(spec.label)}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

function PriorityControl({ req, etag, onDone, onStale }: { req: ServiceRequest; etag: string; onDone: (r: ServiceRequest) => void; onStale: () => void }) {
  const { t } = useI18n();
  const [value, setValue] = useState<Priority>(req.priority);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const { data } = await call<ServiceRequest>(`requests/${req.id}/priority`, {
        method: "PATCH",
        body: { priority: value },
        headers: { "If-Match": etag },
      });
      onDone(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 412) onStale();
      setError(err);
    }
    setBusy(false);
  }

  return (
    <div className="flex flex-wrap items-end gap-2">
      <div className="min-w-40 flex-1">
        <Select
          label={t("act.setPriority")}
          value={value}
          onChange={(e) => setValue(e.target.value as Priority)}
          options={PRIORITIES.map((p) => ({ value: p, label: t(`priority.${p}`) }))}
        />
      </div>
      <Button variant="secondary" busy={busy} disabled={value === req.priority} onClick={save}>
        {t("common.save")}
      </Button>
      <div className="w-full">
        <ErrorNotice error={error} />
      </div>
    </div>
  );
}

function DraftActions({ req, etag }: { req: ServiceRequest; etag: string }) {
  const { t } = useI18n();
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function discard() {
    try {
      await call(`requests/${req.id}`, { method: "DELETE", headers: { "If-Match": etag } });
      router.replace("/requests/");
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-3">
      <ErrorNotice error={error} />
      <div className="flex flex-wrap gap-2">
        <Link
          href={`/requests/new/?id=${req.id}`}
          className="inline-flex min-h-11 items-center rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700"
        >
          {t("act.editDraft")}
        </Link>
        {!confirming ? (
          <Button variant="secondary" onClick={() => setConfirming(true)}>
            {t("req.discard")}
          </Button>
        ) : (
          <Notice tone="warning">
            <p>{t("req.discardConfirm")}</p>
            <div className="mt-2 flex gap-2">
              <Button variant="danger" onClick={discard}>
                {t("req.discard")}
              </Button>
              <Button variant="ghost" onClick={() => setConfirming(false)}>
                {t("common.cancel")}
              </Button>
            </div>
          </Notice>
        )}
      </div>
    </div>
  );
}

export function Actions({
  req,
  etag,
  onChange,
  onStale,
}: {
  req: ServiceRequest;
  etag: string;
  onChange: (r: ServiceRequest) => void;
  onStale: () => void;
}) {
  const { t } = useI18n();
  const { me } = useAuth();
  const [open, setOpen] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  if (!me) return null;

  const isOwner = me.role === "CITIZEN";
  if (isOwner && req.status === "DRAFT") {
    return (
      <Card>
        <SectionTitle>{t("act.title")}</SectionTitle>
        <DraftActions req={req} etag={etag} />
      </Card>
    );
  }

  const specs = available(req, me);
  const staffMayPrioritise =
    OPEN_STATUSES.includes(req.status) &&
    (me.role === "ADMIN" || (me.role === "OFFICER" && (req.assigned_officer?.id === me.id || req.handled_by?.department.code === me.department)));

  if (!specs.length && !staffMayPrioritise) return null;

  return (
    <Card>
      <SectionTitle>{t("act.title")}</SectionTitle>
      <div className="space-y-3">
        {done && <Notice tone="success">{t("act.done")}</Notice>}
        {open === null ? (
          <div className="flex flex-wrap gap-2">
            {specs.map((s) =>
              s.fields.length === 0 ? (
                <ActionForm
                  key={s.action}
                  req={req}
                  spec={s}
                  onCancel={() => undefined}
                  onDone={(r) => {
                    setDone(true);
                    onChange(r);
                  }}
                />
              ) : (
                <Button
                  key={s.action}
                  variant={s.tone === "danger" ? "secondary" : (s.tone ?? "primary")}
                  className={s.tone === "danger" ? "text-red-700" : ""}
                  onClick={() => {
                    setDone(false);
                    setOpen(s.action);
                  }}
                >
                  {t(s.label)}
                </Button>
              ),
            )}
          </div>
        ) : (
          <ActionForm
            req={req}
            spec={specs.find((s) => s.action === open)!}
            onCancel={() => setOpen(null)}
            onDone={(r) => {
              setOpen(null);
              setDone(true);
              onChange(r);
            }}
          />
        )}
        {staffMayPrioritise && open === null && (
          <PriorityControl
            key={req.version}
            req={req}
            etag={etag}
            onStale={onStale}
            onDone={(r) => {
              setDone(true);
              onChange(r);
            }}
          />
        )}
      </div>
    </Card>
  );
}
