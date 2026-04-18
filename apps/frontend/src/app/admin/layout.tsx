export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen p-8">
      <header className="mb-8 pb-4 border-b">
        <h1 className="font-serif text-3xl">ArchiClaude — Admin</h1>
        <nav className="mt-2 flex gap-4 text-sm text-slate-600">
          <a href="/admin" className="hover:underline">
            Dashboard
          </a>
          <a href="/admin/flags" className="hover:underline">
            Feature flags
          </a>
          <a href="/admin/playground" className="hover:underline">
            Playground
          </a>
          <a href="/admin/telemetry" className="hover:underline">
            Télémétrie
          </a>
        </nav>
      </header>
      {children}
    </div>
  );
}
