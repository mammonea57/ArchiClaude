"use client";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

export interface Material {
  id: string;
  nom: string;
  categorie: string;
  sous_categorie: string;
  texture_url: string;
  thumbnail_url: string;
  prompt_en: string;
  prompt_fr: string;
  couleur_dominante: string;
  conforme_abf: boolean;
  regional: string | null;
}

export function useMaterials() {
  const [materials, setMaterials] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<{ items: Material[]; total: number }>("/rendering/materials")
      .then((data) => setMaterials(data.items))
      .catch(() => setMaterials([]))
      .finally(() => setLoading(false));
  }, []);

  return { materials, loading };
}
