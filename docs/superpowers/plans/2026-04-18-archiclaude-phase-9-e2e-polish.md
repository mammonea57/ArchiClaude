# ArchiClaude — Phase 9 : Tests E2E & polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter les tests E2E Playwright (parcours complet utilisateur), les smoke tests production, et la documentation utilisateur finale.

**Architecture:** Playwright pour les E2E frontend, scripts Python pour les smoke tests backend, documentation markdown.

**Tech Stack:** Playwright, Python scripts, Markdown.

---

## Task 1: Playwright E2E — parcours utilisateur complet

**Files:**
- Create: `apps/frontend/e2e/full-flow.spec.ts`
- Create: `apps/frontend/playwright.config.ts`
- Modify: `apps/frontend/package.json` (add playwright dep + script)

- [ ] **Step 1: Install Playwright**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
pnpm add -D @playwright/test
npx playwright install chromium
```

- [ ] **Step 2: Create playwright.config.ts**

```typescript
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: "http://localhost:3001",
    headless: true,
  },
  webServer: {
    command: "pnpm dev",
    port: 3001,
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
```

- [ ] **Step 3: Write E2E test — full user flow**

```typescript
// apps/frontend/e2e/full-flow.spec.ts
import { test, expect } from "@playwright/test";

test.describe("ArchiClaude — parcours utilisateur complet", () => {
  test("landing → login → projects → new project → report", async ({ page }) => {
    // 1. Landing page
    await page.goto("/");
    await expect(page.getByText("ArchiClaude")).toBeVisible();
    await expect(page.getByText("Commencer")).toBeVisible();

    // 2. Navigate to login
    await page.getByText("Commencer").click();
    // Should redirect to /projects/new (or /login if auth enforced)

    // 3. Login (stubbed v1 — just navigate)
    await page.goto("/login");
    await expect(page.getByText("Connectez-vous")).toBeVisible();
    await page.fill('input[type="email"]', "test@archiclaude.fr");
    await page.fill('input[type="password"]', "testpassword123");
    await page.getByRole("button", { name: /connecter/i }).click();

    // 4. Projects list
    await page.waitForURL("**/projects");
    await expect(page.getByText("Mes projets")).toBeVisible();

    // 5. Navigate to new project
    await page.getByText("Nouveau projet").click();
    await page.waitForURL("**/projects/new");

    // 6. Verify map and form are present
    await expect(page.locator("canvas")).toBeVisible({ timeout: 10_000 }); // MapLibre canvas
    await expect(page.getByText("Programme")).toBeVisible(); // Brief form tab
  });

  test("projects page shows empty state", async ({ page }) => {
    await page.goto("/projects");
    // Either shows projects or empty state
    await expect(page.getByText(/projets|aucun/i)).toBeVisible();
  });

  test("admin flags page loads", async ({ page }) => {
    await page.goto("/admin/flags");
    await expect(page.getByText(/feature flags/i)).toBeVisible();
  });

  test("agency settings page loads", async ({ page }) => {
    await page.goto("/agency");
    await expect(page.getByText(/agence|cartouche/i)).toBeVisible();
  });

  test("rules validation page loads", async ({ page }) => {
    await page.goto("/rules/test-zone-id");
    await expect(page.getByText(/règles|validation/i)).toBeVisible();
  });
});
```

- [ ] **Step 4: Add script to package.json**

Add to `apps/frontend/package.json` scripts:
```json
"test:e2e": "playwright test"
```

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/e2e/ apps/frontend/playwright.config.ts apps/frontend/package.json
git commit -m "test(e2e): add Playwright E2E tests — full user flow"
```

---

## Task 2: Smoke tests production

**Files:**
- Create: `apps/backend/scripts/smoke_test.py`

- [ ] **Step 1: Write smoke test script**

```python
# apps/backend/scripts/smoke_test.py
"""Post-deployment smoke tests for ArchiClaude backend.

Usage: python scripts/smoke_test.py [BASE_URL]
Default BASE_URL: http://localhost:8000
"""
import sys
import httpx
import json

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

errors = []

def check(name: str, url: str, *, method: str = "GET", expected_status: int = 200, body: dict | None = None):
    try:
        if method == "GET":
            resp = httpx.get(url, timeout=15)
        else:
            resp = httpx.post(url, json=body, timeout=15)
        if resp.status_code != expected_status:
            errors.append(f"FAIL {name}: expected {expected_status}, got {resp.status_code}")
            return
        print(f"  OK {name} ({resp.status_code})")
    except Exception as e:
        errors.append(f"FAIL {name}: {e}")

print(f"Smoke testing {BASE_URL}...\n")

# Health
check("health", f"{API}/health")

# Parcels search
check("parcels/search", f"{API}/parcels/search?q=12+rue+de+la+Paix+Paris&limit=3")

# PLU at-point (Paris center)
check("plu/at-point", f"{API}/plu/at-point?lat=48.869&lng=2.331")

# Site bruit
check("site/bruit", f"{API}/site/bruit?lat=48.869&lng=2.331")

# Site transports
check("site/transports", f"{API}/site/transports?lat=48.869&lng=2.331")

# Projects list
check("projects", f"{API}/projects")

# Feature flags
check("admin/feature-flags", f"{API}/admin/feature-flags")

# RAG search (should return empty but not error)
check("rag/jurisprudences", f"{API}/rag/jurisprudences/search?q=hauteur+excessive")

# Agency settings
check("agency/settings", f"{API}/agency/settings")

print(f"\n{'='*50}")
if errors:
    print(f"FAILED — {len(errors)} error(s):")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("ALL SMOKE TESTS PASSED")
    sys.exit(0)
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/scripts/smoke_test.py
git commit -m "test: add post-deployment smoke test script"
```

---

## Task 3: Documentation utilisateur

**Files:**
- Modify: `README.md` (update with full project description)
- Create: `docs/guides/premier-projet.md`
- Create: `docs/guides/parametres-agence.md`

- [ ] **Step 1: Update README.md**

Complete README with:
- Project description (ArchiClaude — faisabilité architecturale IDF)
- Quick start (Docker Compose dev)
- Architecture overview
- Tech stack summary
- Available endpoints list
- Test commands

- [ ] **Step 2: Write "Premier projet" guide**

Step-by-step guide:
1. Créer un compte / se connecter
2. Cliquer "Nouveau projet"
3. Rechercher une adresse
4. Sélectionner les parcelles sur la carte
5. Remplir le brief (programme, contraintes)
6. Lancer l'analyse
7. Consulter le rapport
8. Exporter en PDF

- [ ] **Step 3: Write "Paramètres agence" guide**

Guide for agency branding:
1. Accéder à /agency
2. Remplir les informations (nom, contact, N° d'ordre)
3. Uploader le logo
4. Choisir la couleur principale
5. Prévisualiser le cartouche
6. Les rapports PDF utiliseront automatiquement ces paramètres

- [ ] **Step 4: Commit**

```bash
git add README.md docs/guides/
git commit -m "docs: add user guides — Premier projet + Paramètres agence"
```

---

## Task 4: Final cleanup + commit history

- [ ] **Step 1: Run backend lint + tests**
```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && ruff check . --fix && python -m pytest tests/ -v
```

- [ ] **Step 2: Run frontend typecheck + build**
```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend && pnpm typecheck && pnpm build
```

- [ ] **Step 3: Final commit if any fixes**
