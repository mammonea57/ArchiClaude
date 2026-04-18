# ArchiClaude — Phase 8 : Frontend Next.js — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le frontend Next.js complet : auth (login/signup), carte MapLibre avec overlays, formulaire brief + création projet, dashboard faisabilité avec KPIs, panneaux site/compliance/analyse architecte, validation règles, versionnage, cartouche agence, pages admin, export PDF — le tout avec le parcours utilisateur canonique bout-en-bout.

**Architecture:** Next.js 16 App Router + React 19. Pages server-side par défaut, `"use client"` pour les composants interactifs (carte, formulaires, charts). API client via `lib/api.ts` existant. shadcn/ui pour les primitives UI. MapLibre GL JS pour la cartographie. Recharts pour les graphiques. Zod pour la validation formulaires. Tailwind v4 + Inter/Playfair Display.

**Tech Stack:** Next.js 16, React 19, TypeScript 5, Tailwind v4, shadcn/ui, MapLibre GL JS, Recharts, Zod, Auth.js (NextAuth v5), react-markdown.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §8 (Frontend)

---

## File Structure (final état Phase 8)

```
apps/frontend/src/
├── app/
│   ├── layout.tsx                           (MODIFY — add Inter + Playfair fonts, Toaster)
│   ├── page.tsx                             (MODIFY — landing page with CTA)
│   ├── globals.css                          (MODIFY — teal palette, typography)
│   ├── login/page.tsx                       (NEW)
│   ├── signup/page.tsx                      (NEW)
│   ├── account/page.tsx                     (NEW)
│   ├── projects/
│   │   ├── page.tsx                         (NEW — project list)
│   │   ├── new/page.tsx                     (NEW — map + brief form)
│   │   └── [id]/
│   │       ├── page.tsx                     (NEW — project dashboard)
│   │       ├── report/page.tsx              (NEW — interactive report)
│   │       ├── versions/page.tsx            (NEW — version timeline)
│   │       └── settings/page.tsx            (NEW — project settings)
│   ├── rules/[zone_id]/page.tsx             (NEW — rule validation)
│   ├── agency/page.tsx                      (NEW — cartouche editor)
│   ├── admin/
│   │   ├── layout.tsx                       (EXISTS)
│   │   ├── flags/page.tsx                   (EXISTS)
│   │   ├── page.tsx                         (NEW — costs dashboard)
│   │   ├── playground/page.tsx              (NEW)
│   │   └── telemetry/page.tsx               (NEW)
├── components/
│   ├── map/
│   │   ├── MapView.tsx                      (NEW — MapLibre GL)
│   │   ├── ParcelOverlay.tsx                (NEW)
│   │   └── ZoneOverlay.tsx                  (NEW)
│   ├── panels/
│   │   ├── RulesPanel.tsx                   (NEW)
│   │   ├── FeasibilityDashboard.tsx         (NEW)
│   │   ├── ComplianceSummary.tsx            (NEW)
│   │   └── ServitudesList.tsx               (NEW)
│   ├── forms/
│   │   ├── ParcelSearch.tsx                 (NEW — BAN autocomplete)
│   │   ├── BriefForm.tsx                    (NEW — programme brief)
│   │   └── RuleValidator.tsx                (NEW)
│   ├── report/
│   │   ├── ArchitectureNoteRenderer.tsx     (NEW — markdown note)
│   │   ├── TypologyChart.tsx                (NEW — Recharts donut)
│   │   ├── ReportExportButton.tsx           (NEW)
│   │   ├── SitePhotosGallery.tsx            (NEW)
│   │   └── DvfChart.tsx                     (NEW)
│   ├── versions/
│   │   ├── VersionTimeline.tsx              (NEW)
│   │   └── VersionCompare.tsx               (NEW)
│   ├── agency/
│   │   └── CartoucheEditor.tsx              (NEW)
│   ├── admin/
│   │   ├── FlagsTable.tsx                   (EXISTS)
│   │   ├── CostsDashboard.tsx              (NEW)
│   │   ├── Playground.tsx                   (NEW)
│   │   └── TelemetryPanel.tsx               (NEW)
│   └── ui/                                  (EXISTS — shadcn components)
├── lib/
│   ├── api.ts                               (EXISTS — extend with new endpoints)
│   ├── hooks/
│   │   ├── useProjects.ts                   (NEW)
│   │   ├── useParcels.ts                    (NEW)
│   │   └── useFeasibility.ts                (NEW)
│   └── types.ts                             (NEW — frontend-specific types)
└── types/generated/                          (EXISTS — auto-generated from backend)
```

---

## Task 1: Dependencies + design system setup

**Files:**
- Modify: `apps/frontend/package.json`
- Modify: `apps/frontend/src/app/layout.tsx`
- Modify: `apps/frontend/src/app/globals.css`
- Add new shadcn/ui components

- [ ] **Step 1: Install new dependencies**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
pnpm add maplibre-gl@^5 react-map-gl@^8 recharts@^2 react-markdown@^9 next-auth@^5 @auth/core
pnpm add -D @types/maplibre-gl
```

- [ ] **Step 2: Add shadcn/ui components needed**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
npx shadcn@latest add tabs card badge input textarea select separator progress avatar dropdown-menu table sheet tooltip
```

- [ ] **Step 3: Update globals.css with ArchiClaude palette**

```css
/* apps/frontend/src/app/globals.css — add ArchiClaude design tokens */
@import "tailwindcss";

:root {
  --primary: 168 80% 31%;        /* teal #0d9488 */
  --primary-foreground: 0 0% 100%;
  --accent-amber: 38 92% 50%;    /* alertes */
  --accent-red: 0 84% 60%;       /* infaisable */
  --accent-green: 142 71% 45%;   /* cohérent */
  --font-display: 'Playfair Display', serif;
  --font-body: 'Inter', sans-serif;
}

body { font-family: var(--font-body); }
h1, h2, h3 { font-family: var(--font-display); }
```

- [ ] **Step 4: Update layout.tsx with fonts + Toaster**

Add Google Fonts (Inter + Playfair Display) via `next/font/google`. Add shadcn Toaster provider.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/
git commit -m "feat(frontend): setup design system — fonts, palette, shadcn components, maplibre"
```

---

## Task 2: Auth pages — login + signup + account

**Files:**
- Create: `apps/frontend/src/app/login/page.tsx`
- Create: `apps/frontend/src/app/signup/page.tsx`
- Create: `apps/frontend/src/app/account/page.tsx`

- [ ] **Step 1: Create login page**

Simple email/password form + Google OAuth button. Uses shadcn Card, Input, Button. For v1 auth is stubbed — actual Auth.js integration deferred to deployment phase.

```tsx
// apps/frontend/src/app/login/page.tsx
"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { useState } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // v1: stub — redirect to projects
    router.push("/projects");
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl text-center">ArchiClaude</CardTitle>
          <p className="text-center text-muted-foreground">Connectez-vous à votre compte</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div><Label htmlFor="email">Email</Label><Input id="email" type="email" value={email} onChange={e => setEmail(e.target.value)} required /></div>
            <div><Label htmlFor="password">Mot de passe</Label><Input id="password" type="password" value={password} onChange={e => setPassword(e.target.value)} required /></div>
            <Button type="submit" className="w-full">Se connecter</Button>
          </form>
          <div className="mt-4 text-center text-sm">
            <a href="/signup" className="text-primary hover:underline">Créer un compte</a>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
```

- [ ] **Step 2: Create signup page** (similar structure)
- [ ] **Step 3: Create account page** (profile display)
- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/app/login/ apps/frontend/src/app/signup/ apps/frontend/src/app/account/
git commit -m "feat(frontend): add auth pages — login, signup, account"
```

---

## Task 3: Landing page + project list

**Files:**
- Modify: `apps/frontend/src/app/page.tsx`
- Create: `apps/frontend/src/app/projects/page.tsx`
- Create: `apps/frontend/src/lib/hooks/useProjects.ts`
- Create: `apps/frontend/src/lib/types.ts`

- [ ] **Step 1: Create types + hook**

```typescript
// apps/frontend/src/lib/types.ts
export interface Project {
  id: string;
  name: string;
  status: "draft" | "analyzed" | "archived";
  created_at: string;
  confidence_score?: number;
}

export interface GeocodingResult {
  label: string; score: number; lat: number; lng: number;
  citycode: string; city: string;
}

export interface Brief {
  destination: string;
  cible_nb_logements?: number;
  mix_typologique: Record<string, number>;
  cible_sdp_m2?: number;
  hauteur_cible_niveaux?: number;
  emprise_cible_pct?: number;
  stationnement_cible_par_logement?: number;
  espaces_verts_pleine_terre_cible_pct?: number;
}
```

```typescript
// apps/frontend/src/lib/hooks/useProjects.ts
"use client";
import { useState, useEffect } from "react";
import { apiFetch } from "@/lib/api";
import type { Project } from "@/lib/types";

export function useProjects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiFetch<Project[]>("/projects")
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  return { projects, loading };
}
```

- [ ] **Step 2: Update landing page**

Hero section with "Commencer" CTA → `/projects/new`. Architecture-focused design.

- [ ] **Step 3: Create project list page**

Table/cards listing all projects with status badge, confidence, date. "Nouveau projet" button.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/
git commit -m "feat(frontend): add landing page and project list"
```

---

## Task 4: MapView + ParcelSearch — carte interactive

**Files:**
- Create: `apps/frontend/src/components/map/MapView.tsx`
- Create: `apps/frontend/src/components/map/ParcelOverlay.tsx`
- Create: `apps/frontend/src/components/map/ZoneOverlay.tsx`
- Create: `apps/frontend/src/components/forms/ParcelSearch.tsx`
- Create: `apps/frontend/src/lib/hooks/useParcels.ts`

- [ ] **Step 1: Create MapView component**

MapLibre GL with IGN orthophoto tile layer, centered on Paris. Handles click events for parcel selection.

```tsx
// apps/frontend/src/components/map/MapView.tsx
"use client";
import { useRef, useEffect, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

interface MapViewProps {
  center?: [number, number]; // [lng, lat]
  zoom?: number;
  onMapClick?: (lngLat: { lng: number; lat: number }) => void;
  children?: React.ReactNode;
}

export function MapView({ center = [2.35, 48.85], zoom = 12, onMapClick }: MapViewProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!mapContainer.current || map.current) return;
    map.current = new maplibregl.Map({
      container: mapContainer.current,
      style: {
        version: 8,
        sources: {
          "ign-ortho": {
            type: "raster",
            tiles: ["https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg"],
            tileSize: 256,
            attribution: "IGN",
          },
        },
        layers: [{ id: "ign-ortho", type: "raster", source: "ign-ortho" }],
      },
      center,
      zoom,
    });

    if (onMapClick) {
      map.current.on("click", (e) => onMapClick({ lng: e.lngLat.lng, lat: e.lngLat.lat }));
    }

    return () => { map.current?.remove(); map.current = null; };
  }, []);

  return <div ref={mapContainer} className="w-full h-full min-h-[500px] rounded-lg" />;
}
```

- [ ] **Step 2: Create ParcelSearch with BAN autocomplete**

```tsx
// apps/frontend/src/components/forms/ParcelSearch.tsx
"use client";
import { useState, useCallback } from "react";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import type { GeocodingResult } from "@/lib/types";

interface ParcelSearchProps {
  onSelect: (result: GeocodingResult) => void;
}

export function ParcelSearch({ onSelect }: ParcelSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeocodingResult[]>([]);
  const [loading, setLoading] = useState(false);

  const search = useCallback(async (q: string) => {
    if (q.length < 3) { setResults([]); return; }
    setLoading(true);
    try {
      const data = await apiFetch<GeocodingResult[]>(`/parcels/search?q=${encodeURIComponent(q)}&limit=5`);
      setResults(data);
    } catch { setResults([]); }
    finally { setLoading(false); }
  }, []);

  // Debounce 250ms
  const [timer, setTimer] = useState<NodeJS.Timeout>();
  const handleChange = (val: string) => {
    setQuery(val);
    if (timer) clearTimeout(timer);
    setTimer(setTimeout(() => search(val), 250));
  };

  return (
    <div className="relative">
      <Input placeholder="Rechercher une adresse..." value={query} onChange={e => handleChange(e.target.value)} />
      {results.length > 0 && (
        <div className="absolute top-full left-0 right-0 bg-white border rounded-md shadow-lg z-50 mt-1">
          {results.map((r, i) => (
            <button key={i} className="w-full text-left px-3 py-2 hover:bg-gray-100 text-sm"
              onClick={() => { onSelect(r); setQuery(r.label); setResults([]); }}>
              {r.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create overlay components** (ParcelOverlay, ZoneOverlay — GeoJSON layer rendering on map)

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/map/ apps/frontend/src/components/forms/ParcelSearch.tsx apps/frontend/src/lib/hooks/useParcels.ts
git commit -m "feat(frontend): add MapView with IGN ortho + ParcelSearch autocomplete"
```

---

## Task 5: BriefForm + project creation page

**Files:**
- Create: `apps/frontend/src/components/forms/BriefForm.tsx`
- Create: `apps/frontend/src/app/projects/new/page.tsx`

- [ ] **Step 1: Create BriefForm with Zod validation**

Tabbed form: Programme (destination, nb logements, mix typologique, SDP cible) / Contraintes (hauteur R+X, emprise %) / Espaces verts (pleine terre %) / Stationnement (places/logement). Zod schema validates before submission.

- [ ] **Step 2: Create /projects/new page**

Split layout: left = MapView + ParcelSearch, right = BriefForm. "Analyser" button → POST /projects + POST /projects/{id}/analyze.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/forms/BriefForm.tsx apps/frontend/src/app/projects/new/
git commit -m "feat(frontend): add BriefForm with Zod validation + project creation page"
```

---

## Task 6: FeasibilityDashboard + report page

**Files:**
- Create: `apps/frontend/src/components/panels/FeasibilityDashboard.tsx`
- Create: `apps/frontend/src/components/panels/RulesPanel.tsx`
- Create: `apps/frontend/src/components/panels/ComplianceSummary.tsx`
- Create: `apps/frontend/src/components/panels/ServitudesList.tsx`
- Create: `apps/frontend/src/components/report/TypologyChart.tsx`
- Create: `apps/frontend/src/components/report/ArchitectureNoteRenderer.tsx`
- Create: `apps/frontend/src/components/report/ReportExportButton.tsx`
- Create: `apps/frontend/src/app/projects/[id]/page.tsx`
- Create: `apps/frontend/src/app/projects/[id]/report/page.tsx`
- Create: `apps/frontend/src/lib/hooks/useFeasibility.ts`

- [ ] **Step 1: Create KPI dashboard component**

```tsx
// apps/frontend/src/components/panels/FeasibilityDashboard.tsx
"use client";
import { Card, CardContent } from "@/components/ui/card";

interface KPI { label: string; value: string | number; unit?: string; color?: string; }

export function FeasibilityDashboard({ kpis }: { kpis: KPI[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {kpis.map((kpi, i) => (
        <Card key={i}>
          <CardContent className="pt-6 text-center">
            <div className="text-3xl font-bold" style={{ color: kpi.color || "#0d9488" }}>
              {kpi.value}{kpi.unit && <span className="text-lg ml-1">{kpi.unit}</span>}
            </div>
            <div className="text-sm text-muted-foreground mt-1">{kpi.label}</div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create TypologyChart (Recharts donut)**
- [ ] **Step 3: Create ArchitectureNoteRenderer (react-markdown)**
- [ ] **Step 4: Create RulesPanel, ComplianceSummary, ServitudesList**
- [ ] **Step 5: Create ReportExportButton**
- [ ] **Step 6: Create project dashboard page + report page**
- [ ] **Step 7: Commit**

```bash
git add apps/frontend/src/components/panels/ apps/frontend/src/components/report/ apps/frontend/src/app/projects/\[id\]/ apps/frontend/src/lib/hooks/
git commit -m "feat(frontend): add feasibility dashboard, report page with KPIs + analysis renderer"
```

---

## Task 7: Site data components

**Files:**
- Create: `apps/frontend/src/components/report/SitePhotosGallery.tsx`
- Create: `apps/frontend/src/components/report/DvfChart.tsx`

- [ ] **Step 1: Create SitePhotosGallery**

Grid of Mapillary/Street View photos with compass direction labels.

- [ ] **Step 2: Create DvfChart (Recharts bar)**

Price per m² by typology and year.

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/report/
git commit -m "feat(frontend): add site photos gallery + DVF price chart"
```

---

## Task 8: RuleValidator + rules page

**Files:**
- Create: `apps/frontend/src/components/forms/RuleValidator.tsx`
- Create: `apps/frontend/src/app/rules/[zone_id]/page.tsx`

- [ ] **Step 1: Create RuleValidator**

Side-by-side view: extracted values (left) vs editable form (right). Low-confidence fields highlighted amber. Submit button → POST /rules/{id}/feedback.

- [ ] **Step 2: Create rules page**

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/forms/RuleValidator.tsx apps/frontend/src/app/rules/
git commit -m "feat(frontend): add RuleValidator with feedback submission"
```

---

## Task 9: Versioning + agency pages

**Files:**
- Create: `apps/frontend/src/components/versions/VersionTimeline.tsx`
- Create: `apps/frontend/src/components/versions/VersionCompare.tsx`
- Create: `apps/frontend/src/components/agency/CartoucheEditor.tsx`
- Create: `apps/frontend/src/app/projects/[id]/versions/page.tsx`
- Create: `apps/frontend/src/app/projects/[id]/settings/page.tsx`
- Create: `apps/frontend/src/app/agency/page.tsx`

- [ ] **Step 1: Create version components**

VersionTimeline: horizontal timeline V1→V2→V3 with KPI diff indicators.
VersionCompare: split-screen diff between two selected versions.

- [ ] **Step 2: Create CartoucheEditor**

Form with agency name, logo upload, contact info, preview cartouche.

- [ ] **Step 3: Create pages**

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/versions/ apps/frontend/src/components/agency/ apps/frontend/src/app/projects/\[id\]/versions/ apps/frontend/src/app/projects/\[id\]/settings/ apps/frontend/src/app/agency/
git commit -m "feat(frontend): add version timeline/compare + agency cartouche editor"
```

---

## Task 10: Admin pages

**Files:**
- Create: `apps/frontend/src/components/admin/CostsDashboard.tsx`
- Create: `apps/frontend/src/components/admin/Playground.tsx`
- Create: `apps/frontend/src/components/admin/TelemetryPanel.tsx`
- Modify: `apps/frontend/src/app/admin/page.tsx`
- Create: `apps/frontend/src/app/admin/playground/page.tsx`
- Create: `apps/frontend/src/app/admin/telemetry/page.tsx`

- [ ] **Step 1: Create admin components**

CostsDashboard: Recharts line chart of Anthropic costs by day.
Playground: form to test PLU extraction on arbitrary commune/zone.
TelemetryPanel: histograms of most-corrected fields.

- [ ] **Step 2: Create/update admin pages**

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/admin/ apps/frontend/src/app/admin/
git commit -m "feat(frontend): add admin pages — costs, playground, telemetry"
```

---

## Task 11: Vérification finale — typecheck + lint + build

- [ ] **Step 1: Run TypeScript typecheck**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend && pnpm typecheck
```

- [ ] **Step 2: Run ESLint**

```bash
pnpm lint
```

- [ ] **Step 3: Run build**

```bash
pnpm build
```

- [ ] **Step 4: Fix any issues + commit cleanup**
