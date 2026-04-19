"use client";
import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

export function useNotifications() {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: Notification[]; total: number; unread: number }>(
        "/notifications?limit=20"
      );
      setItems(data.items);
      setUnread(data.unread);
    } catch {
      // silently ignore (user may be signed out)
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30_000);
    return () => clearInterval(interval);
  }, [refresh]);

  async function markAllRead() {
    await apiFetch("/notifications/mark-all-read", { method: "POST" });
    refresh();
  }

  return { items, unread, markAllRead, refresh };
}
