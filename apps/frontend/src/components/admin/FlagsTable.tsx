"use client";

import { useEffect, useState } from "react";
import type { FeatureFlagRead } from "@archiclaude/shared-types";

import { ApiError, apiFetch } from "@/lib/api";

export function FlagsTable() {
  const [flags, setFlags] = useState<FeatureFlagRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<FeatureFlagRead[]>("/admin/feature-flags")
      .then(setFlags)
      .catch((e) =>
        setError(e instanceof ApiError ? `Erreur ${e.status}: ${JSON.stringify(e.body)}` : "Erreur réseau"),
      );
  }, []);

  async function toggle(key: string, currentValue: boolean) {
    try {
      const updated = await apiFetch<FeatureFlagRead>(`/admin/feature-flags/${key}`, {
        method: "PUT",
        body: JSON.stringify({ enabled_globally: !currentValue }),
      });
      setFlags((prev) => (prev ? prev.map((f) => (f.key === key ? updated : f)) : prev));
    } catch (e) {
      setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur inconnue");
    }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (flags === null) return <p className="text-slate-500">Chargement…</p>;
  if (flags.length === 0) return <p className="text-slate-500">Aucun flag défini.</p>;

  return (
    <table className="w-full text-left">
      <thead className="border-b text-sm text-slate-500">
        <tr>
          <th className="py-2">Clé</th>
          <th>Global</th>
          <th>Users override</th>
          <th>Description</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {flags.map((f) => (
          <tr key={f.key} className="border-b">
            <td className="py-2 font-mono text-sm">{f.key}</td>
            <td>{f.enabled_globally ? "✓" : "—"}</td>
            <td className="text-sm text-slate-500">{f.enabled_for_user_ids.length}</td>
            <td className="text-sm">{f.description ?? ""}</td>
            <td>
              <button
                type="button"
                className="rounded bg-slate-200 px-3 py-1 text-sm hover:bg-slate-300"
                onClick={() => toggle(f.key, f.enabled_globally)}
              >
                Toggle global
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
