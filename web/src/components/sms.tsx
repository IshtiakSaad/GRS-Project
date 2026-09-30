"use client";

// Demo only: what the fake SMS provider stored for a +880 10… number, so a reviewer can
// read the codes the app "sent". The endpoint does not exist outside demo mode.

import { useCallback, useEffect, useState } from "react";
import { get } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { DemoSms } from "@/lib/types";
import { DEMO } from "./shell";
import { Button, Empty, SectionTitle } from "./ui";

// The six-digit code in a message; the phone number in a link is longer, so it never matches.
const CODE = /\b\d{6}\b/;

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

export function SmsList({ messages, onUse }: { messages: DemoSms[] | null; onUse?: (code: string) => void }) {
  const { t, lang } = useI18n();
  if (messages === null) return null;
  if (messages.length === 0) return <Empty>{t("sms.empty")}</Empty>;
  return (
    <ul className="space-y-2">
      {messages.map((m) => {
        const code = onUse && m.body.match(CODE)?.[0];
        return (
          <li key={m.created_at + m.body} className="rounded-lg bg-slate-100 px-3 py-2">
            <p className="break-words text-sm">{m.body}</p>
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-slate-500">{formatDateTime(m.created_at, lang)}</p>
              {code && (
                <Button variant="secondary" onClick={() => onUse(code)}>
                  {t("sms.use")}
                </Button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** A small inbox under the code form, refreshing every few seconds; "Use this code" fills it in. */
export function SmsPeek({ phone, onUse }: { phone: string; onUse?: (code: string) => void }) {
  const { t } = useI18n();
  const { messages } = useDemoSms(phone);
  if (!DEMO || !phone) return null;
  return (
    <section className="rounded-xl border border-dashed border-amber-300 bg-amber-50/60 p-4">
      <SectionTitle>{t("sms.title")}</SectionTitle>
      <SmsList messages={messages} onUse={onUse} />
    </section>
  );
}
