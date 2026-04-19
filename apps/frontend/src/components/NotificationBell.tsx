"use client";
import { useState } from "react";
import { Bell } from "lucide-react";
import { useNotifications } from "@/lib/hooks/useNotifications";
import { NotificationPanel } from "./NotificationPanel";

export function NotificationBell() {
  const { items, unread, markAllRead } = useNotifications();
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-2 rounded-md hover:bg-slate-100"
      >
        <Bell className="h-5 w-5 text-slate-600" />
        {unread > 0 && (
          <span className="absolute top-1 right-1 bg-red-500 text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && <NotificationPanel items={items} onMarkAllRead={markAllRead} onClose={() => setOpen(false)} />}
    </div>
  );
}
