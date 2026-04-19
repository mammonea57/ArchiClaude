"use client";
import { NotificationItem } from "./NotificationItem";
import type { Notification } from "@/lib/hooks/useNotifications";

export function NotificationPanel({
  items, onMarkAllRead, onClose,
}: {
  items: Notification[]; onMarkAllRead: () => void; onClose: () => void;
}) {
  return (
    <div className="absolute right-0 top-full mt-1 min-w-[360px] max-h-[500px] overflow-y-auto bg-white border border-slate-200 rounded-md shadow-lg z-50">
      <div className="sticky top-0 bg-white border-b border-slate-100 px-3 py-2 flex items-center justify-between">
        <span className="font-semibold text-sm">Notifications</span>
        <button onClick={onMarkAllRead} className="text-xs text-teal-700">
          Tout marquer comme lu
        </button>
      </div>
      {items.length === 0 ? (
        <div className="p-6 text-center text-sm text-slate-500">Aucune notification</div>
      ) : (
        items.map((n) => <NotificationItem key={n.id} notif={n} onClick={onClose} />)
      )}
    </div>
  );
}
