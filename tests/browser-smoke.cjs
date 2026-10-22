// Run against the real server: DEMO_URL=http://127.0.0.1:8765 npm run test:browser
const {chromium} = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.BROWSER_CHANNEL ? {channel: process.env.BROWSER_CHANNEL} : {})});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1100}, acceptDownloads: true});
    const page = await context.newPage();
    const errors = [];
    const external = [];
    page.on("pageerror", error => errors.push(error.message));
    const base = process.env.DEMO_URL || "http://127.0.0.1:8765";
    const origin = new URL(base).origin;
    await page.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.origin !== origin) {
        external.push(url.origin); return route.abort();
      }
      return route.continue();
    });
    async function ready(text) {
      await page.waitForFunction(expected => !document.getElementById("analyze").disabled && document.getElementById("status").textContent.includes(expected), text);
    }
    async function scenario(id, status) {
      await page.locator(`input[value="${id}"]`).check();
      assert.equal(await page.locator("#download").isDisabled(), true);
      await page.locator("#analyze").click(); await ready(status);
    }
    await page.goto(base + "/sample.html");
    await ready("Znaleziono objazd");
    assert.match(await page.locator("#route-length").innerText(), /1,78 km/);
    assert.match(await page.locator("#blocked-count").innerText(), /4 \/ 22/);
    const dir = path.resolve(__dirname, "../docs/assets"); await fs.mkdir(dir, {recursive: true});
    await page.screenshot({path: path.join(dir, "demo-desktop.png"), fullPage: true});
    const downloadEvent = page.waitForEvent("download"); await page.locator("#download").click();
    const download = await downloadEvent;
    const exported = JSON.parse(await fs.readFile(await download.path(), "utf8"));
    assert.equal(exported.type, "FeatureCollection");
    assert.equal(exported.metadata.data_mode, "sample");
    assert(exported.features.some(item => item.properties.layer === "route"));
    await scenario("clear", "Przejazd jest dostępny");
    assert.equal(await page.locator("#extra-distance").innerText(), "0 m");
    await scenario("cutoff", "Brak przejazdu");
    assert.equal(await page.locator("#route-length").innerText(), "Brak trasy");
    await page.locator("#reset").click(); await ready("Znaleziono objazd");
    await page.locator("#origin").selectOption("center");
    await page.locator("#analyze").click(); await ready("Brak przejazdu");
    await page.locator("#reset").click(); await ready("Znaleziono objazd");
    await page.route("**/api/demo/analyze", route => route.abort());
    await page.locator("#analyze").click(); await ready("Nie udało się wykonać analizy");
    assert.equal(await page.locator("#download").isDisabled(), true);
    await page.unroute("**/api/demo/analyze");
    await page.locator("#reset").click(); await ready("Znaleziono objazd");
    for (const width of [390, 720, 1024, 1440]) {
      await page.setViewportSize({width, height: 844});
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `Horizontal overflow at ${width}px`);
      if (width === 390) {
        await page.screenshot({path: path.join(dir, "demo-mobile.png"), fullPage: true});
        await scenario("cutoff", "Brak przejazdu");
        await page.locator("#reset").click(); await ready("Znaleziono objazd");
      }
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    console.log("Browser PASS: desktop/mobile, detour/clear/cutoff, isolated origin, reset, GeoJSON, backend failure/retry, no external requests or JS errors.");
    await context.close();
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
