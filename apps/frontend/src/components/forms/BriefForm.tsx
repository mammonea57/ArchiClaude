"use client";

import { useState } from "react";
import { z } from "zod";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { Brief } from "@/lib/types";

export interface BriefFormProps {
  onSubmit: (brief: Brief) => void;
  loading?: boolean;
}

const MIX_KEYS = ["T1", "T2", "T3", "T4", "T5"] as const;

type MixTypo = Record<(typeof MIX_KEYS)[number], number>;

const briefSchema = z.object({
  destination: z.string().min(1, "Destination requise"),
  cible_nb_logements: z.number().min(0).optional(),
  mix_typologique: z
    .record(z.number().min(0).max(1))
    .refine(
      (m) => {
        const sum = Object.values(m).reduce((a, b) => a + b, 0);
        return sum >= 0.99 && sum <= 1.01;
      },
      { message: "Le mix typologique doit totaliser 100%" },
    ),
  cible_sdp_m2: z.number().min(0).optional(),
  hauteur_cible_niveaux: z.number().min(1).optional(),
  emprise_cible_pct: z.number().min(0).max(100).optional(),
  espaces_verts_pleine_terre_cible_pct: z.number().min(0).max(100).optional(),
  stationnement_cible_par_logement: z.number().min(0).optional(),
});

const DESTINATIONS = [
  { value: "logement_collectif", label: "Logement collectif" },
  { value: "residence_service", label: "Résidence service" },
  { value: "bureaux", label: "Bureaux" },
  { value: "commerce", label: "Commerce" },
  { value: "mixte", label: "Mixte" },
];

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return <p className="mt-1 text-xs text-red-500">{msg}</p>;
}

export default function BriefForm({ onSubmit, loading = false }: BriefFormProps) {
  const [destination, setDestination] = useState("");
  const [nbLogements, setNbLogements] = useState("");
  const [sdp, setSdp] = useState("");
  const [mix, setMix] = useState<MixTypo>({ T1: 0.1, T2: 0.3, T3: 0.4, T4: 0.15, T5: 0.05 });
  const [hauteur, setHauteur] = useState("");
  const [emprise, setEmprise] = useState("");
  const [pleineTerre, setPleineTerre] = useState("");
  const [stationnement, setStationnement] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mixSum = Object.values(mix).reduce((a, b) => a + b, 0);
  const mixSumPct = Math.round(mixSum * 100);

  function handleMixChange(key: (typeof MIX_KEYS)[number], raw: string) {
    const val = parseFloat(raw);
    if (!Number.isNaN(val)) {
      setMix((prev) => ({ ...prev, [key]: val / 100 }));
    } else {
      setMix((prev) => ({ ...prev, [key]: 0 }));
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const data = {
      destination,
      cible_nb_logements: nbLogements ? Number(nbLogements) : undefined,
      mix_typologique: mix as Record<string, number>,
      cible_sdp_m2: sdp ? Number(sdp) : undefined,
      hauteur_cible_niveaux: hauteur ? Number(hauteur) : undefined,
      emprise_cible_pct: emprise ? Number(emprise) : undefined,
      espaces_verts_pleine_terre_cible_pct: pleineTerre ? Number(pleineTerre) : undefined,
      stationnement_cible_par_logement: stationnement ? Number(stationnement) : undefined,
    };

    const parsed = briefSchema.safeParse(data);
    if (!parsed.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path.join(".");
        fieldErrors[key || issue.path[0]?.toString() || "general"] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }

    setErrors({});
    onSubmit(parsed.data as Brief);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 h-full">
      <Tabs defaultValue="programme" className="flex-1 flex flex-col">
        <TabsList className="grid grid-cols-4 w-full mb-2">
          <TabsTrigger value="programme" className="text-xs">Programme</TabsTrigger>
          <TabsTrigger value="contraintes" className="text-xs">Contraintes</TabsTrigger>
          <TabsTrigger value="verts" className="text-xs">Espaces verts</TabsTrigger>
          <TabsTrigger value="stat" className="text-xs">Stationnement</TabsTrigger>
        </TabsList>

        {/* Tab 1 — Programme */}
        <TabsContent value="programme" className="flex-1 flex flex-col gap-4 pt-1">
          <div>
            <Label className="mb-1.5 block text-sm">Destination</Label>
            <Select value={destination} onValueChange={setDestination}>
              <SelectTrigger>
                <SelectValue placeholder="Choisir…" />
              </SelectTrigger>
              <SelectContent>
                {DESTINATIONS.map((d) => (
                  <SelectItem key={d.value} value={d.value}>
                    {d.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldError msg={errors["destination"]} />
          </div>

          <div>
            <Label className="mb-1.5 block text-sm">Nombre de logements cible</Label>
            <Input
              type="number"
              min={0}
              placeholder="ex. 40"
              value={nbLogements}
              onChange={(e) => setNbLogements(e.target.value)}
            />
            <FieldError msg={errors["cible_nb_logements"]} />
          </div>

          <div>
            <Label className="mb-1.5 block text-sm">SDP cible (m²)</Label>
            <Input
              type="number"
              min={0}
              placeholder="ex. 2500"
              value={sdp}
              onChange={(e) => setSdp(e.target.value)}
            />
            <FieldError msg={errors["cible_sdp_m2"]} />
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-sm">Mix typologique</Label>
              <span
                className={`text-xs font-mono tabular-nums ${
                  Math.abs(mixSumPct - 100) <= 1 ? "text-teal-700" : "text-red-500"
                }`}
              >
                {mixSumPct}%
              </span>
            </div>
            <div className="grid grid-cols-5 gap-2">
              {MIX_KEYS.map((key) => (
                <div key={key} className="flex flex-col items-center gap-1">
                  <Label className="text-xs text-slate-500">{key}</Label>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={Math.round(mix[key] * 100)}
                    onChange={(e) => handleMixChange(key, e.target.value)}
                    className="text-center px-1"
                  />
                  <span className="text-[10px] text-slate-400">%</span>
                </div>
              ))}
            </div>
            <FieldError msg={errors["mix_typologique"]} />
          </div>
        </TabsContent>

        {/* Tab 2 — Contraintes */}
        <TabsContent value="contraintes" className="flex-1 flex flex-col gap-4 pt-1">
          <div>
            <Label className="mb-1.5 block text-sm">Hauteur cible</Label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500 w-8">R+</span>
              <Input
                type="number"
                min={0}
                step={1}
                placeholder="ex. 5"
                value={hauteur ? String(Number(hauteur) - 1) : ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setHauteur(v !== "" ? String(Number(v) + 1) : "");
                }}
                className="w-24"
              />
              <span className="text-xs text-slate-400">
                {hauteur ? `(${hauteur} niveaux stockés)` : ""}
              </span>
            </div>
            <p className="mt-1 text-xs text-slate-400">Entrez le nombre d'étages au-dessus du RDC (R+n)</p>
            <FieldError msg={errors["hauteur_cible_niveaux"]} />
          </div>

          <div>
            <Label className="mb-1.5 block text-sm">Emprise au sol cible (%)</Label>
            <Input
              type="number"
              min={0}
              max={100}
              step={1}
              placeholder="ex. 50"
              value={emprise}
              onChange={(e) => setEmprise(e.target.value)}
            />
            <FieldError msg={errors["emprise_cible_pct"]} />
          </div>
        </TabsContent>

        {/* Tab 3 — Espaces verts */}
        <TabsContent value="verts" className="flex-1 flex flex-col gap-4 pt-1">
          <div>
            <Label className="mb-1.5 block text-sm">Pleine terre cible (%)</Label>
            <Input
              type="number"
              min={0}
              max={100}
              step={1}
              placeholder="ex. 30"
              value={pleineTerre}
              onChange={(e) => setPleineTerre(e.target.value)}
            />
            <p className="mt-1 text-xs text-slate-400">
              Part de la parcelle en pleine terre (non imperméabilisée)
            </p>
            <FieldError msg={errors["espaces_verts_pleine_terre_cible_pct"]} />
          </div>
        </TabsContent>

        {/* Tab 4 — Stationnement */}
        <TabsContent value="stat" className="flex-1 flex flex-col gap-4 pt-1">
          <div>
            <Label className="mb-1.5 block text-sm">Places par logement</Label>
            <Input
              type="number"
              min={0}
              step={0.5}
              placeholder="ex. 1.0"
              value={stationnement}
              onChange={(e) => setStationnement(e.target.value)}
            />
            <p className="mt-1 text-xs text-slate-400">
              Peut être 0, 0.5, 1.0, 1.5…
            </p>
            <FieldError msg={errors["stationnement_cible_par_logement"]} />
          </div>
        </TabsContent>
      </Tabs>

      <Button
        type="submit"
        disabled={loading}
        className="w-full text-white font-medium mt-2"
        style={{ backgroundColor: "var(--ac-primary)" }}
      >
        {loading ? "Analyse en cours…" : "Analyser"}
      </Button>
    </form>
  );
}
