import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";
import SessionProviderClient from "@/components/SessionProviderClient";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const playfairDisplay = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-playfair",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ArchiClaude",
  description: "Faisabilité architecturale et dossier PC pour promoteurs IDF",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={`${inter.variable} ${playfairDisplay.variable}`}>
      <body className="font-sans">
        <SessionProviderClient>{children}</SessionProviderClient>
      </body>
    </html>
  );
}
