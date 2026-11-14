# Mockup: Barnard's Star blink viewer

A **mockup** so the team can see the viewer with real data while the real pipeline (download and
ingest) and the real frontend are being built. It is not the project's architecture: stack and
structure are still for the team to decide (see `AGENTS.md`).

- `prepare_barnard.py` — downloads a few SPHEREx cutouts of Barnard's Star from IRSA, picks one
  per visit at nearly the same wavelength, re-aligns them north-up, stretches them and writes
  `data/barnard/` (PNGs + `frames.json`). Each step is explained at the top of the file.
- `index.html`, `mockup.css`, `mockup.js` — the viewer, following `DESIGN.md` §7. Plain HTML/CSS/JS,
  no build step.
- `sky.js` — the **sky sphere prototype** (branch `claude/esfera-viaje`): a spinning sky drawn by
  Aladin Lite, a RA/Dec search that travels there (`animateToRaDec`, then `zoomToFoV`), and the
  viewer opening on arrival at Barnard's Star. See "Sky sphere prototype" below.

## Run it

```sh
# 1. (optional) regenerate the data — the PNGs and frames.json are already committed
python mockup/prepare_barnard.py          # downloads ~48 MB to .cache/spherex (git-ignored)

# 2. serve the folder (fetch() does not work from file://)
python -m http.server 8765 --directory mockup
# open http://127.0.0.1:8765/
```

Use the project's Python (`.venv/bin/python` on Linux, `.venv\Scripts\python` on Windows, or the
shared `D:\dev\lab\.venvs\astro` on Miguel's laptop). Any static server works for step 2.

## What the data shows (run of 2026-11-14)

| Date (UTC) | Release | λ at the star | PA | Measured − Gaia |
|---|---|---|---|---|
| 2025-08-25 00:52 | DR1 | 4.750 µm | 180° | 1.39″ |
| 2026-03-19 09:08 | DR1 | 4.755 µm | 0° | 0.31″ |
| 2026-08-19 04:57 | QR3 | 4.732 µm | 180° | 0.46″ |

Barnard's Star moved **10.21″ (measured) vs 10.25″ (Gaia DR3 + parallax)** in 359 days, about
1.7 SPHEREx pixels. All three frames have a saturated core (OVERFLOW, BLOOM), which pulls the
centroid; the first frame is the worst.

## Sky sphere prototype

The team's idea in three moments: at rest the sky turns on its own; a search turns it to the
coordinates and zooms in; on arrival the sky steps back and the working panel appears.

- **Needs the network.** Aladin Lite 3.8.2 is loaded from jsDelivr (it serves the npm package; the
  same version IRSA's own sky-map pages use) and the sky maps come from IRSA. Nothing talks to CDS,
  whose servers are down. Needs WebGL 2. Without either, the page says so and search still opens
  Barnard's Star.
- **Two different sources, and the page says which is which.** The sphere shows all-sky maps: the
  DSS2 colour survey (visible light) and the SPHEREx DR1 all-sky cube, an *average* of 24 Apr 2025 to
  14 May 2026. The panel shows the dated SPHEREx frames. An average cannot be blinked.
- **Sky layers.** "SPHEREx 4.77 µm" is frame 95 of the cube, the one closest to the wavelength of the
  Barnard frames. "SPHEREx false colour" adds frames 95, 55 and 10 as red, green and blue; those
  three frames are placeholders for the team to choose.
- **Test objects other than Barnard's Star** use SIMBAD positions for epoch 2000. Fast movers have
  drifted since (WISE 0855−0714 by about 2′): the real tool has to propagate them to today.
- `window.skyPrototype` in the browser console gives the Aladin instance and the layers.

### What was checked in Aladin Lite 3.8.2 (2026-11-14)

1. **Picking one frame of the SPHEREx cube: works.** `hips.setFrequency(...)` with the frequency in
   the middle of the frame's interval; the browser then asks IRSA for the tiles of that frame
   (`Npix…_95.png`). Frame 0 is the exception: Aladin asks for `…_0.png`, which IRSA answers with 404.
2. **Mixing three frames as red, green and blue: works, with two workarounds** (both in `sky.js`,
   both tied to this version):
   - Aladin's engine identifies a sky map by its `creator_did`, so three layers of the same cube
     end up sharing one frame. Each layer gets its own id by wrapping a private method
     (`_parseProperties`).
   - With additive blending on, a fully opaque layer still covers the ones below. Opacity 0.99 on
     the green and blue layers makes them add up.
3. **Overlaying a cutout by its WCS: works only with a plain WCS.**
   - The cutout as IRSA delivers it (TAN-SIP, reference pixel outside the image) loads without an
     error but lands in the wrong place: RA 178.81°, Dec +13.59° instead of 269.45°, +4.77°. Rewriting
     the matrix as `CD` and keeping SIP does not fix it.
   - With the header rewritten as plain TAN, fitted at the centre of the cutout (it differs from the
     full WCS by at most 0.04″ over 47 pixels), Aladin puts all three dates in the right place and
     undoes the 180° rotation by itself: the field stars coincide between dates.
   - The north-up PNGs of this mockup, with their WCS passed as an object to `A.image`, also land in
     the right place.
   - Either way a preparation step is needed: IRSA's cutouts are 4 MB and are not served with CORS,
     while the image extension alone is 14 KB.

## What is fake in the mockup

- Only Barnard's Star has prepared frames. Any other position, typed or from a chip, shows the sky
  map and a message.
- The "within X″ of Gaia" badge threshold (0.5″) is a placeholder for the team to decide.
- The project name in the header.
- Space Grotesk is not self-hosted yet; the page falls back to the system font.
