# Sources

Everything used to build this project is listed here, including open-source code and open data, as
the NASA Space Apps rules require. A source is added in the same commit that introduces it.

## Challenge and rules

| Source | Used for | Added |
|---|---|---|
| [Planet X and SPHEREx](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/), NASA Space Apps Challenge 2026 | Challenge statement, test objects and suggested resources, summarized in `AGENTS.md` | 2026-11-14 |
| [Project Submission Guide](https://www.spaceappschallenge.org/resources/project-submission-guide/) and [Judging & Awards Guide](https://www.spaceappschallenge.org/resources/judging-awards-guide/), NASA Space Apps | Submission rules and judging criteria, summarized in `AGENTS.md` | 2026-11-14 |
| [Space Apps Connect](https://github.com/nasa/spaceapps/discussions) (GitHub Discussions of `nasa/spaceapps`), GO Team answers | Rules on AI use, citations and prior work, summarized in `AGENTS.md` | 2026-11-14 |

## NASA data and documentation

| Source | Used for | Added |
|---|---|---|
| [SPHEREx at the NASA/IPAC Infrared Science Archive (IRSA)](https://irsa.ipac.caltech.edu/Missions/spherex.html), including the [SPHEREx Explanatory Supplement](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf) and the [archive user guide](https://caltech-ipac.github.io/spherex-archive-documentation/) | Facts about the data releases, file layout, access services and known pitfalls, summarized in `AGENTS.md`. | 2026-11-14 |
| SPHEREx **DR1** Spectral Images, NASA/IPAC IRSA, [doi:10.26131/IRSA678](https://doi.org/10.26131/IRSA678) (collection `spherex_dr1`) | Two cutouts of Barnard's Star (2025-08-25 and 2026-03-19, detector 6) in the mockup, `mockup/data/barnard/` | 2026-11-14 |
| SPHEREx **QR3** Spectral Images, NASA/IPAC IRSA (collection `spherex_qr3`). DOI still to be looked up. | One cutout of Barnard's Star (2026-08-19, detector 6) in the mockup | 2026-11-14 |
| IRSA services: SIA image search and the SPHEREx cutout service (`?center=…&size=…`) | Finding and downloading the images in `mockup/prepare_barnard.py` | 2026-11-14 |
| [IRSA tutorials for SPHEREx](https://caltech-ipac.github.io/irsa-tutorials/) (`spherex_intro`, `spherex_cutouts`), Caltech/IPAC, BSD-3-Clause | The query, cutout URL and wavelength-at-a-pixel recipe (`WCS(..., key="W")`) used in `mockup/prepare_barnard.py`. Recipe followed, no notebook copied as-is. | 2026-11-14 |

Before submission, add IRSA's official acknowledgement text (from the SPHEREx and IRSA pages) here
and in the page footer.

## Other astronomical data

| Source | Used for | Added |
|---|---|---|
| [Gaia DR3](https://www.cosmos.esa.int/web/gaia/dr3) (ESA), source 4472832130942575872, live query of the [ESA Gaia archive](https://gea.esac.esa.int/archive/). Gaia Collaboration, Vallenari et al. 2023, A&A 674, A1. | Position, proper motion, parallax and radial velocity of Barnard's Star, propagated to each image date to predict where it should be | 2026-11-14 |

## Prior work by the team

| Source | Used for | Added |
|---|---|---|
| Team study notes written before the hackathon (5–13 November 2026) by Miguel Castro with AI assistance (Claude). Private; study only, no project code. | The summary of the challenge, rules and data facts in `AGENTS.md` | 2026-11-14 |
| «Noir Cósmico» v2 (2 October 2026), the design system Miguel Castro wrote for the Bortle Cero websites (e.g. [puenteestelar.bortlecero.com](https://puenteestelar.bortlecero.com/)) before the hackathon and unrelated to Space Apps. | Color palette, type scale, spacing, radii, motion and accessibility rules adapted in `DESIGN.md`. Values and rules only; no code copied from those sites. | 2026-11-14 |

## Software and libraries

| Source | License | Used for | Added |
|---|---|---|---|
| [Space Grotesk](https://github.com/floriankarsten/space-grotesk), by Florian Karsten | SIL Open Font License 1.1 | Typeface of the interface, chosen in `DESIGN.md` (self-hosted; how it is installed is added here when it is) | 2026-11-14 |
| [Astropy](https://www.astropy.org/) 8.0 (Astropy Collaboration 2013, 2018, 2022) | BSD-3-Clause | FITS reading, WCS, coordinates, proper motion and parallax (`mockup/prepare_barnard.py`) | 2026-11-14 |
| [astroquery](https://github.com/astropy/astroquery) 0.4.11 (Ginsburg et al. 2019), with [PyVO](https://github.com/astropy/pyvo) | BSD-3-Clause | IRSA SIA and Gaia archive queries | 2026-11-14 |
| [reproject](https://github.com/astropy/reproject) 0.21 | BSD-3-Clause | Putting every frame on one north-up grid | 2026-11-14 |
| [photutils](https://github.com/astropy/photutils) 3.1 | BSD-3-Clause | Measuring the star's centroid (`centroid_2dg`) | 2026-11-14 |
| [NumPy](https://numpy.org/), [SciPy](https://scipy.org/) | BSD-3-Clause | Array math; SciPy is used by the centroid fit | 2026-11-14 |
| [Matplotlib](https://matplotlib.org/) | Matplotlib License (BSD-compatible) | Writing the grayscale and flag PNGs | 2026-11-14 |
