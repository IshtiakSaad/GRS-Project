"use client";

// Bangla first, English on request. The API answers in the same language (Accept-Language),
// so its error messages need no second translation here.

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { setLanguage } from "./api";
import { messages, type Key } from "./messages";
import type { Lang } from "./types";

const LANG_KEY = "grs.lang";

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
  /** The Bangla or English name of something the API sends in both. */
  name: (x: { name_bn: string; name_en: string } | null | undefined) => string;
  /** Digits in the current language (Bangla digits in Bangla). */
  num: (n: number | string) => string;
}

const Ctx = createContext<I18n | null>(null);

const BN_DIGITS = "০১২৩৪৫৬৭৮৯";

export function toBanglaDigits(s: string): string {
  return s.replace(/[0-9]/g, (d) => BN_DIGITS[Number(d)]);
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("bn");

  useEffect(() => {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(LANG_KEY);
    } catch {}
    if (saved === "en" || saved === "bn") setLangState(saved);
  }, []);

  useEffect(() => {
    setLanguage(lang);
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLanguage(next);
    setLangState(next);
    try {
      localStorage.setItem(LANG_KEY, next);
    } catch {}
  }, []);

  const value = useMemo<I18n>(() => {
    const num = (n: number | string) => (lang === "bn" ? toBanglaDigits(String(n)) : String(n));
    return {
      lang,
      setLang,
      num,
      t: (key, vars) => {
        let s: string = messages[key][lang === "bn" ? 1 : 0];
        if (vars) {
          for (const [k, v] of Object.entries(vars)) {
            s = s.replaceAll(`{${k}}`, typeof v === "number" ? num(v) : v);
          }
        }
        return s;
      },
      name: (x) => (x ? (lang === "bn" ? x.name_bn : x.name_en) : ""),
    };
  }, [lang, setLang]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
