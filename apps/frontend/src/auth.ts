import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";
import Credentials from "next-auth/providers/credentials";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [
    Google({
      clientId: process.env.GOOGLE_OAUTH_CLIENT_ID!,
      clientSecret: process.env.GOOGLE_OAUTH_CLIENT_SECRET!,
    }),
    MicrosoftEntraID({
      clientId: process.env.MICROSOFT_OAUTH_CLIENT_ID!,
      clientSecret: process.env.MICROSOFT_OAUTH_CLIENT_SECRET!,
    }),
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Mot de passe", type: "password" },
      },
      async authorize(credentials) {
        const res = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: credentials?.email,
            password: credentials?.password,
          }),
        });
        if (!res.ok) return null;
        const data = await res.json();
        return {
          id: data.user.id,
          email: data.user.email,
          name: data.user.full_name,
          accessToken: data.access_token,
          workspaceId: data.default_workspace_id,
        } as any;
      },
    }),
  ],
  session: { strategy: "jwt" },
  callbacks: {
    async signIn({ user, account }) {
      if (account && (account.provider === "google" || account.provider === "microsoft-entra-id")) {
        const providerName = account.provider === "microsoft-entra-id" ? "microsoft" : "google";
        const res = await fetch(`${BACKEND_URL}/api/v1/auth/oauth/callback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: providerName,
            email: user.email,
            name: user.name,
            provider_user_id: account.providerAccountId,
          }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        (user as any).accessToken = data.access_token;
        (user as any).workspaceId = data.default_workspace_id;
      }
      return true;
    },
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as any).accessToken;
        token.workspaceId = (user as any).workspaceId;
      }
      return token;
    },
    async session({ session, token }) {
      (session as any).accessToken = token.accessToken;
      (session as any).workspaceId = token.workspaceId;
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});
