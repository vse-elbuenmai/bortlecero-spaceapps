// Mockup of the blink viewer. Reads data/barnard/frames.json, written by prepare_barnard.py.
(() => {
  "use strict";

  const DATA_DIR = "data/barnard/";
  const ZOOMS = [1, 2, 4, 8];
  const SCALE_STEPS = [60, 30, 15, 10, 5, 2]; // arcsec, pick one that draws 40–140 px
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const $ = (id) => document.getElementById(id);
  const stage = $("stage"), plate = $("plate"), img = $("frame-img"), flagsImg = $("flags-img");
  const overlay = $("overlay"), live = $("frame-meta");

  const state = { meta: null, i: 0, zoomIdx: 0, cx: 0, cy: 0, playing: false, fps: 1, timer: null };

  const fmtDeg = (v, d = 4) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d) + "°";
  const fmtDate = (s) => s.slice(0, 16) + " UTC";
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  // ---------- layout: integer screen pixels per SPHEREx pixel, so blocks stay even ----------
  function layout() {
    const n = state.meta.grid.size_px;
    const side = stage.clientWidth;
    const base = Math.max(1, Math.floor(side / n));
    const ppx = base * ZOOMS[state.zoomIdx]; // screen px per data px
    const w = ppx * n;
    const half = side / 2;
    // clamp the view center so we never pan off the image
    const lim = Math.max(0, n / 2 - half / ppx);
    state.cx = Math.min(n / 2 + lim, Math.max(n / 2 - lim, state.cx));
    state.cy = Math.min(n / 2 + lim, Math.max(n / 2 - lim, state.cy));
    plate.style.width = plate.style.height = w + "px";
    plate.style.transform = `translate(${Math.round(half - state.cx * ppx)}px, ${Math.round(half - state.cy * ppx)}px)`;
    $("zoom-out-label").textContent = ZOOMS[state.zoomIdx] + "×";

    const scale = state.meta.grid.pixel_scale_arcsec;
    const arcsec = SCALE_STEPS.find((a) => (a / scale) * ppx <= 140) || 2;
    $("scalebar").style.width = Math.round((arcsec / scale) * ppx) + "px";
    $("scalelabel").textContent = arcsec + "″";
  }

  // ---------- overlay: trajectory for all dates, markers for the current one ----------
  function drawOverlay() {
    const { frames, grid } = state.meta;
    const n = grid.size_px;
    overlay.setAttribute("viewBox", `0 0 ${n} ${n}`);
    overlay.replaceChildren();
    const P = (p) => [p.x + 0.5, p.y + 0.5]; // pixel centers

    const pts = frames.map((f) => P(f.predicted).join(",")).join(" ");
    overlay.append(svgEl("polyline", { points: pts, class: "mk-traj" }));
    frames.forEach((f) => {
      const [x, y] = P(f.predicted);
      overlay.append(svgEl("circle", { cx: x, cy: y, r: 0.25, class: "mk-dot" }));
    });

    const f = frames[state.i];
    const [px, py] = P(f.predicted);
    const r = 2.2; // ≈ 13.5″, a bit wider than the star core so it never hides the data
    overlay.append(svgEl("circle", { cx: px, cy: py, r, class: "mk-pred-halo" }));
    overlay.append(svgEl("circle", { cx: px, cy: py, r, class: "mk-pred" }));

    const [mx, my] = P(f.measured);
    const g = 0.9, a = 2.6; // gap and arm end, in data pixels
    const d = `M${mx} ${my - a}V${my - g}M${mx} ${my + g}V${my + a}M${mx - a} ${my}H${mx - g}M${mx + g} ${my}H${mx + a}`;
    overlay.append(svgEl("path", { d, class: "mk-meas-halo" }));
    overlay.append(svgEl("path", { d, class: "mk-meas" }));
  }

  // ---------- frame + panel ----------
  function badge(kind, icon, text) {
    const li = document.createElement("li");
    li.className = "badge badge-" + kind;
    const ic = document.createElement("span");
    ic.setAttribute("aria-hidden", "true");
    ic.textContent = icon;
    li.append(ic, document.createTextNode(text));
    return li;
  }

  function show(i, { announce = false } = {}) {
    const { frames } = state.meta;
    state.i = (i + frames.length) % frames.length;
    const f = frames[state.i];
    img.src = DATA_DIR + f.image;
    img.alt = `SPHEREx image of ${state.meta.object.name}, ${f.date_utc.slice(0, 10)}, ${f.wavelength_um.toFixed(2)} µm`;
    flagsImg.src = DATA_DIR + f.flags;

    live.setAttribute("aria-live", announce ? "polite" : "off");
    $("frame-count").textContent = `Frame ${state.i + 1} / ${frames.length}`;
    $("m-date").textContent = fmtDate(f.date_utc);
    $("m-wave").textContent = f.wavelength_um.toFixed(3) + " µm";
    $("m-det").textContent = String(f.detector);
    $("m-rel").textContent = f.release;
    $("m-pa").textContent = Math.round(f.pa_deg) + "°";
    $("m-off").textContent = f.offset_arcsec.toFixed(2) + "″";
    $("hud-date").textContent = f.date_utc.slice(0, 10);

    const badges = $("badges");
    badges.replaceChildren();
    if (f.rotated) badges.append(badge("acento", "↻", "Rotated 180°, re-aligned"));
    if (f.saturated) badges.append(badge("aviso", "⚠", "Saturated core"));
    // Mockup threshold, to be decided by the team: SPHEREx astrometry is good to ~0.3″,
    // a saturated core shifts the centroid further.
    if (f.offset_arcsec <= 0.5) badges.append(badge("ok", "✓", `${f.offset_arcsec.toFixed(2)}″ from Gaia`));
    else badges.append(badge("aviso", "⚠", `${f.offset_arcsec.toFixed(2)}″ from Gaia`));
    const prev = frames[state.i - 1];
    if (prev && Math.abs(prev.wavelength_um - f.wavelength_um) > 0.05) {
      badges.append(badge("aviso", "⚠", `Different wavelength (${prev.wavelength_um.toFixed(2)} → ${f.wavelength_um.toFixed(2)} µm)`));
    }

    document.querySelectorAll(".tl-dot").forEach((b, k) => b.setAttribute("aria-current", k === state.i ? "true" : "false"));
    document.querySelectorAll(".tl-label").forEach((l, k) => l.classList.toggle("is-current", k === state.i));
    drawOverlay();
  }

  // ---------- playback ----------
  function setPlaying(on) {
    state.playing = on;
    clearInterval(state.timer);
    const btn = $("play");
    btn.setAttribute("aria-pressed", String(on));
    btn.setAttribute("aria-label", on ? "Pause" : "Play");
    btn.textContent = on ? "❚❚" : "▶";
    if (on) state.timer = setInterval(() => show(state.i + 1), 1000 / state.fps); // hard cut, no fade
  }

  function zoomTo(idx) {
    state.zoomIdx = Math.max(0, Math.min(ZOOMS.length - 1, idx));
    layout();
  }

  // ---------- timeline: dots spaced by real time ----------
  function buildTimeline() {
    const { frames } = state.meta;
    const t0 = frames[0].mjd, t1 = frames[frames.length - 1].mjd;
    const box = $("timeline-dots");
    frames.forEach((f, k) => {
      const pct = ((f.mjd - t0) / (t1 - t0 || 1)) * 100;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tl-dot";
      b.style.left = pct + "%";
      b.setAttribute("aria-label", `Frame ${k + 1}, ${f.date_utc.slice(0, 10)}`);
      b.addEventListener("click", () => { setPlaying(false); show(k, { announce: true }); });
      const label = document.createElement("span");
      label.className = "tl-label";
      label.style.left = pct + "%";
      label.textContent = f.date_utc.slice(0, 10);
      box.append(b, label);
    });
  }

  function summary() {
    const { summary: s, frames } = state.meta;
    const first = frames[0], last = frames[frames.length - 1];
    const dir = last.predicted.y < first.predicted.y ? "north" : "south";
    $("summary").innerHTML =
      `The star moved <strong>${s.measured_motion_arcsec.toFixed(1)}″ ${dir}</strong> in ${Math.round(s.days)} days ` +
      `(${(s.measured_motion_arcsec / state.meta.grid.pixel_scale_arcsec).toFixed(1)} pixels). ` +
      `Gaia predicts <strong>${s.predicted_motion_arcsec.toFixed(1)}″</strong>.`;
  }

  // ---------- events ----------
  $("prev").addEventListener("click", () => { setPlaying(false); show(state.i - 1, { announce: true }); });
  $("next").addEventListener("click", () => { setPlaying(false); show(state.i + 1, { announce: true }); });
  $("play").addEventListener("click", () => setPlaying(!state.playing));
  $("speed").addEventListener("input", (e) => {
    state.fps = Math.min(3, Number(e.target.value)); // WCAG 2.3.1: never above 3 changes/s
    $("speed-out").textContent = state.fps + " fps";
    if (state.playing) setPlaying(true);
  });
  $("zoom-in").addEventListener("click", () => zoomTo(state.zoomIdx + 1));
  $("zoom-out").addEventListener("click", () => zoomTo(state.zoomIdx - 1));
  $("zoom-reset").addEventListener("click", () => { state.cx = state.cy = state.meta.grid.size_px / 2; zoomTo(0); });
  $("flags-toggle").addEventListener("change", (e) => { flagsImg.hidden = !e.target.checked; });

  stage.addEventListener("wheel", (e) => { e.preventDefault(); zoomTo(state.zoomIdx + (e.deltaY < 0 ? 1 : -1)); }, { passive: false });
  let drag = null;
  stage.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, cx: state.cx, cy: state.cy }; stage.setPointerCapture(e.pointerId); });
  stage.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const ppx = parseFloat(plate.style.width) / state.meta.grid.size_px;
    state.cx = drag.cx - (e.clientX - drag.x) / ppx;
    state.cy = drag.cy - (e.clientY - drag.y) / ppx;
    layout();
  });
  stage.addEventListener("pointerup", () => { drag = null; });

  $("viewer").addEventListener("keydown", (e) => {
    if (e.target.closest("input, button:not(.icon-btn)") && e.key === " ") return;
    const keys = {
      " ": () => setPlaying(!state.playing),
      ArrowLeft: () => { setPlaying(false); show(state.i - 1, { announce: true }); },
      ArrowRight: () => { setPlaying(false); show(state.i + 1, { announce: true }); },
      "+": () => zoomTo(state.zoomIdx + 1), "=": () => zoomTo(state.zoomIdx + 1),
      "-": () => zoomTo(state.zoomIdx - 1),
      "0": () => { state.cx = state.cy = state.meta.grid.size_px / 2; zoomTo(0); },
    };
    if (keys[e.key] && !(e.target.type === "range")) { e.preventDefault(); keys[e.key](); }
  });

  // The search and the trip across the sky live in sky.js. It opens this viewer on arrival
  // (the section is hidden until then) and closes it when the person goes back to the sky.
  document.addEventListener("viewer:open", () => {
    if (!state.meta) return;
    show(0);
    layout();
    if (!reduceMotion) setPlaying(true); // with reduced motion it waits for the person
  });
  document.addEventListener("viewer:close", () => setPlaying(false));

  window.addEventListener("resize", () => state.meta && !$("viewer").hidden && layout());

  // ---------- start ----------
  fetch(DATA_DIR + "frames.json")
    .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then((meta) => {
      state.meta = meta;
      state.cx = state.cy = meta.grid.size_px / 2;
      $("obj-coords").textContent = `Gaia DR3 (J2016) ${meta.object.ra.toFixed(4)}°, ${fmtDeg(meta.object.dec)} · FOV ${(meta.grid.size_px * meta.grid.pixel_scale_arcsec / 60).toFixed(1)}′`;
      buildTimeline();
      summary();
      show(0);
      $("loading").hidden = true;
      // If the viewer was opened before the frames arrived, start it now.
      if (!$("viewer").hidden) document.dispatchEvent(new CustomEvent("viewer:open"));
    })
    .catch(() => {
      $("loading").querySelector("p").textContent =
        "These frames could not be loaded. Serve the folder over HTTP (see mockup/README.md).";
    });
})();
