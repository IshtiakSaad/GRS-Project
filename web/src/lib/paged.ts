"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api";
import type { Page } from "./types";

/** The path and query of a `next` link: the API may name itself by an internal host. */
function relative(url: string): string {
  const u = new URL(url, window.location.origin);
  return u.pathname + u.search;
}

/** A keyset-paged list: the first page on load, more on demand. `path` null waits. */
export function usePaged<T>(path: string | null) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [extra, setExtra] = useState<Record<string, unknown>>({});
  const current = useRef(path);

  const load = useCallback(async () => {
    current.current = path;
    if (!path) return;
    setBusy(true);
    setError(null);
    try {
      const page = await get<Page<T> & Record<string, unknown>>(path);
      if (current.current !== path) return; // a newer filter won
      setRows(page.results);
      setNext(page.next);
      const { results: _r, next: _n, previous: _p, ...rest } = page;
      setExtra(rest);
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }, [path]);

  useEffect(() => {
    setRows(null);
    load();
  }, [load]);

  const more = useCallback(async () => {
    if (!next) return;
    setBusy(true);
    try {
      const page = await get<Page<T>>(relative(next));
      setRows((r) => [...(r ?? []), ...page.results]);
      setNext(page.next);
    } catch (err) {
      setError(err);
    }
    setBusy(false);
  }, [next]);

  return { rows, more, hasMore: !!next, busy, error, reload: load, extra };
}
