# SPHEREx blink viewer

The viewer displays live SPHEREx blink series fetched from IRSA via the `spherex_ingest` API for
the five challenge benchmarks and lets visitors look around the sky by test object, by name or by
coordinates. There are no local `mockup/data/` snapshots or `prepare_barnard.py` files: all blink
frames originate from the live IRSA ingestion backend.

The viewer stores successful processed blink bundles (images and metadata) in IndexedDB. Reopening
the same benchmark or exact coordinates in the same browser profile within one hour skips the
ingestion API. The cache holds up to 24 bundles and 24 MiB of bundle payloads; expired entries are
ignored and pruned on writes. Failed searches and bundles missing data due to upstream errors are
not cached. If browser storage is unavailable, searches still run against the API. On GCS, use the
bucket-specific viewer URL below: the path-style `storage.googleapis.com/<bucket>/...` URL serves
the same page but skips persistent caching because it shares an origin with other buckets.

- `index.html`, `sky.css`, `sky.js` — the **sky view**: the whole sky on screen, seen from inside,
  a search panel (one of the five test objects, an object name, or RA and Dec) that travels to the
  position, and the blink viewer in a dialog on arrival. Plain HTML/CSS/JS and one WebGL 2 shader; no libraries, no build step.
- `prepare_sky.py` — builds the three all-sky maps the sky view paints (`sky/*.webp`, `sky/sky.json`).
- `mockup.css`, `mockup.js`, `viewer-data.js`, `viewer-config.json` — the blink viewer, following `DESIGN.md` §7, configured to call `POST /api/v1/jobs` (with `GET /api/v1/blink` fallback for local sync servers).
- `aladin.html`, `sky-aladin.js` — **plan B**: the earlier version of the sky, drawn by Aladin Lite
  with sky maps streamed from IRSA. Kept because it can zoom all the way in. See "Plan B" below.

## Run it

```sh
# 1. serve the folder (fetch() does not work from file://); queries use viewer-config.json
uv run python -m http.server 8765 --directory mockup
# open http://127.0.0.1:8765/
```

Use Astral `uv` (`uv run ...`) or the project's Python (`.venv/bin/python` on Linux, `.venv\Scripts\python` on Windows, or the
shared `D:\dev\lab\.venvs\astro` on Miguel's laptop). Any static server works for step 1.

## Live IRSA hosting

Stage the public static viewer directory from the repository root:

```sh
uv run python scripts/build_hosting.py
uv run python -m http.server 8765 --directory dist/hosting
```

The build copies an explicit list of public HTML, CSS, JavaScript, and sky maps into
`dist/hosting`. Because `mockup/data/` has been removed, `benchmark-manifest.json` records
`version` (hashed from the public viewer assets), `commit_sha`, `"mode": "live_irsa"`, and
`"bundles": {}` with no local `releases/` directory. The standalone Aladin page remains available in
the local checkout.

In staging, the static viewer is hosted on the public GCS bucket
`gs://bortle-cero-nasa-staging-26-viewer` (`https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html`)
and deployed automatically on every push to `main` by `.github/workflows/cd-deploy.yml`, setting
`Cache-Control: no-cache` on mutable entrypoints and manifest (`index.html`, `*.js`, `*.css`,
`*.json`, `sky/sky.json`). Firebase Hosting via `firebase.json` (using `firebase emulators:start` or
`firebase hosting:channel:deploy`) remains an optional alternative.

With `viewer-config.json` pointing to `spherex-ingest-staging` on Cloud Run
(`https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app`, `liveQueries: true`), both benchmark
targets and arbitrary sky coordinates query IRSA through the bounded async job queue
(`POST /api/v1/jobs`, capped at 6 new jobs/min and 8 outstanding; `All` `roles/run.invoker` with
`GCP_REQUIRE_INVOKER_IAM=false` and `SPHEREX_LEGACY_SYNC_ENABLED=false`). For local development
against a local API, start `uv run spherex-ingest serve --host 127.0.0.1 --port 8000` and point
`apiBaseUrl` in your local `mockup/viewer-config.json` to `http://127.0.0.1:8000`.

Verify the live GCS deployment (or optional Firebase Hosting preview) at desktop and phone widths,
checking all five modal views, live coordinate queries, and `Cache-Control` headers:

```sh
curl -I https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html
curl -I https://storage.googleapis.com/bortle-cero-nasa-staging-26-viewer/benchmark-manifest.json
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
- **Looking around.** Drag with the mouse or a finger. When the sky is let go it keeps turning the
  way it was thrown and slows down; if it was spinning by itself before the drag, it settles back
  into that slow spin, now in the direction of the drag. The buttons on the right say what they do
  on hover and go dim when they would change nothing (zoom at its limit, whole sky already shown).
- **Coordinate grid and readout.** Switch on **Coordinate grid** in the sky controls to show
  lines every 30° of right ascension (RA) and 15° of declination (Dec). Brighter lines mark RA 0°
  and the celestial equator (Dec 0°). Move the pointer over the map or touch it to read the sky
  position in degrees. After you lift your finger, the last touched position stays visible.
- **Search.** Three ways to say where, and the last one touched counts. The five test objects come
  from a list in `sky.js` (Gaia DR3 positions and proper motions, moved to today) and are offered
  in a select; choosing one fills in RA and Dec. Any other object can be typed by name: the page
  asks SIMBAD through its mirror at Harvard (`vizier.cfa.harvard.edu`, the Sesame service), from
  the browser, and moves the J2000 position it gets to today with the proper motion. The names of
  the five test objects are answered from the list, with no network. Any place can also be given
  as RA and Dec. The name lookup was removed on 15 Nov to keep the phone layout clear and came back
  the same day in a layout that is no taller on a phone. The mirror does not know every catalogue
  name: on 15 Nov 2026 it found "Vega", "M31" and "Barnard's star", not "GJ 699" or "HIP 87937".
- **What opens on arrival.** Both the five benchmark targets and arbitrary coordinates or resolved
  object names open the blink viewer by querying live SPHEREx data from IRSA through the ingestion
  API configured in `viewer-config.json`.
- `window.skyPrototype` in the browser console gives the view's state.

### While the server works

A position the server has not seen takes a while (it asks IRSA, downloads a cutout per visit and
aligns them; Barnard's Star took 31 s and 52 s in two runs on 15 Nov, a random empty position
71 s). If the answer is not back within 1.2 s the dialog shows the journey of the data: a star,
the telescope, the IRSA archive and your screen, with three numbered stations that follow the
job's real phases (`queued`, `running`, result) and an elapsed-time counter. `viewer-data.js`
reports each phase through the `onProgress` callback of `viewerData.load`. A cached answer opens
the viewer directly. The server keeps a result for 24 hours, but in the memory of a Cloud Run
instance that scales to zero when idle, so the first visitor after a quiet spell waits again.
`DESIGN.md` §7.6 has the drawing's rules.

### The viewer's two levels of detail

The dialog opens in **Basic**: image, playback, band, timeline, the legend (each line switches its
marks on and off; All / None do the four at once), the frame's date, wavelength and detector, four
fixed check cells (roll, core, distance to Gaia, wavelength against the previous frame) and "What
moved". **Advanced**, the other position of the switch in the dialog's header, adds the difference
map, release, position angle, the measured distance to Gaia, the filter's half-width, the Gaia
position of the object, the scientific notes (under the timeline on a wide screen) and the
citations. The choice is remembered in the browser. The four cells are always there, so the panel
keeps its height from one frame to the next while playing. `DESIGN.md` §7.4 and §7.13 have the
details.

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
