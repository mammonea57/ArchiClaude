"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Project } from "@/lib/types";

interface UseFeasibilityResult {
  project: Project | null;
  loading: boolean;
  error: string | null;
}

export function useFeasibility(projectId: string): UseFeasibilityResult {
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    setLoading(true);
    setError(null);

    apiFetch<Project>(`/projects/${projectId}`)
      .then((data) => {
        if (!cancelled) {
          setProject(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Erreur de chargement");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return { project, loading, error };
}
