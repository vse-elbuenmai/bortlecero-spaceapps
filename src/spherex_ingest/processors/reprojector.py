"""WCS reprojection onto a common North-up, East-left celestial grid."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.wcs import WCS
from reproject import reproject_interp

from spherex_ingest.limits import grid_side
from spherex_ingest.processors.cleaners import CleanedFrameResult


@dataclass(frozen=True)
class ReprojectedFrameResult:
    """Reprojected image, variance, Zodi, and boolean masks on the common North-up WCS grid."""

    reprojected_image_mjy_sr: np.ndarray
    repaired_image_mjy_sr: np.ndarray
    reprojected_variance: np.ndarray
    reprojected_zodi_mjy_sr: np.ndarray
    saturation_mask: np.ndarray
    bad_pixel_mask: np.ndarray
    footprint_mask: np.ndarray


class NorthUpCommonReprojector:
    """Reprojects SPHEREx detector cutouts onto a shared North-up ICRS TAN grid.

    Eliminates the 180-degree spacecraft roll (SPS_EPA) flip between 6-month survey passes.
    """

    def __init__(self, default_pixel_scale_arcsec: float = 6.15) -> None:
        self.default_pixel_scale_arcsec = default_pixel_scale_arcsec

    def build_common_wcs(
        self,
        center_ra_deg: float,
        center_dec_deg: float,
        cutout_size_arcsec: float,
        pixel_scale_arcsec: float | None = None,
    ) -> tuple[WCS, tuple[int, int]]:
        """Construct a standard North-up, East-left 2D TAN WCS and (ny, nx) grid shape."""
        scale = pixel_scale_arcsec or self.default_pixel_scale_arcsec
        npix = grid_side(cutout_size_arcsec, scale)
        shape_out = (npix, npix)

        wcs = WCS(naxis=2)
        wcs.wcs.crpix = [(npix + 1) / 2.0, (npix + 1) / 2.0]
        wcs.wcs.cdelt = [-scale / 3600.0, scale / 3600.0]
        wcs.wcs.crval = [float(center_ra_deg), float(center_dec_deg)]
        wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
        wcs.wcs.radesys = "ICRS"
        return wcs, shape_out

    def reproject_frame(
        self,
        cleaned: CleanedFrameResult,
        input_wcs: WCS,
        variance_mjy2_sr2: np.ndarray,
        zodi_mjy_sr: np.ndarray,
        common_wcs: WCS,
        shape_out: tuple[int, int],
    ) -> ReprojectedFrameResult:
        """Reproject cleaned science arrays, variance, Zodi, and bitmasks to the common WCS."""
        repaired_reproj, footprint = reproject_interp(
            (cleaned.repaired_image_mjy_sr, input_wcs),
            common_wcs,
            shape_out=shape_out,
            order="bilinear",
        )
        clean_reproj, _ = reproject_interp(
            (cleaned.clean_image_mjy_sr, input_wcs),
            common_wcs,
            shape_out=shape_out,
            order="bilinear",
        )
        var_reproj, _ = reproject_interp(
            (np.asarray(variance_mjy2_sr2, dtype=np.float64), input_wcs),
            common_wcs,
            shape_out=shape_out,
            order="bilinear",
        )
        zodi_reproj, _ = reproject_interp(
            (np.asarray(zodi_mjy_sr, dtype=np.float64), input_wcs),
            common_wcs,
            shape_out=shape_out,
            order="bilinear",
        )
        sat_float, _ = reproject_interp(
            (cleaned.saturation_mask.astype(np.float64), input_wcs),
            common_wcs,
            shape_out=shape_out,
            order="nearest-neighbor",
        )
        bad_float, _ = reproject_interp(
            (cleaned.bad_pixel_mask.astype(np.float64), input_wcs),
            common_wcs,
            shape_out=shape_out,
            order="nearest-neighbor",
        )

        footprint_mask = np.isfinite(footprint) & (footprint > 0.1)
        saturation_mask = np.isfinite(sat_float) & (sat_float >= 0.25)
        bad_pixel_mask = np.isfinite(bad_float) & (bad_float >= 0.25) & (~saturation_mask)

        # Preserve finite repaired values inside saturated cores while keeping clean_reproj faithful
        nan_clean_in_footprint = footprint_mask & (~np.isfinite(clean_reproj))
        if np.any(nan_clean_in_footprint & np.isfinite(repaired_reproj)):
            saturation_mask = saturation_mask | (
                nan_clean_in_footprint & np.isfinite(repaired_reproj)
            )

        return ReprojectedFrameResult(
            reprojected_image_mjy_sr=clean_reproj,
            repaired_image_mjy_sr=repaired_reproj,
            reprojected_variance=var_reproj,
            reprojected_zodi_mjy_sr=zodi_reproj,
            saturation_mask=saturation_mask,
            bad_pixel_mask=bad_pixel_mask,
            footprint_mask=footprint_mask,
        )
