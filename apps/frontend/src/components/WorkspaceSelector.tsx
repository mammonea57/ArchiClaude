"use client";
import { useState } from "react";
import Link from "next/link";
import { useWorkspaces } from "@/lib/hooks/useWorkspaces";

export function WorkspaceSelector() {
  const { workspaces } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const active = workspaces[0];
  if (!active) return null;

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-slate-200 bg-white text-sm hover:bg-slate-50"
      >
        <span className="font-medium text-slate-800">{active.workspace.name}</span>
        {active.workspace.is_personal && (
          <span className="text-xs text-slate-400">Perso</span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 min-w-[260px] bg-white border border-slate-200 rounded-md shadow-lg py-1 z-50">
          {workspaces.map(({ workspace, role }) => (
            <Link
              key={workspace.id}
              href={`/workspaces/${workspace.id}`}
              className="block px-3 py-2 hover:bg-slate-50 text-sm"
              onClick={() => setOpen(false)}
            >
              <div className="flex justify-between items-center">
                <span>{workspace.name}</span>
                <span className="text-xs text-slate-400">{role}</span>
              </div>
            </Link>
          ))}
          <div className="border-t border-slate-100 my-1" />
          <Link href="/workspaces" className="block px-3 py-2 hover:bg-slate-50 text-sm text-teal-700">
            Gérer les workspaces
          </Link>
        </div>
      )}
    </div>
  );
}
