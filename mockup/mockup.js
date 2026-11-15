// Interactive SPHEREx Multi-Epoch Blink Comparator Viewer
// Supports BlinkBundleDTO (FastAPI REST API and static bundles) and legacy frames.json.
(() => {
  "use strict";

  const ZOOMS = [1, 2, 4, 8];
  const SCALE_STEPS = [60, 30, 15, 10, 5, 2]; // arcsec, pick one that draws 40–140 px
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
  };

  const fmtDeg = (v, d = 4) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d) + "°";
  const fmtDate = (s) => (s ? s.slice(0, 16).replace("T", " ") + " UTC" : "N/A");
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

    const scale = grid.pixel_scale_arcsec || 6.15;
    const arcsec = SCALE_STEPS.find((a) => (a / scale) * ppx <= 140) || 2;
    $("scalebar").style.width = Math.round((arcsec / scale) * ppx) + "px";
    $("scalelabel").textContent = arcsec + "″";
  }

  // ---------- overlay: trajectory for all dates, markers for current one ----------
  function drawOverlay() {
    if (!state.bundle) return;
    if (state.diffMode) {
      overlay.replaceChildren();
      return;
    }
    const grid = state.bundle.grid;
    const w = grid.width_px || grid.size_px || 31;
    const h = grid.height_px || grid.size_px || 31;
    overlay.setAttribute("viewBox", `0 0 ${w} ${h}`);
    overlay.replaceChildren();

    const P = (p) => [p.x + 0.5, p.y + 0.5]; // standard pixel center alignment

    const frames = state.activeFrames;
    if (!frames || frames.length === 0) return;

    // Trajectory of predicted coordinates
    const predPts = frames.map((f) => {
      const px = f.predicted_pixel_x ?? (f.predicted ? f.predicted.x : w / 2);
      const py = f.predicted_pixel_y ?? (f.predicted ? f.predicted.y : h / 2);
      return P({ x: px, y: py });
    });

    if (predPts.length > 1) {
      const ptsStr = predPts.map((pt) => pt.join(",")).join(" ");
      overlay.append(svgEl("polyline", { points: ptsStr, class: "mk-traj" }));
    }
    predPts.forEach(([x, y]) => {
      overlay.append(svgEl("circle", { cx: x, cy: y, r: 0.25, class: "mk-dot" }));
    });

    // Predicted marker for current frame
    const cur = frames[state.i];
    if (!cur) return;
    const curPx = cur.predicted_pixel_x ?? (cur.predicted ? cur.predicted.x : w / 2);
    const curPy = cur.predicted_pixel_y ?? (cur.predicted ? cur.predicted.y : h / 2);
    const [px, py] = P({ x: curPx, y: curPy });
    const r = 2.2;
    overlay.append(svgEl("circle", { cx: px, cy: py, r, class: "mk-pred-halo" }));
    overlay.append(svgEl("circle", { cx: px, cy: py, r, class: "mk-pred" }));

    // Measured centroid marker (only rendered when centroid measurement succeeded)
    const mxVal = cur.measured_centroid_x ?? (cur.measured ? cur.measured.x : null);
    const myVal = cur.measured_centroid_y ?? (cur.measured ? cur.measured.y : null);
    if (mxVal !== null && myVal !== null) {
      const [mx, my] = P({ x: mxVal, y: myVal });
      const g = 0.9, a = 2.6;
      const d = `M${mx} ${my - a}V${my - g}M${mx} ${my + g}V${my + a}M${mx - a} ${my}H${mx - g}M${mx + g} ${my}H${mx + a}`;
      overlay.append(svgEl("path", { d, class: "mk-meas-halo" }));
      overlay.append(svgEl("path", { d, class: "mk-meas" }));
    }
  }

  // ---------- badges ----------
  function badge(kind, icon, text) {
    const li = document.createElement("li");
    li.className = "badge badge-" + kind;
    const ic = document.createElement("span");
    ic.setAttribute("aria-hidden", "true");
    ic.textContent = icon;
    li.append(ic, document.createTextNode(" " + text));
    return li;
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
      $("m-wave").textContent = `${diffMap.mean_wavelength_um.toFixed(3)} µm (Δλ = ${dLambda.toFixed(3)} µm)`;
      $("m-det").textContent = `Band ${diffMap.detector_band}`;
      $("m-rel").textContent = "SPHEREx ΔI";
      $("m-pa").textContent = "Aligned (0°)";
      $("m-off").textContent = "Dipole signature";
      $("hud-date").textContent = `Δt = ${diffMap.baseline_days.toFixed(1)} d`;

      const badges = $("badges");
      badges.replaceChildren();
      badges.append(badge("acento", "±", `Dipole ΔI (Band ${diffMap.detector_band})`));
      badges.append(badge("ok", "✓", `${diffMap.baseline_days.toFixed(1)} days baseline`));
      if (diffMap.delta_wavelength_um != null) {
        badges.append(badge("acento", "λ", `Δλ = ${dLambda.toFixed(3)} µm`));
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

    // Image source: handle png_base64 Data URI or relative path
    if (f.png_base64) {
      img.src = f.png_base64;
    } else if (f.image) {
      const path = f.image.startsWith("data:") ? f.image : (f.image.includes("/") ? f.image : `data/barnard/${f.image}`);
      img.src = path;
    }

    const dateStr = f.obs_time_iso || f.date_utc || "";
    img.alt = `SPHEREx image of ${state.bundle.target.name}, ${dateStr.slice(0, 10)}, ${f.wavelength_um.toFixed(2)} µm`;

    if (f.flags) {
      const fPath = f.flags.startsWith("data:") ? f.flags : (f.flags.includes("/") ? f.flags : `data/barnard/${f.flags}`);
      flagsImg.src = fPath;
    } else {
      flagsImg.hidden = true;
    }

    live.setAttribute("aria-live", announce ? "polite" : "off");
    $("frame-count").textContent = `Frame ${state.i + 1} / ${frames.length}`;
    $("m-date").textContent = fmtDate(dateStr);
    $("m-wave").textContent = f.wavelength_um.toFixed(3) + " µm" +
      (f.bandwidth_um ? ` (±${(f.bandwidth_um / 2).toFixed(3)} µm)` : "");
    $("m-det").textContent = `Band ${f.detector_band || f.detector || "?"}`;
    $("m-rel").textContent = f.collection || f.release || "SPHEREx";
    const pa = f.sps_epa_deg ?? f.pa_deg ?? null;
    $("m-pa").textContent = pa !== null ? Math.round(pa) + "°" : "N/A";

    const off = f.centroid_offset_arcsec ?? f.offset_arcsec ?? null;
    $("m-off").textContent = off !== null ? off.toFixed(2) + "″" : "N/A";
    $("hud-date").textContent = dateStr.slice(0, 10);

    const badges = $("badges");
    badges.replaceChildren();

    // Roll rotation badge
    if (pa !== null && (Math.abs(pa - 180) < 45 || f.rotated)) {
      badges.append(badge("acento", "↻", "Rotated 180°, re-aligned"));
    }

    // Core saturation badge
    if (f.is_saturated_core || f.saturated) {
      badges.append(badge("aviso", "⚠", "Saturated core (halo centroid)"));
    }

    // Centroid astrometry badge
    if (off !== null) {
      if (off <= 0.5) badges.append(badge("ok", "✓", `${off.toFixed(2)}″ from Gaia`));
      else badges.append(badge("aviso", "⚠", `${off.toFixed(2)}″ from Gaia`));
    } else if (f.measured_centroid_x === null && !f.measured) {
      badges.append(badge("aviso", "—", "Unmeasured / diffuse"));
    }

    // Wavelength jump warning
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
  function buildTimeline() {
    const box = $("timeline-dots");
    box.replaceChildren();
    const frames = state.activeFrames;
    if (!frames || frames.length === 0) return;

    const t0 = frames[0].mjd_avg ?? frames[0].mjd;
    const t1 = frames[frames.length - 1].mjd_avg ?? frames[frames.length - 1].mjd;
    const span = t1 - t0 || 1;

    frames.forEach((f, k) => {
      const mjd = f.mjd_avg ?? f.mjd;
      const pct = ((mjd - t0) / span) * 100;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tl-dot";
      b.style.left = pct + "%";
      const dateStr = (f.obs_time_iso || f.date_utc || "").slice(0, 10);
      b.setAttribute("aria-label", `Frame ${k + 1}, ${dateStr}`);
      b.addEventListener("click", () => {
        if (state.diffMode) setDiffMode(false);
        setPlaying(false);
        show(k, { announce: true });
      });
      const label = document.createElement("span");
      label.className = "tl-label";
      label.style.left = pct + "%";
      label.textContent = dateStr;
      box.append(b, label);
    });
  }

  // ---------- band filtering chips ----------
  function buildBandChips(bundle) {
    const container = $("band-chips");
    if (!container) return;
    container.replaceChildren();

    const bands = bundle.available_bands || [];
    if (bands.length === 0) return;

    // "All bands" chip
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = "chip band-chip" + (state.activeBand === null ? " is-active" : "");
    allBtn.textContent = `All Bands (${bundle.frames_chronological.length})`;
    allBtn.setAttribute("aria-pressed", state.activeBand === null ? "true" : "false");
    allBtn.addEventListener("click", () => selectBand(null));
    container.append(allBtn);

    // Individual spectral band chips
    bands.forEach((b) => {
      const bKey = String(b);
      const framesInBand = bundle.frames_by_band && bundle.frames_by_band[bKey]
        ? bundle.frames_by_band[bKey]
        : bundle.frames_chronological.filter((f) => Number(f.detector_band) === Number(b));

      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip band-chip" + (state.activeBand === b ? " is-active" : "");
      chip.textContent = `Band ${b} (${framesInBand.length})`;
      chip.setAttribute("aria-pressed", state.activeBand === b ? "true" : "false");
      chip.addEventListener("click", () => selectBand(b));
      container.append(chip);
    });
  }

  function selectBand(band) {
    if (state.diffMode) setDiffMode(false);
    state.activeBand = band;

    // Update band chips UI
    document.querySelectorAll(".band-chip").forEach((btn) => {
      const isAll = btn.textContent.startsWith("All Bands");
      const isThisBand = btn.textContent.startsWith(`Band ${band} `);
      const active = (band === null && isAll) || (band !== null && isThisBand);
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", String(active));
    });

    if (band === null) {
      state.activeFrames = state.bundle.frames_chronological;
    } else {
      const bKey = String(band);
      state.activeFrames = state.bundle.frames_by_band && state.bundle.frames_by_band[bKey]
        ? state.bundle.frames_by_band[bKey]
        : state.bundle.frames_chronological.filter((f) => Number(f.detector_band) === Number(band));
    }

    buildTimeline();
    updateDiffToggleAvailability();
    summary();
    show(0);
  }

  // ---------- summary ----------
  function summary() {
    if (!state.bundle) return;
    const s = state.bundle.summary;
    const grid = state.bundle.grid;
    const pixScale = grid.pixel_scale_arcsec || 6.15;
    const frames = state.activeFrames;

    if (s && s.measured_motion_arcsec !== undefined) {
      const first = frames[0], last = frames[frames.length - 1];
      const dir = (last.predicted_pixel_y ?? last.predicted.y) < (first.predicted_pixel_y ?? first.predicted.y)
        ? "north" : "south";
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

    const dir = y1 < y0 ? "north" : "south";
    const predDispPx = Math.hypot(x1 - x0, y1 - y0);
    const predDispArcsec = predDispPx * pixScale;

    // Measured motion if centroids are available
    const mx0 = first.measured_centroid_x ?? (first.measured ? first.measured.x : null);
    const my0 = first.measured_centroid_y ?? (first.measured ? first.measured.y : null);
    const mx1 = last.measured_centroid_x ?? (last.measured ? last.measured.x : null);
    const my1 = last.measured_centroid_y ?? (last.measured ? last.measured.y : null);

    if (mx0 !== null && my0 !== null && mx1 !== null && my1 !== null) {
      const measDispPx = Math.hypot(mx1 - mx0, my1 - my0);
      const measDispArcsec = measDispPx * pixScale;
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
  async function loadTarget(targetInput) {
    let targetId = null;
    let ra = null, dec = null, name = null;

    if (typeof targetInput === "string") {
      const lower = targetInput.trim().toLowerCase();
      targetId = BENCHMARK_MAP[lower] || lower;
    } else if (targetInput && typeof targetInput === "object") {
      name = targetInput.name;
      ra = targetInput.ra ?? targetInput.ra_deg;
      dec = targetInput.dec ?? targetInput.dec_deg;

      if (targetInput.target_id) {
        targetId = BENCHMARK_MAP[targetInput.target_id.toLowerCase()] || targetInput.target_id;
      } else if (targetInput.key) {
        targetId = BENCHMARK_MAP[targetInput.key.toLowerCase()] || targetInput.key;
      } else if (name) {
        targetId = BENCHMARK_MAP[name.toLowerCase()] || null;
      }

      if (!targetId && ra !== null && dec !== null) {
        const found = BENCHMARK_COORDS.find(
          (b) => Math.hypot((ra - b.ra) * Math.cos((dec * Math.PI) / 180), dec - b.dec) <= 0.05
        );
        if (found) targetId = found.target_id;
      }
    }

    $("loading").hidden = false;
    $("loading").querySelector("p").textContent = `Loading frames for ${name || targetId || "target"}…`;

    let bundle = null;

    // Candidate URL sources in order of priority:
    // 1. Live FastAPI service
    // 2. Static precomputed bundle in data/<target_id>/bundle.json
    // 3. Fallback data/barnard/frames.json
    const candidates = [];
    if (targetId) {
      candidates.push(`http://localhost:8000/api/v1/blink/${targetId}`);
      candidates.push(`data/${targetId}/bundle.json`);
    } else if (ra !== null && dec !== null) {
      candidates.push(`http://localhost:8000/api/v1/blink?ra=${ra}&dec=${dec}&size_arcsec=180`);
    }
    if (targetId === "barnards_star") {
      candidates.push("data/barnard/frames.json");
    }

    for (const url of candidates) {
      try {
        const resp = await fetch(url, { signal: AbortSignal.timeout(3500) });
        if (resp.ok) {
          const raw = await resp.json();
          bundle = normalizeBundle(raw);
          break;
        }
      } catch {
        // try next candidate
      }
    }

    $("loading").hidden = true;

    if (!bundle || !bundle.frames_chronological || bundle.frames_chronological.length === 0) {
      // Show empty state
      $("viewer").hidden = true;
      $("modal-empty").hidden = false;
      $("modal-title").textContent = name || (targetId ? targetId.replace(/_/g, " ") : "Your position");
      $("modal-coords").textContent = ra !== null && dec !== null
        ? `${fmtDeg(ra, 4)}, ${fmtDeg(dec, 4)}`
        : "";
      const emptyMsg = $("modal-empty-msg");
      if (emptyMsg) {
        emptyMsg.textContent =
          "No precomputed SPHEREx frames available for this target. Start the local ingestion service to process on the fly: uv run spherex-ingest serve --host 0.0.0.0 --port 8000";
      }
      return;
    }

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

    $("modal-empty").hidden = true;
    $("viewer").hidden = false;
    document.querySelector(".modal-how").hidden = false;

    // Header & metadata
    $("modal-title").textContent = bundle.target.name;
    const tgt = bundle.target;
    $("modal-coords").textContent = `Gaia DR3 (${tgt.ref_epoch_jyear?.toFixed(1) || "2016.0"}) ${tgt.ra_deg.toFixed(4)}°, ${fmtDeg(tgt.dec_deg)} · FOV ${((grid.width_px || 31) * (grid.pixel_scale_arcsec || 6.15) / 60).toFixed(1)}′`;
    $("obj-name").textContent = bundle.target.name;
    $("obj-coords").textContent = `RA ${tgt.ra_deg.toFixed(4)}°, Dec ${fmtDeg(tgt.dec_deg)}`;

    renderWarningsAndCitations(bundle);
    buildBandChips(bundle);
    buildTimeline();
    updateDiffToggleAvailability();
    summary();
    show(0);
    layout();

    if (!reduceMotion) setPlaying(true);
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

  $("flags-toggle").addEventListener("change", (e) => {
    flagsImg.hidden = !e.target.checked;
  });

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

  document.addEventListener("viewer:close", () => setPlaying(false));

  document.addEventListener("viewer:load-target", (e) => {
    if (e.detail) loadTarget(e.detail);
  });

  window.addEventListener("resize", () => state.bundle && !$("viewer").hidden && layout());

  // Expose loadTarget globally for router and testing
  window.loadTarget = loadTarget;
  window.viewerState = state;

  // Initial load: Barnard's Star bundle
  loadTarget("barnards_star");
})();
