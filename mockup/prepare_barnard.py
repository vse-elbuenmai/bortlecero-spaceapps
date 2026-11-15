"""Prepare the data for the Barnard's Star mockup (MOCKUP ONLY, not the project pipeline).

What it does, step by step:

1. Gets Barnard's Star from Gaia DR3 (position, proper motion, parallax, radial velocity).
2. Asks IRSA's SIA service which SPHEREx images (DR1 + QR3) cover the star, for one detector.
3. Splits those images into passes (visits separated by more than 30 days) and downloads a few
   small cutouts per pass.
4. Picks one cutout per pass so the star is seen at wavelengths as close as possible
   (each SPHEREx image sees the star at a different wavelength, so this matters).
5. Subtracts the ZODI model, reprojects every frame to one shared north-up grid (this fixes the
   180-degree rotation between passes) and applies the same asinh stretch to all of them.
6. Predicts where the star should be on each date (Gaia + proper motion + parallax) and measures
   where it actually is (centroid on the original, un-reprojected pixels).
7. Writes grayscale PNGs, a flags overlay per frame and frames.json for the web mockup.

Run from the repository root with Astral uv:

    uv run python mockup/prepare_barnard.py

Downloads go to .cache/spherex (git-ignored). Outputs go to mockup/data/barnard/.
"""

from __future__ import annotations

import argparse
import itertools
import json
import urllib.request
from pathlib import Path

import numpy as np
import astropy.units as u
from astropy.coordinates import GCRS, Distance, SkyCoord
from astropy import log
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.time import Time
from astropy.wcs import WCS
from astroquery.ipac.irsa import Irsa
from matplotlib.image import imsave
from photutils.centroids import centroid_2dg, centroid_sources
from reproject import reproject_interp

GAIA_SOURCE_ID = 4472832130942575872  # Barnard's Star in Gaia DR3
# Fallback if the ESA Gaia archive does not answer: Gaia DR3 values for the same source.
GAIA_FALLBACK = dict(ra=269.44850252543836, dec=4.739420051112412, pmra=-801.5509783684709,
                     pmdec=10362.394206546573, parallax=546.975939730948,
                     radial_velocity=-110.46822357177734, ref_epoch=2016.0)

PIXEL_SCALE_ARCSEC = 6.15  # SPHEREx native pixel
# FLAGS bits that are informational, not defects (SOURCE covers ~98 % of a field).
NOT_DEFECTS = {"SOURCE", "FULLSAMPLE"}
SATURATION_BITS = {"OVERFLOW", "NONLINEAR", "BLOOM"}

ROOT = Path(__file__).resolve().parent.parent
# The spectral WCS (key "W") repeats a harmless SIP notice for every cutout; keep the output readable.
log.setLevel("WARNING")


def get_gaia() -> dict:
    try:
        from astroquery.gaia import Gaia

        job = Gaia.launch_job(
            "SELECT ra, dec, pmra, pmdec, parallax, radial_velocity, ref_epoch "
            f"FROM gaiadr3.gaia_source WHERE source_id = {GAIA_SOURCE_ID}"
        )
        row = job.get_results()[0]
        values = {k: float(row[k]) for k in GAIA_FALLBACK}
        values["from"] = "Gaia DR3 (ESA archive, live query)"
        return values
    except Exception as exc:  # network trouble at the venue: keep going with the same numbers
        print(f"  Gaia archive not reachable ({exc.__class__.__name__}); using stored DR3 values")
        return {**GAIA_FALLBACK, "from": "Gaia DR3 (stored values)"}


def star_at(gaia: dict, t: Time) -> SkyCoord:
    """Where the star appears from Earth at time t: proper motion + parallax, no aberration."""
    c0 = SkyCoord(
        ra=gaia["ra"] * u.deg, dec=gaia["dec"] * u.deg,
        distance=Distance(parallax=gaia["parallax"] * u.mas),
        pm_ra_cosdec=gaia["pmra"] * u.mas / u.yr, pm_dec=gaia["pmdec"] * u.mas / u.yr,
        radial_velocity=gaia["radial_velocity"] * u.km / u.s,
        obstime=Time(gaia["ref_epoch"], format="jyear", scale="tcb"),
    )
    bary = c0.apply_space_motion(new_obstime=t)
    # Parallax shift = (seen from Earth) - (same direction at infinity, seen from Earth).
    # Aberration and light bending are the same for both, so they cancel out.
    near = bary.transform_to(GCRS(obstime=t))
    far = SkyCoord(bary.ra, bary.dec, distance=1e9 * u.pc).transform_to(GCRS(obstime=t))
    dlon, dlat = far.spherical_offsets_to(near)
    return SkyCoord(bary.ra, bary.dec).spherical_offsets_by(dlon, dlat)


def split_passes(rows, gap_days=30.0):
    passes, current = [], [rows[0]]
    for prev, row in zip(rows, rows[1:]):
        if row["t_min"] - prev["t_min"] > gap_days:
            passes.append(current)
            current = []
        current.append(row)
    passes.append(current)
    return passes


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
        fh.write(resp.read())
    tmp.replace(dest)
    return dest


def flag_bits(header) -> dict[str, int]:
    bits = {}
    for key in header:
        if key.startswith("MSKN"):
            bits[header[key].strip()] = int(header["MSKM" + key[4:]])
    return bits


def read_cutout(path: Path, star: SkyCoord) -> dict:
    with fits.open(path) as hdul:
        hdr = hdul["IMAGE"].header
        wcs = WCS(hdr)
        x, y = wcs.world_to_pixel(star)
        spectral = WCS(hdr, fobj=hdul, key="W")
        spectral.sip = None
        wave, _ = spectral.pixel_to_world(x, y)
        return dict(
            image=hdul["IMAGE"].data.astype(float),
            zodi=hdul["ZODI"].data.astype(float),
            flags=hdul["FLAGS"].data.astype(np.int64),
            bits=flag_bits(hdul["FLAGS"].header),
            wcs=wcs,
            wavelength_um=float(wave.to(u.um).value),
            pa_deg=float(hdr.get("SPS_EPA", np.nan)),
            date_avg=hdr["DATE-AVG"],
            mjd_avg=float(hdr["MJD-AVG"]),
            obsid=hdr.get("OBSID", ""),
            detector=int(hdr.get("DETECTOR", 0)),
            finast=hdr.get("FINAST"),
            version=hdul[0].header.get("VERSION", ""),
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--detector", type=int, default=6)
    ap.add_argument("--size-deg", type=float, default=0.08, help="cutout side in degrees")
    ap.add_argument("--per-pass", type=int, default=4, help="cutouts downloaded per pass")
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache" / "spherex")
    ap.add_argument("--out", type=Path, default=ROOT / "mockup" / "data" / "barnard")
    args = ap.parse_args()

    print("1. Gaia DR3")
    gaia = get_gaia()
    center = star_at(gaia, Time("2026-03-01"))  # middle of the series: one fixed frame center
    print(f"   center {center.ra.deg:.5f} {center.dec.deg:.5f}  ({gaia['from']})")

    print("2. IRSA SIA (spherex_dr1 + spherex_qr3)")
    res = Irsa.query_sia(pos=(center, 1 * u.arcsec), collection=["spherex_dr1", "spherex_qr3"])
    res = res[res["energy_bandpassname"] == f"SPHEREx-D{args.detector}"]
    res.sort("t_min")
    rows = list(res)
    print(f"   {len(rows)} images on detector {args.detector}")

    print("3. Passes and cutouts")
    passes = split_passes(rows)
    candidates = []
    for i, group in enumerate(passes):
        step = max(1, len(group) // args.per_pass)
        picked = group[::step][: args.per_pass]
        cands = []
        for row in picked:
            url = f"{row['access_url']}?center={center.ra.deg},{center.dec.deg}d&size={args.size_deg}"
            name = Path(str(row["access_url"])).stem + f"_cut{args.size_deg}.fits"
            path = download(url, args.cache / name)
            t = Time(row["t_min"], format="mjd")
            data = read_cutout(path, star_at(gaia, t))
            data["collection"] = str(row["obs_collection"])
            data["file"] = name
            cands.append(data)
            print(f"   pass {i + 1}: {data['date_avg'][:16]}  {data['wavelength_um']:.3f} um  "
                  f"PA {data['pa_deg']:.0f}")
        candidates.append(cands)

    print("4. One frame per pass, closest wavelengths")
    best = min(itertools.product(*candidates),
               key=lambda combo: np.ptp([c["wavelength_um"] for c in combo]))
    frames = list(best)

    print("5. Common north-up grid, ZODI removed, one stretch for all")
    n = int(round(args.size_deg * 3600 / PIXEL_SCALE_ARCSEC))
    n -= (n + 1) % 2  # odd, so the center falls on a pixel
    target = WCS(naxis=2)
    target.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    target.wcs.crval = [center.ra.deg, center.dec.deg]
    target.wcs.crpix = [(n + 1) / 2, (n + 1) / 2]
    target.wcs.cdelt = [-PIXEL_SCALE_ARCSEC / 3600, PIXEL_SCALE_ARCSEC / 3600]  # east left

    for f in frames:
        sky = f["image"] - f["zodi"]
        _, med, _ = sigma_clipped_stats(sky[np.isfinite(sky)], sigma=3)
        sky -= med  # what ZODI misses (lesson from the Andromeda exercise)
        f["regrid"], _ = reproject_interp((sky, f["wcs"]), target, shape_out=(n, n), order="bilinear")
        defect_mask = sum(m for name, m in f["bits"].items() if name not in NOT_DEFECTS)
        bad = ((f["flags"] & defect_mask) != 0).astype(float)
        f["bad_regrid"], _ = reproject_interp((bad, f["wcs"]), target, shape_out=(n, n),
                                              order="nearest-neighbor")

    stack = np.concatenate([f["regrid"][np.isfinite(f["regrid"])] for f in frames])
    _, _, noise = sigma_clipped_stats(stack, sigma=3)
    soft = 3 * noise
    top = np.nanpercentile(stack, 99.9)
    stretch = dict(kind="asinh", softening=float(soft), black=0.0, white=float(top),
                   unit="MJy/sr")

    print("6. Predicted vs measured position")
    args.out.mkdir(parents=True, exist_ok=True)
    out_frames = []
    for i, f in enumerate(frames, start=1):
        t = Time(f["mjd_avg"], format="mjd")
        pred = star_at(gaia, t)
        # Measure on the original pixels (no interpolation), then move to the shared grid.
        px, py = f["wcs"].world_to_pixel(pred)
        sky = f["image"] - f["zodi"]
        sky -= np.nanmedian(sky)
        mx, my = centroid_sources(np.nan_to_num(sky), [float(px)], [float(py)], box_size=7,
                                  centroid_func=centroid_2dg)
        meas = f["wcs"].pixel_to_world(mx[0], my[0])
        gx_p, gy_p = target.world_to_pixel(pred)
        gx_m, gy_m = target.world_to_pixel(meas)
        offset = float(pred.separation(meas).arcsec)

        ix, iy = int(round(float(px))), int(round(float(py)))
        near = f["flags"][max(iy - 2, 0): iy + 3, max(ix - 2, 0): ix + 3]
        near_bits = sorted({name for name, m in f["bits"].items() if np.any(near & m)} - NOT_DEFECTS)
        saturated = bool(set(near_bits) & SATURATION_BITS)

        img = np.arcsinh(np.clip(f["regrid"], 0, None) / soft) / np.arcsinh(top / soft)
        img = np.nan_to_num(np.clip(img, 0, 1))
        png = f"frame_{i}.png"
        imsave(args.out / png, img, cmap="gray", vmin=0, vmax=1, origin="lower")
        rgba = np.zeros((n, n, 4))
        rgba[..., 0], rgba[..., 1], rgba[..., 2] = 248 / 255, 113 / 255, 113 / 255
        rgba[..., 3] = np.where(np.nan_to_num(f["bad_regrid"]) > 0.5, 1.0, 0.0)
        flags_png = f"flags_{i}.png"
        imsave(args.out / flags_png, rgba, origin="lower")

        release = "DR1" if "dr1" in f["collection"] else "QR3"
        out_frames.append(dict(
            image=png, flags=flags_png,
            date_utc=f["date_avg"][:19].replace("T", " "), mjd=f["mjd_avg"],
            release=release, collection=f["collection"], detector=f["detector"],
            obsid=f["obsid"], wavelength_um=round(f["wavelength_um"], 3),
            pa_deg=f["pa_deg"], rotated=bool(abs(f["pa_deg"] - 180) < 1),
            saturated=saturated, flags_near_star=near_bits, finast=f["finast"],
            pipeline_version=f["version"],
            predicted={"ra": pred.ra.deg, "dec": pred.dec.deg,
                       "x": float(gx_p), "y": float(n - 1 - gy_p)},  # y flipped for the PNG
            measured={"ra": meas.ra.deg, "dec": meas.dec.deg,
                      "x": float(gx_m), "y": float(n - 1 - gy_m)},
            offset_arcsec=round(offset, 2),
            source_file=f["file"],
        ))
        print(f"   {out_frames[-1]['date_utc']}  {release}  {f['wavelength_um']:.3f} um  "
              f"PA {f['pa_deg']:.0f}  measured-predicted {offset:.2f}\"  flags {near_bits}")

    first, last = frames[0], frames[-1]
    m0 = SkyCoord(out_frames[0]["measured"]["ra"] * u.deg, out_frames[0]["measured"]["dec"] * u.deg)
    m1 = SkyCoord(out_frames[-1]["measured"]["ra"] * u.deg, out_frames[-1]["measured"]["dec"] * u.deg)
    p0 = SkyCoord(out_frames[0]["predicted"]["ra"] * u.deg, out_frames[0]["predicted"]["dec"] * u.deg)
    p1 = SkyCoord(out_frames[-1]["predicted"]["ra"] * u.deg, out_frames[-1]["predicted"]["dec"] * u.deg)
    meta = dict(
        mockup=True,
        object=dict(name="Barnard's Star", gaia_dr3=str(GAIA_SOURCE_ID), **{
            k: gaia[k] for k in ("ra", "dec", "pmra", "pmdec", "parallax", "radial_velocity",
                                 "ref_epoch")}, astrometry_from=gaia["from"]),
        grid=dict(size_px=n, pixel_scale_arcsec=PIXEL_SCALE_ARCSEC, center_ra=center.ra.deg,
                  center_dec=center.dec.deg, north_up=True, east_left=True),
        stretch=stretch,
        summary=dict(
            days=round(last["mjd_avg"] - first["mjd_avg"], 1),
            measured_motion_arcsec=round(float(m0.separation(m1).arcsec), 2),
            predicted_motion_arcsec=round(float(p0.separation(p1).arcsec), 2),
            wavelength_spread_um=round(float(np.ptp([f["wavelength_um"] for f in frames])), 3),
        ),
        frames=out_frames,
        credit="Data: NASA/JPL-Caltech/SPHEREx, via NASA/IPAC Infrared Science Archive (IRSA). "
               "Astrometry: ESA Gaia DR3.",
    )
    (args.out / "frames.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"7. Wrote {args.out / 'frames.json'}")
    print(f"   summary: {meta['summary']}")


if __name__ == "__main__":
    main()
