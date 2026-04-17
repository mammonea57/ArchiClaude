"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Project } from "@/lib/types";

interface UseProjectsResult {
  projects: Project[];
  loading: boolean;
  error: string | null;
}

export function useProjects(): UseProjectsResult {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    apiFetch<Project[]>("/projects")
      .then((data) => {
        if (!cancelled) {
          setProjects(data);
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
  }, []);

  return { projects, loading, error };
}
