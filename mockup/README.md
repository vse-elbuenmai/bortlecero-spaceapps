# SPHEREx blink viewer

The viewer displays prepared SPHEREx bundles for the five challenge benchmarks and lets visitors
look around the sky by test object, by name or by coordinates.

- `prepare_barnard.py` — downloads a few SPHEREx cutouts of Barnard's Star from IRSA, picks one
  per visit at nearly the same wavelength, re-aligns them north-up, stretches them and writes
  `data/barnard/` (PNGs + `frames.json`). Each step is explained at the top of the file.
- `index.html`, `sky.css`, `sky.js` — the **sky view**: the whole sky on screen, seen from inside,
  a search panel (one of the five test objects, an object name, or RA and Dec) that travels to the
  position, and the blink viewer in a dialog on arrival. Plain HTML/CSS/JS and one WebGL 2 shader; no libraries, no build step.
- `prepare_sky.py` — builds the three all-sky maps the sky view paints (`sky/*.webp`, `sky/sky.json`).
- `mockup.css`, `mockup.js` — the blink viewer, following `DESIGN.md` §7.
- `aladin.html`, `sky-aladin.js` — **plan B**: the earlier version of the sky, drawn by Aladin Lite
  with sky maps streamed from IRSA. Kept because it can zoom all the way in. See "Plan B" below.

## Run it

```sh
# 1. (optional) regenerate the data with uv — the PNGs and frames.json are already committed
uv run python mockup/prepare_barnard.py          # downloads ~48 MB to .cache/spherex (git-ignored)

# 2. serve the folder (fetch() does not work from file://)
uv run python -m http.server 8765 --directory mockup
# open http://127.0.0.1:8765/
```

Use Astral `uv` (`uv run ...`) or the project's Python (`.venv/bin/python` on Linux, `.venv\Scripts\python` on Windows, or the
shared `D:\dev\lab\.venvs\astro` on Miguel's laptop). Any static server works for step 2.

## Benchmark hosting

Build the Firebase Hosting directory from the repository root.

```sh
uv run python scripts/build_hosting.py
firebase emulators:start --only hosting --project demo-spherex
```

The build copies an explicit list of public HTML, CSS, JavaScript, and sky maps into
`dist/hosting`. `benchmark-manifest.json` maps the five targets to static bundles under
`releases/<release SHA-256>/`. The release changes only when the content of at least one bundle
changes. Firebase Hosting tells browsers to revalidate HTML, scripts, runtime configuration, sky
assets and the manifest. Versioned bundles use `public, max-age=31536000, immutable`.
The standalone Aladin page and its legacy data remain available in the local checkout.

On the public origin, the viewer opens benchmarks from the manifest and offers a benchmark-only
status for other positions. Synchronous live queries are available for local development over
HTTP on loopback addresses. To use them, start the API with
`uv run spherex-ingest serve --host 127.0.0.1 --port 8000`, then set `liveQueries` to `true` and
`apiBaseUrl` to `http://127.0.0.1:8000` in your local copy of `mockup/viewer-config.json`.
The client accepts only a loopback HTTP API for this mode. Keep the committed capability disabled.
Production coordinate queries depend on the asynchronous API and admission controls.

Wait for all five bundles to pass the scientific validation in
[issue #13](https://github.com/vse-elbuenmai/bortlecero-spaceapps/issues/13) before publishing a
preview or production release. After approval, rebuild from the reviewed commit and use the
Firebase CLI with the team's staging project. `STAGING_PROJECT_ID` below is a placeholder.

```sh
firebase hosting:channel:deploy benchmark-staging --project STAGING_PROJECT_ID --expires 1d
```

Open the resulting HTTPS preview at desktop and phone widths. Check all five modal views, the
decoded first image and the manifest paths, and confirm no asset requests use HTTP and no requests
go to the ingestion API. Check the cache headers on the preview with these commands, substituting
the preview host and the manifest's release hash.

```sh
curl -I https://PREVIEW_HOST/benchmark-manifest.json
curl -I https://PREVIEW_HOST/releases/RELEASE_HASH/barnards_star.json
```

Run the offline browser suite from the repository root with Node.js 22 and Playwright Chromium.

```sh
uv run python scripts/build_hosting.py
npm --prefix tests/browser ci
npm --prefix tests/browser exec -- playwright install chromium
npm --prefix tests/browser test
```

## What the data shows (run of 2026-11-14)

| Date (UTC) | Release | λ at the star | PA | Measured − Gaia |
|---|---|---|---|---|
| 2025-08-25 00:52 | DR1 | 4.750 µm | 180° | 1.39″ |
| 2026-03-19 09:08 | DR1 | 4.755 µm | 0° | 0.31″ |
| 2026-08-19 04:57 | QR3 | 4.732 µm | 180° | 0.46″ |

Barnard's Star moved **10.21″ (measured) vs 10.25″ (Gaia DR3 + parallax)** in 359 days, about
1.7 SPHEREx pixels. All three frames have a saturated core (OVERFLOW, BLOOM), which pulls the
centroid; the first frame is the worst.

## Sky view

The team's idea: the whole sky fills the screen and turns slowly; a search turns it to the position
and closes in; on arrival a dialog opens with the SPHEREx frames of that position.

- **Own sky maps, no map server.** Each layer is one image of the whole sky (a panorama, 4096 × 2048,
  with a 2048 × 1024 copy shown while it loads), painted on the inside of a sphere by one shader.
  Once the page has loaded the sky view needs the network only to look up object names.
- **Three layers.** "Visible light" is NASA SVS's Deep Star Maps 2020: a drawing from the Gaia,
  Hipparcos and Tycho catalogues, not a photograph. "SPHEREx 4.77 µm" is frame 95 of IRSA's SPHEREx
  DR1 all-sky cube. "SPHEREx false colour" is frames 95, 55 and 10 as red, green and blue; those three
  frames are placeholders for the team to choose. The cube is an *average* of 24 Apr 2025 to
  14 May 2026: a backdrop, never blink data. It is blank near the two ecliptic poles.
- **How close it gets.** One map pixel covers 5.3′ of sky, so the view stops where one screen pixel
  would show less than half a map pixel: about 60° across on a laptop, never closer than 30°. The
  trip ends there, with a ring on the position; the dialog is where the real pixels are.
- **Search.** Three ways to say where, and the last one touched counts. The five test objects come
  from a list in `sky.js` (Gaia DR3 positions and proper motions, moved to today) and are offered
  in a select; choosing one fills in RA and Dec. Any other object can be typed by name: the page
  asks SIMBAD through its mirror at Harvard (`vizier.cfa.harvard.edu`, the Sesame service), from
  the browser, and moves the J2000 position it gets to today with the proper motion. The names of
  the five test objects are answered from the list, with no network. Any place can also be given
  as RA and Dec. The name lookup was removed on 15 Nov to keep the phone layout clear and came back
  the same day in a layout that is no taller on a phone. The mirror does not know every catalogue
  name: on 15 Nov 2026 it found "Vega", "M31" and "Barnard's star", not "GJ 699" or "HIP 87937".
- **What opens on arrival.** The five test objects open the blink viewer with their prepared
  bundle. Any other position opens the dialog with a message: the public page shows the five
  benchmarks only (see "Benchmark hosting" above).
- `window.skyPrototype` in the browser console gives the view's state.

### Rebuilding the sky maps

```sh
uv run --with OpenEXR python mockup/prepare_sky.py   # downloads ~45 MB to .cache/sky (git-ignored)
```

The script checks itself and writes nothing if a check fails: six bright stars must sit on their
catalogue positions in every map (2026-11-14: 6 of 6 in the NASA map, 5 of 6 in the SPHEREx one,
where Vega is faint). That is also how the pixel order inside IRSA's tiles was settled: of the
eight possible orders only one puts the stars in place.

The view itself was checked the same way: with the page open, seven bright stars fall within 2
screen pixels of where `sky.js` computes them, in three different framings.

## Plan B: the sky drawn by Aladin Lite

`aladin.html` is the first version: Aladin Lite 3.8.2 (loaded from jsDelivr) streaming sky maps from
IRSA (DSS2 colour and the SPHEREx cube). It needs the network the whole time, but it can zoom down
to the star. Its three sky layers work with the two workarounds described below.

### What was checked in Aladin Lite 3.8.2 (2026-11-14)

1. **Picking one frame of the SPHEREx cube: works.** `hips.setFrequency(...)` with the frequency in
   the middle of the frame's interval; the browser then asks IRSA for the tiles of that frame
   (`Npix…_95.png`). Frame 0 is the exception: Aladin asks for `…_0.png`, which IRSA answers with 404.
2. **Mixing three frames as red, green and blue: works, with two workarounds** (both in `sky-aladin.js`,
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

- Only Barnard's Star has prepared frames. Any other position opens the
  dialog with a message.
- The "within X″ of Gaia" badge threshold (0.5″) is a placeholder for the team to decide.
- The project name in the header.
- Space Grotesk is not self-hosted yet; the page falls back to the system font.
