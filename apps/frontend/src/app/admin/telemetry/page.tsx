import { TelemetryPanel } from "@/components/admin/TelemetryPanel";

export default function TelemetryPage() {
  return (
    <section>
      <h2 className="text-xl font-serif mb-2">Télémétrie — corrections PLU</h2>
      <p className="text-sm text-slate-500 mb-6">
        Statistiques sur les champs les plus souvent corrigés par les utilisateurs
        et les zones PLU les moins fiables.
      </p>
      <TelemetryPanel />
    </section>
  );
}
