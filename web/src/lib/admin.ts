"use client";

import { useCallback, useEffect, useState } from "react";
import { get } from "./api";
import type { CategoryAdmin, Department } from "./types";

/** An admin list that is not paged: load, and reload after a change. */
export function useList<T>(path: string) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const reload = useCallback(async () => {
    try {
      setRows(await get<T[]>(path));
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, [path]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { rows, error, reload };
}

export const useDepartments = () => useList<Department>("admin/departments");
export const useAdminCategories = () => useList<CategoryAdmin>("admin/categories");
