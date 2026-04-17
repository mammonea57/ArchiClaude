import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ArchiClaude",
  description: "Faisabilité architecturale et dossier PC pour promoteurs IDF",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
