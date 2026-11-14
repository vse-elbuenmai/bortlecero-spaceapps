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
| SPHEREx **QR3** Spectral Images, NASA/IPAC IRSA (collection `spherex_qr3`). | One cutout of Barnard's Star (2026-08-19, detector 6) in the mockup | 2026-11-14 |
| [IRSA tutorials for SPHEREx](https://caltech-ipac.github.io/irsa-tutorials/) (`spherex_intro`, `spherex_cutouts`), Caltech/IPAC, BSD-3-Clause | The query, cutout URL and wavelength-at-a-pixel recipe (`WCS(..., key="W")`) used in `mockup/prepare_barnard.py`. Recipe followed, no notebook copied as-is. | 2026-11-14 |
| SPHEREx DR1 all-sky data cube for visualization (HiPS, `ivo://IPAC/P/SPHEREx/DR1/cube`), SPHEREx Science Data Center, served by IRSA at `irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube` | The SPHEREx layers of the sky sphere prototype (`mockup/sky.js`): frames 95, 55 and 10 | 2026-11-14 |
| IRSA's landing page for that HiPS cube (its page script, based on the CDS HiPSGen landing-page template) | The recipe to select one frame of a cube in Aladin Lite with `setFrequency`. Recipe followed, code written anew. | 2026-11-14 |
| Bock, J. J., et al. (2026), *"The SPHEREx Satellite Mission"*, The Astrophysical Journal, 999:139, [doi:10.3847/1538-4357/ae2be2](https://doi.org/10.3847/1538-4357/ae2be2) | Mission parameters, Linear Variable Filter (LVF) resolving powers and bandpasses (Bands 1–6, $0.75\text{–}5.0\,\mu\text{m}$), survey strategy, and detector specifications. | 2026-11-14 |
| Akeson, R., Dubois-Felsmann, G. P., Crill, B. P., et al. (2026), *"The SPHEREx Image and Spectrophotometry Processing Pipeline"*, The Astrophysical Journal Supplement Series, 285:67, [doi:10.3847/1538-4365/ae8843](https://doi.org/10.3847/1538-4365/ae8843) | Level 2b Multi-Extension FITS layout, bitmask `FLAGS` definitions, `ZODI` zodiacal light extension handling, `WCS-WAVE` lookup table specification, and pipeline task architecture. | 2026-11-14 |
| Crill, B. P., Bach, Y. P., Bryan, S. A., et al. (2025), *"The SPHEREx Sky Simulator: Science Data Modeling for the First All-sky Near-infrared Spectral Survey"*, The Astrophysical Journal Supplement Series, 281:10, [doi:10.3847/1538-4365/ae04cc](https://doi.org/10.3847/1538-4365/ae04cc) | Sub-pixel PSF and centroid sensitivity modeling, H2RG detector non-linearity/saturation behavior, and zodiacal background variation across epochs. | 2026-11-14 |
| [Gaia Collaboration, Vallenari, A., et al. (2023), *Gaia Data Release 3 (Gaia DR3)*](https://www.cosmos.esa.int/web/gaia/dr3), Astronomy & Astrophysics, 674, A1 | Reference J2016.0 astrometry, proper motions ($\mu_{\alpha^*}, \mu_\delta$), and trigonometric parallaxes ($\varpi$) for benchmark validation targets, including Barnard's Star (source 4472832130942575872). | 2026-11-14 |
| [SIMBAD Astronomical Database — Harvard/CfA Mirror](https://simbad.harvard.edu/simbad/) (`simbad.harvard.edu/simbad/sim-tap`), Wenger et al. (2000) | Live TAP target name resolution and astrometric parameter lookup; Epoch-2000 positions of Epsilon Indi B, WISE 0855−0714, RW Aurigae and R Draconis. | 2026-11-14 |
| Luhman, K. L. & Esplin, T. L. (2016), ApJ, 833, 96; Kirkpatrick, J. D., et al. (2021), ApJS, 253, 7 | High-proper-motion and parallax parameters for the Y-dwarf WISE J085510.83−071442.5. | 2026-11-14 |
| DSS2 colour survey as a HiPS (`ivo://CDS/P/DSS2/color`), copy served by IRSA. Digitized Sky Survey, STScI/NASA, coloured and HEALPixed by CDS; Lasker et al. 1996, ASPC 101, 88. | Visible-light background of the sky sphere prototype. | 2026-11-14 |

### Official NASA / IRSA Acknowledgement

> This research has made use of the NASA/IPAC Infrared Science Archive, which is funded by the National Aeronautics and Space Administration and operated by the California Institute of Technology. This publication makes use of data products from the Spectro-Photometer for the History of the Universe, Epoch of Reionization and Ices Explorer (SPHEREx), which is a joint project of the Jet Propulsion Laboratory and the California Institute of Technology in the U.S., funded by NASA, and the Korea Astronomy and Space Science Institute (KASI).

## Prior work by the team

| Source | Used for | Added |
|---|---|---|
| Team study notes written before the hackathon (5–13 November 2026) by Miguel Castro with AI assistance (Claude). Private; study only, no project code. | The summary of the challenge, rules and data facts in `AGENTS.md` | 2026-11-14 |
| «Noir Cósmico» v2 (2 October 2026), the design system Miguel Castro wrote for the Bortle Cero websites (e.g. [puenteestelar.bortlecero.com](https://puenteestelar.bortlecero.com/)) before the hackathon and unrelated to Space Apps. | Color palette, type scale, spacing, radii, motion and accessibility rules adapted in `DESIGN.md`. Values and rules only; no code copied from those sites. | 2026-11-14 |

## Software and libraries

| Source | License | Used for | Added |
|---|---|---|---|
| [Space Grotesk](https://github.com/floriankarsten/space-grotesk), by Florian Karsten | SIL Open Font License 1.1 | Typeface of the interface, chosen in `DESIGN.md` (self-hosted; how it is installed is added here when it is) | 2026-11-14 |
| [Astral `uv`](https://github.com/astral-sh/uv) | Apache-2.0 / MIT | Python environment, package, and lockfile management | 2026-11-14 |
| [Astropy (`astropy`)](https://www.astropy.org/) (Astropy Collaboration et al. 2013, 2022) | BSD-3-Clause | FITS I/O, World Coordinate Systems (`WCS` & `WCS-WAVE` `WAVE-TAB`), proper motion & parallax epoch propagation (`SkyCoord.apply_space_motion`), and physical units | 2026-11-14 |
| [reproject](https://reproject.readthedocs.io/) (Robitaille et al.) | BSD-3-Clause | Reprojecting multi-epoch SPHEREx cutouts (including $180^\circ$ `SPS_EPA` spacecraft flips) onto a common North-up celestial TAN grid | 2026-11-14 |
| [PyVO (`pyvo`)](https://pyvo.readthedocs.io/) | BSD-3-Clause | IVOA Simple Image Access v2 (`SIA2Service`) queries against IRSA (`https://irsa.ipac.caltech.edu/SIA`) | 2026-11-14 |
| [Astroquery (`astroquery`)](https://astroquery.readthedocs.io/) | BSD-3-Clause | Astronomical archive and catalog access utilities | 2026-11-14 |
| [Photutils (`photutils`)](https://photutils.readthedocs.io/) (Bradley et al. 2024) | BSD-3-Clause | Sub-pixel source centroiding (`centroid_com`, `centroid_2dg`) and aperture photometry | 2026-11-14 |
| [NumPy (`numpy`)](https://numpy.org/) & [SciPy (`scipy`)](https://scipy.org/) | BSD-3-Clause | Multi-dimensional array processing, morphological mask dilation, model fitting, and local median filtering | 2026-11-14 |
| [Matplotlib](https://matplotlib.org/) | Matplotlib License (BSD-compatible) | Writing grayscale and flag PNGs in mockup data preparation | 2026-11-14 |
| [FastAPI (`fastapi`)](https://fastapi.tiangolo.com/), [Uvicorn (`uvicorn`)](https://www.uvicorn.org/), & [Pydantic (`pydantic`)](https://docs.pydantic.dev/) | MIT / BSD-3-Clause | Typed domain models, DTO serialization, and CORS-enabled REST API for frontend consumption | 2026-11-14 |
| [HTTPX (`httpx`)](https://www.python-httpx.org/) & [Pillow (`pillow`)](https://python-pillow.org/) | BSD-3-Clause / MIT-CMU | HTTP client for IRSA/SIMBAD requests and arcsinh-stretched PNG frame rendering | 2026-11-14 |
| [Aladin Lite](https://github.com/cds-astro/aladin-lite) 3.8.2 (CDS, Strasbourg Observatory; Boch & Fernique 2014, ASPC 485, 277; Baumann et al. 2022, ASPC 532, 7), loaded from [jsDelivr](https://cdn.jsdelivr.net/npm/aladin-lite@3.8.2/dist/aladin.js) | GPL-3 / LGPL-3 | Sky sphere, trip to coordinates and sky layers in `mockup/sky.js` | 2026-11-14 |
| [Pytest (`pytest`)](https://docs.pytest.org/) & [Ruff (`ruff`)](https://docs.astral.sh/ruff/) | MIT | Automated unit/integration testing and static analysis | 2026-11-14 |
| [GitHub Actions (`actions/checkout`, `actions/setup-python`)](https://github.com/actions) | MIT | Standard continuous integration workflow execution actions | 2026-11-14 |
| [Astral `setup-uv` Action](https://github.com/astral-sh/setup-uv) | Apache-2.0 / MIT | GitHub Action to set up Astral `uv` binary and dependency cache in CI runners | 2026-11-14 |
