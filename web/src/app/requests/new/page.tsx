"use client";

// New request, or editing a draft (?id=). Saving creates the draft once and edits it after
// that, so pressing Submit again after a dropped connection never makes a second request.
// Submit carries an Idempotency-Key that is kept until the answer arrives.

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { viewHref } from "@/components/request-list";
import { Guard } from "@/components/shell";
import {
  Button,
  Card,
  Checkbox,
  ErrorNotice,
  fieldError,
  Loading,
  Notice,
  PageTitle,
  Select,
  TextArea,
  TextInput,
} from "@/components/ui";
import { ApiError, call, idempotencyKey, post } from "@/lib/api";
import { useCategories } from "@/lib/directory";
import { formatSize } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { check, upload } from "@/lib/upload";
import type { Relation, ServiceRequest } from "@/lib/types";

const RELATIONS: Relation[] = ["SPOUSE", "CHILD", "PARENT", "SIBLING", "OTHER"];

interface PendingFile {
  file: File;
  progress: number;
  done: boolean;
  error?: unknown;
}

function NewRequest() {
  const { t, lang, name } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const categories = useCategories();
  const [loading, setLoading] = useState(!!params.get("id"));
  const [draft, setDraft] = useState<{ id: string; etag: string } | null>(null);
  const [form, setForm] = useState({
    category: "",
    title: "",
    description: "",
    forSomeone: false,
    beneficiaryName: "",
    relation: "OTHER" as Relation,
    urgent: false,
    urgencyReason: "",
  });
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [fileProblems, setFileProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState<"" | "save" | "submit">("");
  const [error, setError] = useState<unknown>(null);
  const [duplicate, setDuplicate] = useState(false);
  const submitKey = useRef<string | null>(null);

  // Editing a draft: load it and its ETag.
  useEffect(() => {
    const id = params.get("id");
    if (!id) return;
    call<ServiceRequest>(`requests/${id}`).then(
      ({ data, etag }) => {
        if (data.status !== "DRAFT") {
          router.replace(viewHref(id));
          return;
        }
        setDraft({ id, etag: etag ?? `"${data.version}"` });
        setForm({
          category: data.category.code,
          title: data.title,
          description: data.description,
          forSomeone: !!data.beneficiary,
          beneficiaryName: data.beneficiary?.name ?? "",
          relation: (data.beneficiary?.relation as Relation) ?? "OTHER",
          urgent: data.citizen_urgent,
          urgencyReason: data.urgency_reason ?? "",
        });
        setLoading(false);
      },
      (err) => {
        setError(err);
        setLoading(false);
      },
    );
  }, [params, router]);

  function body() {
    return {
      category: form.category,
      title: form.title,
      description: form.description,
      beneficiary: form.forSomeone ? { name: form.beneficiaryName, relation: form.relation } : null,
      citizen_urgent: form.urgent,
      urgency_reason: form.urgent ? form.urgencyReason : null,
    };
  }

  /** Create the draft, or save changes to it. Returns its id. */
  async function save(): Promise<string> {
    if (!draft) {
      const { data, etag } = await call<ServiceRequest>("requests", { method: "POST", body: body() });
      setDraft({ id: data.id, etag: etag ?? `"${data.version}"` });
      return data.id;
    }
    const { data, etag } = await call<ServiceRequest>(`requests/${draft.id}`, {
      method: "PATCH",
      body: body(),
      headers: { "If-Match": draft.etag },
    });
    setDraft({ id: data.id, etag: etag ?? `"${data.version}"` });
    return data.id;
  }

  async function uploadAll(id: string) {
    for (let i = 0; i < files.length; i++) {
      if (files[i].done) continue;
      const update = (patch: Partial<PendingFile>) =>
        setFiles((fs) => fs.map((f, j) => (j === i ? { ...f, ...patch } : f)));
      try {
        await upload(id, files[i].file, (p) => update({ progress: p }));
        files[i].done = true;
        update({ done: true, progress: 1, error: undefined });
      } catch (err) {
        update({ error: err });
        throw err;
      }
    }
  }

  async function run(kind: "save" | "submit", confirmDuplicate = false) {
    setBusy(kind);
    setError(null);
    try {
      const id = await save();
      await uploadAll(id);
      if (kind === "save") {
        router.push(viewHref(id));
        return;
      }
      submitKey.current ??= idempotencyKey();
      await post<ServiceRequest>(
        `requests/${id}/actions/submit`,
        { confirm_duplicate: confirmDuplicate },
        { headers: { "Idempotency-Key": submitKey.current } },
      );
      router.push(`${viewHref(id)}&submitted=1`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "POSSIBLE_DUPLICATE") {
        setDuplicate(true);
        submitKey.current = null; // a different body next time: a different key
      } else {
        // Keep the key after a network failure: a retry may find the first attempt done.
        if (err instanceof ApiError && err.status !== 0) submitKey.current = null;
        setError(err);
      }
      setBusy("");
    }
  }

  function addFiles(list: FileList | null) {
    if (!list) return;
    const problems: string[] = [];
    const ok: PendingFile[] = [];
    for (const file of Array.from(list)) {
      const p = check(file);
      if (p === "size") problems.push(t("req.fileTooBig", { name: file.name }));
      else if (p === "type") problems.push(t("req.fileType", { name: file.name }));
      else ok.push({ file, progress: 0, done: false });
    }
    setFileProblems(problems);
    setFiles((fs) => [...fs, ...ok]);
  }

  if (loading) return <Loading />;

  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle>{draft && params.get("id") ? t("req.editTitle") : t("req.newTitle")}</PageTitle>
      <Card>
        <form
          className="space-y-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            run("submit");
          }}
        >
          <ErrorNotice error={error} />
          <Select
            label={t("req.pickService")}
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            // No default: a service picked for the citizen is a request sent to the wrong office.
            options={[
              { value: "", label: t("req.choose") },
              ...categories.map((c) => ({
                value: c.code,
                label: `${name(c)} (${t("common.days", { n: c.target_working_days })})`,
              })),
            ]}
            error={fieldError(error, "category")}
          />
          <TextInput
            label={t("req.title")}
            hint={t("req.titleHint")}
            maxLength={200}
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
            error={fieldError(error, "title")}
          />
          <TextArea
            label={t("req.description")}
            hint={t("req.descriptionHint")}
            rows={6}
            maxLength={5000}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            error={fieldError(error, "description")}
          />
          <Checkbox
            label={t("req.forSomeone")}
            checked={form.forSomeone}
            onChange={(e) => setForm({ ...form, forSomeone: e.target.checked })}
          />
          {form.forSomeone && (
            <div className="grid gap-4 sm:grid-cols-2">
              <TextInput
                label={t("req.beneficiaryName")}
                value={form.beneficiaryName}
                onChange={(e) => setForm({ ...form, beneficiaryName: e.target.value })}
              />
              <Select
                label={t("req.relation")}
                value={form.relation}
                onChange={(e) => setForm({ ...form, relation: e.target.value as Relation })}
                options={RELATIONS.map((r) => ({ value: r, label: t(`relation.${r}`) }))}
              />
            </div>
          )}
          <Checkbox
            label={t("req.urgent")}
            checked={form.urgent}
            onChange={(e) => setForm({ ...form, urgent: e.target.checked })}
          />
          {form.urgent && (
            <TextInput
              label={t("req.urgencyReason")}
              value={form.urgencyReason}
              onChange={(e) => setForm({ ...form, urgencyReason: e.target.value })}
              error={fieldError(error, "urgency_reason")}
            />
          )}

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium text-slate-800">{t("req.files")}</legend>
            <p className="text-xs text-slate-500">{t("req.filesHint")}</p>
            <label className="inline-flex min-h-11 cursor-pointer items-center rounded-lg px-4 text-sm font-medium text-brand-700 ring-1 ring-slate-300 hover:bg-brand-50">
              {t("req.addFiles")}
              <input
                type="file"
                multiple
                accept="application/pdf,image/jpeg,image/png"
                className="sr-only"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </label>
            {fileProblems.map((p) => (
              <p key={p} className="text-sm text-red-700">
                {p}
              </p>
            ))}
            <ul className="space-y-1">
              {files.map((f, i) => (
                <li key={`${f.file.name}-${i}`} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">{f.file.name}</span>
                  <span className="text-xs text-slate-500">{formatSize(f.file.size, lang)}</span>
                  {f.error ? (
                    <span className="text-xs text-red-700">{t("file.failed")}</span>
                  ) : f.progress > 0 && !f.done ? (
                    <progress value={f.progress} max={1} className="h-2 w-16" />
                  ) : f.done ? (
                    <span className="text-xs text-brand-700">✓</span>
                  ) : (
                    <button
                      type="button"
                      className="text-xs text-slate-500 underline"
                      onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))}
                    >
                      {t("common.remove")}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </fieldset>

          {duplicate && (
            <Notice tone="warning">
              <p>{t("req.duplicateTitle")}</p>
              <Button variant="secondary" className="mt-2" busy={busy === "submit"} onClick={() => run("submit", true)}>
                {t("req.duplicateSend")}
              </Button>
            </Notice>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <Button type="submit" busy={busy === "submit"} disabled={!!busy || !form.category}>
              {t("req.submit")}
            </Button>
            <Button variant="secondary" busy={busy === "save"} disabled={!!busy || !form.category} onClick={() => run("save")}>
              {t("req.saveDraft")}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Guard roles={["CITIZEN"]}>
      <Suspense fallback={<Loading />}>
        <NewRequest />
      </Suspense>
    </Guard>
  );
}
