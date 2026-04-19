"use client";
import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";

export interface WorkspaceListItem {
  workspace: {
    id: string;
    name: string;
    slug: string;
    description: string | null;
    logo_url: string | null;
    is_personal: boolean;
    created_at: string;
  };
  role: "admin" | "member" | "viewer";
}

export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState<WorkspaceListItem[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<WorkspaceListItem[]>("/workspaces");
      setWorkspaces(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { workspaces, loading, refresh };
}
