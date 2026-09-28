// Usage: node scripts/screenshot.mjs <baseUrl> <outDir> [route ...]
// Full-page screenshots in iPhone size, light and dark.
import { chromium } from "@playwright/test";

const [base = "http://127.0.0.1:8751", out = ".", ...routes] = process.argv.slice(2);
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: scheme,
    isMobile: true, hasTouch: true, locale: "de-AT",
  });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => console.error("pageerror:", e.message));
  for (const r of routes.length ? routes : [""]) {
    await page.goto(`${base}/#/${r}`);
    await page.waitForTimeout(900);
    const name = `${out}/${(r || "start").replace(/[^a-z0-9]+/gi, "_")}-${scheme}.png`;
    await page.screenshot({ path: name, fullPage: true });
    console.log(name);
  }
  await ctx.close();
}
await browser.close();
