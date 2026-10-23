// Viewport-only screenshot (what the phone shows without scrolling).
// Usage: node scripts/screenshot-top.mjs <url> <out.png> [light|dark]
import { chromium } from "@playwright/test";

const [url, out, scheme = "light"] = process.argv.slice(2);
const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, colorScheme: scheme, locale: "de-AT" });
page.on("pageerror", (e) => console.error("pageerror:", e.message));
await page.goto(url);
await page.waitForTimeout(1000);
await page.screenshot({ path: out });
await browser.close();
