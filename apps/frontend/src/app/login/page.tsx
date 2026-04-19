"use client";
import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const res = await signIn("credentials", {
      email, password, redirect: false,
    });
    if (res?.error) {
      setError("Email ou mot de passe incorrect");
      setLoading(false);
    } else {
      router.push("/projects");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-sm p-8">
        <h1 className="font-display text-2xl font-bold text-slate-900 mb-6 text-center">
          Connexion à ArchiClaude
        </h1>

        <div className="space-y-2 mb-6">
          <Button
            onClick={() => signIn("google", { callbackUrl: "/projects" })}
            className="w-full bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
            variant="outline"
          >
            Continuer avec Google
          </Button>
          <Button
            onClick={() => signIn("microsoft-entra-id", { callbackUrl: "/projects" })}
            className="w-full bg-white border border-slate-200 text-slate-700 hover:bg-slate-50"
            variant="outline"
          >
            Continuer avec Microsoft
          </Button>
        </div>

        <div className="flex items-center gap-2 my-4">
          <div className="h-px bg-slate-200 flex-1" />
          <span className="text-xs text-slate-400">ou</span>
          <div className="h-px bg-slate-200 flex-1" />
        </div>

        <form onSubmit={handleCredentials} className="space-y-3">
          <div>
            <Label htmlFor="email" className="text-sm">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="password" className="text-sm">Mot de passe</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button
            type="submit" disabled={loading}
            className="w-full bg-teal-600 text-white hover:bg-teal-700"
          >
            {loading ? "Connexion..." : "Se connecter"}
          </Button>
        </form>

        <p className="text-sm text-slate-500 text-center mt-4">
          Pas encore de compte ? <Link href="/signup" className="text-teal-700 font-medium">Créer un compte</Link>
        </p>
      </div>
    </div>
  );
}
