"use client";

import { useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Upload } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";

interface AgencySettings {
  agency_name: string;
  logo_url: string | null;
  contact_email: string;
  brand_primary_color: string;
  address?: string;
  phone?: string;
  architecte_ordre?: string;
}

interface CartoucheEditorProps {
  onSave?: (settings: AgencySettings) => void;
}

export function CartoucheEditor({ onSave }: CartoucheEditorProps) {
  const [settings, setSettings] = useState<AgencySettings>({
    agency_name: "",
    logo_url: null,
    contact_email: "",
    brand_primary_color: "#0d9488",
    address: "",
    phone: "",
    architecte_ordre: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    apiFetch<AgencySettings>("/agency/settings")
      .then((data) => setSettings(data))
      .catch(() => {
        // Silently use defaults if not yet configured
      })
      .finally(() => setLoading(false));
  }, []);

  function update(field: keyof AgencySettings, value: string) {
    setSettings((prev) => ({ ...prev, [field]: value }));
  }

  async function handleLogoUpload(file: File) {
    setUploadingLogo(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/agency/logo`,
        { method: "POST", body: formData },
      );
      if (!result.ok) throw new Error(`HTTP ${result.status}`);
      const { logo_url } = (await result.json()) as { logo_url: string };
      setSettings((prev) => ({ ...prev, logo_url }));
    } catch {
      setError("Erreur lors du téléversement du logo.");
    } finally {
      setUploadingLogo(false);
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) handleLogoUpload(file);
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleLogoUpload(file);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const updated = await apiFetch<AgencySettings>("/agency/settings", {
        method: "PUT",
        body: JSON.stringify(settings),
      });
      setSettings(updated);
      setSuccess(true);
      onSave?.(updated);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e) {
      setError(
        e instanceof ApiError ? `Erreur ${e.status}` : "Erreur réseau",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-slate-400">Chargement…</p>;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
      {/* Form */}
      <div className="space-y-5">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {success && (
          <div className="rounded-lg border border-teal-300 bg-teal-50 px-4 py-3 text-sm text-teal-700">
            Paramètres enregistrés.
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="agency-name">Nom de l&apos;agence</Label>
          <Input
            id="agency-name"
            value={settings.agency_name}
            onChange={(e) => update("agency_name", e.target.value)}
            placeholder="Agence Dupont Architectes"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="agency-address">Adresse</Label>
          <Input
            id="agency-address"
            value={settings.address ?? ""}
            onChange={(e) => update("address", e.target.value)}
            placeholder="12 rue de la Paix, 75001 Paris"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="agency-email">Email</Label>
            <Input
              id="agency-email"
              type="email"
              value={settings.contact_email}
              onChange={(e) => update("contact_email", e.target.value)}
              placeholder="contact@agence.fr"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="agency-phone">Téléphone</Label>
            <Input
              id="agency-phone"
              type="tel"
              value={settings.phone ?? ""}
              onChange={(e) => update("phone", e.target.value)}
              placeholder="01 23 45 67 89"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="architecte-ordre">N° d&apos;ordre architecte</Label>
          <Input
            id="architecte-ordre"
            value={settings.architecte_ordre ?? ""}
            onChange={(e) => update("architecte_ordre", e.target.value)}
            placeholder="S-12345"
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="brand-color">Couleur principale (hex)</Label>
          <div className="flex gap-2 items-center">
            <input
              type="color"
              value={settings.brand_primary_color}
              onChange={(e) => update("brand_primary_color", e.target.value)}
              className="h-9 w-14 cursor-pointer rounded border border-slate-300 p-1"
            />
            <Input
              id="brand-color"
              value={settings.brand_primary_color}
              onChange={(e) => update("brand_primary_color", e.target.value)}
              placeholder="#0d9488"
              className="font-mono flex-1"
            />
          </div>
        </div>

        <Separator />

        {/* Logo upload */}
        <div className="space-y-2">
          <Label>Logo de l&apos;agence</Label>
          <div
            onDrop={handleDrop}
            onDragOver={(e) => e.preventDefault()}
            onClick={() => fileInputRef.current?.click()}
            className="flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center hover:border-teal-400 hover:bg-teal-50 transition-colors"
          >
            {settings.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={settings.logo_url}
                alt="Logo agence"
                className="max-h-16 max-w-[200px] object-contain"
              />
            ) : (
              <>
                <Upload className="h-8 w-8 text-slate-400 mb-2" />
                <p className="text-sm text-slate-500">
                  Glissez un fichier ou cliquez pour sélectionner
                </p>
                <p className="text-xs text-slate-400 mt-1">PNG, JPG, SVG — max 2 Mo</p>
              </>
            )}
            {uploadingLogo && (
              <p className="mt-2 text-sm text-teal-600">Téléversement…</p>
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />
        </div>

        <Button
          onClick={handleSave}
          disabled={saving}
          className="w-full bg-teal-600 hover:bg-teal-700 text-white"
        >
          {saving ? "Enregistrement…" : "Enregistrer les paramètres"}
        </Button>
      </div>

      {/* Preview */}
      <div className="space-y-3">
        <p className="text-sm font-medium text-slate-700">Aperçu cartouche</p>
        <div className="rounded-xl border-2 bg-white shadow-sm overflow-hidden"
          style={{ borderColor: settings.brand_primary_color }}>
          {/* Header bar */}
          <div
            className="px-4 py-2 text-white text-xs font-semibold flex items-center justify-between"
            style={{ backgroundColor: settings.brand_primary_color }}
          >
            <span>DOSSIER DE PERMIS DE CONSTRUIRE</span>
            <span>ArchiClaude</span>
          </div>

          {/* Footer area */}
          <div className="px-4 py-4 flex items-start gap-4">
            {settings.logo_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={settings.logo_url}
                alt="Logo"
                className="h-12 w-12 object-contain shrink-0"
              />
            ) : (
              <div
                className="h-12 w-12 rounded flex items-center justify-center text-white text-xs font-bold shrink-0"
                style={{ backgroundColor: settings.brand_primary_color }}
              >
                {settings.agency_name.slice(0, 2).toUpperCase() || "AG"}
              </div>
            )}

            <div className="text-xs text-slate-700 space-y-0.5">
              <p className="font-semibold text-sm">
                {settings.agency_name || "Nom de l'agence"}
              </p>
              {settings.address && <p>{settings.address}</p>}
              {settings.contact_email && <p>{settings.contact_email}</p>}
              {settings.phone && <p>{settings.phone}</p>}
              {settings.architecte_ordre && (
                <p className="text-slate-500">Ordre: {settings.architecte_ordre}</p>
              )}
            </div>
          </div>

          <div
            className="h-1 w-full"
            style={{ backgroundColor: settings.brand_primary_color }}
          />
        </div>
        <p className="text-xs text-slate-400">
          Aperçu du pied de page du rapport PDF.
        </p>
      </div>
    </div>
  );
}
