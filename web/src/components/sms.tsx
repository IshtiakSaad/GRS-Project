"use client";

// Demo only: what the fake SMS provider stored for a +880 10… number, so a reviewer can
// read the codes the app "sent". The endpoint does not exist outside demo mode.

import { useCallback, useEffect, useState } from "react";
import { get } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { DemoSms } from "@/lib/types";
import { DEMO } from "./shell";
import { Empty, SectionTitle } from "./ui";

export function useDemoSms(phone: string, poll = true) {
  const [messages, setMessages] = useState<DemoSms[] | null>(null);
  const load = useCallback(async () => {
    if (!phone.trim()) return setMessages(null);
    try {
      setMessages(await get<DemoSms[]>(`demo/sms/${encodeURIComponent(phone.trim())}`, { auth: false }));
    } catch {
      setMessages([]);
    }
  }, [phone]);

  useEffect(() => {
    load();
    if (!poll) return;
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load, poll]);

  return { messages, reload: load };
}

export function SmsList({ messages }: { messages: DemoSms[] | null }) {
  const { t, lang } = useI18n();
  if (messages === null) return null;
  if (messages.length === 0) return <Empty>{t("sms.empty")}</Empty>;
  return (
    <ul className="space-y-2">
      {messages.map((m) => (
        <li key={m.created_at + m.body} className="rounded-lg bg-slate-100 px-3 py-2">
          <p className="text-sm">{m.body}</p>
          <p className="mt-1 text-xs text-slate-500">{formatDateTime(m.created_at, lang)}</p>
        </li>
      ))}
    </ul>
  );
}

/** A small inbox under the code form, refreshing every few seconds. */
export function SmsPeek({ phone }: { phone: string }) {
  const { t } = useI18n();
  const { messages } = useDemoSms(phone);
  if (!DEMO || !phone) return null;
  return (
    <section className="rounded-xl border border-dashed border-amber-300 bg-amber-50/60 p-4">
      <SectionTitle>{t("sms.title")}</SectionTitle>
      <SmsList messages={messages} />
    </section>
  );
}
