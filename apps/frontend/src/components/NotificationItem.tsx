"use client";
import Link from "next/link";
import type { Notification } from "@/lib/hooks/useNotifications";

export function NotificationItem({ notif, onClick }: { notif: Notification; onClick?: () => void }) {
  const date = new Date(notif.created_at).toLocaleDateString("fr-FR", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
  const content = (
    <div className={`px-3 py-2 hover:bg-slate-50 border-b border-slate-100 ${notif.read_at ? "opacity-70" : "font-medium"}`}>
      <div className="text-sm text-slate-900">{notif.title}</div>
      {notif.body && <div className="text-xs text-slate-500 mt-0.5">{notif.body}</div>}
      <div className="text-xs text-slate-400 mt-1">{date}</div>
    </div>
  );
  if (notif.link) return <Link href={notif.link} onClick={onClick}>{content}</Link>;
  return content;
}
