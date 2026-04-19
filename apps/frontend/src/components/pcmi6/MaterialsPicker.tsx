"use client";
import { useMemo, useState } from "react";
import { Input } from "@/components/ui/input";
import { MaterialCard } from "./MaterialCard";
import { useMaterials } from "@/lib/hooks/useMaterials";

const CATEGORIES = [
  { id: "facades", label: "Façades" },
  { id: "toitures", label: "Toitures" },
  { id: "menuiseries", label: "Menuiseries" },
  { id: "clotures", label: "Clôtures" },
  { id: "sols_exterieurs", label: "Sols ext." },
  { id: "vegetal", label: "Végétal" },
];

interface Props {
  value: Record<string, string>; // surface -> material_id
  onChange: (next: Record<string, string>) => void;
  currentSurface: string; // which surface is being picked (facade, toiture, etc.)
}

export function MaterialsPicker({ value, onChange, currentSurface }: Props) {
  const { materials, loading } = useMaterials();
  const [category, setCategory] = useState<string>("facades");
  const [query, setQuery] = useState("");
  const [abfOnly, setAbfOnly] = useState(false);

  const filtered = useMemo(() => {
    return materials
      .filter((m) => m.categorie === category)
      .filter((m) => !abfOnly || m.conforme_abf)
      .filter((m) =>
        query === "" ? true : m.nom.toLowerCase().includes(query.toLowerCase()),
      );
  }, [materials, category, abfOnly, query]);

  if (loading) return <p className="text-sm text-slate-500">Chargement des matériaux…</p>;

  return (
    <div className="flex flex-col gap-3">
      {/* Category tabs */}
      <div className="flex flex-wrap gap-1">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => setCategory(c.id)}
            className={`px-3 py-1 text-xs rounded transition-colors ${
              category === c.id
                ? "bg-teal-600 text-white"
                : "bg-white text-slate-700 border border-slate-200"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <Input
          type="text"
          placeholder="Rechercher…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="h-8 text-sm"
        />
        <label className="flex items-center gap-1 text-xs text-slate-600 whitespace-nowrap">
          <input
            type="checkbox"
            checked={abfOnly}
            onChange={(e) => setAbfOnly(e.target.checked)}
          />
          ABF
        </label>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-3 gap-2">
        {filtered.map((m) => (
          <MaterialCard
            key={m.id}
            material={m}
            selected={value[currentSurface] === m.id}
            onClick={() => onChange({ ...value, [currentSurface]: m.id })}
          />
        ))}
      </div>

      {filtered.length === 0 && (
        <p className="text-sm text-slate-400">Aucun matériau trouvé pour cette recherche.</p>
      )}
    </div>
  );
}
