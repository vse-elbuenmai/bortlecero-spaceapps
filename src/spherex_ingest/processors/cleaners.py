"""Zodiacal light subtraction, flag decoding, and saturated core repair for SPHEREx frames."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.stats import sigma_clipped_stats
from scipy.ndimage import binary_dilation

from spherex_ingest.domain.models import RawCutoutFrame, SPHERExFlagBits


@dataclass(frozen=True)
class CleanedFrameResult:
    """Output of Zodi subtraction and bitmask artifact cleaning on a single cutout."""

    clean_image_mjy_sr: np.ndarray
    repaired_image_mjy_sr: np.ndarray
    saturation_mask: np.ndarray
    bad_pixel_mask: np.ndarray
    residual_bg_mjy_sr: float


class ZodiAndFlagCleaner:
    """Subtracts Zodiacal foreground, masks bad artifacts, and repairs saturated stellar cores."""

    def __init__(self, subtract_residual_bg: bool = True, sigma_clip: float = 3.0) -> None:
        self._subtract_residual_bg = subtract_residual_bg
        self._sigma_clip = sigma_clip

    def clean(self, raw: RawCutoutFrame) -> CleanedFrameResult:
        """Clean a single RawCutoutFrame by subtracting Zodi and decoding SPHEREx FLAGS."""
        image = np.array(raw.image_mjy_sr, dtype=np.float64, copy=True)
        zodi = np.nan_to_num(np.asarray(raw.zodi_mjy_sr, dtype=np.float64), nan=0.0)
        flags = np.asarray(raw.flags_bitmask, dtype=np.int64)

        clean_image = image - zodi

        overflow_flagged = (flags & SPHERExFlagBits.saturation_mask()) != 0
        finite_mask = np.isfinite(clean_image)
        if np.any(finite_mask):
            p95 = float(np.nanpercentile(clean_image[finite_mask], 95.0))
            med = float(np.nanmedian(clean_image[finite_mask]))
            mad = float(np.nanmedian(np.abs(clean_image[finite_mask] - med)))
            high_flux_thresh = max(p95, med + 10.0 * max(mad * 1.4826, 1e-3))
            high_flux_seed = overflow_flagged | (finite_mask & (clean_image >= high_flux_thresh))
        else:
            high_flux_seed = overflow_flagged

        dilated_halo = binary_dilation(high_flux_seed, iterations=2)
        nan_core_adjacent = (~finite_mask) & dilated_halo
        saturation_mask = overflow_flagged | nan_core_adjacent

        raw_bad_mask = (flags & SPHERExFlagBits.bad_artifact_mask()) != 0
        bad_pixel_mask = raw_bad_mask & (~saturation_mask)

        residual_bg = 0.0
        valid_bg_mask = finite_mask & (~saturation_mask) & (~bad_pixel_mask)
        if self._subtract_residual_bg and np.count_nonzero(valid_bg_mask) >= 9:
            _, median_bg, _ = sigma_clipped_stats(
                clean_image[valid_bg_mask],
                sigma=self._sigma_clip,
                maxiters=5,
            )
            if np.isfinite(median_bg):
                residual_bg = float(median_bg)
                clean_image = clean_image - residual_bg

        clean_image = self._interpolate_bad_pixels(
            clean_image,
            bad_pixel_mask=bad_pixel_mask,
            saturation_mask=saturation_mask,
        )

        repaired_image = self._repair_saturated_cores(
            clean_image,
            saturation_mask=saturation_mask,
            bad_pixel_mask=bad_pixel_mask,
        )

        return CleanedFrameResult(
            clean_image_mjy_sr=clean_image,
            repaired_image_mjy_sr=repaired_image,
            saturation_mask=saturation_mask,
            bad_pixel_mask=bad_pixel_mask,
            residual_bg_mjy_sr=residual_bg,
        )

    @staticmethod
    def _interpolate_bad_pixels(
        image: np.ndarray,
        bad_pixel_mask: np.ndarray,
        saturation_mask: np.ndarray,
    ) -> np.ndarray:
        """Replace isolated bad pixels with the median of valid 3x3 neighbors."""
        out = image.copy()
        ny, nx = out.shape
        bad_ys, bad_xs = np.where(bad_pixel_mask)
        valid_donor = np.isfinite(out) & (~bad_pixel_mask) & (~saturation_mask)

        for y, x in zip(bad_ys, bad_xs, strict=False):
            y0, y1 = max(0, int(y) - 1), min(ny, int(y) + 2)
            x0, x1 = max(0, int(x) - 1), min(nx, int(x) + 2)
            patch_valid = valid_donor[y0:y1, x0:x1]
            if np.any(patch_valid):
                out[y, x] = float(np.median(out[y0:y1, x0:x1][patch_valid]))
            else:
                out[y, x] = 0.0
        return out

    @staticmethod
    def _repair_saturated_cores(
        image: np.ndarray,
        saturation_mask: np.ndarray,
        bad_pixel_mask: np.ndarray,
    ) -> np.ndarray:
        """Fill saturated NaN cores with the 98th percentile of surrounding 5x5 halo pixels."""
        repaired = image.copy()
        ny, nx = repaired.shape
        nan_sat = saturation_mask & (~np.isfinite(repaired))
        if not np.any(nan_sat):
            return repaired

        valid_finite = np.isfinite(repaired) & (~bad_pixel_mask)
        global_fallback = (
            float(np.nanpercentile(repaired[valid_finite], 99.0))
            if np.any(valid_finite)
            else 100.0
        )

        sat_ys, sat_xs = np.where(nan_sat)
        for y, x in zip(sat_ys, sat_xs, strict=False):
            y0, y1 = max(0, int(y) - 3), min(ny, int(y) + 4)
            x0, x1 = max(0, int(x) - 3), min(nx, int(x) + 4)
            halo_valid = valid_finite[y0:y1, x0:x1]
            if np.any(halo_valid):
                repaired[y, x] = float(np.percentile(repaired[y0:y1, x0:x1][halo_valid], 98.0))
            else:
                repaired[y, x] = global_fallback
        return repaired
