"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { BuildingModelRow } from "@/lib/types";

interface UseBuildingModelResult {
  buildingModel: BuildingModelRow | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
  /** Refetch the current BM without reloading the page. Returns the new
   *  BM (or throws on network error). */
  refresh: () => Promise<BuildingModelRow | null>;
}

export function useBuildingModel(projectId: string): UseBuildingModelResult {
  const [buildingModel, setBuildingModel] = useState<BuildingModelRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const fetchOnce = useCallback(async (): Promise<BuildingModelRow | null> => {
    try {
      // Cache-bust via timestamp to defeat any intermediate HTTP cache (browser, service worker, proxy).
      const data = await apiFetch<BuildingModelRow>(`/projects/${projectId}/building_model?t=${Date.now()}`);
      // Only replace state if the version actually changed — avoids needless
      // re-renders on polls when nothing moved.
      setBuildingModel((prev) => {
        if (prev && prev.version === data.version) return prev;
        return data;
      });
      setError(null);
      setNotFound(false);
      return data;
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
        return null;
      }
      setError(err instanceof Error ? err.message : "Erreur de chargement");
      throw err;
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setNotFound(false);

    // Initial fetch
    fetchOnce().catch(() => { /* already handled */ });

    // Auto-poll every 3s so the UI never lags behind backend edits/fixes.
    // Silent (no loading flicker) — result replaces state only if the version
    // differs, to avoid needless re-renders.
    const poll = setInterval(() => {
      if (cancelled) return;
      fetchOnce().catch(() => {});
    }, 3000);

    // Also refetch when the tab regains focus (user switches back).
    const onVis = () => {
      if (document.visibilityState === "visible" && !cancelled) {
        fetchOnce().catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", onVis);

    return () => {
      cancelled = true;
      clearInterval(poll);
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", onVis);
    };
  }, [projectId, fetchOnce]);

  return { buildingModel, loading, error, notFound, refresh: fetchOnce };
}
