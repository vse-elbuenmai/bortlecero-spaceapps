# Bortle Cero — Planet X and SPHEREx Blink Comparator

**Team Bortle Cero** (Guadalajara Local Event) submission repository for the **NASA Space Apps Challenge 2026** challenge: [**Planet X and SPHEREx**](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/).

---

## Overview

NASA's **SPHEREx** (*Spectro-Photometer for the History of the Universe, Epoch of Reionization, and Ices Explorer*) maps the entire sky every six months across 102 near-infrared spectral channels ($0.75\text{–}5.0\,\mu\text{m}$) at $6.15''/\text{pixel}$ resolution. By comparing multi-epoch SPHEREx observations of the same patch of sky, astronomers and citizen scientists can spot high-proper-motion objects (nearby brown dwarfs, solar system bodies, or a hypothetical Planet X) and variable stars.

However, **naively blinking raw SPHEREx cutouts fails** due to six physical and instrumental characteristics of the observatory (documented in [Bock et al. 2026](https://doi.org/10.3847/1538-4357/ae2be2), [Akeson et al. 2026](https://doi.org/10.3847/1538-4365/ae8843), and [Crill et al. 2025](https://doi.org/10.3847/1538-4365/ae04cc)):

1. **$180^\circ$ Spacecraft Roll Flip (`SPS_EPA`):** Between survey passes, the telescope views the same sky region rotated by $180^\circ$ with up to $0.5\%$ optical distortion. Without reprojecting onto a unified North-up celestial grid, stars jump wildly across the frame.
2. **Linear Variable Filter (LVF) Wavelength Gradient:** Every detector pixel samples a different wavelength $\lambda(x, y)$. A source's apparent brightness changes between exposures simply because it fell on different spectral bandpasses unless frames are tagged via the `WCS-WAVE` lookup table and grouped by spectral band (Bands 1–6).
3. **Unsubtracted Zodiacal Light Foreground (`ZODI`):** SPHEREx Level 2b `IMAGE` extensions include the zodiacal dust foreground (which varies by up to $3\times$ over the year). The `ZODI` extension must be subtracted (`IMAGE - ZODI`) before comparing epochs.
4. **Saturated Cores & Bitmask `FLAGS`:** Bright benchmark targets such as **Barnard's Star** and **R Draconis** saturate the H2RG detector core (producing `NaN` values and setting the `OVERFLOW` bit in `FLAGS`), while ~1.1% of pixels suffer cosmic-ray transients. Our pipeline decodes the 32-bit `FLAGS` bitmask, masks transient artifacts, and reconstructs saturated stellar cores for visual blinking and exposes saturation masks alongside the display matrices.
5. **Sub-Pixel Proper Motion & Parallax:** Even the fastest star in the sky (**Barnard's Star**, $10.39''/\text{yr}$) moves only $\approx 0.84\text{ pixels}$ per 6-month survey pass, with a trigonometric parallax ellipse of $0.55''$ ($1.09''$ peak-to-peak). Our pipeline propagates Gaia DR3 astrometry ($\mu_{\alpha^*}, \mu_\delta, \varpi$) to the exact `MJD-AVG` of each exposure using `astropy.coordinates.SkyCoord.apply_space_motion` and measures sub-pixel centroids.
6. **WISE J085510.83−071442.5 Epoch Shift & Extreme Cold SED:** The challenge prompt coordinates for WISE 0855−0714 are from its ~2010 discovery epoch; by 2025–2026 it has moved ~20 SPHEREx pixels West to $\text{RA}\approx 133.760^\circ, \text{Dec}\approx -7.2422^\circ$, and at $T_{\text{eff}} \approx 250\text{ K}$ it is detectable only at $\lambda > 3.9\,\mu\text{m}$ (SPHEREx Bands 5 and 6).

---

## Data ingestion pipeline

The viewer submits a sky position or benchmark ID to the FastAPI job API. For a
new search, the worker queries IRSA for matching SPHEREx Level 2b exposures and
downloads only the selected FITS cutouts. It subtracts the zodiacal foreground,
handles detector artifacts, aligns the images on a common sky grid, and exports a
blink bundle with PNGs, spectral metadata, quality masks, and difference maps.

The [ingestion guide](docs/GUIA-EQUIPO-INGESTA.md) walks through the full process
in Spanish, from IRSA discovery and download to image preprocessing and display.
The [async API guide](docs/ASYNC-INGESTION.md) documents job status and results.

---

## Quickstart (with Astral `uv`)

### 1. Install Environment and Dependencies

```bash
uv venv --python 3.14 .venv
uv sync --extra dev
```

### 2. List Official NASA Space Apps Benchmark Targets

```bash
uv run spherex-ingest list-benchmarks
```

| Target ID | Name | Category | RA (deg) | Dec (deg) | Epoch | Key SPHEREx Behavior |
|---|---|---|---|---|---|---|
| `barnards_star` | Barnard's Star | High Proper Motion | `269.452077` | `+4.693365` | J2016.0 | Moves $10.39''/\text{yr}$ ($\approx 0.84\text{ px}$/pass); saturated core (`OVERFLOW` flag) |
| `epsilon_indi_b` | Epsilon Indi B | Brown Dwarf | `331.076454` | `-56.793818` | J2016.0 | Clean unsaturated T1+T6 binary brown dwarf ($4.72''/\text{yr}$), 4 passes |
| `wise_0855_0714` | WISE J085510.83−071442.5 | Brown Dwarf (Y) | `133.760000` | `-7.242200` | J2025.5 | Coldest brown dwarf (~250 K); ~20 px West of 2010 pos; Bands 5 & 6 only |
| `rw_aurigae` | RW Aurigae | Variable Star | `76.956522` | `+30.401407` | J2016.0 | T Tauri variable; compare strictly within same spectral band |
| `r_draconis` | R Draconis | Variable Star | `248.171951` | `+66.754053` | J2016.0 | Mira variable in North Ecliptic Pole Deep Field (`dr1_deep`, `qr3_deep`) |

### 3. Ingest Real SPHEREx Data from NASA/IRSA

```bash
# Ingest a single benchmark target and export JSON + PNG bundle to output/
uv run spherex-ingest ingest --target epsilon_indi_b --max-frames 12

# Ingest all 5 benchmark targets
uv run spherex-ingest ingest --all-benchmarks --max-frames 12

# Ingest any custom RA/Dec coordinate on the sky
uv run spherex-ingest ingest --ra 331.068 --dec -56.789 --name "Custom Field"
```

### 4. Start the FastAPI Backend Server (CORS Proxy + Live Pipeline)

```bash
uv run spherex-ingest serve --host 0.0.0.0 --port 8000
```

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`:
- `GET /api/v1/health` — Service health check.
- `GET /api/v1/benchmarks` — List the 5 benchmark targets and metadata.
- `POST /api/v1/jobs` — Submit a position or object search, or get a cached result.
- `GET /api/v1/jobs/{job_id}` — Check progress.
- `GET /api/v1/jobs/{job_id}/result` — Get the completed blink bundle.

### 5. Run Automated Tests & Linter

```bash
uv run pytest
uv run ruff check src/ tests/
```

---

## Cloud Run staging & keyless delivery

See the [container and staging guide](docs/CLOUD-RUN.md) for local smoke tests and private deployment, [GCP bootstrap guide](deploy/gcp/README.md) for OIDC/WIF provisioning, and the [operations runbook](docs/OPERATIONS-RUNBOOK.md) for monitoring, alerts, and rollback procedures.

## License & Citations

Released under the **Apache License 2.0**. See [docs/SOURCES.md](docs/SOURCES.md) for full scientific citations, NASA/IRSA acknowledgements, and software attributions, and [docs/AI-USAGE.md](docs/AI-USAGE.md) for the transparent AI usage log.
