"use client";
import { use, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RoleBadge } from "@/components/RoleBadge";
import { apiFetch } from "@/lib/api";

interface Member {
  user_id: string; email: string; full_name: string | null;
  role: "admin" | "member" | "viewer"; joined_at: string | null;
}

export default function WorkspaceMembersPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [members, setMembers] = useState<Member[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member" | "viewer">("member");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Member[]>(`/workspaces/${id}/members`).then(setMembers).catch(() => setMembers([]));
  }, [id]);

  async function invite() {
    setError(null);
    try {
      await apiFetch(`/workspaces/${id}/invitations`, {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
      });
      setInviteEmail("");
    } catch {
      setError("Impossible d'inviter");
    }
  }

  return (
    <main className="max-w-4xl mx-auto p-8">
      <h1 className="font-display text-2xl font-bold text-slate-900 mb-6">Membres</h1>

      <div className="bg-white border border-slate-200 rounded-lg p-4 mb-6">
        <h2 className="font-semibold text-sm text-slate-700 mb-3">Inviter un membre</h2>
        <div className="flex gap-2 flex-wrap">
          <Input
            placeholder="email@example.com"
            value={inviteEmail}
            onChange={(e) => setInviteEmail(e.target.value)}
          />
          <select
            value={inviteRole}
            onChange={(e) => setInviteRole(e.target.value as "admin" | "member" | "viewer")}
            className="border border-slate-200 rounded-md px-2 text-sm"
          >
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </select>
          <Button onClick={invite} className="bg-teal-600 text-white hover:bg-teal-700">
            Inviter
          </Button>
        </div>
        {error && <p className="text-sm text-red-600 mt-2">{error}</p>}
      </div>

      <div className="bg-white border border-slate-200 rounded-lg divide-y divide-slate-100">
        {members.map((m) => (
          <div key={m.user_id} className="flex items-center justify-between p-4">
            <div>
              <div className="font-medium text-slate-900">{m.full_name ?? m.email}</div>
              <div className="text-sm text-slate-500">{m.email}</div>
            </div>
            <RoleBadge role={m.role} />
          </div>
        ))}
      </div>
    </main>
  );
}
