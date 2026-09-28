"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ButtonLink, Card, SectionTitle } from "@/components/ui";
import { get } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { Category } from "@/lib/types";

export default function Home() {
  const { t, name, num } = useI18n();
  const { me } = useAuth();
  const router = useRouter();
  const [categories, setCategories] = useState<Category[]>([]);

  useEffect(() => {
    if (me) router.replace(homeFor(me.role));
  }, [me, router]);

  useEffect(() => {
    get<Category[]>("categories", { auth: false }).then(setCategories, () => setCategories([]));
  }, []);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl bg-brand-700 px-5 py-8 text-white sm:px-8 sm:py-12">
        <h1 className="max-w-2xl text-2xl font-semibold leading-snug sm:text-3xl">{t("home.title")}</h1>
        <p className="mt-3 max-w-2xl text-brand-50">{t("home.lead")}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <ButtonLink href="/register/" variant="secondary">
            {t("nav.register")}
          </ButtonLink>
          <ButtonLink href="/login/" className="bg-white/10 ring-1 ring-white/40 hover:bg-white/20">
            {t("nav.login")}
          </ButtonLink>
        </div>
      </section>

      {categories.length > 0 && (
        <Card>
          <SectionTitle>{t("home.services")}</SectionTitle>
          <ul className="grid gap-2 sm:grid-cols-2">
            {categories.map((c) => (
              <li key={c.code} className="rounded-lg bg-slate-50 px-3 py-2">
                <p className="text-sm font-medium">{name(c)}</p>
                <p className="text-xs text-slate-500">{t("common.days", { n: c.target_working_days })}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <SectionTitle>{t("home.tryDemo")}</SectionTitle>
        <p className="text-sm text-slate-600">{t("home.tryDemoHint")}</p>
        <p className="mt-2 text-sm text-slate-600">
          {t("common.phone")}: {num("01000000101")} · {t("common.password")}: demo-password-2026
        </p>
      </Card>
    </div>
  );
}
