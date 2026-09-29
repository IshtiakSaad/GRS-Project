"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor, useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import type { Key } from "@/lib/messages";
import type { Role } from "@/lib/types";
import { Button, ButtonLink, ErrorNotice, Loading, Notice } from "./ui";

export const DEMO = process.env.NEXT_PUBLIC_DEMO !== "false";

const NAV: Record<Role | "anon", [Key, string][]> = {
  anon: [
    ["nav.login", "/login/"],
    ["nav.register", "/register/"],
  ],
  CITIZEN: [
    ["nav.myRequests", "/requests/"],
    ["nav.newRequest", "/requests/new/"],
    ["nav.track", "/track/"],
    ["nav.profile", "/profile/"],
  ],
  OFFICER: [
    ["nav.queue", "/officer/"],
    ["nav.track", "/track/"],
    ["nav.breakGlass", "/officer/break-glass/"],
    ["nav.profile", "/profile/"],
  ],
  ADMIN: [
    ["nav.dashboard", "/admin/"],
    ["nav.allRequests", "/admin/requests/"],
    ["nav.reviews", "/admin/reviews/"],
    ["nav.people", "/admin/people/"],
    ["nav.directory", "/admin/directory/"],
    ["nav.breakGlass", "/admin/break-glass/"],
    ["nav.profile", "/profile/"],
  ],
};

export function Shell({ children }: { children: React.ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const { state, me, signOut } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const items = NAV[me?.role ?? "anon"];

  return (
    <div className="flex min-h-dvh flex-col">
      {DEMO && (
        <div className="bg-amber-100 px-4 py-1.5 text-center text-xs text-amber-900">
          {t("app.demo")}{" "}
          <Link href="/demo-sms/" className="font-medium underline">
            {t("app.smsInbox")}
          </Link>
        </div>
      )}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <Link href={me ? homeFor(me.role) : "/"} className="flex items-center gap-2 font-semibold text-brand-700">
            <span aria-hidden className="grid h-8 w-8 place-items-center rounded-full bg-brand-600 text-sm text-white">
              ●
            </span>
            <span className="hidden sm:inline">{t("app.name")}</span>
            <span className="sm:hidden">{t("app.short")}</span>
          </Link>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setLang(lang === "bn" ? "en" : "bn")}
              className="min-h-10 rounded-lg px-3 text-sm font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50"
              lang={lang === "bn" ? "en" : "bn"}
            >
              {t("app.language")}
            </button>
            {me && (
              <button
                type="button"
                onClick={async () => {
                  await signOut();
                  router.replace("/login/");
                }}
                className="min-h-10 rounded-lg px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                {t("nav.logout")}
              </button>
            )}
          </div>
        </div>
        {state.status !== "loading" && (
          <nav aria-label={t("nav.menu")} className="mx-auto max-w-5xl px-2">
            {/* Wraps on a phone: seven admin items do not fit, and hidden ones look missing. */}
            <ul className="flex flex-wrap gap-x-1">
              {items.map(([key, href]) => {
                const active = isActive(pathname, href);
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      aria-current={active ? "page" : undefined}
                      className={`block whitespace-nowrap border-b-2 px-3 py-2.5 text-sm ${
                        active
                          ? "border-brand-600 font-medium text-brand-700"
                          : "border-transparent text-slate-600 hover:text-slate-900"
                      }`}
                    >
                      {t(key)}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">{children}</main>
      <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-500">
        <a href="/api/docs/" className="underline">
          {t("app.apiDocs")}
        </a>
      </footer>
    </div>
  );
}

// Section pages light up for their sub-pages; the role home pages only for themselves (and
// "My requests" for a request being viewed), so "Dashboard" is not lit on every /admin/ page.
function isActive(pathname: string, href: string) {
  if (pathname === href) return true;
  if (href === "/requests/") return pathname.startsWith("/requests/view");
  if (href === "/admin/" || href === "/officer/") return false;
  return pathname.startsWith(href);
}

/** Renders children only for a logged-in user with one of `roles`; otherwise sends them to log in. */
export function Guard({ roles, children }: { roles?: Role[]; children: React.ReactNode }) {
  const { state, me, reload } = useAuth();
  const { t } = useI18n();
  const router = useRouter();

  useEffect(() => {
    if (state.status === "anon") {
      const here = window.location.pathname + window.location.search;
      router.replace(`/login/?next=${encodeURIComponent(here)}`);
    }
  }, [state.status, router]);

  if (state.status === "error") {
    return (
      <div className="space-y-4">
        <ErrorNotice error={state.error} />
        <Button onClick={() => reload()}>{t("app.retry")}</Button>
      </div>
    );
  }
  if (!me) return <Loading />;
  if (roles && !roles.includes(me.role)) {
    return (
      <div className="space-y-4">
        <Notice tone="warning">{t("app.notAllowed")}</Notice>
        <ButtonLink href={homeFor(me.role)}>{t("app.home")}</ButtonLink>
      </div>
    );
  }
  return <>{children}</>;
}

/** Where to go after login: the `next` parameter if it is a path on this site. */
export function safeNext(raw: string | null, fallback: string): string {
  if (raw && raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\")) return raw;
  return fallback;
}
