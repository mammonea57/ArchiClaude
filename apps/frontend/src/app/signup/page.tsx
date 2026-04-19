"use client";
import { useState } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${base}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password, full_name: fullName }),
      });
      if (!res.ok) {
        setError("Impossible de créer le compte (email déjà utilisé ?)");
        setLoading(false);
        return;
      }
      const signInRes = await signIn("credentials", {
        email, password, redirect: false,
      });
      if (signInRes?.error) {
        setError("Inscription OK, échec de la connexion auto — connectez-vous");
        setLoading(false);
        router.push("/login");
      } else {
        router.push("/projects");
      }
    } catch {
      setError("Erreur réseau");
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md bg-white border border-slate-200 rounded-2xl shadow-sm p-8">
        <h1 className="font-display text-2xl font-bold text-slate-900 mb-6 text-center">
          Créer un compte ArchiClaude
        </h1>

        <div className="space-y-2 mb-6">
          <Button onClick={() => signIn("google", { callbackUrl: "/projects" })} variant="outline" className="w-full">
            Continuer avec Google
          </Button>
          <Button onClick={() => signIn("microsoft-entra-id", { callbackUrl: "/projects" })} variant="outline" className="w-full">
            Continuer avec Microsoft
          </Button>
        </div>

        <div className="flex items-center gap-2 my-4">
          <div className="h-px bg-slate-200 flex-1" />
          <span className="text-xs text-slate-400">ou</span>
          <div className="h-px bg-slate-200 flex-1" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <Label htmlFor="fullName" className="text-sm">Nom complet</Label>
            <Input id="fullName" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="email" className="text-sm">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="password" className="text-sm">Mot de passe (min. 10 caractères)</Label>
            <Input id="password" type="password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Button
            type="submit" disabled={loading}
            className="w-full bg-teal-600 text-white hover:bg-teal-700"
          >
            {loading ? "Création..." : "Créer mon compte"}
          </Button>
        </form>

        <p className="text-sm text-slate-500 text-center mt-4">
          Déjà un compte ? <Link href="/login" className="text-teal-700 font-medium">Se connecter</Link>
        </p>
      </div>
    </div>
  );
}
