const { expect, test } = require("@playwright/test");
const { readFile } = require("node:fs/promises");
const { resolve, extname, sep } = require("node:path");

const staged = resolve(__dirname, "../../dist/hosting");
const source = resolve(__dirname, "../../mockup");
const publicOrigin = "https://viewer.example";
const localOrigin = "http://127.0.0.1:8765";
const png1x1 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=";
const targets = [
  ["barnard", "barnards_star", "Barnard's Star", { ra: 269.4485, dec: 4.7394 }],
  ["epsindib", "epsilon_indi_b", "Epsilon Indi B", { ra: 331.0765, dec: -56.7938 }],
  ["wise0855", "wise_0855_0714", "WISE 0855−0714", { ra: 133.76, dec: -7.2422 }],
  ["rwaur", "rw_aurigae", "RW Aurigae", { ra: 76.9565, dec: 30.4014 }],
  ["rdra", "r_draconis", "R Draconis", { ra: 248.1674, dec: 66.7550 }],
];
const contentTypes = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".png": "image/png",
  ".webp": "image/webp",
};

function makeBundle({
  targetId,
  name,
  ra,
  dec,
  px0 = 15.0,
  py0 = 15.0,
  px1 = 15.0,
  py1 = 15.0,
  mx0 = 15.0,
  my0 = 15.0,
  mx1 = 15.0,
  my1 = 15.0,
  days = 150,
}) {
  return {
    schema_version: "1.0.0",
    target: {
      target_id: targetId,
      name,
      category: targetId.startsWith("coord_") ? "custom" : "benchmark",
      ra_deg: ra,
      dec_deg: dec,
      ref_epoch_jyear: 2016.0,
      cutout_size_arcsec: 180.0,
      collections: ["spherex_dr1", "spherex_qr3"],
    },
    grid: {
      center_ra_deg: ra,
      center_dec_deg: dec,
      pixel_scale_arcsec: 6.15,
      width_px: 31,
      height_px: 31,
      orientation: "North-up, East-left (ICRS TAN)",
    },
    total_frames: 2,
    available_bands: [2],
    frames_chronological: [
      {
        frame_id: `${targetId}_1`,
        collection: "spherex_dr1",
        detector_band: 2,
        mjd_avg: 60800.0,
        obs_time_iso: "2025-05-05T00:00:00Z",
        sps_epa_deg: 0.0,
        wavelength_um: 1.5,
        bandwidth_um: 0.05,
        predicted_pixel_x: px0,
        predicted_pixel_y: py0,
        measured_centroid_x: mx0,
        measured_centroid_y: my0,
        centroid_offset_arcsec: 0.14,
        is_saturated_core: false,
        png_base64: png1x1,
      },
      {
        frame_id: `${targetId}_2`,
        collection: "spherex_qr3",
        detector_band: 2,
        mjd_avg: 60800.0 + days,
        obs_time_iso: "2025-10-02T00:00:00Z",
        sps_epa_deg: 180.0,
        wavelength_um: 1.52,
        bandwidth_um: 0.05,
        predicted_pixel_x: px1,
        predicted_pixel_y: py1,
        measured_centroid_x: mx1,
        measured_centroid_y: my1,
        centroid_offset_arcsec: 0.14,
        is_saturated_core: false,
        png_base64: png1x1,
      },
    ],
    frames_by_band: {},
    difference_maps: [],
    scientific_warnings: ["Test warning"],
    citations: ["SPHEREx DR1/QR3 (NASA/IPAC IRSA)"],
  };
}

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

async function searchCoordinates(page, ra = "0", dec = "0") {
  await expect(page.locator("#search-body")).toBeVisible();
  await page.locator("#ra").fill(ra);
  await page.locator("#dec").fill(dec);
  await page.locator("#search-form button[type=submit]").click();
}

test("the optional grid brightens the celestial axes and the desktop readout reports a known sky position", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await serve(page, publicOrigin, staged);
  const grid = page.getByRole("button", { name: "Coordinate grid" });
  const readout = page.locator("#pointer-coords");
  await expect(grid).toBeEnabled();
  await expect(grid).toHaveAttribute("aria-pressed", "false");
  await expect(readout).toBeHidden();

  await page.mouse.move(720, 450);
  await expect(readout).toHaveText("Pointer: RA 266.4000°, Dec −20.0000°");
  // Use the existing sky-to-screen calculation to locate Barnard's catalog position.
  const barnard = await page.evaluate(() => window.skyPrototype.project(269.4485, 4.7394));
  await page.mouse.move(barnard.x, barnard.y);
  await expect(readout).toHaveText(/^Pointer: RA 269\.448\d°, Dec \+4\.739\d°$/);
  const beforeZoom = await readout.textContent();
  await page.mouse.wheel(0, -160);
  await expect(readout).not.toHaveText(beforeZoom);
  await expect(readout).toContainText("Pointer: RA");
  await page.mouse.move(720, 32);
  await expect(readout).toBeHidden();

  // Sample the actual WebGL output at the RA 0° / Dec 0° intersection and a point away from
  // any grid line. The GPU buffer must be read in the same task as the draw.
  await expect.poll(() => page.evaluate(() => window.skyPrototype.state.textures.visible?.width)).toBe(4096);
  const sample = () => page.evaluate(() => {
    const { state, project, redraw } = window.skyPrototype;
    Object.assign(state, { ra: 0, dec: 0 });
    redraw();
    const gl = state.gl;
    return [[0, 0], [12, 7]].map(([ra, dec]) => {
      const point = project(ra, dec), rgb = new Uint8Array(4);
      gl.readPixels(Math.floor(point.x), gl.drawingBufferHeight - 1 - Math.floor(point.y),
        1, 1, gl.RGBA, gl.UNSIGNED_BYTE, rgb);
      return [...rgb];
    });
  });
  const off = await sample();
  await grid.focus();
  await grid.press("Space");
  await expect(grid).toHaveAttribute("aria-pressed", "true");
  const on = await sample();
  expect(on[0][2]).toBeGreaterThan(off[0][2] + 35);
  expect(on[1]).toEqual(off[1]);
  await grid.click();
  await expect(grid).toHaveAttribute("aria-pressed", "false");
  expect(await sample()).toEqual(off);
});

test.describe("touch sky coordinates", () => {
  test.use({ viewport: { width: 360, height: 800 }, hasTouch: true, isMobile: true, deviceScaleFactor: 3 });

  test("show the primary finger's position while dragging and keep the last touch after release", async ({ page, context }) => {
    await serve(page, publicOrigin, staged);
    await expect(page.getByRole("button", { name: "Coordinate grid" })).toBeEnabled();
    await expect(page.locator(".sky-readout")).toBeHidden();
    const readout = page.locator("#pointer-coords");
    await expect(readout).toBeHidden();
    const session = await context.newCDPSession(page);
    const touch = (type, ...touchPoints) => session.send("Input.dispatchTouchEvent", { type, touchPoints });
    await touch("touchStart", { x: 180, y: 400 });
    await expect(readout).toHaveText("Touch: RA 266.4000°, Dec −20.0000°");
    await touch("touchMove", { x: 224, y: 422 });
    await expect(readout).not.toHaveText("Touch: RA 266.4000°, Dec −20.0000°");
    const coords = (await readout.textContent()).replace("Touch:", "Last touch:");
    await touch("touchEnd");
    await expect(readout).toHaveText(coords);
    await page.getByRole("button", { name: "Zoom in" }).tap();
    await expect(readout).toHaveText(coords);
  });
});

for (const viewport of [{ width: 1440, height: 900 }, { width: 360, height: 800 }]) {
  test(`HTTPS viewer opens all five benchmarks and coordinates via async IRSA jobs at ${viewport.width} px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const byId = Object.fromEntries(targets.map(([, id, name, coords]) => [id, makeBundle({ targetId: id, name, ...coords })]));
    const jobBodies = [];
    const requests = await serve(page, publicOrigin, staged, {
      "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
      "/api/v1/jobs": async (route) => {
        expect(route.request().method()).toBe("POST");
        const body = route.request().postDataJSON();
        jobBodies.push(body);
        const bundle = body.query
          ? byId[body.query]
          : makeBundle({ targetId: "coord_0d0_p0d0", name: "Your position", ra: body.ra, dec: body.dec });
        return route.fulfill({
          status: 200,
          json: { job_id: `job-${jobBodies.length}`, status: "succeeded", result: bundle },
        });
      },
    });

    for (const [key, id, name] of targets) {
      await pickTarget(page, key);
      await expect(page.locator("#viewer-modal")).toBeVisible();
      await expect(page.locator("#modal-title")).toHaveText(name);
      await expect(page.locator("#viewer")).toBeVisible();
      await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth))
        .toBeGreaterThan(0);
      expect(jobBodies.at(-1)).toEqual({ query: id, size_arcsec: 180, max_frames: 12 });
      await page.locator("#modal-close").click();
    }

    await searchCoordinates(page, "0", "0");
    await expect(page.locator("#viewer")).toBeVisible();
    expect(jobBodies.at(-1)).toEqual({ ra: 0, dec: 0, size_arcsec: 180, max_frames: 12 });
    expect(requests.every((url) => !url.startsWith("http:"))).toBeTruthy();
    expect(requests.some((url) => /\/(data|releases)\//.test(new URL(url).pathname))).toBeFalsy();
    expect(requests.some((url) => new URL(url).pathname === "/benchmark-manifest.json")).toBeFalsy();
  });
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 360, height: 800 }]) {
  test(`minimize keeps the frames and reopens them without a new job at ${viewport.width} px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const bundle = makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 });
    let jobs = 0;
    await serve(page, publicOrigin, staged, {
      "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
      "/api/v1/jobs": (route) => {
        jobs += 1;
        return route.fulfill({ status: 200, json: { job_id: `job-${jobs}`, status: "succeeded", result: bundle } });
      },
    });

    await pickTarget(page, "barnard");
    await expect(page.locator("#viewer")).toBeVisible();
    // The dialog fills the screen, without a horizontal scroll
    const box = await page.locator("#viewer-modal").boundingBox();
    expect(Math.round(box.width)).toBe(viewport.width);
    expect(await page.locator("#viewer-modal").evaluate((d) => d.scrollWidth <= d.clientWidth)).toBeTruthy();
    // No Band 6 in this series: it opens on the longest band with two frames, and says its range
    await expect(page.locator("#band-select option:checked")).toHaveText("Band 2 · 1.10–1.62 µm · 2 frames");
    await expect(page.locator("#band-spectrum")).toContainText("1.10–1.62 µm");
    await page.locator("#next").click();
    await expect(page.locator("#frame-count")).toHaveText("Frame 2 / 2");

    await page.locator("#modal-minimize").click();
    await expect(page.locator("#viewer-modal")).toBeHidden();
    const restore = page.locator("#viewer-restore");
    await expect(restore).toBeVisible();
    await expect(restore).toContainText("Barnard's Star");
    await restore.click();
    await expect(page.locator("#viewer")).toBeVisible();
    await expect(page.locator("#frame-count")).toHaveText("Frame 2 / 2");

    // Escape minimizes too, and searching the same object reopens it with no new job
    await page.keyboard.press("Escape");
    await expect(page.locator("#viewer-modal")).toBeHidden();
    await page.locator("#search-toggle").click();
    await pickTarget(page, "barnard");
    await expect(page.locator("#viewer")).toBeVisible();
    expect(jobs).toBe(1);

    // Close forgets: the pill goes, and the next search loads the series again (from the browser's
    // own bundle cache here, so still one job)
    await page.evaluate(() => { window.__kept = window.viewerState.bundle; });
    await page.locator("#modal-close").click();
    await expect(restore).toBeHidden();
    await pickTarget(page, "barnard");
    await expect(page.locator("#viewer")).toBeVisible();
    await expect.poll(() => page.evaluate(() => Boolean(window.viewerState.bundle) && window.viewerState.bundle !== window.__kept))
      .toBeTruthy();
    await expect(page.locator("#frame-count")).toHaveText("Frame 1 / 2");
  });
}

test("the guided tour explains the six bands with their ranges", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const bundle = makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 });
  await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => route.fulfill({ status: 200, json: { job_id: "job-1", status: "succeeded", result: bundle } }),
  });
  await pickTarget(page, "barnard");
  await expect(page.locator("#viewer")).toBeVisible();
  await page.locator("#modal-tour-open").click();
  await page.locator("#tour-next").click();
  await page.locator("#tour-next").click();
  await expect(page.locator("#tour-title")).toHaveText("Spectral Band Filter");
  const rows = page.locator(".band-table tbody tr");
  await expect(rows).toHaveCount(6);
  await expect(rows.nth(5)).toContainText("4.42–5.00 µm");
  await expect(rows.nth(5)).toHaveClass(/is-default/);
  await expect(page.locator(".band-table .spec-seg")).toHaveCount(6);
});

test("a slow benchmark search keeps the loading scene in sync with the server", async ({ page }) => {
  let phase = "queued";
  const bundle = makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 });
  await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => route.fulfill({ json: { status: "queued", job_id: "benchmark" } }),
    "/api/v1/jobs/benchmark": (route) => route.fulfill({ json: { status: phase, job_id: "benchmark" } }),
    "/api/v1/jobs/benchmark/result": (route) => route.fulfill({ json: bundle }),
  });

  await pickTarget(page, "barnard");
  const loading = page.locator("#modal-loading");
  await expect(loading).toBeVisible();
  await expect(loading).toHaveAttribute("data-step", "1");
  phase = "running";
  await expect(loading).toHaveAttribute("data-step", "2");
  phase = "succeeded";
  await expect(page.locator("#viewer")).toBeVisible();
  await expect(loading).toBeHidden();
});

test("exact coordinates reuse rendered frames after reload until the browser cache expires", async ({ page }) => {
  const jobs = [];
  await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => {
      const { ra, dec } = route.request().postDataJSON();
      jobs.push(ra);
      return route.fulfill({ json: {
        status: "succeeded",
        result: makeBundle({ targetId: "coord_test", name: `Position ${ra}`, ra, dec }),
      } });
    },
  });

  async function showPosition(ra) {
    await searchCoordinates(page, String(ra), "0");
    await expect(page.locator("#modal-title")).toHaveText(`Position ${ra}`);
    await expect(page.locator("#viewer")).toBeVisible();
    await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
    await page.locator("#modal-close").click();
  }

  await showPosition(0);
  await page.reload();
  await showPosition(0);
  expect(jobs).toEqual([0]);

  await showPosition(1);
  expect(jobs).toEqual([0, 1]);

  await page.clock.setFixedTime(new Date(Date.now() + 61 * 60 * 1000));
  await showPosition(0);
  expect(jobs).toEqual([0, 1, 0]);
});

test("browser storage evicts an older bundle before exceeding its byte budget", async ({ page }) => {
  const jobs = [];
  await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => {
      const { ra, dec } = route.request().postDataJSON();
      jobs.push(ra);
      const bundle = makeBundle({ targetId: "coord_test", name: "Position", ra, dec });
      bundle.scientific_warnings = ["x".repeat(13 * 1024 * 1024)];
      return route.fulfill({ json: { status: "succeeded", result: bundle } });
    },
  });
  const load = (ra) => page.evaluate(async (ra) => {
    const { status } = await window.viewerData.load({ ra, dec: 0 }, new AbortController().signal);
    return status;
  }, ra);
  // The viewer writes in the background. Wait for each transaction to settle before loading again.
  const cachedPositions = () => page.evaluate(() => new Promise((resolve, reject) => {
    const open = indexedDB.open("bortle-cero-blink", 1);
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const db = open.result;
      const keys = db.transaction("bundles").objectStore("bundles").getAllKeys();
      keys.onerror = () => reject(keys.error);
      keys.onsuccess = () => resolve(keys.result.map((key) => JSON.parse(key)[2].ra));
      db.close();
    };
  }));

  expect(await load(0)).toBe("ready");
  await expect.poll(cachedPositions).toEqual([0]);
  expect(await load(1)).toBe("ready");
  await expect.poll(cachedPositions).toEqual([1]);
  expect(await load(1)).toBe("ready");
  expect(await load(0)).toBe("ready");
  expect(jobs).toEqual([0, 1, 0]);
});

test("disabled browser storage still allows live ingestion", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "indexedDB", {
      get: () => { throw new DOMException("Storage disabled", "SecurityError"); },
    });
  });
  await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => route.fulfill({ json: {
      status: "succeeded",
      result: makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 }),
    } }),
  });
  await pickTarget(page, "barnard");
  await expect(page.locator("#viewer")).toBeVisible();
});

test("liveQueries disabled reports unavailability without calling ingestion API or local data", async ({ page }) => {
  const requests = await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: false, apiBaseUrl: "" } }),
  });
  await pickTarget(page, "barnard");
  await expect(page.locator("#modal-empty-msg")).toContainText("Live SPHEREx IRSA queries are currently disabled");
  expect(requests.some((url) => /\/(api|data|releases)\//.test(new URL(url).pathname))).toBeFalsy();
});

test("legacy sync API fallback loads benchmark and distinguishes pending, empty and upstream failure", async ({ page }) => {
  let apiStatus = 400;
  let unblock;
  let began;
  const started = new Promise((resolve) => { began = resolve; });
  const pending = new Promise((resolve) => { unblock = resolve; });
  const requests = await serve(page, localOrigin, source, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: "" } }),
    "/api/v1/blink/barnards_star": (route) => route.fulfill({
      json: makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 }),
    }),
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

  await pickTarget(page, "barnard");
  await expect(page.locator("#viewer")).toBeVisible();
  await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth))
    .toBeGreaterThan(0);
  expect(requests).toContain(`${localOrigin}/api/v1/blink/barnards_star`);
  await page.locator("#modal-close").click();

  await searchCoordinates(page);
  await started;
  await expect(page.locator("#modal-empty-msg")).toHaveText("Loading SPHEREx frames…");
  unblock();
  await expect(page.locator("#modal-empty-msg")).toContainText("No SPHEREx observations cover this position");
  await page.locator("#modal-close").click();

  apiStatus = 502;
  await searchCoordinates(page);
  await expect(page.locator("#modal-empty-msg")).toContainText("The SPHEREx frames could not be loaded");
  expect(requests.some((url) => /\/(data|releases)\//.test(new URL(url).pathname))).toBeFalsy();
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

test("the name of a test object routes to the live benchmark API without asking the name service", async ({ page }) => {
  const requests = await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => route.fulfill({
      json: {
        job_id: "job-barnard",
        status: "succeeded",
        result: makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 }),
      },
    }),
  });
  await searchName(page, "barnard's star");
  await expect(page.locator("#viewer-modal")).toBeVisible();
  await expect(page.locator("#modal-title")).toHaveText("Barnard's Star");
  await expect(page.locator("#viewer")).toBeVisible();
  await expect(page.locator("select#object")).toHaveValue("barnard");
  expect(requests.some((url) => url.includes("nph-sesame"))).toBeFalsy();
  expect(requests.some((url) => /\/(data|releases)\//.test(new URL(url).pathname))).toBeFalsy();
});

test("any other name is looked up in SIMBAD, submits async job, polls status, and renders returned bundle", async ({ page }) => {
  let pollCount = 0;
  let postedBody = null;
  const requests = await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": async (route) => {
      expect(route.request().method()).toBe("POST");
      postedBody = route.request().postDataJSON();
      return route.fulfill({ status: 202, json: { job_id: "job-vega-1", status: "queued" } });
    },
    "/api/v1/jobs/job-vega-1": async (route) => {
      expect(route.request().method()).toBe("GET");
      pollCount += 1;
      return route.fulfill({
        json: { job_id: "job-vega-1", status: pollCount === 1 ? "running" : "succeeded" },
      });
    },
    "/api/v1/jobs/job-vega-1/result": async (route) => {
      expect(route.request().method()).toBe("GET");
      return route.fulfill({
        json: makeBundle({
          targetId: "coord_279d23_p38d78",
          name: "Vega",
          ra: 279.2347,
          dec: 38.7837,
          px0: 15.0,
          py0: 15.0,
          px1: 15.01,
          py1: 14.99,
          mx0: 15.02,
          my0: 15.01,
          mx1: 15.03,
          my1: 15.0,
          days: 150,
        }),
      });
    },
  });
  await page.route(sesame, sesameAnswer(vega));
  await page.locator("select#object").selectOption("barnard");
  await searchName(page, "Vega");

  await expect(page.locator("#viewer-modal")).toBeVisible();
  await expect(page.locator("#viewer")).toBeVisible();
  await expect(page.locator("#obj-name")).toHaveText("Vega");
  await expect(page.locator("#summary")).toContainText("Position is stationary within the 6.15″ pixel scale over 150 days");
  await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth))
    .toBeGreaterThan(0);
  // Typing a name drops the chosen test object, and the trip writes the position found.
  await expect(page.locator("select#object")).toHaveValue("");
  await expect(page.locator("#ra")).toHaveValue(/^279\.23/);
  await expect(page.locator("#dec")).toHaveValue(/^\+38\.78/);

  expect(postedBody).toMatchObject({ size_arcsec: 180, max_frames: 12 });
  expect(postedBody.ra).toBeCloseTo(279.23, 1);
  expect(postedBody.dec).toBeCloseTo(38.78, 1);
  expect(pollCount).toBe(2);
  expect(requests).toContain("https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-ox/S?Vega");
  expect(requests).toContain(`${publicOrigin}/api/v1/jobs`);
  expect(requests).toContain(`${publicOrigin}/api/v1/jobs/job-vega-1`);
  expect(requests).toContain(`${publicOrigin}/api/v1/jobs/job-vega-1/result`);
  expect(requests.every((url) => !url.startsWith("http:"))).toBeTruthy();
  expect(requests.some((url) => /\/(data|releases)\//.test(new URL(url).pathname))).toBeFalsy();
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

test("catalog aliases resolve benchmarks offline and Sesame falls back to SNV when S has no coords", async ({ page }) => {
  const requests = await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => {
      const body = route.request().postDataJSON();
      const bundle = body.query === "barnards_star"
        ? makeBundle({ targetId: "barnards_star", name: "Barnard's Star", ra: 269.4485, dec: 4.7394 })
        : makeBundle({ targetId: "coord_279d23_p38d78", name: "Vega", ra: body.ra, dec: body.dec });
      return route.fulfill({ json: { job_id: "job-alias", status: "succeeded", result: bundle } });
    },
  });
  await searchName(page, "GJ 699");
  await expect(page.locator("#viewer-modal")).toBeVisible();
  await expect(page.locator("#modal-title")).toHaveText("Barnard's Star");
  await expect(page.locator("#viewer")).toBeVisible();
  expect(requests.some((url) => url.includes("nph-sesame"))).toBeFalsy();
  await page.locator("#modal-close").click();

  await page.route(sesame, (route) => {
    const url = route.request().url();
    if (url.includes("/-ox/S?")) {
      return route.fulfill({
        contentType: "text/xml",
        body: `<?xml version="1.0" encoding="UTF-8"?><Sesame><Target option="S"><name>Vega</name></Target></Sesame>`,
      });
    }
    return sesameAnswer(vega)(route);
  });
  await searchName(page, "Vega");
  await expect(page.locator("#viewer-modal")).toBeVisible();
  await expect(page.locator("#modal-title")).toHaveText("Vega");
  expect(requests).toContain("https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-ox/S?Vega");
  expect(requests).toContain("https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-ox/SNV?Vega");
  expect(requests.some((url) => /\/(data|releases)\//.test(new URL(url).pathname))).toBeFalsy();
});

test("summary reports 8-direction compass bearing and stationary threshold for RW Aurigae and WISE 0855", async ({ page }) => {
  const bundles = {
    rw_aurigae: makeBundle({
      targetId: "rw_aurigae",
      name: "RW Aurigae",
      ra: 76.9565,
      dec: 30.4014,
      px0: 15.0,
      py0: 15.0,
      px1: 15.0,
      py1: 15.0,
      mx0: 14.87,
      my0: 15.0,
      mx1: 14.76,
      my1: 14.94,
      days: 15,
    }),
    wise_0855_0714: makeBundle({
      targetId: "wise_0855_0714",
      name: "WISE 0855−0714",
      ra: 133.76,
      dec: -7.2422,
      px0: 14.45,
      py0: 15.02,
      px1: 15.80,
      py1: 14.90,
      mx0: null,
      my0: null,
      mx1: null,
      my1: null,
      days: 373,
    }),
  };
  await serve(page, publicOrigin, staged, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: publicOrigin } }),
    "/api/v1/jobs": (route) => {
      const { query } = route.request().postDataJSON();
      return route.fulfill({ json: { job_id: `job-${query}`, status: "succeeded", result: bundles[query] } });
    },
  });

  await pickTarget(page, "rwaur");
  await expect(page.locator("#viewer")).toBeVisible();
  await expect(page.locator("#summary")).toContainText("Position is stationary within the 6.15″ pixel scale");
  await page.locator("#modal-close").click();

  await pickTarget(page, "wise0855");
  await expect(page.locator("#viewer")).toBeVisible();
  await expect(page.locator("#summary")).toContainText("west");
});

// Deep stack (schema 1.1.0): a synthetic block on the two-frame fixture. The real numbers come from
// the engine; these only exercise the switch, the texts and the fallbacks.
const stackPng = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==";
function withStack(bundle, overrides = {}) {
  return {
    ...bundle,
    schema_version: "1.1.0",
    deep_stack: {
      mode: "target_tracked",
      frame_count: 12,
      frame_ids: bundle.frames_chronological.map((f) => f.frame_id),
      detector_bands: [6, 5, 5],
      wavelength_min_um: 3.82,
      wavelength_max_um: 4.98,
      mjd_start: 60800.0,
      mjd_end: 61173.0,
      obs_time_start_iso: "2025-05-05T00:00:00Z",
      obs_time_end_iso: "2026-05-13T00:00:00Z",
      max_tracking_shift_px: 1.9,
      target_pixel_x: 15.0,
      target_pixel_y: 15.0,
      noise_mjy_sr: 0.012,
      single_frame_noise_mjy_sr: 0.037,
      noise_reduction_factor: 3.1,
      peak_snr: 10.24,
      sky_fixed_peak_snr: 6.0,
      detected: true,
      detection_threshold_sigma: 5.0,
      measured_centroid_x: 15.1,
      measured_centroid_y: 14.9,
      centroid_offset_arcsec: 0.83,
      rejected_pixel_count: 3,
      matrix_mjy_sr: [[0.1, null], [null, 0.2]],
      png_base64: stackPng,
      ...overrides,
    },
    deep_stack_skipped_reason: null,
  };
}

for (const viewport of [{ width: 1440, height: 900 }, { width: 360, height: 800 }]) {
  test(`the deep stack switch shows the stack, stays hidden for old bundles and explains a skip at ${viewport.width} px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const base = (id, name, coords) => makeBundle({ targetId: id, name, ...coords });
    const bundles = {
      wise_0855_0714: withStack(base("wise_0855_0714", "WISE 0855−0714", { ra: 133.76, dec: -7.2422 })),
      // Not detected, and following the motion changes nothing: no tracking line; null fields tolerated
      epsilon_indi_b: withStack(base("epsilon_indi_b", "Epsilon Indi B", { ra: 331.0765, dec: -56.7938 }), {
        detected: false, peak_snr: 2.1, sky_fixed_peak_snr: null, centroid_offset_arcsec: null,
        measured_centroid_x: null, measured_centroid_y: null, noise_reduction_factor: null, frame_count: 4,
      }),
      barnards_star: base("barnards_star", "Barnard's Star", { ra: 269.4485, dec: 4.7394 }),
      r_draconis: {
        ...base("r_draconis", "R Draconis", { ra: 248.1674, dec: 66.7550 }),
        schema_version: "1.1.0", deep_stack: null, deep_stack_skipped_reason: "target_saturated",
      },
    };
    await serve(page, localOrigin, source, {
      "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true, apiBaseUrl: "" } }),
      "/api/v1/jobs": (route) => {
        const { query } = route.request().postDataJSON();
        return route.fulfill({ json: { job_id: `job-${query}`, status: "succeeded", result: bundles[query] } });
      },
    });
    const frames = page.getByRole("radio", { name: "Single frames" });
    const stack = page.getByRole("radio", { name: /^Stack/ });

    await pickTarget(page, "wise0855");
    await expect(page.locator("#viewer")).toBeVisible();
    await expect(page.locator("#view-row")).toBeVisible();
    await expect(frames).toHaveAttribute("aria-checked", "true");
    await expect(stack).toHaveText("Stack of 12");
    await expect(page.locator("#frame-count")).toHaveText("Frame 1 / 2");

    await stack.click();
    await expect(stack).toHaveAttribute("aria-checked", "true");
    await expect(page.locator("#frame-img")).toHaveAttribute("src", stackPng);
    await expect.poll(() => page.locator("#frame-img").evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
    await expect(page.locator("#frame-count")).toHaveText("Stack of 12 exposures");
    await expect(page.locator("#m-wave")).toHaveText("3.82–4.98 µm");
    await expect(page.locator("#m-det")).toHaveText("Bands 5–6");
    await expect(page.locator("#m-date")).toHaveText("2025-05-05 → 2026-05-13");
    await expect(page.locator("#st-gaia")).toHaveText("✓ Detected 10.2σ");
    await expect(page.locator("#stack-headline"))
      .toHaveText("Detected in the stack: 10.2σ, 0.8″ from the predicted position.");
    await expect(page.locator("#stack-facts")).toContainText("Noise 3.1× lower than in a single frame");
    await expect(page.locator("#stack-facts")).toContainText("Without following the predicted motion: 6.0σ");
    await expect(page.locator(".stack-caveat")).toBeVisible();
    await expect(page.locator(".panel .result")).toBeHidden();
    for (const id of ["#play", "#prev", "#next", "#speed", "#band-select"]) {
      await expect(page.locator(id)).toBeDisabled();
    }
    await expect(page.locator("#zoom-in")).toBeEnabled();
    // The spectrum legend shows what the stack covers, not the band left in the dimmed select
    await expect(page.locator("#band-spectrum")).toHaveText("Stack · 3.82–4.98 µm");
    const segment = await page.locator("#band-spectrum .spec-seg").evaluate((el) => [el.style.left, el.style.width]);
    expect(parseFloat(segment[0])).toBeCloseTo(((3.82 - 0.75) / 4.25) * 100, 1);
    expect(parseFloat(segment[1])).toBeCloseTo(((4.98 - 3.82) / 4.25) * 100, 1);
    // The prediction ring sits on the stack; there is no path in a target-tracked image
    await expect(page.locator("#overlay .mk-pred")).toHaveCount(1);
    await expect(page.locator("#overlay .mk-traj")).toHaveCount(0);
    // Arrow keys inside the switch change the view, not the frame
    await stack.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(frames).toHaveAttribute("aria-checked", "true");
    await expect(frames).toBeFocused();
    await expect(page.locator("#frame-count")).toHaveText("Frame 1 / 2");
    await expect(page.locator("#play")).toBeEnabled();
    await expect(page.locator(".panel .result")).toBeVisible();
    await expect(page.locator("#band-spectrum")).not.toContainText("Stack");
    await page.keyboard.press("ArrowRight");
    await expect(page.locator("#frame-count")).toHaveText("Stack of 12 exposures");
    await page.locator("#modal-close").click();

    // A new target opens on the single frames again; an honest line when nothing is detected
    await pickTarget(page, "epsindib");
    await expect(page.locator("#modal-title")).toHaveText("Epsilon Indi B");
    await expect(frames).toHaveAttribute("aria-checked", "true");
    await expect(page.locator("#frame-count")).toHaveText("Frame 1 / 2");
    await expect(page.locator("#play")).toBeEnabled();
    await stack.click();
    await expect(page.locator("#st-gaia")).toHaveText("— Not detected, 2.1σ");
    await expect(page.locator("#stack-headline")).toHaveText("Not detected in the stack (peak 2.1σ, below the 5σ threshold).");
    await expect(page.locator("#stack-facts")).not.toContainText("Without following");
    await page.locator("#modal-close").click();

    // Old bundle: no switch at all
    await pickTarget(page, "barnard");
    await expect(page.locator("#modal-title")).toHaveText("Barnard's Star");
    await expect(page.locator("#view-row")).toBeHidden();
    await expect(page.locator("#frame-count")).toHaveText("Frame 1 / 2");
    await page.locator("#modal-close").click();

    // Skipped: the switch is there, disabled, with the reason
    await pickTarget(page, "rdra");
    await expect(page.locator("#modal-title")).toHaveText("R Draconis");
    await expect(page.locator("#view-row")).toBeVisible();
    await expect(stack).toBeDisabled();
    await expect(page.locator("#view-note")).toHaveText(
      "Stack unavailable: the star saturates the detector, so stacking cannot help.");
  });
}

test("transient status and result errors retry the same accepted job", async ({ page }) => {
  let posts = 0;
  let polls = 0;
  let results = 0;
  const bundle = makeBundle({ targetId: "coord_retry", name: "Retry", ra: 10, dec: 20 });
  await serve(page, localOrigin, source, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true } }),
    "/api/v1/jobs": (route) => {
      posts++;
      return route.fulfill({ status: 202, json: { status: "queued", job_id: "retry" } });
    },
    "/api/v1/jobs/retry": (route) => {
      polls++;
      if (polls === 1) return route.fulfill({ status: 404 });
      if (polls === 2) return route.fulfill({ status: 503 });
      return route.fulfill({ json: { status: "succeeded", job_id: "retry" } });
    },
    "/api/v1/jobs/retry/result": (route) => {
      results++;
      return results === 1
        ? route.fulfill({ status: 502 })
        : route.fulfill({ json: bundle });
    },
  });
  const response = await page.evaluate(() => (
    window.viewerData.load({ ra: 10, dec: 20 }, new AbortController().signal)
  ));
  expect(response.status).toBe("ready");
  expect(posts).toBe(1);
  expect(polls).toBe(3);
  expect(results).toBe(2);
});

test("viewer distinguishes queue admission, lost jobs, and archive failure", async ({ page }) => {
  const jobIds = ["lost", "upstream", "empty"];
  let posts = 0;
  let lostPolls = 0;
  await serve(page, localOrigin, source, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true } }),
    "/api/v1/jobs": (route) => {
      if (posts++ === 0) {
        return route.fulfill({ status: 429, headers: { "Retry-After": "27" } });
      }
      return route.fulfill({ status: 202, json: { status: "queued", job_id: jobIds[posts - 2] } });
    },
    "/api/v1/jobs/lost": (route) => {
      lostPolls++;
      return route.fulfill({ status: 404 });
    },
    "/api/v1/jobs/upstream": (route) => route.fulfill({
      json: { status: "failed", error_code: "upstream_unavailable" },
    }),
    "/api/v1/jobs/empty": (route) => route.fulfill({
      json: { status: "failed", error_code: "no_observations" },
    }),
  });
  const search = () => page.evaluate(() => (
    window.viewerData.load({ ra: 21, dec: 22 }, new AbortController().signal)
  ));
  expect(await search()).toEqual({ status: "queue-busy", retryAfter: 27 });
  expect(posts).toBe(1);
  expect(await search()).toEqual({ status: "job-lost" });
  expect(lostPolls).toBe(3);
  expect(await search()).toEqual({ status: "upstream-unavailable" });
  expect(await search()).toEqual({ status: "no-observations" });
  expect(posts).toBe(4);
});

test("viewer stops polling when the overall search deadline expires", async ({ page }) => {
  let polls = 0;
  await page.addInitScript(() => {
    const deadline = new AbortController();
    const timeout = AbortSignal.timeout.bind(AbortSignal);
    AbortSignal.timeout = (delay) => delay === 300000 ? deadline.signal : timeout(delay);
    const fetch = window.fetch.bind(window);
    window.fetch = async (url, options) => {
      const response = await fetch(url, options);
      if (new URL(url, location.href).pathname === "/api/v1/jobs/pending") {
        deadline.abort(new DOMException("Search deadline elapsed", "TimeoutError"));
      }
      return response;
    };
  });
  await serve(page, localOrigin, source, {
    "/viewer-config.json": (route) => route.fulfill({ json: { liveQueries: true } }),
    "/api/v1/jobs": (route) => route.fulfill({
      status: 202, json: { status: "queued", job_id: "pending" },
    }),
    "/api/v1/jobs/pending": (route) => {
      polls++;
      return route.fulfill({ json: { status: "running", job_id: "pending" } });
    },
  });
  const response = await page.evaluate(() => (
    window.viewerData.load({ ra: 10, dec: 20 }, new AbortController().signal)
  ));
  expect(response).toEqual({ status: "search-timeout" });
  expect(polls).toBe(1);
});
