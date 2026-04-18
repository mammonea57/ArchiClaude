import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: { baseURL: "http://localhost:3001", headless: true },
  webServer: {
    command: "pnpm dev",
    port: 3001,
    reuseExistingServer: true,
    timeout: 30_000,
  },
});
