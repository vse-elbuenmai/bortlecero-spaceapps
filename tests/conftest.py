"""Shared pytest fixtures for synthetic SPHEREx Level 2b Multi-Extension FITS data."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from spherex_ingest.domain.models import RawCutoutFrame, SPHERExFlagBits
from spherex_ingest.infrastructure.mef_parser import SPHERExMEFParser


def make_synthetic_spherex_hdulist(
    center_ra_deg: float = 331.07645,
    center_dec_deg: float = -56.79382,
    star_ra_deg: float | None = None,
    star_dec_deg: float | None = None,
    shape: tuple[int, int] = (31, 31),
    pixel_scale_arcsec: float = 6.15,
    sps_epa_deg: float = 0.0,
    detector_band: int = 2,
    mjd_avg: float = 60800.0,
    obs_time_iso: str = "2025-05-05T00:00:00",
    peak_flux_mjy_sr: float = 250.0,
    psf_sigma_px: float = 1.35,
    zodi_level_mjy_sr: float = 42.0,
    saturate_core: bool = False,
    transient_pixel: tuple[int, int] | None = (5, 6),
    include_sip_without_suffix: bool = False,
) -> fits.HDUList:
    """Build a synthetic SPHEREx Level 2b Multi-Extension FITS HDUList.

    Includes PRIMARY, IMAGE, FLAGS, VARIANCE, ZODI, and WCS-WAVE extensions.
    """
    ny, nx = shape
    s_ra = star_ra_deg if star_ra_deg is not None else center_ra_deg
    s_dec = star_dec_deg if star_dec_deg is not None else center_dec_deg

    theta = np.deg2rad(sps_epa_deg)
    scale_deg = pixel_scale_arcsec / 3600.0
    cos_t = float(np.cos(theta))
    sin_t = float(np.sin(theta))

    # Standard North-up East-left when sps_epa_deg == 0, flipped 180 deg when sps_epa_deg == 180
    cd1_1 = -scale_deg * cos_t
    cd1_2 = scale_deg * sin_t
    cd2_1 = -scale_deg * sin_t
    cd2_2 = -scale_deg * cos_t if abs(sps_epa_deg - 180.0) < 1e-3 else scale_deg * cos_t
    if abs(sps_epa_deg - 180.0) < 1e-3:
        cd1_1 = scale_deg
        cd1_2 = 0.0
        cd2_1 = 0.0
        cd2_2 = -scale_deg
    elif abs(sps_epa_deg) < 1e-3:
        cd1_1 = -scale_deg
        cd1_2 = 0.0
        cd2_1 = 0.0
        cd2_2 = scale_deg

    # Slight 2-pixel pointing offset from cutout center so 180-deg roll moves raw pixel coords
    crpix1 = (nx + 1) / 2.0 + 1.5
    crpix2 = (ny + 1) / 2.0 - 1.0

    img_hdr = fits.Header()
    img_hdr["XTENSION"] = "IMAGE"
    img_hdr["EXTNAME"] = "IMAGE"
    img_hdr["NAXIS"] = 2
    img_hdr["NAXIS1"] = nx
    img_hdr["NAXIS2"] = ny
    img_hdr["CTYPE1"] = "RA---TAN"
    img_hdr["CTYPE2"] = "DEC--TAN"
    img_hdr["CRPIX1"] = crpix1
    img_hdr["CRPIX2"] = crpix2
    img_hdr["CRVAL1"] = center_ra_deg
    img_hdr["CRVAL2"] = center_dec_deg
    img_hdr["CD1_1"] = cd1_1
    img_hdr["CD1_2"] = cd1_2
    img_hdr["CD2_1"] = cd2_1
    img_hdr["CD2_2"] = cd2_2
    img_hdr["RADESYS"] = "ICRS"
    img_hdr["DETECTOR"] = detector_band
    img_hdr["MJD-AVG"] = mjd_avg
    img_hdr["DATE-AVG"] = obs_time_iso
    img_hdr["SPS_EPA"] = sps_epa_deg
    img_hdr["FINAST"] = 0
    img_hdr["WAVELEN"] = 1.37 if detector_band == 2 else 4.42
    img_hdr["BANDWID"] = 0.034

    if include_sip_without_suffix:
        img_hdr["A_ORDER"] = 2
        img_hdr["B_ORDER"] = 2
        img_hdr["A_2_0"] = 0.0
        img_hdr["B_0_2"] = 0.0

    wcs = WCS(img_hdr, naxis=2)
    x_star_arr, y_star_arr = wcs.wcs_world2pix(s_ra, s_dec, 0)
    x_star = float(x_star_arr)
    y_star = float(y_star_arr)

    yy, xx = np.mgrid[0:ny, 0:nx]
    zodi = (zodi_level_mjy_sr + 0.05 * (yy - ny / 2.0)).astype(np.float32)

    psf = peak_flux_mjy_sr * np.exp(
        -((xx - x_star) ** 2 + (yy - y_star) ** 2) / (2.0 * psf_sigma_px**2)
    )
    image = (zodi + psf).astype(np.float32)
    flags = np.zeros((ny, nx), dtype=np.uint32)
    variance = np.full((ny, nx), 0.25, dtype=np.float32)

    if saturate_core:
        iy = int(np.clip(round(y_star), 1, ny - 2))
        ix = int(np.clip(round(x_star), 1, nx - 2))
        image[iy, ix] = np.nan
        flags[iy - 1 : iy + 2, ix - 1 : ix + 2] |= int(SPHERExFlagBits.OVERFLOW)

    if transient_pixel is not None:
        ty, tx = transient_pixel
        if 0 <= ty < ny and 0 <= tx < nx:
            image[ty, tx] = 9999.0
            flags[ty, tx] |= int(SPHERExFlagBits.TRANSIENT)

    primary_hdu = fits.PrimaryHDU()
    primary_hdu.header["MISSION"] = "SPHEREx"
    primary_hdu.header["DETECTOR"] = detector_band

    image_hdu = fits.ImageHDU(data=image, header=img_hdr, name="IMAGE")
    flags_hdu = fits.ImageHDU(data=flags, name="FLAGS")
    var_hdu = fits.ImageHDU(data=variance, name="VARIANCE")
    zodi_hdu = fits.ImageHDU(data=zodi, name="ZODI")

    # Dummy WCS-WAVE binary table extension matching SPHEREx MEF structure
    col_lam = fits.Column(name="WAVELENGTH", format="1E", array=np.array([1.37], dtype=np.float32))
    wcs_wave_hdu = fits.BinTableHDU.from_columns([col_lam], name="WCS-WAVE")

    return fits.HDUList([primary_hdu, image_hdu, flags_hdu, var_hdu, zodi_hdu, wcs_wave_hdu])


@pytest.fixture
def mef_factory() -> Callable[..., fits.HDUList]:
    """Return factory callable that builds synthetic SPHEREx Level 2b HDULists."""
    return make_synthetic_spherex_hdulist


@pytest.fixture
def raw_cutout_factory() -> Callable[..., RawCutoutFrame]:
    """Return factory callable that builds parsed RawCutoutFrame instances."""
    parser = SPHERExMEFParser()

    def _build(
        frame_id: str = "synth_frame_01",
        collection: str = "spherex_dr1",
        **kwargs: object,
    ) -> RawCutoutFrame:
        center_ra = float(kwargs.get("center_ra_deg", 331.07645))
        center_dec = float(kwargs.get("center_dec_deg", -56.79382))
        hdul = make_synthetic_spherex_hdulist(**kwargs)  # type: ignore[arg-type]
        return parser.parse_hdulist(
            hdul=hdul,
            target_ra_deg=center_ra,
            target_dec_deg=center_dec,
            collection=collection,
            source_url=f"https://irsa.ipac.caltech.edu/SIA/{frame_id}.fits",
            frame_id=frame_id,
        )

    return _build
