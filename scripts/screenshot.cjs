// Capture the rendered plans page tab for visual verification.
// Usage: node screenshot.js <project_id> <tab>
//   tab ∈ { masse, niveaux, coupes, facades, axo, tableaux, situation, photomontages, ombres, pc4 }
// Outputs: /tmp/archiclaude-<tab>.png
const { chromium } = require("playwright");

(async () => {
const [, , projectId, tab = "masse"] = process.argv;
if (!projectId) {
  console.error("Usage: node screenshot.js <project_id> <tab>");
  process.exit(1);
}

const url = `http://localhost:3010/projects/${projectId}/plans?tab=${tab}`;
const out = `/tmp/archiclaude-${tab}.png`;

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(1500); // let SVG draw + images load
await page.screenshot({ path: out, fullPage: true });
await browser.close();
console.log(`saved ${out}`);
})();
