"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { BilanResult } from "@/lib/types";

interface UseBilanResult {
  bilan: BilanResult | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
}

export function useBilan(projectId: string): UseBilanResult {
  const [bilan, setBilan] = useState<BilanResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    setNotFound(false);

    apiFetch<BilanResult>(`/projects/${projectId}/feasibility/bilan`)
      .then((data) => {
        if (cancelled) return;
        setBilan(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(err instanceof Error ? err.message : "Erreur de chargement");
        }
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return { bilan, loading, error, notFound };
}
