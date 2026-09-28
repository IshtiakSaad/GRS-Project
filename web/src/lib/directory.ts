"use client";

import { useEffect, useState } from "react";
import { get } from "./api";
import type { Category } from "./types";

let cached: Promise<Category[]> | null = null;

/** The active services, fetched once per page load (the list rarely changes). */
export function useCategories(): Category[] {
  const [rows, setRows] = useState<Category[]>([]);
  useEffect(() => {
    cached ??= get<Category[]>("categories", { auth: false }).catch(() => {
      cached = null;
      return [];
    });
    cached.then(setRows);
  }, []);
  return rows;
}
