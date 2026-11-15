const { expect, test } = require("@playwright/test");
const { readFile } = require("node:fs/promises");
const { resolve, extname, sep } = require("node:path");

const staged = resolve(__dirname, "../../dist/hosting");
const source = resolve(__dirname, "../../mockup");
const publicOrigin = "https://viewer.example";
const localOrigin = "http://127.0.0.1:8765";
const targets = [
  ["barnard", "barnards_star", "Barnard's Star"],
  ["epsindib", "epsilon_indi_b", "Epsilon Indi B"],
  ["wise0855", "wise_0855_0714", /^WISE (?:0855−0714|J085510\.83-071442\.5)$/],
  ["rwaur", "rw_aurigae", "RW Aurigae"],
  ["rdra", "r_draconis", "R Draconis"],
];
const contentTypes = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".webp": "image/webp",
};

async function serve(page, origin, root, overrides = {}) {
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (overrides[url.pathname]) return overrides[url.pathname](route, url);
    const path = resolve(root, "." + (url.pathname === "/" ? "/index.html" : url.pathname));
    if (!path.startsWith(root + sep)) return route.fulfill({ status: 404 });
    try {
      const body = await readFile(path);
      return route.fulfill({ contentType: contentTypes[extname(path)], body });
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      return route.fulfill({ status: 404 });
    }
  });
  await page.goto(origin);
  return requests;
}

async function pickTarget(page, key) {
  await expect(page.locator("#search-body")).toBeVisible();
  const select = page.locator("select#object");
  if (await select.count()) {
    await select.selectOption(key);
    await page.locator("#search-form button[type=submit]").click();
  } else {
    const chip = page.locator(`[data-object="${key}"]`);
    await chip.click();
  }
}

async function searchCoordinates(page) {
  await expect(page.locator("#search-body")).toBeVisible();
  await page.locator("#ra").fill("0");
  await page.locator("#dec").fill("0");
  await page.locator("#search-form button[type=submit]").click();
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 360, height: 800 }]) {
  test(`HTTPS viewer opens all five deployed benchmarks at ${viewport.width} px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const requests = await serve(page, publicOrigin, staged);
    const manifest = JSON.parse(await readFile(resolve(staged, "benchmark-manifest.json")));
    for (const [key, id, name] of targets) {
      await pickTarget(page, key);
      await expect(page.locator("#viewer-modal")).toBeVisible();
      await expect(page.locator("#modal-title")).toHaveText(name);
      await expect(page.locator("#viewer")).toBeVisible();
      await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth))
        .toBeGreaterThan(0);
      expect(requests).toContain(`${publicOrigin}/${manifest.bundles[id]}`);
      await page.locator("#modal-close").click();
    }
    await searchCoordinates(page);
    await expect(page.locator("#modal-empty-msg")).toContainText("Only the five prepared benchmark targets");
    expect(requests.every((url) => !url.startsWith("http:"))).toBeTruthy();
    expect(requests.some((url) => new URL(url).pathname.startsWith("/api/"))).toBeFalsy();
    expect(requests.some((url) => new URL(url).pathname.startsWith("/data/"))).toBeFalsy();
  });
}

test("a missing production release reports failure without an ingestion or legacy fallback", async ({ page }) => {
  const requests = await serve(page, publicOrigin, staged, {
    "/benchmark-manifest.json": (route) => route.fulfill({ status: 404 }),
  });
  await pickTarget(page, "barnard");
  await expect(page.locator("#modal-empty-msg")).toHaveText("The SPHEREx frames could not be loaded. Please try again later.");
  expect(requests.some((url) => /\/(api|data)\//.test(new URL(url).pathname))).toBeFalsy();
});

test("a loopback checkout falls back to the legacy Barnard frames when the local bundle is missing", async ({ page }) => {
  const requests = await serve(page, localOrigin, source, {
    "/data/barnards_star/bundle.json": (route) => route.fulfill({ status: 404 }),
  });
  await pickTarget(page, "barnard");
  await expect(page.locator("#viewer")).toBeVisible();
  await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth))
    .toBeGreaterThan(0);
  expect(requests).toContain(`${localOrigin}/data/barnard/frames.json`);
  expect(requests.some((url) => new URL(url).pathname.startsWith("/api/"))).toBeFalsy();
});

test("explicit local API use distinguishes a pending request, empty data and upstream failure", async ({ page }) => {
  let apiStatus = 400;
  let unblock;
  let began;
  const started = new Promise((resolve) => { began = resolve; });
  const pending = new Promise((resolve) => { unblock = resolve; });
  await serve(page, localOrigin, source, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: "" } }),
    "/api/v1/blink": async (route, url) => {
      expect(Object.fromEntries(url.searchParams)).toEqual({ ra: "0", dec: "0", size_arcsec: "180" });
      began();
      await pending;
      return route.fulfill({
        status: apiStatus,
        json: { detail: apiStatus === 400 ? "No SPHEREx Level 2b cutouts found for target." : "Upstream failed." },
      });
    },
  });
  await searchCoordinates(page);
  await started;
  await expect(page.locator("#modal-empty-msg")).toHaveText("Loading SPHEREx frames…");
  unblock();
  await expect(page.locator("#modal-empty-msg")).toContainText("No SPHEREx observations cover this position");
  await page.locator("#modal-close").click();

  apiStatus = 502;
  await searchCoordinates(page);
  await expect(page.locator("#modal-empty-msg")).toContainText("The SPHEREx frames could not be loaded");
});

// Name lookup. The page asks SIMBAD through Sesame at Harvard; here its answers are canned, so the
// suite stays offline. The XML has the fields the page reads, as Sesame returned them for Vega.
const sesame = "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/**";
const sesameAnswer = (body) => (route) => route.fulfill({
  contentType: "text/xml",
  body: `<?xml version="1.0" encoding="UTF-8"?><Sesame><Target option="S">${body}</Target></Sesame>`,
});
const vega = `<name>Vega</name><Resolver name="Sc=Simbad (CDS, via client/server)">
  <jradeg>279.23473479</jradeg><jdedeg>38.78368896</jdedeg>
  <pm><pmRA>200.94</pmRA><pmDE>286.23</pmDE></pm><oname>* alf Lyr</oname></Resolver>`;

async function searchName(page, name) {
  await expect(page.locator("#search-body")).toBeVisible();
  await page.locator("#name").fill(name);
  await page.locator("#search-form button[type=submit]").click();
}

test("the name of a test object opens its benchmark without asking the name service", async ({ page }) => {
  const requests = await serve(page, publicOrigin, staged);
  await searchName(page, "barnard's star");
  await expect(page.locator("#viewer-modal")).toBeVisible();
  await expect(page.locator("#modal-title")).toHaveText("Barnard's Star");
  await expect(page.locator("#viewer")).toBeVisible();
  await expect(page.locator("select#object")).toHaveValue("barnard");
  expect(requests.some((url) => url.includes("nph-sesame"))).toBeFalsy();
});

test("any other name is looked up in SIMBAD and the sky travels to where the object is today", async ({ page }) => {
  const requests = await serve(page, publicOrigin, staged);
  await page.route(sesame, sesameAnswer(vega));
  await page.locator("select#object").selectOption("barnard");
  await searchName(page, "Vega");
  await expect(page.locator("#viewer-modal")).toBeVisible();
  await expect(page.locator("#modal-title")).toHaveText("Vega");
  await expect(page.locator("#modal-coords")).toContainText("SIMBAD: * alf Lyr");
  await expect(page.locator("#modal-empty-msg")).toContainText("Only the five prepared benchmark targets");
  // Typing a name drops the chosen test object, and the trip writes the position found.
  await expect(page.locator("select#object")).toHaveValue("");
  await expect(page.locator("#ra")).toHaveValue(/^279\.23/);
  await expect(page.locator("#dec")).toHaveValue(/^\+38\.78/);
  expect(requests).toContain("https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-ox/S?Vega");
  expect(requests.every((url) => !url.startsWith("http:"))).toBeTruthy();
});

test("an unknown name and a silent name service are explained next to the field", async ({ page }) => {
  await serve(page, publicOrigin, staged);
  await page.route(sesame, sesameAnswer("<name>Qwertyuiopzz</name><INFO> *** Nothing found *** </INFO>"));
  await searchName(page, "Qwertyuiopzz");
  await expect(page.locator("#name-err")).toContainText("did not find “Qwertyuiopzz”");
  await expect(page.locator("#name")).toHaveAttribute("aria-invalid", "true");
  await expect(page.locator("#viewer-modal")).toBeHidden();

  await page.unroute(sesame); // back to the suite's default: every other origin is unreachable
  await searchName(page, "Vega");
  await expect(page.locator("#name-err")).toContainText("The name service (SIMBAD at Harvard) is not responding");
  await expect(page.locator("#viewer-modal")).toBeHidden();
});

test("typing a position clears the name, and choosing a test object clears both", async ({ page }) => {
  await serve(page, publicOrigin, staged);
  await expect(page.locator("#search-body")).toBeVisible();
  await page.locator("#name").fill("Vega");
  await page.locator("#ra").fill("10");
  await expect(page.locator("#name")).toHaveValue("");
  await page.locator("#name").fill("Vega");
  await expect(page.locator("#ra")).toHaveValue("");
  await page.locator("select#object").selectOption("rdra");
  await expect(page.locator("#name")).toHaveValue("");
  await expect(page.locator("#ra")).toHaveValue(/^248\.1/);
});
