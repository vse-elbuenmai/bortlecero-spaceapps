// Interactive SPHEREx Multi-Epoch Blink Comparator Viewer
// Supports BlinkBundleDTO (FastAPI REST API and static bundles) and legacy frames.json.
(() => {
  "use strict";

  const ZOOMS = [1, 2, 4, 8];
  const SCALE_STEPS = [60, 30, 15, 10, 5, 2]; // arcsec, pick one that draws 40–140 px
  const ICON_PAUSE = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.5 3.5v9M10.5 3.5v9"/></svg>';
  const ICON_PLAY = '<svg viewBox="0 0 16 16" aria-hidden="true"><path class="ico-fill" d="M5.2 3.4l6.9 4.6-6.9 4.6z"/></svg>';
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const BENCHMARK_MAP = {
    barnard: "barnards_star",
    barnards_star: "barnards_star",
    "barnard's star": "barnards_star",
    epsindib: "epsilon_indi_b",
    epsilon_indi_b: "epsilon_indi_b",
    "epsilon indi b": "epsilon_indi_b",
    wise0855: "wise_0855_0714",
    wise_0855_0714: "wise_0855_0714",
    "wise 0855": "wise_0855_0714",
    "wise 0855−0714": "wise_0855_0714",
    rwaur: "rw_aurigae",
    rw_aurigae: "rw_aurigae",
    "rw aurigae": "rw_aurigae",
    rdra: "r_draconis",
    r_draconis: "r_draconis",
    "r draconis": "r_draconis",
  };

  const BENCHMARK_COORDS = [
    { target_id: "barnards_star", ra: 269.4485, dec: 4.7394, name: "Barnard's Star" },
    { target_id: "epsilon_indi_b", ra: 331.0765, dec: -56.7938, name: "Epsilon Indi B" },
    { target_id: "wise_0855_0714", ra: 133.76, dec: -7.2422, name: "WISE 0855−0714" },
    { target_id: "rw_aurigae", ra: 76.9565, dec: 30.4014, name: "RW Aurigae" },
    { target_id: "r_draconis", ra: 248.1674, dec: 66.7550, name: "R Draconis" },
  ];

  const $ = (id) => document.getElementById(id);
  const stage = $("stage"), plate = $("plate"), img = $("frame-img"), flagsImg = $("flags-img");
  const overlay = $("overlay"), live = $("frame-meta");

  const state = {
    bundle: null,          // BlinkBundleDTO
    activeBand: null,      // null = all, or number
    activeFrames: [],      // array of FrameMetadataDTO
    diffMode: false,       // toggle dipole difference map view
    activeDiffMap: null,   // DifferenceMapDTO currently displayed
    i: 0,
    zoomIdx: 0,
    cx: 0,
    cy: 0,
    playing: false,
    fps: 1,
    timer: null,
    tlX: null,             // where each timeline dot sits, in px along the track
    overlays: { predicted: true, measured: true, path: true, flags: false }, // marks drawn over the image
    legacyFlags: false,    // the current frame brings its flags as an image (frames.json)
    mode: "basic",         // detail level: "basic" or "advanced"
  };

  const fmtDeg = (v, d = 4) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d) + "°";
  const fmtDate = (s) => (s ? s.slice(0, 16).replace("T", " ") + " UTC" : "N/A");
  const frameDay = (f) => (f.obs_time_iso || f.date_utc || "").slice(0, 10);
  const framesOfBand = (bundle, band) =>
    bundle.frames_by_band && bundle.frames_by_band[String(band)]
      ? bundle.frames_by_band[String(band)]
      : bundle.frames_chronological.filter((f) => Number(f.detector_band) === Number(band));
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  // ---------- layout: integer screen pixels per SPHEREx pixel ----------
  function layout() {
    if (!state.bundle) return;
    const grid = state.bundle.grid;
    const n = grid.width_px || grid.size_px || 31;
    const side = stage.clientWidth || 320;
    const base = Math.max(1, Math.floor(side / n));
    const ppx = base * ZOOMS[state.zoomIdx]; // screen px per data px
    const w = ppx * n;
    const half = side / 2;
    const lim = Math.max(0, n / 2 - half / ppx);
    state.cx = Math.min(n / 2 + lim, Math.max(n / 2 - lim, state.cx));
    state.cy = Math.min(n / 2 + lim, Math.max(n / 2 - lim, state.cy));
    plate.style.width = plate.style.height = w + "px";
    plate.style.transform = `translate(${Math.round(half - state.cx * ppx)}px, ${Math.round(half - state.cy * ppx)}px)`;
    $("zoom-out-label").textContent = ZOOMS[state.zoomIdx] + "×";
    // At 1× the image is always centred, so the reset has nothing to do either
    $("zoom-in").disabled = state.zoomIdx >= ZOOMS.length - 1;
    $("zoom-out").disabled = state.zoomIdx <= 0;
    $("zoom-reset").disabled = state.zoomIdx <= 0;

    const scale = grid.pixel_scale_arcsec || 6.15;
    const arcsec = SCALE_STEPS.find((a) => (a / scale) * ppx <= 140) || 2;
    $("scalebar").style.width = Math.round((arcsec / scale) * ppx) + "px";
    $("scalelabel").textContent = arcsec + "″";
  }

  // ---------- overlay: trajectory for all dates, markers for current one ----------
  // Each kind of mark has a switch in the legend (state.overlays).
  function drawOverlay() {
    if (!state.bundle) return;
    overlay.replaceChildren();
    if (state.diffMode) return;
    const grid = state.bundle.grid;
    const w = grid.width_px || grid.size_px || 31;
    const h = grid.height_px || grid.size_px || 31;
    overlay.setAttribute("viewBox", `0 0 ${w} ${h}`);

    const P = (p) => [p.x + 0.5, p.y + 0.5]; // standard pixel center alignment

    const frames = state.activeFrames;
    if (!frames || frames.length === 0) return;
    const cur = frames[state.i];
    if (!cur) return;

    // Flagged pixels of this frame (bundles carry them as two masks; frames.json as an image)
    if (state.overlays.flags) {
      const paint = (mask, cls) => {
        if (!Array.isArray(mask)) return;
        mask.forEach((row, y) => {
          if (!Array.isArray(row)) return;
          row.forEach((v, x) => { if (v) overlay.append(svgEl("rect", { x, y, width: 1, height: 1, class: cls })); });
        });
      };
      paint(cur.bad_pixel_mask, "mk-flag-bad");
      paint(cur.saturation_mask, "mk-flag-sat");
    }

    // Trajectory of predicted coordinates
    if (state.overlays.path && frames.length > 1) {
      const predPts = frames.map((f) => {
        const px = f.predicted_pixel_x ?? (f.predicted ? f.predicted.x : w / 2);
        const py = f.predicted_pixel_y ?? (f.predicted ? f.predicted.y : h / 2);
        return P({ x: px, y: py });
      });
      overlay.append(svgEl("polyline", { points: predPts.map((pt) => pt.join(",")).join(" "), class: "mk-traj" }));
      predPts.forEach(([x, y]) => overlay.append(svgEl("circle", { cx: x, cy: y, r: 0.25, class: "mk-dot" })));
    }

    // Predicted marker for current frame
    if (state.overlays.predicted) {
      const curPx = cur.predicted_pixel_x ?? (cur.predicted ? cur.predicted.x : w / 2);
      const curPy = cur.predicted_pixel_y ?? (cur.predicted ? cur.predicted.y : h / 2);
      const [px, py] = P({ x: curPx, y: curPy });
      const r = 2.2;
      overlay.append(svgEl("circle", { cx: px, cy: py, r, class: "mk-pred-halo" }));
      overlay.append(svgEl("circle", { cx: px, cy: py, r, class: "mk-pred" }));
    }

    // Measured centroid marker (only rendered when centroid measurement succeeded)
    const mxVal = cur.measured_centroid_x ?? (cur.measured ? cur.measured.x : null);
    const myVal = cur.measured_centroid_y ?? (cur.measured ? cur.measured.y : null);
    if (state.overlays.measured && mxVal !== null && myVal !== null) {
      const [mx, my] = P({ x: mxVal, y: myVal });
      const g = 0.9, a = 2.6;
      const d = `M${mx} ${my - a}V${my - g}M${mx} ${my + g}V${my + a}M${mx - a} ${my}H${mx - g}M${mx + g} ${my}H${mx + a}`;
      overlay.append(svgEl("path", { d, class: "mk-meas-halo" }));
      overlay.append(svgEl("path", { d, class: "mk-meas" }));
    }
  }

  function applyOverlays() {
    flagsImg.hidden = !(state.overlays.flags && state.legacyFlags && !state.diffMode);
    drawOverlay();
  }

  function setOverlay(key, on) {
    if (!(key in state.overlays)) return;
    state.overlays[key] = on;
    document.querySelectorAll(`input[data-overlay="${key}"]`).forEach((input) => { input.checked = on; });
    applyOverlays();
  }

  // ---------- frame checks: four cells that are always there (DESIGN §7.4) ----------
  function setStatus(id, kind, text, title) {
    const el = $(id);
    if (!el) return;
    el.textContent = text;
    el.className = "status-v is-" + kind;
    el.title = title || "";
  }

  // ---------- detail level: basic hides the numbers only a check needs (DESIGN §7.13) ----------
  function setMode(mode, { remember = true } = {}) {
    state.mode = mode === "advanced" ? "advanced" : "basic";
    const dialog = $("viewer-modal"), sw = $("mode-switch");
    if (dialog) dialog.dataset.mode = state.mode;
    if (sw) {
      sw.classList.toggle("is-advanced", state.mode === "advanced");
      sw.querySelectorAll("[role=radio]").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === state.mode)));
    }
    if (state.diffMode && state.mode === "basic") setDiffMode(false); // its button is not shown in basic
    if (remember) { try { localStorage.setItem("viewer-detail", state.mode); } catch { /* private window */ } }
  }

  // ---------- show frame or difference map ----------
  function show(i, { announce = false } = {}) {
    if (!state.bundle) return;

    if (state.diffMode && state.activeDiffMap) {
      const diffMap = state.activeDiffMap;
      img.src = diffMap.png_base64 || "";
      img.alt = `SPHEREx difference map for ${state.bundle.target.name}, Band ${diffMap.detector_band}, baseline ${diffMap.baseline_days.toFixed(1)} days`;
      flagsImg.hidden = true;

      live.setAttribute("aria-live", announce ? "polite" : "off");
      $("frame-count").textContent = `Difference Map · Band ${diffMap.detector_band}`;
      $("m-date").textContent = `${diffMap.baseline_days.toFixed(1)} days baseline`;
      const dLambda = diffMap.delta_wavelength_um != null ? Number(diffMap.delta_wavelength_um) : 0;
      $("m-wave").textContent = `${diffMap.mean_wavelength_um.toFixed(3)} µm`;
      $("m-det").textContent = `Band ${diffMap.detector_band}`;
      $("m-rel").textContent = "SPHEREx ΔI";
      $("m-pa").textContent = "Aligned (0°)";
      $("m-off").textContent = "Dipole signature";
      $("hud-date").textContent = `Δt = ${diffMap.baseline_days.toFixed(1)} d`;

      setStatus("st-roll", "acento", "↻ Aligned (0°)");
      setStatus("st-core", "off", "— Not applicable");
      setStatus("st-gaia", "acento", "± Dipole ΔI", `Dipole signature of proper motion in Band ${diffMap.detector_band}`);
      if (diffMap.delta_wavelength_um != null) {
        setStatus("st-wave", dLambda > 0.05 ? "aviso" : "ok", `${dLambda > 0.05 ? "⚠" : "✓"} Δλ ${dLambda.toFixed(3)} µm`,
          "Wavelength difference between the two epochs");
      } else {
        setStatus("st-wave", "off", "— Unknown Δλ");
      }

      const dLamStr = diffMap.delta_wavelength_um != null
        ? ` with spectral shift Δλ = ${dLambda.toFixed(3)} µm across epochs`
        : "";
      $("summary").innerHTML =
        `Difference map (<strong>ΔI = I<sub>t2</sub> − I<sub>t1</sub></strong>) shows the ` +
        `<strong>dipole signature of proper motion</strong> over ${diffMap.baseline_days.toFixed(1)} days in Band ${diffMap.detector_band}${dLamStr}: ` +
        `negative flux where the object was, and positive flux where it moved.`;

      drawOverlay();
      return;
    }

    const frames = state.activeFrames;
    if (!frames || frames.length === 0) return;

    state.i = (i + frames.length) % frames.length;
    const f = frames[state.i];

    // Image source: handle png_base64 Data URI or URL
    if (f.png_base64) {
      img.src = f.png_base64;
    } else if (f.image) {
      img.src = f.image;
    }

    const dateStr = f.obs_time_iso || f.date_utc || "";
    img.alt = `SPHEREx image of ${state.bundle.target.name}, ${dateStr.slice(0, 10)}, ${f.wavelength_um.toFixed(2)} µm`;

    state.legacyFlags = Boolean(f.flags);
    if (f.flags) {
      flagsImg.src = f.flags;
    }
    flagsImg.hidden = !(state.overlays.flags && state.legacyFlags);

    live.setAttribute("aria-live", announce ? "polite" : "off");
    $("frame-count").textContent = `Frame ${state.i + 1} / ${frames.length}`;
    $("m-date").textContent = fmtDate(dateStr);
    // The half-width of the filter is a number for the advanced level only
    $("m-wave").replaceChildren(document.createTextNode(f.wavelength_um.toFixed(3)));
    if (f.bandwidth_um) {
      const span = document.createElement("span");
      span.className = "adv";
      span.textContent = ` ± ${(f.bandwidth_um / 2).toFixed(3)}`;
      $("m-wave").append(span);
    }
    $("m-wave").append(document.createTextNode(" µm"));
    $("m-det").textContent = `Band ${f.detector_band || f.detector || "?"}`;
    $("m-rel").textContent = f.collection || f.release || "SPHEREx";
    const pa = f.sps_epa_deg ?? f.pa_deg ?? null;
    $("m-pa").textContent = pa !== null ? Math.round(pa) + "°" : "N/A";

    const off = f.centroid_offset_arcsec ?? f.offset_arcsec ?? null;
    $("m-off").textContent = off !== null ? off.toFixed(2) + "″" : "N/A";
    $("hud-date").textContent = dateStr.slice(0, 10);

    // Roll: the spacecraft saw this frame upside down and it was re-aligned north-up
    const rotated = pa !== null && (Math.abs(pa - 180) < 45 || f.rotated);
    setStatus("st-roll", rotated ? "acento" : "ok", rotated ? "↻ 180°, aligned" : "✓ 0°, as taken",
      rotated ? "Taken with the spacecraft rolled 180° and turned back north-up" : "Taken north-up");

    // Core saturation
    const saturated = Boolean(f.is_saturated_core || f.saturated);
    setStatus("st-core", saturated ? "aviso" : "ok", saturated ? "⚠ Saturated" : "✓ Not saturated",
      saturated ? "The core of the star is saturated: the centroid comes from its halo" : "");

    // Centroid against Gaia's prediction
    if (off !== null) {
      setStatus("st-gaia", off <= 0.5 ? "ok" : "aviso", `${off <= 0.5 ? "✓" : "⚠"} ${off.toFixed(2)}″ off`,
        `Measured centre ${off.toFixed(2)}″ from where Gaia DR3 predicts the star`);
    } else {
      setStatus("st-gaia", "off", "— Unmeasured", "No centroid: the star is diffuse or saturated here");
    }

    // Wavelength against the previous frame: a change in brightness between two colours proves nothing
    const prev = frames[state.i - 1];
    if (!prev) {
      setStatus("st-wave", "off", "— First frame");
    } else if (Math.abs(prev.wavelength_um - f.wavelength_um) > 0.05) {
      setStatus("st-wave", "aviso", `⚠ ${prev.wavelength_um.toFixed(2)}→${f.wavelength_um.toFixed(2)} µm`,
        "Different wavelength than the previous frame: a change in brightness is not variability");
    } else {
      setStatus("st-wave", "ok", "✓ Same as before", "Same wavelength as the previous frame: brightness can be compared");
    }

    document.querySelectorAll(".tl-dot").forEach((b, k) => b.setAttribute("aria-current", k === state.i ? "true" : "false"));
    placeTimelineLabel();
    drawOverlay();
  }

  // ---------- playback ----------
  function setPlaying(on) {
    state.playing = on;
    clearInterval(state.timer);
    const btn = $("play");
    btn.setAttribute("aria-pressed", String(on));
    btn.setAttribute("aria-label", on ? "Pause" : "Play");
    btn.innerHTML = on ? ICON_PAUSE : ICON_PLAY;
    if (on) {
      if (state.diffMode) setDiffMode(false);
      state.timer = setInterval(() => show(state.i + 1), 1000 / state.fps);
    }
  }

  function zoomTo(idx) {
    state.zoomIdx = Math.max(0, Math.min(ZOOMS.length - 1, idx));
    layout();
  }

  // ---------- difference map toggle ----------
  function getDiffMapForCurrentBand() {
    if (!state.bundle || !state.bundle.difference_maps || state.bundle.difference_maps.length === 0) {
      return null;
    }
    if (state.activeBand !== null) {
      return state.bundle.difference_maps.find((d) => Number(d.detector_band) === Number(state.activeBand)) || null;
    }
    return state.bundle.difference_maps[0];
  }

  function updateDiffToggleAvailability() {
    const diffBtn = $("diff-toggle");
    if (!diffBtn) return;
    const diffMap = getDiffMapForCurrentBand();
    if (diffMap) {
      diffBtn.disabled = false;
      const dLStr = diffMap.delta_wavelength_um != null ? `, Δλ=${diffMap.delta_wavelength_um.toFixed(3)} µm` : "";
      diffBtn.title = `Toggle difference map for Band ${diffMap.detector_band} (${diffMap.baseline_days.toFixed(1)} d baseline${dLStr})`;
    } else {
      diffBtn.disabled = true;
      diffBtn.title = "No difference map available for this band (requires 2+ epochs)";
      if (state.diffMode) setDiffMode(false);
    }
  }

  function setDiffMode(on) {
    state.diffMode = on;
    const diffBtn = $("diff-toggle");
    if (diffBtn) diffBtn.setAttribute("aria-pressed", String(on));
    if (on) {
      setPlaying(false);
      state.activeDiffMap = getDiffMapForCurrentBand();
      show(0);
    } else {
      show(state.i);
      summary();
    }
  }

  // ---------- timeline ----------
  // One dot per frame. Dots follow real time, with a floor on the gap so that frames taken a few
  // days apart do not pile up. Under the track: the first date, the last date and the current one.
  const TL_MIN_GAP = 14; // px between neighbouring dots
  const TL_HALF_TARGET = 22; // px: half of the widest touch target a dot gets

  function buildTimeline() {
    const box = $("timeline-dots");
    box.replaceChildren();
    state.tlX = null;
    const frames = state.activeFrames;
    if (!frames || frames.length === 0) return;

    frames.forEach((f, k) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tl-dot";
      b.setAttribute("aria-label", `Frame ${k + 1}, ${frameDay(f)}`);
      b.addEventListener("click", () => {
        if (state.diffMode) setDiffMode(false);
        setPlaying(false);
        show(k, { announce: true });
      });
      box.append(b);
    });
    $("tl-start").textContent = frameDay(frames[0]);
    $("tl-end").textContent = frames.length > 1 ? frameDay(frames[frames.length - 1]) : "";
    placeTimeline();
  }

  function placeTimeline() {
    const frames = state.activeFrames;
    const dots = [...document.querySelectorAll(".tl-dot")];
    const width = $("timeline-dots").clientWidth;
    if (!frames || !dots.length || dots.length !== frames.length || !width) return;

    const mjd = (f) => f.mjd_avg ?? f.mjd;
    const t0 = mjd(frames[0]);
    const span = mjd(frames[frames.length - 1]) - t0 || 1;
    const gap = Math.min(TL_MIN_GAP, width / Math.max(1, frames.length - 1));
    const free = width - gap * (frames.length - 1); // what is left to share out in proportion to time
    $("timeline-dots").classList.toggle("is-dense", gap < 12);
    const xs = frames.map((f, k) => gap * k + free * ((mjd(f) - t0) / span));

    dots.forEach((dot, k) => {
      // A dot owns the space up to halfway to each neighbour, so a tap lands on the dot under it.
      const before = k ? Math.min(TL_HALF_TARGET, (xs[k] - xs[k - 1]) / 2) : TL_HALF_TARGET;
      const after = k < xs.length - 1 ? Math.min(TL_HALF_TARGET, (xs[k + 1] - xs[k]) / 2) : TL_HALF_TARGET;
      dot.style.left = xs[k] - before + "px";
      dot.style.width = before + after + "px";
      dot.style.setProperty("--tl-mark", before + "px");
    });
    state.tlX = xs;
    placeTimelineLabel();
  }

  // The current date sits under its dot, kept inside the track; an end date steps aside for it.
  function placeTimelineLabel() {
    const frames = state.activeFrames;
    const current = $("tl-current");
    if (!frames || !state.tlX || !frames[state.i]) return;
    current.textContent = frameDay(frames[state.i]);
    const width = $("timeline-dots").clientWidth;
    const w = current.offsetWidth;
    const left = Math.max(0, Math.min(width - w, state.tlX[state.i] - w / 2));
    current.style.left = left + "px";
    $("tl-start").classList.toggle("is-hidden", left < $("tl-start").offsetWidth + 10);
    $("tl-end").classList.toggle("is-hidden", left + w > width - $("tl-end").offsetWidth - 10);
  }

  // ---------- band filter ----------
  function buildBandOptions(bundle) {
    const select = $("band-select");
    if (!select) return;
    select.replaceChildren();

    const bands = bundle.available_bands || [];
    const count = (n) => `${n} frame${n === 1 ? "" : "s"}`;
    const option = (value, label) => {
      const o = document.createElement("option");
      o.value = value;
      o.textContent = label;
      return o;
    };
    select.append(option("", `All bands · ${count(bundle.frames_chronological.length)}`));
    bands.forEach((b) => select.append(option(String(b), `Band ${b} · ${count(framesOfBand(bundle, b).length)}`)));
    select.value = state.activeBand === null ? "" : String(state.activeBand);
    select.closest(".band-row").hidden = bands.length === 0;
  }

  function selectBand(band) {
    if (state.diffMode) setDiffMode(false);
    state.activeBand = band;
    $("band-select").value = band === null ? "" : String(band);

    state.activeFrames = band === null ? state.bundle.frames_chronological : framesOfBand(state.bundle, band);

    buildTimeline();
    updateDiffToggleAvailability();
    summary();
    show(0);
  }

  // ---------- summary ----------
  const COMPASS_DIRS = [
    "north", "northeast", "east", "southeast",
    "south", "southwest", "west", "northwest",
  ];

  // Display coordinates have East to the left (dx < 0) and North up (dy < 0).
  function compassBearing(dx, dy) {
    if (dx === 0 && dy === 0) return "north";
    const angleDeg = (Math.atan2(-dx, -dy) * (180 / Math.PI) + 360) % 360;
    return COMPASS_DIRS[Math.round(angleDeg / 45) % 8];
  }

  function summary() {
    if (!state.bundle) return;
    const s = state.bundle.summary;
    const grid = state.bundle.grid;
    const pixScale = grid.pixel_scale_arcsec || 6.15;
    const frames = state.activeFrames;

    if (s && s.measured_motion_arcsec !== undefined) {
      const first = frames[0], last = frames[frames.length - 1];
      const dx = (last.predicted_pixel_x ?? last.predicted.x) - (first.predicted_pixel_x ?? first.predicted.x);
      const dy = (last.predicted_pixel_y ?? last.predicted.y) - (first.predicted_pixel_y ?? first.predicted.y);
      const dir = compassBearing(dx, dy);
      $("summary").innerHTML =
        `The object moved <strong>${s.measured_motion_arcsec.toFixed(1)}″ ${dir}</strong> in ${Math.round(s.days)} days ` +
        `(${(s.measured_motion_arcsec / pixScale).toFixed(1)} pixels). ` +
        `Gaia predicts <strong>${s.predicted_motion_arcsec.toFixed(1)}″</strong>.`;
      return;
    }

    if (!frames || frames.length < 2) {
      $("summary").innerHTML = `Target sequence has ${frames ? frames.length : 0} frame(s).`;
      return;
    }

    const first = frames[0], last = frames[frames.length - 1];
    const t0 = first.mjd_avg ?? first.mjd;
    const t1 = last.mjd_avg ?? last.mjd;
    const days = Math.max(1, Math.round(t1 - t0));

    const y0 = first.predicted_pixel_y ?? (first.predicted ? first.predicted.y : 0);
    const y1 = last.predicted_pixel_y ?? (last.predicted ? last.predicted.y : 0);
    const x0 = first.predicted_pixel_x ?? (first.predicted ? first.predicted.x : 0);
    const x1 = last.predicted_pixel_x ?? (last.predicted ? last.predicted.x : 0);

    const dx = x1 - x0;
    const dy = y1 - y0;
    const dir = compassBearing(dx, dy);
    const predDispPx = Math.hypot(dx, dy);
    const predDispArcsec = predDispPx * pixScale;

    // Measured motion if centroids are available
    const mx0 = first.measured_centroid_x ?? (first.measured ? first.measured.x : null);
    const my0 = first.measured_centroid_y ?? (first.measured ? first.measured.y : null);
    const mx1 = last.measured_centroid_x ?? (last.measured ? last.measured.x : null);
    const my1 = last.measured_centroid_y ?? (last.measured ? last.measured.y : null);

    const hasMeasured = mx0 !== null && my0 !== null && mx1 !== null && my1 !== null;
    const measDispPx = hasMeasured ? Math.hypot(mx1 - mx0, my1 - my0) : null;
    const measDispArcsec = measDispPx !== null ? measDispPx * pixScale : null;

    if (predDispArcsec < 0.5 && measDispPx !== null && measDispPx < 0.35) {
      $("summary").innerHTML =
        `Position is stationary within the ${pixScale.toFixed(2)}″ pixel scale over ${days} days ` +
        `(centroid offset ${measDispArcsec.toFixed(1)}″, ${measDispPx.toFixed(2)} pixels; ` +
        `Gaia predicts <strong>${predDispArcsec.toFixed(1)}″</strong>).`;
    } else if (measDispPx !== null) {
      $("summary").innerHTML =
        `The object moved <strong>${measDispArcsec.toFixed(1)}″ ${dir}</strong> in ${days} days ` +
        `(${measDispPx.toFixed(1)} pixels). ` +
        `Gaia astrometry predicts <strong>${predDispArcsec.toFixed(1)}″</strong>.`;
    } else {
      $("summary").innerHTML =
        `Gaia astrometry predicts <strong>${predDispArcsec.toFixed(1)}″ ${dir}</strong> displacement in ${days} days ` +
        `(${predDispPx.toFixed(1)} pixels). Photometric center is diffuse or saturated.`;
    }
  }

  // ---------- scientific warnings and citations ----------
  function renderWarningsAndCitations(bundle) {
    const warningsBlock = $("panel-warnings");
    const warningsList = $("warnings-list");
    if (warningsBlock && warningsList) {
      warningsList.replaceChildren();
      const warnings = bundle.scientific_warnings || [];
      if (warnings.length > 0) {
        warnings.forEach((w) => {
          const li = document.createElement("li");
          li.textContent = w;
          warningsList.append(li);
        });
        warningsBlock.hidden = false;
      } else {
        warningsBlock.hidden = true;
      }
    }

    const citationsBlock = $("panel-citations");
    const citationsList = $("citations-list");
    if (citationsBlock && citationsList) {
      citationsList.replaceChildren();
      const citations = bundle.citations || [];
      if (citations.length > 0) {
        citations.forEach((c) => {
          const li = document.createElement("li");
          li.textContent = c;
          citationsList.append(li);
        });
        citationsBlock.hidden = false;
      } else {
        citationsBlock.hidden = true;
      }
    }
  }

  // ---------- bundle adapter for backward compatibility ----------
  function normalizeBundle(raw) {
    if (raw.schema_version || raw.frames_chronological) {
      return raw;
    }
    // Legacy frames.json adapter
    const obj = raw.object || {};
    const grid = raw.grid || {};
    const frames = raw.frames || [];
    return {
      schema_version: "0.1.0-compat",
      target: {
        target_id: "barnards_star",
        name: obj.name || "Barnard's Star",
        category: "high_proper_motion",
        ra_deg: obj.ra || 269.4485,
        dec_deg: obj.dec || 4.7394,
        ref_epoch_jyear: 2016.0,
        pm_ra_cosdec_mas_yr: -801.551,
        pm_dec_mas_yr: 10362.394,
        parallax_mas: 546.976,
        cutout_size_arcsec: 180.0,
        collections: ["spherex_dr1", "spherex_qr3"],
        notes: "Barnard's Star legacy frames.",
      },
      grid: {
        center_ra_deg: grid.center_ra || 269.4485,
        center_dec_deg: grid.center_dec || 4.7394,
        pixel_scale_arcsec: grid.pixel_scale_arcsec || 6.15,
        width_px: grid.size_px || 31,
        height_px: grid.size_px || 31,
        orientation: "North-up, East-left (ICRS TAN)",
      },
      total_frames: frames.length,
      available_bands: [2],
      frames_chronological: frames.map((f, k) => ({
        frame_id: "barnard_legacy_" + (k + 1),
        collection: f.release || "spherex_dr1",
        detector_band: f.detector || 2,
        mjd_avg: f.mjd,
        obs_time_iso: f.date_utc,
        sps_epa_deg: f.pa_deg,
        wavelength_um: f.wavelength_um,
        bandwidth_um: 0.1,
        predicted_pixel_x: f.predicted ? f.predicted.x : 15,
        predicted_pixel_y: f.predicted ? f.predicted.y : 15,
        measured_centroid_x: f.measured ? f.measured.x : null,
        measured_centroid_y: f.measured ? f.measured.y : null,
        centroid_offset_arcsec: f.offset_arcsec,
        is_saturated_core: Boolean(f.saturated),
        image: f.image,
        flags: f.flags,
        predicted: f.predicted,
        measured: f.measured,
      })),
      frames_by_band: {
        "2": frames,
      },
      difference_maps: [],
      scientific_warnings: [
        "180-degree spacecraft roll (SPS_EPA) flip reprojected onto North-up grid.",
        "Saturated core detected in Barnard's Star; reconstructed from PSF halo.",
      ],
      citations: [
        "SPHEREx Explanatory Supplement & Data Release 1 (NASA/IPAC IRSA, 2026)",
        "Gaia Data Release 3 (ESA Gaia Collaboration, 2023)",
      ],
      summary: raw.summary,
    };
  }

  // ---------- target loader ----------
  const messages = {
    "live-disabled": "Live SPHEREx IRSA queries are currently disabled in the viewer configuration.",
    "no-observations": "No SPHEREx observations cover this position in the requested collections.",
    "job-lost": "This search is no longer available. Search again to reload the frames.",
    "upstream-unavailable": "The SPHEREx archive is temporarily unavailable. Please try again later.",
    "search-timeout": "This search is taking longer than expected. Search again to check for frames.",
    unavailable: "The SPHEREx frames could not be loaded. Please try again later.",
  };
  let targetRequest;

  // The loading scene (DESIGN §7.6): shown only if the answer takes more than a moment, so a
  // cached result opens the viewer straight away. Its station follows the phase the server reports.
  const LOADING_SHOW_AFTER_MS = 1200;
  const STEP_OF_PHASE = { submitting: 1, queued: 1, running: 2, result: 3 };
  function beginLoading() {
    const box = $("modal-loading");
    if (!box) return { progress() {}, end() {} };
    const t0 = performance.now();
    let step = 1, shown = false;
    const render = () => {
      box.dataset.step = String(step);
      box.querySelectorAll(".ld-steps li").forEach((li) => {
        if (Number(li.dataset.step) === step) li.setAttribute("aria-current", "step");
        else li.removeAttribute("aria-current");
      });
    };
    const elapsed = () => {
      const s = Math.floor((performance.now() - t0) / 1000);
      $("loading-elapsed").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    };
    const showTimer = setTimeout(() => { shown = true; render(); elapsed(); box.hidden = false; }, LOADING_SHOW_AFTER_MS);
    const tick = setInterval(() => { if (shown) elapsed(); }, 1000);
    return {
      progress(p) {
        step = STEP_OF_PHASE[p && p.phase] || step;
        if (shown) render();
      },
      end() { clearTimeout(showTimer); clearInterval(tick); box.hidden = true; },
    };
  }

  function setTargetStatus(message) {
    const status = $("modal-empty");
    if (!status) return;
    status.hidden = !message;
    $("modal-empty-msg").textContent = message || "";
    $("open-barnard").hidden = message === "Loading SPHEREx frames…";
  }

  async function loadTarget(targetInput) {
    let targetId = null;
    let ra = null, dec = null;

    if (typeof targetInput === "string") {
      const lower = targetInput.trim().toLowerCase();
      targetId = Object.hasOwn(BENCHMARK_MAP, lower) ? BENCHMARK_MAP[lower] : null;
    } else if (targetInput && typeof targetInput === "object") {
      ra = targetInput.ra ?? targetInput.ra_deg ?? null;
      dec = targetInput.dec ?? targetInput.dec_deg ?? null;

      const key = (targetInput.target_id || targetInput.key || targetInput.name)?.toLowerCase();
      if (Object.hasOwn(BENCHMARK_MAP, key)) targetId = BENCHMARK_MAP[key];

      if (!targetId && ra !== null && dec !== null) {
        const found = BENCHMARK_COORDS.find(
          (b) => Math.hypot((ra - b.ra) * Math.cos((dec * Math.PI) / 180), dec - b.dec) <= 0.05
        );
        if (found) targetId = found.target_id;
      }
    }

    targetRequest?.abort();
    const { signal } = (targetRequest = new AbortController());
    setPlaying(false);
    state.bundle = null;
    const help = document.querySelector(".modal-how");
    if (help) help.hidden = true;
    if ($("modal-empty")) {
      $("viewer").hidden = true;
      setTargetStatus("Loading SPHEREx frames…");
    }
    $("loading").hidden = false;
    const loading = beginLoading();
    let result;
    try {
      result = await window.viewerData.load({ targetId, ra, dec }, signal, loading.progress);
    } catch (error) {
      if (signal.aborted) return;
      throw error;
    } finally {
      loading.end();
    }
    if (signal.aborted) return;
    $("loading").hidden = true;

    if (result.status !== "ready") {
      const message = result.status === "queue-busy"
        ? `The search queue is busy. Try again in ${result.retryAfter} seconds.`
        : messages[result.status] || messages.unavailable;
      setTargetStatus(message);
      return;
    }
    const bundle = normalizeBundle(result.bundle);

    // Set bundle into viewer
    state.bundle = bundle;
    state.activeBand = null;
    state.activeFrames = bundle.frames_chronological;
    state.diffMode = false;
    state.activeDiffMap = null;
    state.i = 0;

    const grid = bundle.grid;
    state.cx = (grid.width_px || grid.size_px || 31) / 2;
    state.cy = (grid.height_px || grid.size_px || 31) / 2;

    setTargetStatus("");
    if ($("modal-empty")) $("viewer").hidden = false;
    if (help) help.hidden = false;

    // Header & metadata
    const tgt = bundle.target;
    if ($("modal-title")) {
      $("modal-title").textContent = tgt.name;
      $("modal-coords").textContent = `Gaia DR3 (${tgt.ref_epoch_jyear?.toFixed(1) || "2016.0"}) ${tgt.ra_deg.toFixed(4)}°, ${fmtDeg(tgt.dec_deg)} · FOV ${((grid.width_px || 31) * (grid.pixel_scale_arcsec || 6.15) / 60).toFixed(1)}′`;
    }
    $("obj-name").textContent = bundle.target.name;
    $("obj-coords").textContent = `RA ${tgt.ra_deg.toFixed(4)}°, Dec ${fmtDeg(tgt.dec_deg)}`;

    renderWarningsAndCitations(bundle);
    buildBandOptions(bundle);
    buildTimeline();
    updateDiffToggleAvailability();
    summary();
    show(0);
    layout();

    if (!reduceMotion && !$("viewer").hidden) setPlaying(true);
  }

  // ---------- events ----------
  $("prev").addEventListener("click", () => {
    if (state.diffMode) setDiffMode(false);
    setPlaying(false);
    show(state.i - 1, { announce: true });
  });

  $("next").addEventListener("click", () => {
    if (state.diffMode) setDiffMode(false);
    setPlaying(false);
    show(state.i + 1, { announce: true });
  });

  $("play").addEventListener("click", () => {
    if (state.diffMode) setDiffMode(false);
    setPlaying(!state.playing);
  });

  $("speed").addEventListener("input", (e) => {
    state.fps = Math.min(3, Number(e.target.value));
    $("speed-out").textContent = state.fps + " fps";
    if (state.playing) setPlaying(true);
  });

  $("zoom-in").addEventListener("click", () => zoomTo(state.zoomIdx + 1));
  $("zoom-out").addEventListener("click", () => zoomTo(state.zoomIdx - 1));
  $("zoom-reset").addEventListener("click", () => {
    const grid = state.bundle ? state.bundle.grid : null;
    const n = grid ? (grid.width_px || grid.size_px || 31) : 31;
    state.cx = state.cy = n / 2;
    zoomTo(0);
  });

  // Legend switches: one per kind of mark, plus All and None
  document.querySelectorAll("input[data-overlay]").forEach((input) => {
    input.addEventListener("change", (e) => setOverlay(e.target.dataset.overlay, e.target.checked));
  });
  const legacyFlagsToggle = $("flags-toggle");
  if (legacyFlagsToggle && !legacyFlagsToggle.dataset.overlay) {
    legacyFlagsToggle.addEventListener("change", (e) => setOverlay("flags", e.target.checked));
  }
  $("legend-all")?.addEventListener("click", () => Object.keys(state.overlays).forEach((k) => setOverlay(k, true)));
  $("legend-none")?.addEventListener("click", () => Object.keys(state.overlays).forEach((k) => setOverlay(k, false)));

  // Detail level: remembered between visits
  const modeSwitch = $("mode-switch");
  if (modeSwitch) {
    modeSwitch.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-mode]");
      if (btn) setMode(btn.dataset.mode);
    });
    modeSwitch.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      setMode(state.mode === "basic" ? "advanced" : "basic");
      modeSwitch.querySelector(`[data-mode="${state.mode}"]`).focus();
    });
  }
  let savedMode = null;
  try { savedMode = localStorage.getItem("viewer-detail"); } catch { /* private window */ }
  setMode(savedMode || "basic", { remember: false });

  const diffToggleBtn = $("diff-toggle");
  if (diffToggleBtn) {
    diffToggleBtn.addEventListener("click", () => {
      setDiffMode(!state.diffMode);
    });
  }

  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    zoomTo(state.zoomIdx + (e.deltaY < 0 ? 1 : -1));
  }, { passive: false });

  let drag = null;
  stage.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY, cx: state.cx, cy: state.cy };
    stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener("pointermove", (e) => {
    if (!drag || !state.bundle) return;
    const n = state.bundle.grid.width_px || state.bundle.grid.size_px || 31;
    const ppx = parseFloat(plate.style.width) / n;
    state.cx = drag.cx - (e.clientX - drag.x) / ppx;
    state.cy = drag.cy - (e.clientY - drag.y) / ppx;
    layout();
  });
  stage.addEventListener("pointerup", () => { drag = null; });

  $("viewer").addEventListener("keydown", (e) => {
    if (e.target.closest("input, button:not(.icon-btn)") && e.key === " ") return;
    const keys = {
      " ": () => {
        if (state.diffMode) setDiffMode(false);
        setPlaying(!state.playing);
      },
      ArrowLeft: () => {
        if (state.diffMode) setDiffMode(false);
        setPlaying(false);
        show(state.i - 1, { announce: true });
      },
      ArrowRight: () => {
        if (state.diffMode) setDiffMode(false);
        setPlaying(false);
        show(state.i + 1, { announce: true });
      },
      "+": () => zoomTo(state.zoomIdx + 1),
      "=": () => zoomTo(state.zoomIdx + 1),
      "-": () => zoomTo(state.zoomIdx - 1),
      "0": () => {
        const grid = state.bundle ? state.bundle.grid : null;
        const n = grid ? (grid.width_px || grid.size_px || 31) : 31;
        state.cx = state.cy = n / 2;
        zoomTo(0);
      },
    };
    if (keys[e.key] && !(e.target.type === "range")) {
      e.preventDefault();
      keys[e.key]();
    }
  });

  document.addEventListener("viewer:open", () => {
    if (!state.bundle) return;
    show(state.i);
    layout();
    if (!reduceMotion && !state.diffMode) setPlaying(true);
  });

  document.addEventListener("viewer:close", () => {
    if ($("viewer-modal")) targetRequest?.abort();
    setPlaying(false);
  });

  document.addEventListener("viewer:load-target", (e) => {
    if (e.detail) loadTarget(e.detail);
  });

  window.addEventListener("resize", () => state.bundle && !$("viewer").hidden && layout());
  // The timeline is laid out in pixels, so it follows its own width (also when the dialog opens).
  new ResizeObserver(() => placeTimeline()).observe($("timeline-dots"));
  $("band-select").addEventListener("change", (e) => selectBand(e.target.value === "" ? null : Number(e.target.value)));

  // Expose loadTarget globally for router and testing
  window.loadTarget = loadTarget;
  window.viewerState = state;

  // ---------- Interactive Guided Tour (DESIGN.md / Noir Cósmico v2) ----------
  const SKY_TOUR_STEPS = [
    {
      target: "#sky-canvas",
      isCanvas: true,
      title: "Explore the Sky in 3D",
      desc: "The whole sky seen from inside. Click and drag with mouse or touch to turn the celestial sphere in any direction (360°). Scroll or pinch to zoom into constellations and deep space.",
    },
    {
      target: ".sky-layers",
      title: "Wavelength & Spectral Layers",
      desc: "Switch the celestial sphere between Visible optical light (NASA SVS) and SPHEREx infrared all-sky surveys (4.77 µm and false-colour). The live readout displays the exact celestial coordinates (RA/Dec) where you are looking.",
    },
    {
      target: ".sky-tools",
      title: "Camera & Rotation Controls",
      desc: "Convenient controls to zoom in (+), zoom out (-), pause or resume background sky rotation, and instantly reset your camera back to the full celestial view.",
    },
    {
      target: "#search",
      title: "Target Search & Discovery",
      desc: "The core launchpad: select one of the 5 NASA benchmark objects (e.g., Barnard's Star or WISE 0855), search any star or galaxy via SIMBAD, or input custom RA/Dec. Click 'Go there' to travel across the sky and open the SPHEREx Blink Viewer.",
    },
    {
      target: ".header-actions",
      title: "Attribution & Tour Help",
      desc: "Review mission credits and scientific data citations (NASA IRSA, Gaia DR3, SIMBAD), or click the '?' button anytime to replay this interactive guide.",
    },
  ];

  const VIEWER_TOUR_STEPS = [
    {
      target: "#stage",
      title: "SPHEREx Multi-Epoch Stage",
      desc: "Reprojected, north-up SPHEREx image cutouts across observation epochs. Overlays highlight Gaia DR3 predicted position (teal dashed circle), measured centroid (amber cross), and trajectory over time.",
    },
    {
      target: ".controls",
      title: "Playback & Difference Map",
      desc: "Play or pause the blink sequence, step through epochs, adjust playback speed, and toggle Difference Map (ΔI) to immediately expose fast-moving or variable infrared sources.",
    },
    {
      target: ".band-row",
      title: "Spectral Band Filter",
      desc: "Filter observations across SPHEREx's 6 spectral detector bands (0.75 – 5.0 µm) to inspect identical wavelengths between different visits.",
    },
    {
      target: ".timeline-wrap",
      title: "Observation Timeline",
      desc: "Interactive timeline tracking each observation visit and UTC date. Click any dot to directly jump to a specific observation epoch.",
    },
    {
      target: ".panel",
      title: "Astrometry & Scientific Data",
      desc: "Detailed object metadata, proper motion displacement, astrometric offset against Gaia DR3, and scientific flags (e.g. saturated pixels or non-linear regimes).",
    },
  ];

  let currentTourSteps = [];
  let currentTourIndex = 0;
  let isTourActive = false;

  function initTour() {
    const tourBtn = $("tour-open");
    const modalTourBtn = $("modal-tour-open");
    const dialog = $("tour-dialog");
    const card = $("tour-card");
    const skipBtn = $("tour-skip");
    const prevBtn = $("tour-prev");
    const nextBtn = $("tour-next");
    let lastTriggerBtn = null;

    if (!dialog || !card) return;

    function startTour(triggerBtn) {
      lastTriggerBtn = triggerBtn || tourBtn;
      const modal = $("viewer-modal");
      const isModalOpen = modal && modal.open && !modal.hidden;
      currentTourSteps = isModalOpen ? VIEWER_TOUR_STEPS : SKY_TOUR_STEPS;
      currentTourIndex = 0;
      isTourActive = true;

      // If search panel is collapsed in sky mode, expand it so it's visible
      const journey = $("search");
      const searchBody = $("search-body");
      if (!isModalOpen && journey && searchBody && searchBody.hidden) {
        searchBody.hidden = false;
        journey.classList.remove("is-collapsed");
        const toggle = $("search-toggle");
        if (toggle) {
          toggle.textContent = "Hide";
          toggle.setAttribute("aria-expanded", "true");
        }
      }

      if (!dialog.open) {
        dialog.showModal();
      }
      renderTourStep();
    }

    function closeTour() {
      isTourActive = false;
      if (dialog && dialog.open) {
        dialog.close();
      }
      if (lastTriggerBtn && typeof lastTriggerBtn.focus === "function") {
        lastTriggerBtn.focus();
      }
    }

    function renderTourStep() {
      if (currentTourIndex < 0 || currentTourIndex >= currentTourSteps.length) {
        closeTour();
        return;
      }

      const step = currentTourSteps[currentTourIndex];
      const counter = $("tour-counter");
      const title = $("tour-title");
      const desc = $("tour-desc");

      if (counter) counter.textContent = `${currentTourIndex + 1} / ${currentTourSteps.length} · GUIDED TOUR`;
      if (title) title.textContent = step.title;
      if (desc) desc.textContent = step.desc;

      if (prevBtn) prevBtn.disabled = currentTourIndex === 0;
      if (nextBtn) {
        nextBtn.textContent = currentTourIndex === currentTourSteps.length - 1 ? "Finish" : "Next";
        nextBtn.focus();
      }

      updateSpotlightAndCard(step);
    }

    function updateSpotlightAndCard(step) {
      const spotlight = $("tour-spotlight");
      if (!spotlight || !card) return;

      const targetEl = document.querySelector(step.target);
      if (targetEl && targetEl.scrollIntoView && !step.isCanvas) {
        targetEl.scrollIntoView({ block: "nearest", inline: "nearest" });
      }

      let top, left, width, height, radius = "16px";

      if (step.isCanvas) {
        // Full screen selection for 3D Sky canvas: no awkward inner box!
        top = 0;
        left = 0;
        width = window.innerWidth;
        height = window.innerHeight;
        radius = "0px";
        spotlight.style.border = "2px solid rgba(184, 212, 240, 0.45)";
      } else if (!targetEl) {
        const w = Math.min(window.innerWidth * 0.9, 640);
        const h = 200;
        top = Math.round((window.innerHeight - h) / 2);
        left = Math.round((window.innerWidth - w) / 2);
        width = w;
        height = h;
        radius = "16px";
        spotlight.style.border = "1.5px solid rgba(184, 212, 240, 0.75)";
      } else {
        const rect = targetEl.getBoundingClientRect();
        const pad = 8;
        top = Math.max(4, Math.round(rect.top - pad));
        left = Math.max(4, Math.round(rect.left - pad));
        width = Math.round(rect.width + pad * 2);
        height = Math.round(rect.height + pad * 2);

        if (targetEl.classList.contains("tour-help-btn") || targetEl.classList.contains("icon-btn")) {
          radius = "50%";
        } else {
          radius = "16px";
        }
        spotlight.style.border = "1.5px solid rgba(184, 212, 240, 0.75)";
      }

      spotlight.style.top = `${top}px`;
      spotlight.style.left = `${left}px`;
      spotlight.style.width = `${width}px`;
      spotlight.style.height = `${height}px`;
      spotlight.style.borderRadius = radius;

      // Position card
      const cardW = Math.min(380, window.innerWidth - 32);
      const cardH = card.offsetHeight || 210;
      const vw = window.innerWidth;
      const vh = window.innerHeight;

      let cardTop, cardLeft;

      if (step.isCanvas) {
        cardTop = 80; // Top center below header
        cardLeft = Math.round((vw - cardW) / 2);
      } else if (top + height + cardH + 18 <= vh) {
        // Fits below target
        cardTop = top + height + 16;
        cardLeft = left + (width - cardW) / 2;
      } else if (top - cardH - 18 >= 0) {
        // Fits above target
        cardTop = top - cardH - 16;
        cardLeft = left + (width - cardW) / 2;
      } else if (left - cardW - 18 >= 0) {
        // Fits to the left
        cardLeft = left - cardW - 16;
        cardTop = top;
      } else {
        // Fits to the right
        cardLeft = left + width + 16;
        cardTop = top;
      }

      // Clamping within viewport
      cardLeft = Math.max(16, Math.min(vw - cardW - 16, cardLeft));
      cardTop = Math.max(16, Math.min(vh - cardH - 16, cardTop));

      card.style.top = `${cardTop}px`;
      card.style.left = `${cardLeft}px`;
      card.style.width = `${cardW}px`;
    }

    if (tourBtn) {
      tourBtn.addEventListener("click", () => {
        if (isTourActive) closeTour();
        else startTour(tourBtn);
      });
    }

    if (modalTourBtn) {
      modalTourBtn.addEventListener("click", () => {
        if (isTourActive) closeTour();
        else startTour(modalTourBtn);
      });
    }

    if (skipBtn) skipBtn.addEventListener("click", closeTour);
    if (prevBtn) prevBtn.addEventListener("click", () => {
      if (currentTourIndex > 0) {
        currentTourIndex--;
        renderTourStep();
      }
    });
    if (nextBtn) nextBtn.addEventListener("click", () => {
      if (currentTourIndex < currentTourSteps.length - 1) {
        currentTourIndex++;
        renderTourStep();
      } else {
        closeTour();
      }
    });

    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) closeTour();
    });

    dialog.addEventListener("cancel", (e) => {
      e.preventDefault();
      closeTour();
    });

    window.addEventListener("resize", () => {
      if (isTourActive) {
        updateSpotlightAndCard(currentTourSteps[currentTourIndex]);
      }
    });

    dialog.addEventListener("keydown", (e) => {
      if (!isTourActive) return;
      if (e.key === "Escape") {
        e.preventDefault();
        closeTour();
      } else if (e.key === "ArrowRight") {
        if (currentTourIndex < currentTourSteps.length - 1) {
          e.preventDefault();
          currentTourIndex++;
          renderTourStep();
        }
      } else if (e.key === "ArrowLeft") {
        if (currentTourIndex > 0) {
          e.preventDefault();
          currentTourIndex--;
          renderTourStep();
        }
      }
    });
  }

  initTour();

  // The legacy Aladin page opens its inline Barnard viewer without a target event.
  if (!$("viewer-modal")) loadTarget("barnards_star");
})();
