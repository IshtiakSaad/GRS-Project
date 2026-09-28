"use client";

import { useEffect, useState } from "react";

/** Seconds left until a resend is allowed; restart() begins a new wait. */
export function useCountdown(initial: number) {
  const [left, setLeft] = useState(initial);
  useEffect(() => {
    if (left <= 0) return;
    const id = setTimeout(() => setLeft((n) => n - 1), 1000);
    return () => clearTimeout(id);
  }, [left]);
  return { left, restart: (n: number) => setLeft(n) };
}
