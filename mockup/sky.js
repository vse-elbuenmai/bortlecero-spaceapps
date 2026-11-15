// Full-screen sky view of the mockup: the whole sky seen from inside, a search that travels to
// a position, and the blink viewer in a dialog on arrival. No libraries: one WebGL 2 shader
// paints a panorama of the sky (built by prepare_sky.py) on the inside of a sphere.
// A test for the team to judge, not a decision on stack or architecture (see mockup/README.md).

const TEXTURES = "sky/";
const LAYERS = { visible: "visible", spherex: "spherex-477", colour: "spherex-rgb" };
const REST_FOV = 120; // degrees across the screen when showing "the whole sky"
const MAX_FOV = 170;
const SPIN_DEG_PER_S = 1.5;
const SHARPNESS = 0.5; // closest zoom: one screen pixel shows no less than half a map pixel
// Name lookup: SIMBAD through the Sesame service of its mirror at Harvard (the CDS servers are down).
const SESAME = "https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-ox/S?";
const LOOKUP_TIMEOUT_MS = 10000;

// Test objects: position, epoch and proper motion (mas/yr), moved to today before travelling.
// Barnard's Star, Epsilon Indi B and R Draconis: Gaia DR3, live query of the ESA archive on
// 2026-11-14. WISE 0855−0714 is not in Gaia: position for 2025.5 from the team's study notes
// (Luhman & Esplin 2016; Kirkpatrick et al. 2021). RW Aurigae: SIMBAD, epoch 2000.
const OBJECTS = {
  barnard: { key: "barnards_star", name: "Barnard's Star", ra: 269.44850253, dec: 4.73942005, epoch: 2016.0, pmra: -801.551, pmdec: 10362.394 },
  epsindib: { key: "epsilon_indi_b", name: "Epsilon Indi B", ra: 331.0764526, dec: -56.79381207, epoch: 2016.0, pmra: 3981.977, pmdec: -2466.832 },
  wise0855: { key: "wise_0855_0714", name: "WISE 0855−0714", ra: 133.76, dec: -7.2422, epoch: 2025.5, pmra: -8118, pmdec: 680 },
  rwaur: { key: "rw_aurigae", name: "RW Aurigae", ra: 76.95652603, dec: 30.40143817, epoch: 2000.0, pmra: 0, pmdec: 0 },
  rdra: { key: "r_draconis", name: "R Draconis", ra: 248.16737837, dec: 66.75500675, epoch: 2016.0, pmra: -20.643, pmdec: 6.149 },
};

const ICON_PAUSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 3.5v9M10.5 3.5v9"/></svg>';
const ICON_PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path class="ico-fill" d="M5.2 3.4l6.9 4.6-6.9 4.6z"/></svg>';
const NOTE_SECONDS = 5; // how long the note about the layer shows by itself on phones
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const $ = (id) => document.getElementById(id);
const canvas = $("sky-canvas"), modal = $("viewer-modal"), viewer = $("viewer"), msg = $("search-msg");
const RAD = Math.PI / 180;
const pointerReadout = $("pointer-coords");
const skyFallback = $("sky-fallback");
let activePointer = null, lastTouch = null, pointerDirty = false;

const state = {
  ra: 266.4, dec: -20, fov: REST_FOV, // view centre (degrees) and field of view across the screen
  layer: "visible", fade: null, // fade: { from, start } while two layers cross-fade
  spinning: !reduceMotion, trip: null, target: null, grid: false,
  gl: null, uniforms: null, textures: {}, mapWidth: 2048, meta: null, dirty: true, last: 0,
};
// Handy in the browser console, and used to check that stars land where the maths says they do.
window.skyPrototype = { state, project: (ra, dec) => project(ra, dec), redraw: () => draw(performance.now()) };

const fmtRa = (v) => (v >= 359.99995 ? 0 : v).toFixed(4) + "°";
const fmtDec = (v) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(4) + "°";
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

// ---------- sky geometry ----------
// Unit vector of a sky position, and the three axes of the view: forward (the centre of the
// screen), east and north. From inside the sphere east is to the LEFT, as on any sky chart.
const vec = (ra, dec) => [Math.cos(dec * RAD) * Math.cos(ra * RAD), Math.cos(dec * RAD) * Math.sin(ra * RAD), Math.sin(dec * RAD)];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
function axes() {
  const r = state.ra * RAD, d = state.dec * RAD;
  return {
    f: vec(state.ra, state.dec),
    e: [-Math.sin(r), Math.cos(r), 0],
    n: [-Math.sin(d) * Math.cos(r), -Math.sin(d) * Math.sin(r), Math.cos(d)],
  };
}
// The screen uses a stereographic projection: it stays natural-looking at very wide angles.
// Half the screen width measures 2·tan(fov/4) in its plane.
const planeHalfWidth = () => 2 * Math.tan((state.fov * RAD) / 4);

// Where a sky position falls on the screen (CSS pixels), or null if it is behind the viewer.
function project(ra, dec) {
  const { f, e, n } = axes(), d = vec(ra, dec), z = dot(d, f);
  if (z < -0.6) return null;
  const k = 2 / (1 + z) / planeHalfWidth(), w = canvas.clientWidth, h = canvas.clientHeight;
  return { x: (1 + -dot(d, e) * k) * w / 2, y: h / 2 - dot(d, n) * k * w / 2 };
}

// The inverse calculation used in the sky shader, with screen Y increasing downwards here.
function skyAtPointer({ x, y }, { f, e, n }) {
  const rect = canvas.getBoundingClientRect();
  const u = (x - rect.left) / rect.width, v = (y - rect.top) / rect.height;
  if (!Number.isFinite(u) || !Number.isFinite(v) || u < 0 || u >= 1 || v < 0 || v >= 1) return null;
  const width = planeHalfWidth();
  const px = (2 * u - 1) * width, py = (1 - 2 * v) * width / (canvas.width / canvas.height);
  const r2 = px * px + py * py;
  const d = f.map((forward, i) => (-4 * px * e[i] + 4 * py * n[i] + (4 - r2) * forward) / (4 + r2));
  const xy = Math.hypot(d[0], d[1]);
  return {
    ra: xy < 1e-12 ? null : (Math.atan2(d[1], d[0]) / RAD + 360) % 360,
    dec: Math.atan2(d[2], xy) / RAD,
  };
}

// Closest zoom the current map allows before it turns to mush on this screen.
function minFov() {
  const mapWidth = state.mapWidth; // the full-size map, not the small one shown while it loads
  // Never closer than 30°: a narrow phone screen would allow more, but its real pixels are finer
  // than the CSS pixels counted here, and the team wants every trip to end between 30° and 60°.
  return clamp((4 * Math.atan((Math.PI * canvas.clientWidth * SHARPNESS) / (2 * mapWidth))) / RAD, 30, 90);
}

// ---------- WebGL ----------
const VERTEX = `#version 300 es
in vec2 aPos; out vec2 vNdc;
void main() { vNdc = aPos; gl_Position = vec4(aPos, 0.0, 1.0); }`;

const FRAGMENT = `#version 300 es
precision highp float;
in vec2 vNdc; out vec4 outColor;
uniform sampler2D uMapA, uMapB;
uniform float uMix, uHalfWidth, uAspect;
uniform vec3 uForward, uEast, uNorth;
uniform bool uGrid;
const float PI = 3.141592653589793;
float gridLine(float distance, float radiansPerPixel) {
  return 1.0 - smoothstep(0.2, 1.25, distance / max(radiansPerPixel, 1e-6));
}
float gridDistance(float angle, float stepSize) {
  return abs(mod(angle + stepSize * 0.5, stepSize) - stepSize * 0.5);
}
void main() {
  vec2 p = vec2(vNdc.x, vNdc.y / uAspect) * uHalfWidth;          // point on the projection plane
  float r2 = dot(p, p);
  vec3 c = vec3(4.0 * p, 4.0 - r2) / (4.0 + r2);                 // direction in the view's axes
  vec3 d = -c.x * uEast + c.y * uNorth + c.z * uForward;         // east to the left
  float ra = atan(d.y, d.x), dec = asin(clamp(d.z, -1.0, 1.0));
  // The panorama has RA 0h in the middle and RA growing to the left; north at the top.
  float v = 0.5 - dec / PI;
  float ua = 0.5 - ra / (2.0 * PI);
  float ub = fract(ua + 0.5) - 0.5;                              // same place, seam on the other side
  bool b = fwidth(ub) < fwidth(ua);                              // pick the one with no seam here
  vec2 uv = vec2(b ? ub : ua, v);
  vec2 gx = vec2(b ? dFdx(ub) : dFdx(ua), dFdx(v)), gy = vec2(b ? dFdy(ub) : dFdy(ua), dFdy(v));
  vec3 color = mix(textureGrad(uMapA, uv, gx, gy).rgb, textureGrad(uMapB, uv, gx, gy).rgb, uMix);
  if (uGrid) {
    // Use the seam-safe texture gradients for RA. Fade meridians into the poles as they converge.
    float raPixel = (abs(gx.x) + abs(gy.x)) * 2.0 * PI;
    float decPixel = (abs(gx.y) + abs(gy.y)) * PI;
    float poleFade = smoothstep(0.0, 0.04, length(d.xy));
    float meridians = gridLine(gridDistance(ra, PI / 6.0), raPixel) * poleFade;
    float parallels = gridLine(gridDistance(dec, PI / 12.0), decPixel);
    float axes = max(gridLine(abs(ra), raPixel) * poleFade, gridLine(abs(dec), decPixel));
    // Use the sky palette's star blue, with stronger strokes for RA 0° and Dec 0°.
    color = mix(color, vec3(184.0, 212.0, 240.0) / 255.0, max(0.40 * max(meridians, parallels), 0.78 * axes));
  }
  outColor = vec4(color, 1.0);
}`;

function initGl() {
  const gl = canvas.getContext("webgl2", { antialias: false, alpha: false });
  if (!gl) return false;
  const compile = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  gl.useProgram(prog);
  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW); // one big triangle
  const loc = gl.getAttribLocation(prog, "aPos");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  state.uniforms = Object.fromEntries(
    ["uMapA", "uMapB", "uMix", "uHalfWidth", "uAspect", "uForward", "uEast", "uNorth", "uGrid"].map((n) => [n, gl.getUniformLocation(prog, n)])
  );
  state.gl = gl;
  state.mapWidth = gl.getParameter(gl.MAX_TEXTURE_SIZE) >= 4096 ? 4096 : 2048;
  return true;
}

function uploadTexture(image) {
  const gl = state.gl, tex = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  gl.generateMipmap(gl.TEXTURE_2D);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  const aniso = gl.getExtension("EXT_texture_filter_anisotropic");
  if (aniso) gl.texParameterf(gl.TEXTURE_2D, aniso.TEXTURE_MAX_ANISOTROPY_EXT, 4);
  return tex;
}

const loadImage = (src) => new Promise((resolve, reject) => {
  const img = new Image();
  img.onload = () => resolve(img);
  img.onerror = () => reject(new Error("Could not load " + src));
  img.src = src;
});

// A layer shows its small map at once and swaps to the large one when it arrives.
async function loadLayer(key) {
  if (state.textures[key]) return;
  const gl = state.gl, put = (img) => {
    const old = state.textures[key];
    state.textures[key] = { tex: uploadTexture(img), width: img.naturalWidth };
    if (old) gl.deleteTexture(old.tex);
    state.dirty = true;
  };
  put(await loadImage(`${TEXTURES}${LAYERS[key]}_2048.webp`));
  if (state.mapWidth >= 4096) {
    loadImage(`${TEXTURES}${LAYERS[key]}_4096.webp`).then((img) => state.textures[key] && put(img)).catch(console.warn);
  }
}

function resize() {
  const scale = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.round(canvas.clientWidth * scale), h = Math.round(canvas.clientHeight * scale);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  if (state.gl) state.gl.viewport(0, 0, w, h);
  document.documentElement.style.setProperty("--journey-h", $("search").offsetHeight + "px");
  state.dirty = true;
}

function draw(now) {
  const gl = state.gl, u = state.uniforms, { f, e, n } = axes();
  let from = state.layer, mix = 0;
  if (state.fade) {
    const k = reduceMotion ? 1 : (now - state.fade.start) / 400;
    if (k >= 1) {
      // keep at most two maps in memory: phones run out of it quickly
      for (const key of Object.keys(state.textures)) {
        if (key !== state.layer) { gl.deleteTexture(state.textures[key].tex); delete state.textures[key]; }
      }
      state.fade = null;
    } else { from = state.fade.from; mix = k; state.dirty = true; }
  }
  const a = state.textures[from] || state.textures[state.layer], b = state.textures[state.layer] || a;
  if (!a) return;
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, a.tex); gl.uniform1i(u.uMapA, 0);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, b.tex); gl.uniform1i(u.uMapB, 1);
  gl.uniform1f(u.uMix, mix);
  gl.uniform1f(u.uHalfWidth, planeHalfWidth());
  gl.uniform1f(u.uAspect, canvas.width / canvas.height);
  gl.uniform1i(u.uGrid, Number(state.grid));
  gl.uniform3fv(u.uForward, f); gl.uniform3fv(u.uEast, e); gl.uniform3fv(u.uNorth, n);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
}

// ---------- the loop: rotation at rest, trips, redraws ----------
function frame(now) {
  const dt = Math.min(0.5, (now - (state.last || now)) / 1000);
  state.last = now;
  if (state.trip) stepTrip(now);
  else if (state.spinning && !modal.open) { state.ra = (state.ra + SPIN_DEG_PER_S * dt) % 360; state.dirty = true; }
  if (state.dirty || pointerDirty) updatePointerReadout();
  if (state.dirty) {
    state.dirty = false;
    if (state.gl) draw(now);
    updateOverlay();
  }
  requestAnimationFrame(frame);
}

function updatePointerReadout() {
  pointerDirty = false;
  const position = activePointer ? skyAtPointer(activePointer, axes()) : lastTouch;
  let text = "";
  if (position) {
    const label = !activePointer ? "Last touch" : activePointer.type === "touch" ? "Touch" : "Pointer";
    const ra = position.ra === null ? "—" : fmtRa(position.ra);
    text = `${label}: RA ${ra}, Dec ${fmtDec(position.dec)}`;
  }
  if (pointerReadout.textContent !== text) pointerReadout.textContent = text;
  pointerReadout.hidden = !text;
}

function updateOverlay() {
  const closest = state.fov <= minFov() + 0.05;
  $("sky-coords").textContent =
    `${fmtRa(state.ra)}, ${fmtDec(state.dec)} · FOV ${state.fov.toFixed(0)}°${closest ? " · closest view" : ""}`;
  const reticle = $("reticle"), p = state.target && project(state.target.ra, state.target.dec);
  reticle.hidden = !p;
  if (p) reticle.style.transform = `translate(${p.x.toFixed(1)}px, ${p.y.toFixed(1)}px)`;
}

function setSpinning(on) {
  state.spinning = on && !reduceMotion;
  const btn = $("spin-toggle");
  btn.setAttribute("aria-pressed", String(state.spinning));
  btn.setAttribute("aria-label", state.spinning ? "Pause rotation" : "Rotate the sky");
  btn.innerHTML = state.spinning ? ICON_PAUSE : ICON_PLAY;
}

function setFov(fov) {
  state.fov = clamp(fov, minFov(), MAX_FOV);
  state.dirty = true;
}

// ---------- layers ----------
function caption(key) {
  const L = state.meta && state.meta.layers;
  if (!L) return "";
  const s = L["spherex-477"], c = L["spherex-rgb"], w = (v) => v.toFixed(2);
  const span = `${s.average_of[0]} to ${s.average_of[1]}`;
  return {
    visible: "Visible sky, drawn from the Gaia, Hipparcos and Tycho star catalogues (NASA SVS). Not a photograph.",
    spherex: `SPHEREx all-sky average at ${w(s.wavelength_um)} µm, ${span} (IRSA). A backdrop: the dated frames open in the viewer. Blank near the two ecliptic poles.`,
    colour: `SPHEREx all-sky average, ${span} (IRSA). False colour: ${w(c.wavelengths_um.red)} µm red, ${w(c.wavelengths_um.green)} µm green, ${w(c.wavelengths_um.blue)} µm blue. Blank near the two ecliptic poles.`,
  }[key];
}

async function setLayer(key) {
  $("layer-select").value = key;
  $("sky-credit").textContent = caption(key);
  showNoteBriefly();
  if (!state.gl || key === state.layer) return;
  try {
    await loadLayer(key);
  } catch (err) {
    $("sky-credit").textContent = "This sky layer could not be loaded. Check the connection and try again.";
    return;
  }
  state.fade = { from: state.layer, start: performance.now() };
  state.layer = key;
  state.dirty = true;
}

// ---------- coordinates and names ----------
// Accepts decimal degrees (269.4485, +4.7394) and sexagesimal (17h57m48.5s, 17:57:48.5,
// +04°44′22″, +04 44 22). Sexagesimal RA is in hours unless it is marked with ° or d.
function parseAngle(text, isRa) {
  const s = text.trim().replace(/−/g, "-");
  if (/^[+-]?\d+(\.\d+)?\s*(°|d|deg)?$/i.test(s)) return parseFloat(s);
  const m = s.match(/^([+-])?\s*(\d{1,3})\s*[h°d:\s]\s*(\d{1,2})\s*[m′':\s]\s*(\d{1,2}(?:\.\d+)?)?\s*[s″"]?$/i);
  if (!m || +m[3] >= 60 || +(m[4] || 0) >= 60) return NaN;
  const value = +m[2] + +m[3] / 60 + +(m[4] || 0) / 3600;
  return (m[1] === "-" ? -1 : 1) * value * (isRa && !/[°d]/i.test(s) ? 15 : 1);
}

// Catalogue position moved to today with its proper motion (a straight line; parallax ignored,
// which is far below what this sky view can show).
function today(o) {
  const years = new Date().getUTCFullYear() + (new Date().getUTCMonth() + 0.5) / 12 - o.epoch;
  const dec = o.dec + (o.pmdec / 3.6e6) * years;
  return { key: o.key, name: o.name, simbad: o.simbad, dec, ra: (o.ra + ((o.pmra / 3.6e6) * years) / Math.cos(o.dec * RAD) + 360) % 360 };
}

const BENCHMARK_ALIASES = {
  gj699: OBJECTS.barnard,
  gl699: OBJECTS.barnard,
  hip87937: OBJECTS.barnard,
  gj845b: OBJECTS.epsindib,
  epsindb: OBJECTS.epsindib,
  epsindib: OBJECTS.epsindib,
  wise0855: OBJECTS.wise0855,
  wisej085510830714425: OBJECTS.wise0855,
  rwaur: OBJECTS.rwaur,
  hd240764: OBJECTS.rwaur,
  rdra: OBJECTS.rdra,
  hd149880: OBJECTS.rdra,
  hip81014: OBJECTS.rdra,
};

async function querySesame(url, name) {
  const reply = await fetch(url, { signal: AbortSignal.timeout(LOOKUP_TIMEOUT_MS) });
  if (!reply.ok) throw new Error(`The name service answered ${reply.status}`);
  const xml = new DOMParser().parseFromString(await reply.text(), "text/xml");
  const num = (tag) => { const el = xml.querySelector(tag); return el ? parseFloat(el.textContent) : NaN; };
  if (Number.isNaN(num("jradeg")) || Number.isNaN(num("jdedeg"))) return null;
  const oname = xml.querySelector("oname");
  return today({
    name, // what the person typed; SIMBAD's own identifier goes next to it
    simbad: oname ? oname.textContent.replace(/\s+/g, " ").trim() : "",
    ra: num("jradeg"), dec: num("jdedeg"), epoch: 2000, pmra: num("pmRA") || 0, pmdec: num("pmDE") || 0,
  });
}

// Where an object with this name is today. The five test objects are answered from the list above,
// with no network. Any other name is asked to SIMBAD (falling back to SIMBAD+NED+VizieR), which
// gives the position for J2000 and the proper motion. Returns null when Sesame does not know the
// name, and throws when it does not answer.
async function resolveName(name) {
  const plain = (text) => text.toLowerCase().replace(/[^a-z0-9]/g, "");
  const key = plain(name);
  const known = Object.values(OBJECTS).find((o) => plain(o.name) === key) || BENCHMARK_ALIASES[key];
  if (known) return today(known);
  const encoded = encodeURIComponent(name);
  const primary = await querySesame(SESAME + encoded, name);
  if (primary) return primary;
  return querySesame(SESAME.replace("-ox/S?", "-ox/SNV?") + encoded, name);
}

function fieldError(id, text) {
  const input = $(id), err = $(id + "-err");
  input.setAttribute("aria-invalid", String(Boolean(text)));
  err.hidden = !text;
  err.textContent = text ? "⚠ " + text : "";
}
const say = (text) => { msg.hidden = !text; msg.textContent = text || ""; };

// On phones the note about the layer (what the map is, and that it is a drawing or an average) is
// tucked behind the info button. It still shows by itself for a few seconds when the page loads
// and whenever the layer changes, so nobody takes the backdrop for a photograph unawares.
let noteTimer = 0;
function setInfo(open) {
  clearTimeout(noteTimer);
  const layers = document.querySelector(".sky-layers");
  layers.classList.toggle("show-note", open);
  layers.classList.toggle("show-coords", open);
  $("info-toggle").setAttribute("aria-expanded", String(open));
}
function showNoteBriefly() {
  const layers = document.querySelector(".sky-layers");
  if (layers.classList.contains("show-coords") || !$("sky-credit").textContent) return; // opened by hand: leave it
  clearTimeout(noteTimer);
  layers.classList.add("show-note");
  noteTimer = setTimeout(() => layers.classList.remove("show-note"), NOTE_SECONDS * 1000);
}

// The ring on the marked position: play its arrival once (CSS), then let it rest.
function pingReticle() {
  const reticle = $("reticle");
  reticle.classList.remove("is-arriving");
  void reticle.offsetWidth; // restart the animation
  reticle.classList.add("is-arriving");
}

// Which test object the search shows as chosen (none for a typed position).
function setObject(objectKey) {
  $("object").value = objectKey || "";
}

// ---------- the trip ----------
function travel(target) {
  if (modal.open) modal.close();
  setSpinning(false);
  setSearchOpen(false);
  state.target = null;
  $("ra").value = target.ra.toFixed(4);
  $("dec").value = (target.dec >= 0 ? "+" : "") + target.dec.toFixed(4);
  $("reticle-label").textContent = target.name || `${fmtRa(target.ra)}, ${fmtDec(target.dec)}`;
  say(`Travelling to ${target.name ? target.name + ", " : ""}${fmtRa(target.ra)}, ${fmtDec(target.dec)}…`);
  const arrivalFov = minFov();
  if (reduceMotion || !state.gl) {
    Object.assign(state, { ra: target.ra, dec: target.dec, fov: arrivalFov, dirty: true });
    return arrive(target);
  }
  state.trip = {
    target, start: performance.now(), duration: 5200,
    from: vec(state.ra, state.dec), to: vec(target.ra, target.dec),
    fov0: state.fov, fovWide: Math.max(state.fov, REST_FOV), fov1: arrivalFov,
  };
}

// Turn along the shortest arc while pulling back, then close in on the position.
function stepTrip(now) {
  const t = state.trip, k = clamp((now - t.start) / t.duration, 0, 1);
  const turn = ease(clamp(k / 0.62, 0, 1)), angle = Math.acos(clamp(dot(t.from, t.to), -1, 1));
  let d = t.to;
  if (angle > 1e-6 && turn < 1) {
    const s = Math.sin(angle), a = Math.sin((1 - turn) * angle) / s, b = Math.sin(turn * angle) / s;
    d = t.from.map((v, i) => a * v + b * t.to[i]);
  }
  state.dec = Math.asin(clamp(d[2], -1, 1)) / RAD;
  state.ra = (Math.atan2(d[1], d[0]) / RAD + 360) % 360;
  if (k < 0.55) state.fov = t.fov0 + (t.fovWide - t.fov0) * ease(clamp(k / 0.25, 0, 1));
  else state.fov = t.fovWide * (t.fov1 / t.fovWide) ** ease((k - 0.55) / 0.45); // even steps of zoom
  state.dirty = true;
  if (k >= 1) { state.trip = null; arrive(t.target); }
}

function arrive(target) {
  state.target = target;
  state.dirty = true;
  say("");
  pingReticle();
  setTimeout(() => openModal(target), reduceMotion ? 0 : 900); // long enough to see the ring land
}

function findPreparedBenchmark(target) {
  if (!target) return null;
  if (target.key) {
    const byKey = Object.entries(OBJECTS).find(([k, o]) => o.key === target.key || k === target.key);
    if (byKey) return { chipKey: byKey[0], ...byKey[1] };
  }
  if (target.target_id) {
    const byTid = Object.entries(OBJECTS).find(([k, o]) => o.key === target.target_id || k === target.target_id);
    if (byTid) return { chipKey: byTid[0], ...byTid[1] };
  }
  if (target.name) {
    const lowerName = target.name.toLowerCase();
    const byName = Object.entries(OBJECTS).find(([k, o]) => o.name.toLowerCase() === lowerName || k.toLowerCase() === lowerName);
    if (byName) return { chipKey: byName[0], ...byName[1] };
  }
  if (target.ra !== undefined && target.dec !== undefined) {
    for (const [k, obj] of Object.entries(OBJECTS)) {
      const d = Math.hypot((target.ra - obj.ra) * Math.cos(obj.dec * RAD), target.dec - obj.dec);
      if (d <= 0.15) return { chipKey: k, ...obj };
    }
  }
  return null;
}

function isPrepared(target) {
  return findPreparedBenchmark(target) !== null;
}

function openModal(target) {
  const bench = findPreparedBenchmark(target);
  const targetId = bench ? bench.key : (target.target_id || null);
  const targetName = bench ? bench.name : (target.name || "Your position");

  $("modal-title").textContent = targetName;
  $("modal-coords").textContent = `${fmtRa(target.ra)}, ${fmtDec(target.dec)} · position for today` +
    (target.simbad ? ` · SIMBAD: ${target.simbad}` : "");

  modal.showModal();

  // Dispatch viewer:load-target to mockup.js
  document.dispatchEvent(new CustomEvent("viewer:load-target", {
    detail: {
      target_id: targetId,
      name: targetName,
      ra: target.ra,
      dec: target.dec,
    }
  }));
}

function wholeSky() {
  if (modal.open) modal.close();
  state.target = null;
  state.trip = null;
  setObject(null);
  say("");
  setSearchOpen(true);
  if (reduceMotion || !state.gl) { setFov(REST_FOV); return; }
  const from = state.fov, start = performance.now();
  const step = (now) => {
    const k = clamp((now - start) / 1500, 0, 1);
    if (state.trip) return;
    setFov(from + (REST_FOV - from) * ease(k));
    if (k < 1) requestAnimationFrame(step);
    else setSpinning(true);
  };
  requestAnimationFrame(step);
}

function setSearchOpen(open) {
  $("search-body").hidden = !open;
  $("search").classList.toggle("is-collapsed", !open);
  const btn = $("search-toggle");
  btn.textContent = open ? "Hide" : "Search";
  btn.setAttribute("aria-expanded", String(open));
  resize();
}

// ---------- events ----------
function bindEvents() {
  const fields = ["object", "name", "ra", "dec"];
  let searches = 0; // so the answer to a slow name lookup cannot override a newer search
  $("search-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const search = ++searches;
    fields.forEach((id) => fieldError(id, ""));
    const name = $("name").value.trim();
    if (name) {
      say(`Looking up “${name}”…`);
      let found;
      try {
        found = await resolveName(name);
      } catch {
        if (search !== searches) return;
        say("");
        return fieldError("name", "The name service (SIMBAD at Harvard) is not responding. Try again, or enter RA and Dec.");
      }
      if (search !== searches) return;
      if (!found) {
        say("");
        return fieldError("name", `The name service (SIMBAD at Harvard) did not find “${name}”. Try another name, or enter RA and Dec.`);
      }
      const bench = findPreparedBenchmark(found);
      setObject(bench ? bench.chipKey : null);
      return travel(found);
    }
    const objectKey = $("object").value;
    if (objectKey) return travel(today(OBJECTS[objectKey]));
    const ra = parseAngle($("ra").value, true), dec = parseAngle($("dec").value, false);
    const raBad = Number.isNaN(ra) || ra < 0 || ra >= 360, decBad = Number.isNaN(dec) || dec < -90 || dec > 90;
    if (!$("ra").value.trim() && !$("dec").value.trim()) return fieldError("object", "Choose a test object, type an object name, or enter RA and Dec.");
    fieldError("ra", raBad ? "RA must be between 0° and 360° (or 0h and 24h)" : "");
    fieldError("dec", decBad ? "Dec must be between −90° and +90°" : "");
    if (raBad || decBad) return (raBad ? $("ra") : $("dec")).focus();
    const target = { ra, dec };
    const bench = findPreparedBenchmark(target);
    setObject(bench ? bench.chipKey : null);
    travel(bench ? { ...target, ...bench } : target);
  });
  // A test object, a name and a pair of coordinates are three ways to say the same thing, and the
  // last one touched is the one that counts: choosing an object fills in where it is today and
  // clears the name, typing a name clears the choice and the position, and typing a position
  // clears the choice and the name. Nothing travels until "Go there", so stepping through the list
  // with the keyboard does not move the sky.
  $("object").addEventListener("change", () => {
    fields.forEach((id) => fieldError(id, ""));
    const object = OBJECTS[$("object").value];
    if (!object) return;
    const target = today(object);
    $("name").value = "";
    $("ra").value = target.ra.toFixed(5);
    $("dec").value = (target.dec >= 0 ? "+" : "−") + Math.abs(target.dec).toFixed(5);
  });
  $("name").addEventListener("input", () => {
    setObject(null);
    $("ra").value = $("dec").value = "";
  });
  for (const id of ["ra", "dec"]) $(id).addEventListener("input", () => {
    setObject(null);
    $("name").value = "";
  });

  $("layer-select").addEventListener("change", (e) => setLayer(e.target.value));
  $("info-toggle").addEventListener("click", () => setInfo(!document.querySelector(".sky-layers").classList.contains("show-coords")));

  $("spin-toggle").addEventListener("click", () => setSpinning(!state.spinning));
  $("grid-toggle").addEventListener("click", (e) => {
    state.grid = !state.grid;
    e.currentTarget.setAttribute("aria-pressed", String(state.grid));
    state.dirty = true;
  });
  $("zoom-sky-in").addEventListener("click", () => setFov(state.fov / 1.25));
  $("zoom-sky-out").addEventListener("click", () => setFov(state.fov * 1.25));
  $("whole-sky").addEventListener("click", wholeSky);
  $("search-toggle").addEventListener("click", () => setSearchOpen($("search-body").hidden));
  $("modal-close").addEventListener("click", () => modal.close());
  $("open-barnard").addEventListener("click", () => {
    $("name").value = "";
    setObject("barnard");
    travel(today(OBJECTS.barnard));
  });
  $("credits-open").addEventListener("click", () => $("credits").showModal());
  $("credits-close").addEventListener("click", () => $("credits").close());
  modal.addEventListener("close", () => {
    document.dispatchEvent(new CustomEvent("viewer:close"));
    setSearchOpen(true);
    if (state.target) pingReticle(); // back on the sky: point at the place again
  });

  // Looking around: drag to turn, wheel or pinch to zoom, arrows and +/− from the keyboard.
  const pointers = new Map();
  let pinch = 0;
  const trackPointer = (e) => {
    if (!e.isPrimary || !skyFallback.hidden) return;
    activePointer = { id: e.pointerId, type: e.pointerType, x: e.clientX, y: e.clientY };
    lastTouch = null;
    pointerDirty = true;
  };
  const clearPointer = (e) => {
    if (activePointer?.id !== e.pointerId) return;
    activePointer = null;
    pointerDirty = true;
  };
  const hold = () => { state.trip = null; if (state.spinning) setSpinning(false); };
  const turn = (dx, dy) => {
    const degPerPx = (2 * planeHalfWidth()) / canvas.clientWidth / RAD;
    state.dec = clamp(state.dec + dy * degPerPx, -89.5, 89.5);
    state.ra = (state.ra + (dx * degPerPx) / Math.max(0.05, Math.cos(state.dec * RAD)) + 360) % 360;
    state.dirty = true;
  };
  canvas.addEventListener("pointerdown", (e) => {
    trackPointer(e);
    hold();
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    pinch = 0;
  });
  canvas.addEventListener("pointermove", (e) => {
    trackPointer(e);
    const p = pointers.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (pointers.size === 1) return turn(dx, dy);
    const [a, b] = [...pointers.values()], dist = Math.hypot(a.x - b.x, a.y - b.y);
    if (pinch) setFov(state.fov * (pinch / dist));
    pinch = dist;
  });
  canvas.addEventListener("pointerleave", clearPointer);
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    canvas.addEventListener(type, (e) => {
      if (!pointers.delete(e.pointerId)) return;
      pinch = 0;
      if (type === "pointerup" && e.pointerType === "touch" && activePointer?.id === e.pointerId) {
        lastTouch = skyAtPointer({ x: e.clientX, y: e.clientY }, axes());
        clearPointer(e);
      } else if (type !== "pointerup") clearPointer(e);
    });
  }
  canvas.addEventListener("wheel", (e) => { e.preventDefault(); hold(); setFov(state.fov * Math.exp(e.deltaY * 0.0015)); }, { passive: false });
  canvas.addEventListener("keydown", (e) => {
    const step = canvas.clientWidth / 12;
    const keys = {
      ArrowLeft: () => turn(step, 0), ArrowRight: () => turn(-step, 0),
      ArrowUp: () => turn(0, step), ArrowDown: () => turn(0, -step),
      "+": () => setFov(state.fov / 1.25), "=": () => setFov(state.fov / 1.25), "-": () => setFov(state.fov * 1.25),
    };
    if (keys[e.key]) { e.preventDefault(); hold(); keys[e.key](); }
  });
  window.addEventListener("resize", resize);
}

// ---------- start ----------
async function start() {
  bindEvents();
  setSpinning(state.spinning);
  state.meta = await fetch(TEXTURES + "sky.json").then((r) => r.json()).catch(() => null);
  setLayer(state.layer);
  try {
    if (!initGl()) throw new Error("WebGL 2 is not available");
    resize();
    await loadLayer(state.layer);
    skyFallback.hidden = true;
    $("grid-toggle").disabled = false;
  } catch (err) {
    console.error(err);
    state.gl = null;
    skyFallback.textContent = "The sky map could not start on this device (it needs WebGL 2). Search still works.";
  }
  resize();
  requestAnimationFrame(frame);
}

start();
