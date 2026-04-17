export default function HomePage() {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-2xl text-center space-y-4">
        <h1 className="font-serif text-5xl">ArchiClaude</h1>
        <p className="text-lg text-slate-600">
          Faisabilité architecturale et dossier PC pour promoteurs en Île-de-France.
        </p>
        <p className="text-sm text-slate-500">
          Phase 0 — setup infrastructure. Prochain jalon : sélection de parcelles sur carte.
        </p>
      </div>
    </main>
  );
}
