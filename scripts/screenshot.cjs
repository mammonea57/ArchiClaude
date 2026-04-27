// Capture the rendered plans page tab for visual verification.
// Usage:
//   node screenshot.cjs <project_id> <tab>             # full tab, capped at 1900px
//   node screenshot.cjs <project_id> <tab> <selector>  # crop to one element, full res
//
//   tab ∈ { masse, niveaux, coupes, facades, axo, tableaux, situation, photomontages, ombres, pc4 }
//
// Selector forms:
//   - raw CSS selector, e.g. '[data-coupe=AA]'
//   - shorthand 'AA' or 'BB' on the coupes tab → '[data-coupe=AA|BB]'
//
// Outputs:
//   /tmp/archiclaude-<tab>.png                  (no selector)
//   /tmp/archiclaude-<tab>-<safe-selector>.png  (with selector)
//
// Image dims are capped (longest side ≤ 1900px) so the file stays readable by
// Claude's Read tool, which rejects images > 2000px on either side.
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");

(async () => {
const [, , projectId, tab = "masse", selectorArg] = process.argv;
if (!projectId) {
  console.error("Usage: node screenshot.cjs <project_id> <tab> [selector]");
  process.exit(1);
}

// Resolve shorthand selectors (e.g. "AA" on coupes tab → '[data-coupe=AA]').
let selector = null;
if (selectorArg) {
  if (tab === "coupes" && /^(AA|BB)$/.test(selectorArg)) {
    selector = `[data-coupe=${selectorArg}]`;
  } else if (tab === "facades" && /^(nord|sud|est|ouest)$/.test(selectorArg)) {
    selector = `[data-facade=${selectorArg}]`;
  } else {
    selector = selectorArg;
  }
}

const safeSel = selector ? selector.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "") : null;
const out = safeSel
  ? `/tmp/archiclaude-${tab}-${safeSel}.png`
  : `/tmp/archiclaude-${tab}.png`;

const url = `http://localhost:3010/projects/${projectId}/plans?tab=${tab}`;

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1 });
const page = await ctx.newPage();
await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(1500); // let SVG draw + images load

if (selector) {
  const handle = page.locator(selector).first();
  await handle.waitFor({ state: "visible", timeout: 10000 });
  await handle.screenshot({ path: out });
} else {
  await page.screenshot({ path: out, fullPage: true });
}

await browser.close();

// Hard cap longest side at 1900px (Read tool rejects > 2000px).
try {
  execFileSync("/usr/bin/sips", ["-Z", "1900", out], { stdio: "ignore" });
} catch (e) {
  console.error("sips resize failed:", e.message);
}

console.log(`saved ${out}`);
})();
