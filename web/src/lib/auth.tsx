"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  endSession,
  get,
  hasSession,
  onSessionEnd,
  post,
  resume,
  startSession,
  type TrustMode,
} from "./api";
import type { Me, Role, Tokens } from "./types";

type State =
  | { status: "loading" }
  | { status: "anon" }
  | { status: "in"; me: Me }
  // Signed in, but the account could not be loaded (rate limit, outage, no connection). The
  // tokens are kept: this is not a logout.
  | { status: "error"; error: unknown };

const LOAD_ATTEMPTS = 4;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

interface Auth {
  state: State;
  me: Me | null;
  signIn: (tokens: Tokens, mode: TrustMode) => Promise<Me>;
  signOut: () => Promise<void>;
  reload: () => Promise<void>;
}

const Ctx = createContext<Auth | null>(null);

// Between the two login steps: the short-lived mfa_token and the chosen trust mode.
export const MFA_KEY = "grs.mfa";

export function homeFor(role: Role): string {
  return role === "ADMIN" ? "/admin/" : role === "OFFICER" ? "/officer/" : "/requests/";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });

  // Only a refused session signs the person out (the API layer ends it on those 401s). A 429,
  // a server error or a dropped connection is retried, honouring Retry-After, then shown as
  // an error with the session intact.
  const load = useCallback(async () => {
    setState((s) => (s.status === "error" ? { status: "loading" } : s));
    for (let attempt = 1; ; attempt++) {
      try {
        const me = await get<Me>("me");
        setState({ status: "in", me });
        return me;
      } catch (err) {
        if ((err instanceof ApiError && err.status === 401) || !hasSession()) {
          setState({ status: "anon" });
          return null;
        }
        if (attempt >= LOAD_ATTEMPTS) {
          setState({ status: "error", error: err });
          return null;
        }
        const wait = err instanceof ApiError && err.retryAfter ? err.retryAfter : 2 ** attempt;
        await sleep(Math.min(wait, 10) * 1000);
      }
    }
  }, []);

  useEffect(() => {
    const off = onSessionEnd(() => setState({ status: "anon" }));
    (async () => {
      if (hasSession() && (await resume())) await load();
      else setState({ status: "anon" });
    })();
    return () => {
      off();
    };
  }, [load]);

  const signIn = useCallback(
    async (tokens: Tokens, mode: TrustMode) => {
      startSession(tokens, mode);
      const me = await load();
      if (!me) throw new Error("login did not stick");
      return me;
    },
    [load],
  );

  const signOut = useCallback(async () => {
    try {
      await post("auth/logout");
    } catch {
      // The session ends here either way; the server's copy expires on its own.
    }
    endSession();
  }, []);

  const reload = useCallback(async () => {
    await load();
  }, [load]);

  const value = useMemo<Auth>(
    () => ({
      state,
      me: state.status === "in" ? state.me : null,
      signIn,
      signOut,
      reload,
    }),
    [state, signIn, signOut, reload],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
