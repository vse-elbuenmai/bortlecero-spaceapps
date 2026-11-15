// Sky sphere prototype: a spinning sky (Aladin Lite + sky maps served by IRSA), a RA/Dec search
// that travels there, and the blink viewer opening on arrival at Barnard's Star.
// A test for the team to judge, not a decision on stack or architecture (see mockup/README.md).
//
// Aladin Lite is pinned to 3.8.2 (the version IRSA's own HiPS pages use) and loaded from jsDelivr,
// which serves the npm package. CDS's own server is down, so nothing here talks to CDS.
import A from "https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js";

const IRSA_HIPS = "https://irsa.ipac.caltech.edu/data/hips/";
const BACKGROUND_URL = IRSA_HIPS + "CDS/DSS2/color";
const CUBE_URL = IRSA_HIPS + "SPHEREx/spherex_allsky_cube";

// Cube frames used here. Frame index = 17 * (band - 1) + (channel - 1), per the cube's properties.
// 95 is the frame closest to the wavelength of the Barnard blink frames (~4.75 µm).
// The three false-colour frames are placeholders for the team to choose.
const FRAME_MONO = 95;
const FRAMES_RGB = { red: 95, green: 55, blue: 10 };

const FULL_FOV = 180; // widest view of the orthographic (SIN) projection: the sky as a globe
const ARRIVAL_FOV = 1; // degrees
const SPIN_DEG_PER_S = 2;
const BARNARD_RADIUS_DEG = 0.04; // half the side of the prepared frames

// Test objects. Barnard's Star uses the centre of the prepared frames (its 2025–2026 position).
// The others are catalogue positions for epoch 2000 from SIMBAD (Harvard mirror, queried
// 2026-11-14): fast movers have drifted since, and the real tool must propagate them.
const OBJECTS = {
  barnard: { name: "Barnard's Star", prepared: true },
  epsindib: { name: "Epsilon Indi B", ra: 331.04415, dec: -56.78284, epoch2000: true },
  wise0855: { name: "WISE 0855−0714", ra: 133.81891, dec: -7.24705, epoch2000: true },
  rwaur: { name: "RW Aurigae", ra: 76.95653, dec: 30.40144, epoch2000: true },
  rdra: { name: "R Draconis", ra: 248.16761, dec: 66.75498, epoch2000: true },
};

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (id) => document.getElementById(id);
const sky = $("sky"), view = $("sky-view"), viewer = $("viewer"), msg = $("search-msg");

const state = {
  aladin: null, cube: null, layers: {}, mode: "visible", monoOpacity: 1,
  spinning: false, trip: 0, lastFrame: 0,
};
window.skyPrototype = state; // handy in the browser console while the team tries things

const fmtRa = (v) => v.toFixed(4) + "°";
const fmtDec = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(4) + "°";
const mjdToDate = (mjd) => new Date((mjd - 40587) * 86400e3).toISOString().slice(0, 10);

// ---------- coordinates ----------
// Accepts decimal degrees (269.4485, +4.7394) and sexagesimal (17h57m48.5s, 17:57:48.5,
// +04°44′22″, +04 44 22). Sexagesimal RA is in hours unless it is marked with ° or d.
function parseAngle(text, isRa) {
  const s = text.trim().replace(/−/g, "-");
  if (/^[+-]?\d+(\.\d+)?\s*(°|d|deg)?$/i.test(s)) return parseFloat(s);
  const m = s.match(/^([+-])?\s*(\d{1,3})\s*[h°d:\s]\s*(\d{1,2})\s*[m′':\s]\s*(\d{1,2}(?:\.\d+)?)?\s*[s″"]?$/i);
  if (!m || +m[3] >= 60 || +(m[4] || 0) >= 60) return NaN;
  const value = +m[2] + +m[3] / 60 + +(m[4] || 0) / 3600;
  const inHours = isRa && !/[°d]/i.test(s);
  return (m[1] === "-" ? -1 : 1) * value * (inHours ? 15 : 1);
}

function setFieldError(id, text) {
  const input = $(id), err = $(id + "-err");
  input.setAttribute("aria-invalid", String(Boolean(text)));
  err.hidden = !text;
  err.textContent = text ? "⚠ " + text : "";
}

function say(text) {
  msg.hidden = !text;
  msg.textContent = text || "";
}

// ---------- SPHEREx all-sky cube ----------
async function loadCubeProperties() {
  const text = await (await fetch(CUBE_URL + "/properties")).text();
  const p = {};
  for (const line of text.split("\n")) {
    const m = line.match(/^([a-z_0-9]+)\s*=\s*(.*)$/i);
    if (m) p[m[1]] = m[2].trim();
  }
  const light = 299792458;
  return {
    depth: +p.hips_cube_depth,
    fLow: light / +p.em_max,
    fHigh: light / +p.em_min,
    wavelengths: (p.data_cube_crval3_arr || "").split(/\s+/).map(Number),
    from: mjdToDate(+p.t_min),
    to: mjdToDate(+p.t_max),
  };
}

// Aladin Lite shows frame floor((f - fLow) / (fHigh - fLow) * depth) of a cube, so asking for the
// frequency in the middle of that interval selects the frame (recipe from IRSA's HiPS landing page).
const frameFrequency = (frame) =>
  state.cube.fLow + ((frame + 0.5) / state.cube.depth) * (state.cube.fHigh - state.cube.fLow);

// One layer showing one frame of the cube. `setup` runs once the layer is in the view.
function addCubeLayer(tag, frame, setup) {
  const hips = A.imageHiPS(CUBE_URL, {
    name: `SPHEREx ${state.cube.wavelengths[frame]} µm`,
    successCallback: (h) => {
      h.setFrequency({ value: frameFrequency(frame), unit: "Hz" });
      setup(h);
    },
  });
  // WORKAROUND, tied to Aladin Lite 3.8.2: its engine identifies a HiPS by creator_did, so two
  // layers of the same cube would share one frame. Giving each layer its own id keeps them apart.
  // This wraps a private method; re-test it before changing the pinned version.
  const parse = hips._parseProperties;
  hips._parseProperties = function (properties) {
    parse.call(this, properties);
    this.creatorDid += "#" + tag;
  };
  state.layers[tag] = hips;
  state.aladin.setOverlayImageLayer(hips, "spherex-" + tag);
  return hips;
}

function setMode(mode) {
  state.mode = mode;
  const L = state.layers;
  if (mode !== "visible" && !L.red) addCubeLayer("red", FRAME_MONO, () => setMode(state.mode));
  if (mode === "colour" && !L.green) {
    addCubeLayer("green", FRAMES_RGB.green, () => setMode(state.mode));
    addCubeLayer("blue", FRAMES_RGB.blue, () => setMode(state.mode));
  }
  // The red layer doubles as the single-wavelength (grayscale) view.
  if (L.red && L.red.added) {
    L.red.setColormap(mode === "colour" ? "red" : "grayscale");
    L.red.setOpacity(mode === "visible" ? 0 : mode === "colour" ? 1 : state.monoOpacity);
  }
  for (const tag of ["green", "blue"]) {
    if (!L[tag] || !L[tag].added) continue;
    L[tag].setColormap(tag);
    L[tag].setBlendingConfig(true);
    // In 3.8.2 a fully opaque layer is drawn over the ones below even with additive blending on;
    // just under 1 makes the three frames add up.
    L[tag].setOpacity(mode === "colour" ? 0.99 : 0);
  }
  document.querySelectorAll("[data-layer]").forEach((b) => {
    const on = b.dataset.layer === mode;
    b.classList.toggle("is-active", on);
    b.setAttribute("aria-pressed", String(on));
  });
  const c = state.cube, w = (f) => c.wavelengths[f].toFixed(2);
  $("sky-credit").textContent = {
    visible: "Background: DSS2 colour, visible light (STScI/NASA, via IRSA).",
    spherex: `SPHEREx DR1 all-sky average at ${w(FRAME_MONO)} µm, ${c.from} to ${c.to}. Not the dated frames used for blinking.`,
    colour: `SPHEREx DR1 all-sky average, ${c.from} to ${c.to}. False colour: ${w(FRAMES_RGB.red)} µm red, ${w(FRAMES_RGB.green)} µm green, ${w(FRAMES_RGB.blue)} µm blue.`,
  }[mode];
}

// ---------- rotation at rest ----------
function setSpinning(on) {
  state.spinning = on && !reduceMotion;
  const btn = $("spin-toggle");
  btn.setAttribute("aria-pressed", String(state.spinning));
  btn.setAttribute("aria-label", state.spinning ? "Pause rotation" : "Rotate the sky");
  btn.textContent = state.spinning ? "❚❚" : "▶";
  state.lastFrame = 0;
  if (state.spinning) requestAnimationFrame(spinStep);
}

function spinStep(now) {
  if (!state.spinning) return;
  if (state.lastFrame) {
    const [ra, dec] = state.aladin.getRaDec();
    const dt = Math.min(0.5, (now - state.lastFrame) / 1000); // keeps the pace on a slow machine
    state.aladin.gotoRaDec((ra + SPIN_DEG_PER_S * dt) % 360, dec);
  }
  state.lastFrame = now;
  requestAnimationFrame(spinStep);
}

function updateHud() {
  const [ra, dec] = state.aladin.getRaDec();
  const fov = state.aladin.getFov()[0];
  $("sky-coords").textContent =
    `${fmtRa(ra)}, ${fmtDec(dec)} · FOV ${fov >= 10 ? Math.round(fov) : fov.toFixed(1)}°`;
}

// ---------- the trip ----------
function openViewer() {
  sky.classList.add("is-arrived");
  viewer.hidden = false;
  $("how").hidden = false;
  $("back-to-sky").hidden = false;
  document.dispatchEvent(new CustomEvent("viewer:open"));
  viewer.focus({ preventScroll: true });
  viewer.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
}

function closeViewer() {
  document.dispatchEvent(new CustomEvent("viewer:close"));
  viewer.hidden = true;
  $("how").hidden = true;
  $("back-to-sky").hidden = true;
  sky.classList.remove("is-arrived");
}

function arrive(target) {
  if (target.prepared) {
    say("");
    openViewer();
    return;
  }
  say(
    `No prepared frames for ${target.name || "this position"} yet: this prototype only has Barnard's Star. ` +
      "The map shows SPHEREx's all-sky average here." +
      (target.epoch2000 ? " Catalogue position for epoch 2000 (SIMBAD); the object has moved since." : "")
  );
}

function travel(target) {
  const trip = ++state.trip;
  const current = () => trip === state.trip;
  closeViewer();
  setSpinning(false);
  say(`Travelling to ${fmtRa(target.ra)}, ${fmtDec(target.dec)}…`);

  const a = state.aladin;
  if (!a) return arrive(target); // no sky map (see start()): go straight to the result
  if (reduceMotion) {
    a.gotoRaDec(target.ra, target.dec);
    a.setFoV(ARRIVAL_FOV);
    if (state.mode === "visible") setMode("spherex");
    return arrive(target);
  }
  const seconds = 2.5;
  const zoomIn = () => {
    if (!current()) return;
    // The SPHEREx map fades in over the visible sky while zooming in.
    if (state.mode === "visible") {
      const t0 = performance.now();
      state.monoOpacity = 0;
      setMode("spherex");
      const fade = (now) => {
        const k = current() ? Math.min(1, (now - t0) / (seconds * 1000)) : 1;
        state.monoOpacity = k;
        const red = state.layers.red;
        if (red && red.added && state.mode === "spherex") red.setOpacity(k);
        if (k < 1) requestAnimationFrame(fade);
      };
      requestAnimationFrame(fade);
    }
    a.zoomToFoV(ARRIVAL_FOV, seconds, () => current() && arrive(target));
  };
  const rotate = () => current() && a.animateToRaDec(target.ra, target.dec, seconds, zoomIn);
  // Coming from a close-up, pull back first so the rotation reads as a trip across the sky.
  if (a.getFov()[0] < 30) a.zoomToFoV(60, 1.2, rotate);
  else rotate();
}

function backToSky() {
  state.trip++;
  closeViewer();
  say("");
  document.querySelectorAll("[data-object]").forEach((c) => {
    c.classList.remove("is-active");
    c.setAttribute("aria-pressed", "false");
  });
  if (!state.aladin) return;
  setMode("visible");
  if (reduceMotion) state.aladin.setFoV(FULL_FOV);
  else state.aladin.zoomToFoV(FULL_FOV, 2, () => setSpinning(true));
  sky.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
}

// ---------- events ----------
function bindEvents(barnard) {
  OBJECTS.barnard.ra = barnard.ra;
  OBJECTS.barnard.dec = barnard.dec;

  $("search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const ra = parseAngle($("ra").value, true), dec = parseAngle($("dec").value, false);
    const raBad = Number.isNaN(ra) || ra < 0 || ra >= 360;
    const decBad = Number.isNaN(dec) || dec < -90 || dec > 90;
    setFieldError("ra", raBad ? "RA must be between 0° and 360° (or 0h and 24h)" : "");
    setFieldError("dec", decBad ? "Dec must be between −90° and +90°" : "");
    if (raBad || decBad) {
      (raBad ? $("ra") : $("dec")).focus();
      return;
    }
    const sep = Math.hypot((ra - barnard.ra) * Math.cos((dec * Math.PI) / 180), dec - barnard.dec);
    document.querySelectorAll("[data-object]").forEach((c) => {
      const on = c.dataset.object === "barnard" && sep <= BARNARD_RADIUS_DEG;
      c.classList.toggle("is-active", on);
      c.setAttribute("aria-pressed", String(on));
    });
    travel(sep <= BARNARD_RADIUS_DEG ? OBJECTS.barnard : { ra, dec });
  });

  document.querySelectorAll("[data-object]").forEach((chip) =>
    chip.addEventListener("click", () => {
      const target = OBJECTS[chip.dataset.object];
      document.querySelectorAll("[data-object]").forEach((c) => {
        c.classList.toggle("is-active", c === chip);
        c.setAttribute("aria-pressed", String(c === chip));
      });
      $("ra").value = target.ra.toFixed(4);
      $("dec").value = (target.dec >= 0 ? "+" : "") + target.dec.toFixed(4);
      setFieldError("ra", "");
      setFieldError("dec", "");
      travel(target);
    })
  );

  document.querySelectorAll("[data-layer]").forEach((b) =>
    b.addEventListener("click", () => state.aladin && setMode(b.dataset.layer))
  );
  $("spin-toggle").addEventListener("click", () => setSpinning(!state.spinning));
  $("back-to-sky").addEventListener("click", backToSky);
  // Touching the sky hands control to the person: the rotation stops.
  for (const type of ["pointerdown", "wheel", "keydown"]) {
    view.addEventListener(type, () => state.spinning && setSpinning(false), { passive: true });
  }
}

// ---------- start ----------
async function start() {
  const meta = await (await fetch("data/barnard/frames.json")).json();
  bindEvents({ ra: meta.grid.center_ra, dec: meta.grid.center_dec });
  try {
    await A.init;
    state.cube = await loadCubeProperties();
    state.aladin = A.aladin("#sky-view", {
      survey: [], // no default survey: it would come from CDS
      log: false, // no usage logging to CDS
      backgroundColor: "rgb(4, 7, 11)",
      projection: "SIN",
      cooFrame: "icrsd",
      target: "266.4 -20",
      fov: FULL_FOV,
      showReticle: false,
      showLayersControl: false,
      showZoomControl: false,
      showFullscreenControl: false,
      showProjectionControl: false,
      showCooGridControl: false,
      showCooLocation: false,
      showFov: false,
      showFrame: false,
      showStatusBar: false,
      showContextMenu: false,
      showSettingsControl: false,
      showShareControl: false,
      showSimbadPointerControl: false,
    });
    state.aladin.setBaseImageLayer(A.imageHiPS(BACKGROUND_URL, { name: "DSS2 colour" }));
    setMode("visible");
    setSpinning(true);
    setInterval(updateHud, 200);
    $("sky-loading").hidden = true;
    sky.classList.add("is-ready");
  } catch (err) {
    console.error(err);
    $("sky-loading").textContent =
      "The sky map could not start (it needs WebGL 2 and access to IRSA). Search still works: pick a test object below.";
  }
}

start();
