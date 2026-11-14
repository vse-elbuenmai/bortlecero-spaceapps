"""Build the all-sky textures of the mockup's sky view (MOCKUP ONLY, not the project pipeline).

The sky view paints one image of the whole sky on the inside of a sphere. This script makes
those images, one per layer, as plate carree panoramas (like a 360-degree photo):

    column x  ->  RA  = 180 - 360 * x / width     (RA 0h in the middle, RA grows to the left)
    row    y  ->  Dec =  90 - 180 * y / height    (north at the top)

That is the layout NASA's star map already has, and it is how the sky looks from inside.

Layers:

1. visible      NASA SVS "Deep Star Maps 2020": stars drawn from the Hipparcos-2, Tycho-2 and
                Gaia DR2 catalogues. It is a drawing from a catalogue, not a photograph.
2. spherex-477  Frame 95 (4.77 um) of the SPHEREx DR1 all-sky cube served by IRSA, with the
                brightness stretch IRSA baked into its tiles (asinh, 0 to 40 MJy/sr).
3. spherex-rgb  Frames 95, 55 and 10 of the same cube as red, green and blue (false colour).

The SPHEREx cube is an AVERAGE of 24 Apr 2025 to 14 May 2026: a backdrop, never blink data.

Run from the repository root. OpenEXR is only needed here, so it is not a project dependency:

    uv run --with OpenEXR python mockup/prepare_sky.py

Downloads (about 45 MB) go to .cache/sky (git-ignored). Outputs go to mockup/sky/.
The script checks its own work: it finds bright stars in every layer and stops if any of them
is not where the catalogue says, which would mean a mirrored or rotated map.
"""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import astropy.units as u
import numpy as np
from astropy_healpix import lonlat_to_healpix
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "sky"
OUT = ROOT / "mockup" / "sky"

SVS_URL = "https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/starmap_2020_4k.exr"
CUBE_URL = "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube"

WIDTHS = (4096, 2048)  # 4096 is the largest texture every phone can be trusted with
TILE_ORDER = 1  # 48 tiles of 512 px: 3.4 arcmin per pixel, finer than the 5.3 arcmin output
TILE_BITS = 9  # 512 = 2**9 pixels per tile side
FRAME_MONO = 95
FRAMES_RGB = {"red": 95, "green": 55, "blue": 10}

# Bright stars used to check the orientation of every map (ICRS, degrees; from SIMBAD).
CHECK_STARS = {
    "Sirius": (101.2872, -16.7161),
    "Canopus": (95.9880, -52.6957),
    "Arcturus": (213.9153, 19.1824),
    "Vega": (279.2347, 38.7837),
    "Betelgeuse": (88.7929, 7.4071),
    "Antares": (247.3519, -26.4320),
}


def download(url: str, dest: Path) -> Path:
    if not dest.is_file() or dest.stat().st_size == 0:
        dest.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "sky-texture-builder"})
        with urllib.request.urlopen(request, timeout=120) as response:
            dest.write_bytes(response.read())
    return dest


def sky_grid(width: int) -> tuple[np.ndarray, np.ndarray]:
    """RA and Dec (degrees) of the centre of every pixel of a width x width/2 panorama."""
    height = width // 2
    ra = (180.0 - 360.0 * (np.arange(width) + 0.5) / width) % 360.0
    dec = 90.0 - 180.0 * (np.arange(height) + 0.5) / height
    return np.meshgrid(ra, dec)


def pixel_of(ra: float, dec: float, width: int) -> tuple[float, float]:
    return ((180.0 - ra) % 360.0) / 360.0 * width - 0.5, (90.0 - dec) / 180.0 * (width // 2) - 0.5


# ---------- layer 1: NASA SVS star map ----------
def build_visible() -> np.ndarray:
    import OpenEXR  # only this layer needs it

    path = download(SVS_URL, CACHE / "starmap_2020_4k.exr")
    linear = OpenEXR.File(str(path)).channels()["RGB"].pixels.astype(np.float32)
    # The file is linear light with a huge range (the faint Milky Way and Sirius in one image).
    # asinh keeps the faint glow visible without burning the bright stars, as in astrophotography.
    soft, white = 0.012, 0.9
    stretched = np.arcsinh(linear / soft) / np.arcsinh(white / soft)
    return (np.clip(stretched, 0, 1) * 255 + 0.5).astype(np.uint8)


# ---------- layers 2 and 3: SPHEREx all-sky cube ----------
def compact_bits(v: np.ndarray) -> np.ndarray:
    """Keep every other bit of v (bit 0, 2, 4...) packed together: undoes the Z-order curve."""
    out = np.zeros_like(v)
    for bit in range(TILE_BITS):
        out |= ((v >> (2 * bit)) & 1) << bit
    return out


def load_frame_tiles(frame: int) -> np.ndarray:
    def one(npix: int) -> np.ndarray:
        name = f"Norder{TILE_ORDER}/Dir0/Npix{npix}_{frame}.png"
        path = download(f"{CUBE_URL}/{name}", CACHE / "cube" / name)
        return np.asarray(Image.open(path).convert("L"))

    with ThreadPoolExecutor(8) as pool:
        return np.stack(list(pool.map(one, range(12 * 4**TILE_ORDER))))


def tile_lookup(width: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """For every pixel of the panorama: which tile it falls in and its two in-tile coordinates."""
    ra, dec = sky_grid(width)
    nside = 2 ** (TILE_ORDER + TILE_BITS)
    index = lonlat_to_healpix(ra * u.deg, dec * u.deg, nside, order="nested").astype(np.int64)
    sub = index & (4**TILE_BITS - 1)
    return index >> (2 * TILE_BITS), compact_bits(sub), compact_bits(sub >> 1)


# A tile is a square image, and its pixels follow HEALPix's Z-order curve. Which way the curve
# runs inside the PNG has 8 possibilities (4 rotations, mirrored or not). LAYOUT is the one that
# gives a seamless, correctly oriented sky; find_layout() re-derives it and the star check below
# confirms it on every run.
N = 2**TILE_BITS - 1
LAYOUTS = {
    "a,b": lambda a, b: (a, b), "b,a": lambda a, b: (b, a),
    "a,-b": lambda a, b: (a, N - b), "-b,a": lambda a, b: (N - b, a),
    "-a,b": lambda a, b: (N - a, b), "b,-a": lambda a, b: (b, N - a),
    "-a,-b": lambda a, b: (N - a, N - b), "-b,-a": lambda a, b: (N - b, N - a),
}
LAYOUT = "a,b"  # (row, column) = (a, b): 5 of 6 check stars in place; the other seven give 0 or 1


def sample(tiles: np.ndarray, lookup: tuple, layout: str) -> np.ndarray:
    tile, a, b = lookup
    row, col = LAYOUTS[layout](a, b)
    return tiles[tile, row, col]


def find_layout(tiles: np.ndarray) -> str:
    """The right layout is the one with the smoothest sky: wrong ones scramble every tile.

    Smoothness is measured on 16 x 16 pixel averages, so pixel noise does not hide the seams.
    """
    lookup = tile_lookup(2048)
    roughness = {}
    for name in LAYOUTS:
        img = sample(tiles, lookup, name).astype(np.float32)
        blocks = img.reshape(img.shape[0] // 16, 16, img.shape[1] // 16, 16).mean(axis=(1, 3))
        roughness[name] = float(np.abs(np.diff(blocks, axis=0)).mean() + np.abs(np.diff(blocks, axis=1)).mean())
    return min(roughness, key=roughness.get)


def build_cube_frame(frame: int, lookup: tuple) -> np.ndarray:
    return sample(load_frame_tiles(frame), lookup, LAYOUT)


def to_width(img: np.ndarray, width: int) -> Image.Image:
    """Shrink by averaging blocks of pixels, so fine detail does not turn into speckle."""
    pil = Image.fromarray(img)
    return pil if pil.width == width else pil.resize((width, width // 2), Image.Resampling.BOX)


# ---------- self-check ----------
def check_stars(name: str, img: np.ndarray, need: int) -> list[str]:
    """Each bright star must be the brightest thing within about 1.5 degrees of its position."""
    gray = img if img.ndim == 2 else img.max(axis=2)
    width, lines, good = gray.shape[1], [], 0
    reach = max(3, round(1.5 / 360 * width))
    for star, (ra, dec) in CHECK_STARS.items():
        x, y = pixel_of(ra, dec, width)
        xi, yi = round(x), round(y)
        patch = gray[yi - reach : yi + reach + 1, xi - reach : xi + reach + 1].astype(np.float32)
        ys, xs = np.nonzero(patch >= patch.max() - 2)
        off = float(np.hypot(xs.mean() - reach, ys.mean() - reach))
        ok = off <= 2.0 and patch.max() > np.median(gray) + 40
        good += ok
        lines.append(f"    {star:<11} {'ok ' if ok else 'NO '} peak {off:4.1f} px from the catalogue position")
    print(f"  {name}: {good}/{len(CHECK_STARS)} stars in place")
    print("\n".join(lines))
    if good < need:
        raise SystemExit(f"{name}: the map is not oriented as expected. Nothing was written.")
    return lines


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = max(WIDTHS)

    print("1/3 visible (NASA SVS Deep Star Maps 2020)")
    visible = build_visible()
    check_stars("visible", visible, need=6)

    print("2/3 SPHEREx frames from IRSA's all-sky cube")
    lookup = tile_lookup(2 * big)  # sampled at twice the size, then averaged down
    frames = {f: build_cube_frame(f, lookup) for f in sorted({FRAME_MONO, *FRAMES_RGB.values()})}
    found = find_layout(load_frame_tiles(FRAME_MONO))
    if found != LAYOUT:
        raise SystemExit(f"Tile layout check failed: expected {LAYOUT}, smoothest is {found}.")
    # Not every optical star is bright at 4.77 um, and the brightest saturate: 4 of 6 is enough
    # to rule out a mirrored or rotated map.
    check_stars("spherex-477", frames[FRAME_MONO], need=4)

    print("3/3 false colour")
    channels = []
    for colour in ("red", "green", "blue"):
        c = frames[FRAMES_RGB[colour]].astype(np.float32)
        low, high = np.percentile(c, 2), np.percentile(c, 99.7)
        channels.append(np.clip((c - low) / (high - low), 0, 1) ** 0.8)  # same recipe per channel
    rgb = (np.dstack(channels) * 255 + 0.5).astype(np.uint8)

    layers = {"visible": visible, "spherex-477": frames[FRAME_MONO], "spherex-rgb": rgb}
    sizes = {}
    for name, img in layers.items():
        for width in WIDTHS:
            path = OUT / f"{name}_{width}.webp"
            to_width(img, width).save(path, "WEBP", quality=82, method=6)
            sizes[path.name] = path.stat().st_size
            print(f"  wrote {path.name}  {path.stat().st_size / 1e6:.2f} MB")

    props = download(f"{CUBE_URL}/properties", CACHE / "cube" / "properties").read_text()
    waves = [float(v) for v in props.split("data_cube_crval3_arr")[1].split("=")[1].split("\n")[0].split()]
    meta = {
        "generated": date.today().isoformat(),
        "projection": "plate carree; RA = 180 - 360*x/width, Dec = 90 - 180*y/height",
        "widths": list(WIDTHS),
        "files": sizes,
        "layers": {
            "visible": {
                "source": "NASA SVS Deep Star Maps 2020 (starmap_2020_4k.exr)",
                "note": "Drawn from the Hipparcos-2, Tycho-2 and Gaia DR2 star catalogues. Not a photograph.",
                "credit": "NASA/Goddard Space Flight Center Scientific Visualization Studio. Gaia DR2: ESA/Gaia/DPAC.",
            },
            "spherex-477": {
                "source": "SPHEREx DR1 all-sky data cube (IRSA HiPS), frame 95",
                "wavelength_um": waves[FRAME_MONO],
                "average_of": ["2025-04-24", "2026-05-14"],
                "credit": "NASA/JPL-Caltech/SPHEREx, via NASA/IPAC Infrared Science Archive (IRSA).",
            },
            "spherex-rgb": {
                "source": "SPHEREx DR1 all-sky data cube (IRSA HiPS), frames 95, 55 and 10",
                "wavelengths_um": {c: waves[f] for c, f in FRAMES_RGB.items()},
                "average_of": ["2025-04-24", "2026-05-14"],
                "credit": "NASA/JPL-Caltech/SPHEREx, via NASA/IPAC Infrared Science Archive (IRSA).",
            },
        },
    }
    (OUT / "sky.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print("  wrote sky.json")


if __name__ == "__main__":
    main()
