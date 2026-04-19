"use client";

import { useEffect, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { BuildingModelRow } from "@/lib/types";

interface UseBuildingModelResult {
  buildingModel: BuildingModelRow | null;
  loading: boolean;
  error: string | null;
  notFound: boolean;
}

export function useBuildingModel(projectId: string): UseBuildingModelResult {
  const [buildingModel, setBuildingModel] = useState<BuildingModelRow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    setLoading(true);
    setError(null);
    setNotFound(false);

    apiFetch<BuildingModelRow>(`/projects/${projectId}/building_model`)
      .then((data) => {
        if (cancelled) return;
        setBuildingModel(data);
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

  return { buildingModel, loading, error, notFound };
}
