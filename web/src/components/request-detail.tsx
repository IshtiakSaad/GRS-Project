"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDate, formatDateTime, formatSize, isOverdue } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { messages, type Key } from "@/lib/messages";
import { usePaged } from "@/lib/paged";
import { check, settled, upload } from "@/lib/upload";
import {
  OPEN_STATUSES,
  type AccessEntry,
  type Attachment,
  type Comment,
  type ServiceRequest,
  type TimelineEvent,
} from "@/lib/types";
import { Button, Card, Checkbox, Detail, Empty, ErrorNotice, Loading, Notice, PriorityLabel, StatusBadge, TextArea } from "./ui";

// --- summary ---------------------------------------------------------------------------------

export function Summary({ req, staff }: { req: ServiceRequest; staff: boolean }) {
  const { t, lang, name, num } = useI18n();
  const open = OPEN_STATUSES.includes(req.status);
  const late = isOverdue(req.due_at, open);
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-500">
            {req.tracking_no ? `${t("req.tracking")} ${num(req.tracking_no)}` : t("status.DRAFT")}
          </p>
          <h1 className="mt-1 text-lg font-semibold text-slate-900 sm:text-xl">{req.title}</h1>
        </div>
        <StatusBadge status={req.status} staff={staff} />
      </div>
      {req.status === "AWAITING_CITIZEN" && !staff && (
        <div className="mt-3">
          <Notice tone="warning">{t("req.waitingForYou")}</Notice>
        </div>
      )}
      <dl className="mt-3 divide-y divide-slate-100">
        <Detail label={t("common.category")}>{name(req.category)}</Detail>
        {req.handled_by && <Detail label={t("req.office")}>{name(req.handled_by.department)}</Detail>}
        {req.submitted_at && <Detail label={t("req.submittedAt")}>{formatDateTime(req.submitted_at, lang)}</Detail>}
        {req.due_at && open && (
          <Detail label={t("req.dueAt")}>
            <span className={late ? "font-semibold text-red-700" : ""}>
              {formatDate(req.due_at, lang)}
              {late && ` · ${t("common.overdue")}`}
            </span>
          </Detail>
        )}
        {req.closed_at && <Detail label={t("req.resolvedAt")}>{formatDateTime(req.closed_at, lang)}</Detail>}
        {staff && req.owner && (
          <Detail label={t("req.citizen")}>
            {req.owner.name} · {req.owner.phone}
          </Detail>
        )}
        {staff && (
          <Detail label={t("req.assignedTo")}>{req.assigned_officer?.name ?? t("req.unassigned")}</Detail>
        )}
        {staff && (
          <Detail label={t("common.priority")}>
            <PriorityLabel priority={req.priority} />
          </Detail>
        )}
        {req.beneficiary && (
          <Detail label={t("req.for")}>
            {req.beneficiary.name} ({t(`relation.${req.beneficiary.relation}` as Key)})
          </Detail>
        )}
        {req.citizen_urgent && (
          <Detail label={t("req.urgent")}>
            <span className="text-red-700">{req.urgency_reason || t("req.urgentFlag")}</span>
          </Detail>
        )}
      </dl>
      <p className="mt-3 whitespace-pre-wrap text-sm text-slate-800">{req.description}</p>
      {req.resolution_note && req.status === "RESOLVED" && (
        <div className="mt-4 rounded-lg bg-brand-50 p-3 text-sm">
          <p className="font-medium text-brand-800">{t("req.resolution")}</p>
          <p className="mt-1 whitespace-pre-wrap">{req.resolution_note}</p>
        </div>
      )}
      {req.status === "REJECTED" && (req.rejection_reason_code || req.rejection_note) && (
        <div className="mt-4 rounded-lg bg-red-50 p-3 text-sm">
          <p className="font-medium text-red-800">
            {t("req.rejection")}
            {req.rejection_reason_code ? `: ${t(`reject.${req.rejection_reason_code}` as Key)}` : ""}
          </p>
          {req.rejection_note && <p className="mt-1 whitespace-pre-wrap">{req.rejection_note}</p>}
        </div>
      )}
      {!staff && req.reopen_deadline && (req.status === "RESOLVED" || req.status === "REJECTED") && (
        <p className="mt-3 text-xs text-slate-500">
          {t("req.reopenUntil", { date: formatDate(req.reopen_deadline, lang) })}
        </p>
      )}
    </Card>
  );
}

// --- timeline --------------------------------------------------------------------------------

function eventText(e: TimelineEvent, t: (k: Key, v?: Record<string, string | number>) => string): string[] {
  const d = (e.data ?? {}) as Record<string, string>;
  const lines: string[] = [];
  if (e.type === "request_info" && d.reason_code) lines.push(t(`pause.${d.reason_code}` as Key));
  if (e.type === "reject" && d.reason_code) lines.push(t(`reject.${d.reason_code}` as Key));
  if (e.type === "set_priority" && d.to) lines.push(`${t(`priority.${d.from}` as Key)} → ${t(`priority.${d.to}` as Key)}`);
  for (const k of ["message", "note", "reason"]) if (d[k]) lines.push(d[k]);
  return lines;
}

export function Timeline({ id, version }: { id: string; version: number }) {
  const { t, lang } = useI18n();
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    get<TimelineEvent[]>(`requests/${id}/timeline`).then(setEvents, setError);
  }, [id, version]);

  if (error) return <ErrorNotice error={error} />;
  if (!events) return <Loading />;
  if (!events.length) return <Empty />;
  return (
    <ol className="relative space-y-4 border-l-2 border-slate-200 pl-5">
      {events.map((e, i) => {
        const key = `event.${e.type}`;
        // Event types without a label (added to the API later) show their raw name.
        const label = key in messages ? t(key as Key, { name: String(e.data?.name ?? "") }) : e.type;
        return (
          <li key={`${e.at}-${i}`} className="relative">
            <span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full bg-brand-600 ring-4 ring-white" />
            <p className="text-sm font-medium text-slate-900">
              {label}
              {e.is_public === false && (
                <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-normal text-slate-600">
                  {t("req.internal")}
                </span>
              )}
            </p>
            <p className="text-xs text-slate-500">
              {formatDateTime(e.at, lang)} · {t(`role.${e.actor_role}` as Key)}
            </p>
            {eventText(e, t).map((line) => (
              <p key={line} className="mt-1 whitespace-pre-wrap text-sm text-slate-700">
                {line}
              </p>
            ))}
          </li>
        );
      })}
    </ol>
  );
}

// --- messages --------------------------------------------------------------------------------

export function Messages({ req, staff, onChange }: { req: ServiceRequest; staff: boolean; onChange: () => void }) {
  const { t, lang } = useI18n();
  const { me } = useAuth();
  const list = usePaged<Comment>(`requests/${req.id}/comments?page_size=50`);
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const closed = ["RESOLVED", "REJECTED", "WITHDRAWN"].includes(req.status);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post<Comment>(`requests/${req.id}/comments`, staff ? { body, internal } : { body });
      setBody("");
      await list.reload();
      onChange(); // a citizen's answer may have resumed the request
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }

  const who = (c: Comment) => {
    if (c.author.name) return c.author.name;
    if (c.author.role === "CITIZEN") return staff ? t("req.citizen") : t("req.you");
    return c.author.department ? `${t("req.office")} · ${c.author.department}` : t("req.office");
  };

  return (
    <div className="space-y-4">
      {list.rows === null ? (
        <Loading />
      ) : list.rows.length === 0 ? (
        <Empty>{t("req.noMessages")}</Empty>
      ) : (
        <ul className="space-y-3">
          {list.rows.map((c) => {
            const mine = c.author.role === me?.role && c.author.role === "CITIZEN";
            return (
              <li
                key={c.id}
                className={`rounded-xl p-3 text-sm ${
                  c.internal ? "bg-amber-50 ring-1 ring-amber-200" : mine ? "ml-6 bg-brand-50" : "mr-6 bg-slate-100"
                }`}
              >
                <p className="text-xs text-slate-500">
                  {who(c)} · {formatDateTime(c.created_at, lang)}
                  {c.internal && ` · ${t("req.internal")}`}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{c.body}</p>
              </li>
            );
          })}
        </ul>
      )}
      {list.hasMore && (
        <Button variant="secondary" onClick={list.more} busy={list.busy}>
          {t("common.more")}
        </Button>
      )}
      {req.status !== "DRAFT" && !closed && (
        <form onSubmit={send} className="space-y-3">
          <ErrorNotice error={error} />
          <TextArea label={t("req.writeMessage")} rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          {staff && <Checkbox label={t("req.internalNote")} checked={internal} onChange={(e) => setInternal(e.target.checked)} />}
          <Button type="submit" busy={busy} disabled={!body.trim()}>
            {t("req.send")}
          </Button>
        </form>
      )}
    </div>
  );
}

// --- files -----------------------------------------------------------------------------------

export function Files({ req }: { req: ServiceRequest }) {
  const { t, lang } = useI18n();
  const [rows, setRows] = useState<Attachment[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [progress, setProgress] = useState<{ name: string; value: number } | null>(null);
  const closed = ["RESOLVED", "REJECTED", "WITHDRAWN"].includes(req.status);

  const load = useCallback(async () => {
    try {
      const list = await get<Attachment[]>(`requests/${req.id}/attachments`);
      setRows(list);
      // Keep polling while any file is still being checked.
      const waiting = list.filter((a) => a.status === "PENDING" || a.status === "VERIFYING");
      if (waiting.length) {
        await Promise.all(waiting.map((a) => settled(a.id, 15)));
        setRows(await get<Attachment[]>(`requests/${req.id}/attachments`));
      }
    } catch (err) {
      setError(err);
    }
  }, [req.id]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(list: FileList | null) {
    if (!list) return;
    setError(null);
    for (const file of Array.from(list)) {
      const problem = check(file);
      if (problem) {
        setError(new Error(problem === "size" ? t("req.fileTooBig", { name: file.name }) : t("req.fileType", { name: file.name })));
        continue;
      }
      try {
        setProgress({ name: file.name, value: 0 });
        await upload(req.id, file, (value) => setProgress({ name: file.name, value }));
      } catch (err) {
        setError(err);
      }
    }
    setProgress(null);
    load();
  }

  async function download(a: Attachment) {
    setError(null);
    try {
      const { url } = await get<{ url: string }>(`attachments/${a.id}/download`);
      window.location.href = url;
    } catch (err) {
      setError(err);
    }
  }

  return (
    <div className="space-y-3">
      {error instanceof Error && !("status" in error) ? <Notice tone="error">{error.message}</Notice> : <ErrorNotice error={error} />}
      {rows === null ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty>{t("req.noFiles")}</Empty>
      ) : (
        <ul className="space-y-2">
          {rows.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm">
              <span className="min-w-0 flex-1 truncate">{a.name}</span>
              <span className="text-xs text-slate-500">{formatSize(a.size, lang)}</span>
              <span
                className={`text-xs ${a.status === "READY" ? "text-brand-700" : a.status === "REJECTED" ? "text-red-700" : "text-slate-500"}`}
              >
                {t(`file.${a.status}` as Key)}
              </span>
              {a.status === "READY" && (
                <Button variant="ghost" onClick={() => download(a)}>
                  {t("req.download")}
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {progress && (
        <div className="flex items-center gap-3 text-sm">
          <span className="truncate">{progress.name}</span>
          <progress value={progress.value} max={1} className="h-2 w-24" />
        </div>
      )}
      {!closed && (
        <label className="inline-flex min-h-11 cursor-pointer items-center rounded-lg px-4 text-sm font-medium text-brand-700 ring-1 ring-slate-300 hover:bg-brand-50">
          {t("req.addFiles")}
          <input
            type="file"
            multiple
            accept="application/pdf,image/jpeg,image/png"
            className="sr-only"
            onChange={(e) => {
              add(e.target.files);
              e.target.value = "";
            }}
          />
        </label>
      )}
    </div>
  );
}

// --- access log ------------------------------------------------------------------------------

export function AccessLog({ id, admin }: { id: string; admin: boolean }) {
  const { t, lang, name } = useI18n();
  const list = usePaged<AccessEntry>(`requests/${id}/access-log`);
  const appearances = Number(list.extra.list_appearances ?? 0);
  if (list.error) return <ErrorNotice error={list.error} />;
  if (!list.rows) return <Loading />;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">{t("req.accessLogHint")}</p>
      {list.rows.length === 0 ? (
        <Empty />
      ) : (
        <ul className="divide-y divide-slate-100">
          {list.rows.map((a, i) => (
            <li key={`${a.at}-${i}`} className="py-2 text-sm">
              <p>
                <span className="font-medium">{t(`access.${a.kind}` as Key)}</span>
                {" · "}
                {name(a.office) || t(`role.${a.role}` as Key)}
                {admin && a.actor ? ` · ${a.actor.name}` : ""}
              </p>
              <p className="text-xs text-slate-500">{formatDateTime(a.at, lang)}</p>
              {a.break_glass && (
                <p className="text-xs text-amber-800">
                  {t("access.breakGlass")}
                  {admin && a.break_glass_reason ? `: ${t(`bgr.${a.break_glass_reason}` as Key)}` : ""}
                  {admin && a.break_glass_note ? ` · ${a.break_glass_note}` : ""}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
      {list.hasMore && (
        <Button variant="secondary" onClick={list.more} busy={list.busy}>
          {t("common.more")}
        </Button>
      )}
      {appearances > 0 && <p className="text-xs text-slate-500">{t("req.listAppearances", { n: appearances })}</p>}
    </div>
  );
}
