"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

interface Prefs {
  in_app_enabled: boolean;
  email_workspace_invitations: boolean;
  email_project_analyzed: boolean;
  email_project_ready_for_pc: boolean;
  email_mentions: boolean;
  email_comments: boolean;
  email_pcmi6_generated: boolean;
  email_weekly_digest: boolean;
}

const TOGGLES: { key: keyof Prefs; label: string; section: string }[] = [
  { key: "email_workspace_invitations", label: "Invitations aux workspaces", section: "Partage & collaboration" },
  { key: "email_mentions", label: "Mentions (@user)", section: "Partage & collaboration" },
  { key: "email_comments", label: "Commentaires sur mes projets", section: "Partage & collaboration" },
  { key: "email_project_analyzed", label: "Projet analysé", section: "Progression des projets" },
  { key: "email_project_ready_for_pc", label: "Projet prêt pour dépôt PC", section: "Progression des projets" },
  { key: "email_pcmi6_generated", label: "Rendu PCMI6 généré", section: "Progression des projets" },
  { key: "email_weekly_digest", label: "Récap hebdomadaire", section: "Annonces produit" },
];

export default function NotificationsPrefsPage() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch<Prefs>("/account/notifications").then(setPrefs).catch(() => setPrefs(null));
  }, []);

  async function update(key: keyof Prefs, value: boolean) {
    if (!prefs) return;
    setSaving(true);
    const updated = await apiFetch<Prefs>("/account/notifications", {
      method: "PATCH",
      body: JSON.stringify({ [key]: value }),
    });
    setPrefs(updated);
    setSaving(false);
  }

  if (!prefs) return <div className="p-8">Chargement...</div>;

  const grouped: Record<string, typeof TOGGLES> = {};
  for (const t of TOGGLES) {
    grouped[t.section] = grouped[t.section] ?? [];
    grouped[t.section].push(t);
  }

  return (
    <main className="max-w-2xl mx-auto p-8">
      <h1 className="font-display text-3xl font-bold text-slate-900 mb-6">
        Préférences de notifications
      </h1>
      {Object.entries(grouped).map(([section, toggles]) => (
        <div key={section} className="mb-8">
          <h2 className="font-display text-lg font-semibold text-slate-700 mb-3">{section}</h2>
          <div className="space-y-2">
            {toggles.map((t) => (
              <label key={t.key} className="flex items-center justify-between border border-slate-200 rounded-lg p-3 bg-white">
                <span className="text-sm text-slate-700">{t.label}</span>
                <input
                  type="checkbox"
                  checked={prefs[t.key] as boolean}
                  onChange={(e) => update(t.key, e.target.checked)}
                  disabled={saving}
                  className="h-5 w-5 accent-teal-600"
                />
              </label>
            ))}
          </div>
        </div>
      ))}
    </main>
  );
}
