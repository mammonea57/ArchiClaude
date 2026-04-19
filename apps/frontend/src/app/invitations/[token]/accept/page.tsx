"use client";
import { use, useState } from "react";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

export default function AcceptInvitationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const { data: session, status } = useSession();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setLoading(true);
    try {
      await apiFetch(`/invitations/${token}/accept`, { method: "POST" });
      router.push("/projects");
    } catch {
      setError("Impossible d'accepter l'invitation (expirée ou déjà utilisée)");
      setLoading(false);
    }
  }

  if (status === "loading") return <div className="p-8">Chargement...</div>;

  if (!session) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="bg-white border border-slate-200 rounded-2xl p-8 max-w-md text-center">
          <h1 className="font-display text-xl font-bold mb-4">Invitation ArchiClaude</h1>
          <p className="text-sm text-slate-600 mb-4">
            Connectez-vous ou créez un compte pour accepter cette invitation.
          </p>
          <div className="flex gap-2 justify-center">
            <Link href={`/login?callbackUrl=${encodeURIComponent(`/invitations/${token}/accept`)}`}>
              <Button variant="outline">Se connecter</Button>
            </Link>
            <Link href={`/signup?callbackUrl=${encodeURIComponent(`/invitations/${token}/accept`)}`}>
              <Button className="bg-teal-600 text-white hover:bg-teal-700">Créer un compte</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white border border-slate-200 rounded-2xl p-8 max-w-md text-center">
        <h1 className="font-display text-xl font-bold mb-2">Rejoindre ce workspace ?</h1>
        <p className="text-sm text-slate-600 mb-6">Vous êtes invité(e) à rejoindre un workspace sur ArchiClaude.</p>
        {error && <p className="text-sm text-red-600 mb-3">{error}</p>}
        <div className="flex gap-2 justify-center">
          <Button variant="outline" onClick={() => router.push("/projects")}>Décliner</Button>
          <Button onClick={accept} disabled={loading} className="bg-teal-600 text-white hover:bg-teal-700">
            {loading ? "..." : "Accepter"}
          </Button>
        </div>
      </div>
    </div>
  );
}
