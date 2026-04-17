"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

// Placeholder profile — auth stubbed for v1
const PLACEHOLDER_USER = {
  name: "Anthony Mammone",
  email: "mammonea57@gmail.com",
};

export default function AccountPage() {
  const router = useRouter();

  function handleLogout() {
    router.push("/login");
  }

  return (
    <main className="min-h-screen bg-slate-50">
      {/* Navigation */}
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <Link href="/projects" className="font-display text-xl font-semibold text-slate-900">
            ArchiClaude
          </Link>
          <Link href="/projects" className="text-sm text-slate-500 hover:text-slate-700 transition-colors">
            Mes projets
          </Link>
        </div>
      </nav>

      <div className="max-w-4xl mx-auto px-6 py-12">
        <h1 className="font-display text-3xl font-bold text-slate-900 mb-8">Mon compte</h1>

        <div className="grid gap-6 max-w-lg">
          {/* Profile card */}
          <Card className="border border-slate-200 shadow-none">
            <CardHeader className="pb-4">
              <CardTitle className="text-base text-slate-900">Profil</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">
                  Nom
                </p>
                <p className="text-sm text-slate-800 font-medium">{PLACEHOLDER_USER.name}</p>
              </div>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-400 mb-1">
                  E-mail
                </p>
                <p className="text-sm text-slate-800">{PLACEHOLDER_USER.email}</p>
              </div>
            </CardContent>
          </Card>

          {/* Danger zone */}
          <Card className="border border-slate-200 shadow-none">
            <CardHeader className="pb-4">
              <CardTitle className="text-base text-slate-900">Session</CardTitle>
            </CardHeader>
            <CardContent>
              <Button
                variant="outline"
                className="border-slate-200 text-slate-700 hover:bg-slate-50 hover:text-slate-900"
                onClick={handleLogout}
              >
                Se déconnecter
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </main>
  );
}
