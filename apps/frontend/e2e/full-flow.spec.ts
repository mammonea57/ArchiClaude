import { test, expect } from "@playwright/test";

test("landing page loads with ArchiClaude and Commencer", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("text=ArchiClaude").first()).toBeVisible();
  await expect(page.locator("text=Commencer").first()).toBeVisible();
});

test("login page has form fields", async ({ page }) => {
  await page.goto("/login");
  await expect(page.locator('input[type="email"], input[name="email"]').first()).toBeVisible();
  await expect(page.locator('input[type="password"], input[name="password"]').first()).toBeVisible();
});

test("projects page shows Mes projets", async ({ page }) => {
  await page.goto("/projects");
  await expect(page.locator("text=Mes projets").first()).toBeVisible();
});

test("admin flags page loads", async ({ page }) => {
  await page.goto("/admin/flags");
  await expect(page.locator("text=Feature flags").first()).toBeVisible();
});

test("agency settings page loads", async ({ page }) => {
  await page.goto("/agency");
  // Page contains agency branding settings header
  await expect(
    page.getByText(/agence|cartouche|Paramètres/i).first()
  ).toBeVisible();
});
