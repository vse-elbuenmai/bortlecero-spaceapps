# Sources

Everything used to build this project is listed here, including open-source code and open data, as
the NASA Space Apps rules require. A source is added in the same commit that introduces it.

## Challenge and rules

| Source | Used for | Added |
|---|---|---|
| [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/), NASA Space Apps Challenge 2026 | Challenge statement, test objects and suggested resources, summarized in `AGENTS.md` | 2026-11-14 |
| [Project Submission Guide](https://www.spaceappschallenge.org/resources/project-submission-guide/) and [Judging & Awards Guide](https://www.spaceappschallenge.org/resources/judging-awards-guide/), NASA Space Apps | Submission rules and judging criteria, summarized in `AGENTS.md` | 2026-11-14 |
| [Space Apps Connect](https://github.com/nasa/spaceapps/discussions) (GitHub Discussions of `nasa/spaceapps`), GO Team answers | Rules on AI use, citations and prior work, summarized in `AGENTS.md` | 2026-11-14 |

## NASA data, astronomical catalogs, and mission papers

| Source | Used for | Added |
|---|---|---|
| [SPHEREx at the NASA/IPAC Infrared Science Archive (IRSA)](https://irsa.ipac.caltech.edu/Missions/spherex.html), including the [SPHEREx Explanatory Supplement](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf), [archive user guide](https://caltech-ipac.github.io/spherex-archive-documentation/), SIAv2 (`https://irsa.ipac.caltech.edu/SIA`), and Cutout Service (`spherex_dr1`, `spherex_qr3`, `spherex_dr1_deep`, `spherex_qr3_deep`) | Live querying and retrieval of SPHEREx Level 2b calibrated spectral image Multi-Extension FITS cutouts (`IMAGE`, `FLAGS`, `VARIANCE`, `ZODI`, `EPSF`, `WCS-WAVE`). | 2026-11-14 |
| SPHEREx **DR1** Spectral Images, NASA/IPAC IRSA, [doi:10.26131/IRSA678](https://doi.org/10.26131/IRSA678) (collection `spherex_dr1`) | Two cutouts of Barnard's Star (2025-08-25 and 2026-03-19, detector 6) in the mockup, `mockup/data/barnard/` | 2026-11-14 |
| SPHEREx **QR3** Spectral Images, NASA/IPAC IRSA (collection `spherex_qr3`). DOI still to be looked up. | One cutout of Barnard's Star (2026-08-19, detector 6) in the mockup | 2026-11-14 |
| [IRSA tutorials for SPHEREx](https://caltech-ipac.github.io/irsa-tutorials/) (`spherex_intro`, `spherex_cutouts`), Caltech/IPAC, BSD-3-Clause | The query, cutout URL and wavelength-at-a-pixel recipe (`WCS(..., key="W")`) used in `mockup/prepare_barnard.py`. Recipe followed, no notebook copied as-is. | 2026-11-14 |
| SPHEREx DR1 all-sky data cube for visualization (HiPS, `ivo://IPAC/P/SPHEREx/DR1/cube`), SPHEREx Science Data Center, served by IRSA at `irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube` | The two SPHEREx sky layers of the mockup, frames 95, 55 and 10: order-1 tiles turned into all-sky maps by `mockup/prepare_sky.py` (`mockup/sky/spherex-*.webp`); the same frames are streamed by plan B (`mockup/aladin.html`) | 2026-11-14 |
| [Deep Star Maps 2020](https://svs.gsfc.nasa.gov/4851), NASA/Goddard Space Flight Center Scientific Visualization Studio (Ernie Wright), `starmap_2020_4k.exr`. Gaia DR2: ESA/Gaia/DPAC. | The "Visible light" layer of the sky view: tone-mapped (asinh) and converted by `mockup/prepare_sky.py` into `mockup/sky/visible_*.webp`. A drawing from the Hipparcos-2, Tycho-2 and Gaia DR2 catalogues, not a photograph. | 2026-11-14 |
| IRSA's landing page for that HiPS cube (its page script, based on the CDS HiPSGen landing-page template) | The recipe to select one frame of a cube in Aladin Lite with `setFrequency`. Recipe followed, code written anew. | 2026-11-14 |
| Bock, J. J., et al. (2026), *"The SPHEREx Satellite Mission"*, The Astrophysical Journal, 999:139, [doi:10.3847/1538-4357/ae2be2](https://doi.org/10.3847/1538-4357/ae2be2) | Mission parameters, Linear Variable Filter (LVF) resolving powers and bandpasses (Bands 1–6, $0.75\text{–}5.0\,\mu\text{m}$), survey strategy, and detector specifications. | 2026-11-14 |
| Akeson, R., Dubois-Felsmann, G. P., Crill, B. P., et al. (2026), *"The SPHEREx Image and Spectrophotometry Processing Pipeline"*, The Astrophysical Journal Supplement Series, 285:67, [doi:10.3847/1538-4365/ae8843](https://doi.org/10.3847/1538-4365/ae8843) | Level 2b Multi-Extension FITS layout, bitmask `FLAGS` definitions, `ZODI` zodiacal light extension handling, `WCS-WAVE` lookup table specification, and pipeline task architecture. | 2026-11-14 |
| Crill, B. P., Bach, Y. P., Bryan, S. A., et al. (2025), *"The SPHEREx Sky Simulator: Science Data Modeling for the First All-sky Near-infrared Spectral Survey"*, The Astrophysical Journal Supplement Series, 281:10, [doi:10.3847/1538-4365/ae04cc](https://doi.org/10.3847/1538-4365/ae04cc) | Sub-pixel PSF and centroid sensitivity modeling, H2RG detector non-linearity/saturation behavior, and zodiacal background variation across epochs. | 2026-11-14 |
| [Gaia Collaboration, Vallenari, A., et al. (2023), *Gaia Data Release 3 (Gaia DR3)*](https://www.cosmos.esa.int/web/gaia/dr3), Astronomy & Astrophysics, 674, A1 | Reference J2016.0 astrometry, proper motions ($\mu_{\alpha^*}, \mu_\delta$), and trigonometric parallaxes ($\varpi$) for benchmark validation targets, including Barnard's Star (source 4472832130942575872). Also the positions and proper motions of Barnard's Star, Epsilon Indi B and R Draconis (source 1648328016354496384) in `mockup/sky.js`, live query of 2026-11-14. | 2026-11-14 |
| [SIMBAD Astronomical Database — Harvard/CfA Mirror](https://simbad.harvard.edu/simbad/) (`simbad.harvard.edu/simbad/sim-tap`), Wenger et al. (2000) | Live TAP target name resolution and astrometric parameter lookup; Epoch-2000 positions of Epsilon Indi B, WISE 0855−0714, RW Aurigae and R Draconis. The sky view (`mockup/sky.js`) resolves object names from the browser with the Sesame service of the same mirror (`vizier.cfa.harvard.edu/viz-bin/nph-sesame`). | 2026-11-14 |
| Luhman, K. L. & Esplin, T. L. (2016), ApJ, 833, 96; Kirkpatrick, J. D., et al. (2021), ApJS, 253, 7 | High-proper-motion and parallax parameters for the Y-dwarf WISE J085510.83−071442.5. | 2026-11-14 |
| DSS2 colour survey as a HiPS (`ivo://CDS/P/DSS2/color`), copy served by IRSA. Digitized Sky Survey, STScI/NASA, coloured and HEALPixed by CDS; Lasker et al. 1996, ASPC 101, 88. | Visible-light background of plan B (`mockup/aladin.html`). | 2026-11-14 |

### Official NASA / IRSA Acknowledgement

> This research has made use of the NASA/IPAC Infrared Science Archive, which is funded by the National Aeronautics and Space Administration and operated by the California Institute of Technology. This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology in the U.S., funded by NASA, and the Korea Astronomy and Space Science Institute (KASI).

## Prior work by the team

| Source | Used for | Added |
|---|---|---|
| Team study notes written before the hackathon (5–13 November 2026) by Miguel Castro with AI assistance (Claude). Private; study only, no project code. | The summary of the challenge, rules and data facts in `AGENTS.md` | 2026-11-14 |
| «Noir Cósmico» v2 (2 October 2026), the design system Miguel Castro wrote for the Bortle Cero websites (e.g. [puenteestelar.bortlecero.com](https://puenteestelar.bortlecero.com/)) before the hackathon and unrelated to Space Apps. | Color palette, type scale, spacing, radii, motion and accessibility rules adapted in `DESIGN.md`. Values and rules only; no code copied from those sites. | 2026-11-14 |
| Layout of the date search of [puenteestelar.bortlecero.com](https://puenteestelar.bortlecero.com/) (Miguel Castro, before the hackathon): a floating panel with a small label, a question as title and one input row. | The look of the search panel of the sky view (`DESIGN.md` §7.11). Looked at in the browser and rebuilt from the design tokens; no code copied. | 2026-11-14 |

## Other references

| Source | Used for | Added |
|---|---|---|
| [The full sky in the ultraviolet](https://menard.pha.jhu.edu/uvmap/), Brice Ménard (2026), its "inside" view | The approach of the sky view: one panorama of the whole sky painted inside a sphere with plain WebGL. Only the approach, seen by using the page: no code, images or data taken. | 2026-11-14 |
| [Cloud Storage generation preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions) and [object lifecycle management](https://docs.cloud.google.com/storage/docs/lifecycle) | Atomic manifest publication and retention for private live-query results. | 2026-11-15 |
| [Python temporary files](https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile) and [atomic replacement](https://docs.python.org/3/library/os.html#os.replace) | Publish validated cache entries and self-contained local exports from temporary sibling files. | 2026-11-15 |
| [IAU FITS Standard](https://fits.gsfc.nasa.gov/fits_standard.html) and [Astropy FITS file handling](https://docs.astropy.org/en/stable/io/fits/api/files.html) | Validate FITS block alignment and the last HDU's byte extent before caching a cutout. | 2026-11-15 |

## Software and libraries

| Source | License | Used for | Added |
|---|---|---|---|
| [Space Grotesk](https://github.com/floriankarsten/space-grotesk), by Florian Karsten | SIL Open Font License 1.1 | Typeface of the interface, chosen in `DESIGN.md` (self-hosted; how it is installed is added here when it is) | 2026-11-14 |
| [Astral `uv`](https://github.com/astral-sh/uv) | Apache-2.0 / MIT | Python environment, package, and lockfile management | 2026-11-14 |
| [Google Cloud Storage for Python](https://github.com/googleapis/google-cloud-python/tree/main/packages/google-cloud-storage) | Apache-2.0 | Private result bucket access through Application Default Credentials and object generation preconditions. | 2026-11-15 |
| [SQLite transactions](https://www.sqlite.org/lang_transaction.html) and [page limits](https://www.sqlite.org/pragma.html#pragma_max_page_count) | Public domain | Cross-process local result publication and storage capacity. | 2026-11-15 |
| [Astropy (`astropy`)](https://www.astropy.org/) (Astropy Collaboration et al. 2013, 2022) | BSD-3-Clause | FITS I/O, World Coordinate Systems (`WCS` & `WCS-WAVE` `WAVE-TAB`), proper motion & parallax epoch propagation (`SkyCoord.apply_space_motion`), and physical units | 2026-11-14 |
| [reproject](https://reproject.readthedocs.io/) (Robitaille et al.) | BSD-3-Clause | Reprojecting multi-epoch SPHEREx cutouts (including $180^\circ$ `SPS_EPA` spacecraft flips) onto a common North-up celestial TAN grid | 2026-11-14 |
| [PyVO (`pyvo`)](https://pyvo.readthedocs.io/) | BSD-3-Clause | IVOA Simple Image Access v2 (`SIA2Service`) queries against IRSA (`https://irsa.ipac.caltech.edu/SIA`) | 2026-11-14 |
| [Astroquery (`astroquery`)](https://astroquery.readthedocs.io/) | BSD-3-Clause | Astronomical archive and catalog access utilities | 2026-11-14 |
| [Photutils (`photutils`)](https://photutils.readthedocs.io/) (Bradley et al. 2024) | BSD-3-Clause | Sub-pixel source centroiding (`centroid_com`, `centroid_2dg`) and aperture photometry | 2026-11-14 |
| [NumPy (`numpy`)](https://numpy.org/) & [SciPy (`scipy`)](https://scipy.org/) | BSD-3-Clause | Multi-dimensional array processing, morphological mask dilation, model fitting, and local median filtering | 2026-11-14 |
| [Matplotlib](https://matplotlib.org/) | Matplotlib License (BSD-compatible) | Writing grayscale and flag PNGs in mockup data preparation | 2026-11-14 |
| [FastAPI (`fastapi`)](https://fastapi.tiangolo.com/), [Uvicorn (`uvicorn`)](https://www.uvicorn.org/), & [Pydantic (`pydantic`)](https://docs.pydantic.dev/) | MIT / BSD-3-Clause | Typed domain models, DTO serialization, and CORS-enabled REST API for frontend consumption | 2026-11-14 |
| [HTTPX (`httpx`)](https://www.python-httpx.org/) & [Pillow (`pillow`)](https://python-pillow.org/) | BSD-3-Clause / MIT-CMU | HTTP client for IRSA/SIMBAD requests and arcsinh-stretched PNG frame rendering | 2026-11-14 |
| [Aladin Lite](https://github.com/cds-astro/aladin-lite) 3.8.2 (CDS, Strasbourg Observatory; Boch & Fernique 2014, ASPC 485, 277; Baumann et al. 2022, ASPC 532, 7), loaded from [jsDelivr](https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js) | GPL-3 / LGPL-3 | Sky sphere, trip to coordinates and sky layers in plan B (`mockup/aladin.html`, `mockup/sky-aladin.js`) | 2026-11-14 |
| [OpenEXR](https://openexr.com/) Python bindings (Academy Software Foundation) | BSD-3-Clause | Reading NASA's star map in `mockup/prepare_sky.py`. Build step of the mockup only, run with `uv run --with OpenEXR`: not a dependency of the package | 2026-11-14 |
| [astropy-healpix](https://github.com/astropy/astropy-healpix) | BSD-3-Clause | Finding the tile and pixel of each sky position when turning IRSA's HiPS tiles into all-sky maps (`mockup/prepare_sky.py`); Pillow writes the WebP files | 2026-11-14 |
| [Pytest (`pytest`)](https://docs.pytest.org/) & [Ruff (`ruff`)](https://docs.astral.sh/ruff/) | MIT | Automated unit/integration testing and static analysis | 2026-11-14 |
| [GitHub Actions (`actions/checkout`, `actions/setup-python`)](https://github.com/actions) | MIT | Standard continuous integration workflow execution actions | 2026-11-14 |
| [Astral `setup-uv` Action](https://github.com/astral-sh/setup-uv) | Apache-2.0 / MIT | GitHub Action to set up Astral `uv` binary and dependency cache in CI runners | 2026-11-14 |
| [Firebase Hosting configuration](https://firebase.google.com/docs/hosting/full-config) | Managed Google service | Serving the static benchmark viewer with HTTPS and release cache headers | 2026-11-15 |
| [Playwright](https://github.com/microsoft/playwright) | Apache-2.0 | Offline Chromium tests for the hosted viewer, benchmark fallback and ingestion statuses | 2026-11-15 |
| [GitHub Actions Node.js setup](https://github.com/actions/setup-node) | MIT | Provisioning Node.js for browser CI | 2026-11-15 |
| [Docker Official Image for Python](https://github.com/docker-library/python) | PSF-2.0 for Python | Digest-pinned CPython 3.14 base image for the ingestion service | 2026-11-15 |

## Public ingestion operations

- [Cloud Tasks queue limits and retries](https://docs.cloud.google.com/tasks/docs/configuring-queues).
- [Google Cloud Free Tier and trial limits](https://docs.cloud.google.com/free/docs/free-cloud-features).
- [Cloud Run job cost guidance](https://docs.cloud.google.com/run/docs/jobs-cost-optimization).

## Deployment references

| Source | Used for | Added |
|---|---|---|
| [Cloud Run runtime contract](https://docs.cloud.google.com/run/docs/container-contract), [YAML reference](https://docs.cloud.google.com/run/docs/reference/yaml/v1), [health checks](https://docs.cloud.google.com/run/docs/configuring/healthchecks), and [in-memory volumes](https://docs.cloud.google.com/run/docs/configuring/services/in-memory-volume-mounts) | Port, graceful shutdown, staging service specification, HTTP probes, and bounded scratch volume | 2026-11-15 |
| [Astral uv Docker guide](https://docs.astral.sh/uv/guides/integration/docker/) | Multi-stage container build with locked runtime dependencies | 2026-11-15 |
| [`google-github-actions/auth`](https://github.com/google-github-actions/auth) | Keyless OIDC/Workload Identity Federation authentication from GitHub Actions to Google Cloud | 2026-11-15 |
| [Google Cloud Workload Identity Federation with GitHub Actions](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines) | Least-privilege OIDC pool/provider attribute mapping and repository conditions | 2026-11-15 |

## Public ingestion operations

- [Cloud Tasks queue limits and retries](https://docs.cloud.google.com/tasks/docs/configuring-queues).
- [Google Cloud Free Tier and trial limits](https://docs.cloud.google.com/free/docs/free-cloud-features).
- [Cloud Run job cost guidance](https://docs.cloud.google.com/run/docs/jobs-cost-optimization).
- [Google Cloud Tasks HTTP Target & OIDC Authentication](https://cloud.google.com/tasks/docs/creating-http-target-tasks#oidc) — referenced for the `CloudTasksJobDispatcher` and `OIDCWorkerAuthVerifier` contract.
- [Google Cloud Firestore Transactions](https://cloud.google.com/firestore/docs/manage-data/transactions) — referenced for the `FirestoreJobStore` atomic deduplication, admission, and lease-claim contract.
