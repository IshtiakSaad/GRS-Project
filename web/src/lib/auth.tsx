"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
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

type State = { status: "loading" } | { status: "anon" } | { status: "in"; me: Me };

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

  const load = useCallback(async () => {
    try {
      const me = await get<Me>("me");
      setState({ status: "in", me });
      return me;
    } catch {
      setState({ status: "anon" });
      return null;
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
