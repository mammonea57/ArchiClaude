"use client";

const STYLES: Record<string, string> = {
  admin: "bg-teal-100 text-teal-700",
  member: "bg-blue-100 text-blue-700",
  viewer: "bg-slate-100 text-slate-600",
};

export function RoleBadge({ role }: { role: string }) {
  const style = STYLES[role] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${style}`}>
      {role}
    </span>
  );
}
