# Mockup: Barnard's Star blink viewer

A **mockup** so the team can see the viewer with real data while the real pipeline (download and
ingest) and the real frontend are being built. It is not the project's architecture: stack and
structure are still for the team to decide (see `AGENTS.md`).

- `prepare_barnard.py` — downloads a few SPHEREx cutouts of Barnard's Star from IRSA, picks one
  per visit at nearly the same wavelength, re-aligns them north-up, stretches them and writes
  `data/barnard/` (PNGs + `frames.json`). Each step is explained at the top of the file.
- `index.html`, `mockup.css`, `mockup.js` — the viewer, following `DESIGN.md` §7. Plain HTML/CSS/JS,
  no build step.

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

## What is fake in the mockup

- RA/Dec search and the other four test objects only show a message.
- The "within X″ of Gaia" badge threshold (0.5″) is a placeholder for the team to decide.
- The project name in the header.
- Space Grotesk is not self-hosted yet; the page falls back to the system font.
