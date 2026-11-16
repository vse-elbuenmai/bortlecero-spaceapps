"""Target-tracked co-addition ("deep stack") of the reprojected exposures of one target.

A source too faint for any single exposure can still be found by adding the exposures:
the signal adds up while the noise averages down, roughly as the square root of the number
of exposures. Because a nearby star or brown dwarf moves between exposures, each frame is
first shifted so that the position predicted for its date lands on the same pixel. This is
the "comet mode" of astrophotography stacking: align on the moving object, not on the field.

The stack mixes exposures taken at different wavelengths, so it says that something is
there and where it is. It is not a brightness measurement.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import shift as ndimage_shift

from spherex_ingest.domain.models import ProcessedBlinkFrame

MAD_TO_SIGMA = 1.4826
SKIP_TOO_FEW_FRAMES = "too_few_frames"
SKIP_TARGET_SATURATED = "target_saturated"


@dataclass(frozen=True)
class DeepStackResult:
    """The co-added image in the target's rest frame and what was measured on it.

    Pixel coordinates follow the array convention of ``ProcessedBlinkFrame`` (row 0 south).
    """

    image_mjy_sr: np.ndarray
    coverage: np.ndarray
    frame_ids: tuple[str, ...]
    detector_bands: tuple[int, ...]
    wavelength_min_um: float
    wavelength_max_um: float
    mjd_start: float
    mjd_end: float
    obs_time_start_iso: str
    obs_time_end_iso: str
    max_tracking_shift_px: float
    target_pixel_x: float
    target_pixel_y: float
    noise_mjy_sr: float
    single_frame_noise_mjy_sr: float
    noise_reduction_factor: float
    peak_snr: float | None
    sky_fixed_peak_snr: float | None
    detected: bool
    detection_threshold_sigma: float
    measured_centroid_x: float | None
    measured_centroid_y: float | None
    centroid_offset_arcsec: float | None
    rejected_pixel_count: int


@dataclass(frozen=True)
class _Combined:
    image: np.ndarray
    coverage: np.ndarray
    rejected: int


class TargetTrackedStacker:
    """Co-adds reprojected frames while following the predicted motion of the target."""

    def __init__(
        self,
        min_frames: int = 3,
        detection_sigma: float = 5.0,
        clip_sigma: float = 5.0,
        min_frames_for_clipping: int = 4,
        core_radius_px: float = 1.5,
        noise_inner_radius_px: float = 4.0,
        centroid_half_size_px: int = 2,
    ) -> None:
        self._min_frames = max(2, min_frames)
        self._detection_sigma = detection_sigma
        self._clip_sigma = clip_sigma
        self._min_frames_for_clipping = min_frames_for_clipping
        self._core_radius_px = core_radius_px
        self._noise_inner_radius_px = noise_inner_radius_px
        self._centroid_half_size_px = centroid_half_size_px

    def stack(
        self,
        frames: Sequence[ProcessedBlinkFrame],
        pixel_scale_arcsec: float,
    ) -> tuple[DeepStackResult | None, str | None]:
        """Return the deep stack, or ``None`` with the reason it could not be built."""
        ordered = sorted(frames, key=lambda f: (f.mjd_avg, f.detector_band, f.frame_id))
        if len(ordered) < self._min_frames:
            return None, SKIP_TOO_FEW_FRAMES

        ny, nx = ordered[0].reprojected_image_mjy_sr.shape
        center_x = (nx - 1) / 2.0
        center_y = (ny - 1) / 2.0

        used: list[ProcessedBlinkFrame] = []
        tracked: list[np.ndarray] = []
        fixed: list[np.ndarray] = []
        tracked_sigmas: list[float] = []
        fixed_sigmas: list[float] = []
        saturated = 0
        for frame in ordered:
            if frame.is_saturated_core:
                # Too much light, not too little: adding exposures cannot recover the core.
                saturated += 1
                continue
            if frame.reprojected_image_mjy_sr.shape != (ny, nx):
                continue
            if not (0.0 <= frame.predicted_pixel_x <= nx - 1) or not (
                0.0 <= frame.predicted_pixel_y <= ny - 1
            ):
                continue

            image = np.asarray(frame.reprojected_image_mjy_sr, dtype=np.float64)
            valid = (
                np.isfinite(image)
                & frame.footprint_mask
                & (~frame.bad_pixel_mask)
                & (~frame.saturation_mask)
            )
            unshifted, unshifted_sigma = self._level(np.where(valid, image, np.nan))
            shifted, shifted_sigma = self._level(
                self._shift(
                    image,
                    valid,
                    dy=center_y - frame.predicted_pixel_y,
                    dx=center_x - frame.predicted_pixel_x,
                )
            )
            if unshifted_sigma is None or shifted_sigma is None:
                continue

            used.append(frame)
            tracked.append(shifted)
            fixed.append(unshifted)
            tracked_sigmas.append(shifted_sigma)
            fixed_sigmas.append(unshifted_sigma)

        if len(used) < self._min_frames:
            if saturated > 0 and len(used) + saturated >= self._min_frames:
                return None, SKIP_TARGET_SATURATED
            return None, SKIP_TOO_FEW_FRAMES

        combined = self._combine(np.stack(tracked), np.asarray(tracked_sigmas))
        image, noise = self._level_outside_core(combined.image, center_x, center_y)
        if noise is None:
            return None, SKIP_TOO_FEW_FRAMES

        peak_snr, peak_xy = self._peak(image, noise, center_x, center_y)
        detected = peak_snr is not None and peak_snr >= self._detection_sigma

        measured_x: float | None = None
        measured_y: float | None = None
        offset_arcsec: float | None = None
        if detected and peak_xy is not None:
            centroid = self._centroid(image, peak_xy)
            if centroid is not None:
                offset_px = math.hypot(centroid[0] - center_x, centroid[1] - center_y)
                if offset_px <= self._core_radius_px + 1.0:
                    measured_x, measured_y = centroid
                    offset_arcsec = offset_px * pixel_scale_arcsec

        # Control: the same exposures added without following the motion. For a target that
        # really moves as predicted, the tracked stack must be the sharper of the two.
        mean_pred_x = float(np.mean([f.predicted_pixel_x for f in used]))
        mean_pred_y = float(np.mean([f.predicted_pixel_y for f in used]))
        fixed_combined = self._combine(np.stack(fixed), np.asarray(fixed_sigmas))
        fixed_image, fixed_noise = self._level_outside_core(
            fixed_combined.image, mean_pred_x, mean_pred_y
        )
        sky_fixed_peak_snr = (
            self._peak(fixed_image, fixed_noise, mean_pred_x, mean_pred_y)[0]
            if fixed_noise is not None
            else None
        )

        single_noise = float(np.median(fixed_sigmas))
        max_shift = max(
            math.hypot(center_x - f.predicted_pixel_x, center_y - f.predicted_pixel_y)
            for f in used
        )
        wavelengths = [f.wavelength_um for f in used]

        return (
            DeepStackResult(
                image_mjy_sr=image,
                coverage=combined.coverage,
                frame_ids=tuple(f.frame_id for f in used),
                detector_bands=tuple(sorted({f.detector_band for f in used})),
                wavelength_min_um=float(min(wavelengths)),
                wavelength_max_um=float(max(wavelengths)),
                mjd_start=float(used[0].mjd_avg),
                mjd_end=float(used[-1].mjd_avg),
                obs_time_start_iso=used[0].obs_time_iso,
                obs_time_end_iso=used[-1].obs_time_iso,
                max_tracking_shift_px=float(max_shift),
                target_pixel_x=center_x,
                target_pixel_y=center_y,
                noise_mjy_sr=noise,
                single_frame_noise_mjy_sr=single_noise,
                noise_reduction_factor=single_noise / noise,
                peak_snr=peak_snr,
                sky_fixed_peak_snr=sky_fixed_peak_snr,
                detected=detected,
                detection_threshold_sigma=self._detection_sigma,
                measured_centroid_x=measured_x,
                measured_centroid_y=measured_y,
                centroid_offset_arcsec=offset_arcsec,
                rejected_pixel_count=combined.rejected,
            ),
            None,
        )

    @staticmethod
    def _shift(image: np.ndarray, valid: np.ndarray, dy: float, dx: float) -> np.ndarray:
        """Shift by a sub-pixel amount without letting masked pixels leak into their neighbours.

        The data and its validity map are shifted separately and divided, so a masked pixel
        only lowers the weight of the output pixels it touches instead of poisoning them.
        """
        weights = valid.astype(np.float64)
        data = np.where(valid, image, 0.0)
        shifted_data = ndimage_shift(data, (dy, dx), order=1, mode="constant", cval=0.0)
        shifted_weights = ndimage_shift(weights, (dy, dx), order=1, mode="constant", cval=0.0)
        out = np.full(image.shape, np.nan, dtype=np.float64)
        np.divide(shifted_data, shifted_weights, out=out, where=shifted_weights >= 0.5)
        return out

    @staticmethod
    def _robust_sigma(values: np.ndarray) -> tuple[float, float] | None:
        """Median and MAD-based standard deviation, insensitive to the stars in the field."""
        finite = values[np.isfinite(values)]
        if finite.size < 9:
            return None
        median = float(np.median(finite))
        sigma = MAD_TO_SIGMA * float(np.median(np.abs(finite - median)))
        if not np.isfinite(sigma) or sigma <= 0.0:
            return None
        return median, sigma

    def _level(self, image: np.ndarray) -> tuple[np.ndarray, float | None]:
        """Subtract the sky level of one exposure and report its noise."""
        stats = self._robust_sigma(image)
        if stats is None:
            return image, None
        return image - stats[0], stats[1]

    def _level_outside_core(
        self, image: np.ndarray, x: float, y: float
    ) -> tuple[np.ndarray, float | None]:
        """Measure sky level and noise away from the target, on the image itself."""
        yy, xx = np.indices(image.shape)
        away = np.hypot(xx - x, yy - y) >= self._noise_inner_radius_px
        stats = self._robust_sigma(image[away])
        if stats is None:
            stats = self._robust_sigma(image)
        if stats is None:
            return image, None
        return image - stats[0], stats[1]

    def _combine(self, cube: np.ndarray, sigmas: np.ndarray) -> _Combined:
        """Inverse-variance weighted mean with rejection of discordant pixels."""
        n_frames = cube.shape[0]
        valid = np.isfinite(cube)
        n_valid = valid.sum(axis=0)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            median = np.nanmedian(cube, axis=0)
        median = np.nan_to_num(median, nan=0.0)

        # A cosmic ray lands in one exposure only. The tolerance grows with the brightness of
        # the pixel because each exposure sees a different wavelength, so a real star is
        # allowed to differ between exposures.
        tolerance = self._clip_sigma * np.sqrt(
            sigmas[:, None, None] ** 2 + (0.5 * np.abs(median)[None, :, :]) ** 2
        )
        deviation = np.abs(np.where(valid, cube, 0.0) - median[None, :, :])
        outlier = valid & (n_valid[None, :, :] >= self._min_frames_for_clipping) & (
            deviation > tolerance
        )
        keep = valid & (~outlier)

        weights = np.where(keep, 1.0 / sigmas[:, None, None] ** 2, 0.0)
        weight_sum = weights.sum(axis=0)
        weighted = (np.where(keep, cube, 0.0) * weights).sum(axis=0)
        coverage = keep.sum(axis=0)

        min_coverage = max(2, math.ceil(n_frames / 2))
        image = np.full(cube.shape[1:], np.nan, dtype=np.float64)
        np.divide(weighted, weight_sum, out=image, where=coverage >= min_coverage)
        return _Combined(image=image, coverage=coverage, rejected=int(outlier.sum()))

    def _peak(
        self, image: np.ndarray, noise: float | None, x: float, y: float
    ) -> tuple[float | None, tuple[int, int] | None]:
        """Brightest pixel within the core radius of the prediction, in units of the noise."""
        if noise is None:
            return None, None
        yy, xx = np.indices(image.shape)
        core = (np.hypot(xx - x, yy - y) <= self._core_radius_px) & np.isfinite(image)
        if not np.any(core):
            return None, None
        masked = np.where(core, image, -np.inf)
        peak_y, peak_x = np.unravel_index(int(np.argmax(masked)), image.shape)
        return float(image[peak_y, peak_x] / noise), (int(peak_x), int(peak_y))

    def _centroid(self, image: np.ndarray, peak_xy: tuple[int, int]) -> tuple[float, float] | None:
        """Centre of light of the positive flux in a small window around the peak."""
        ny, nx = image.shape
        half = self._centroid_half_size_px
        x0, x1 = max(0, peak_xy[0] - half), min(nx, peak_xy[0] + half + 1)
        y0, y1 = max(0, peak_xy[1] - half), min(ny, peak_xy[1] + half + 1)
        window = np.clip(np.nan_to_num(image[y0:y1, x0:x1], nan=0.0), 0.0, None)
        total = float(window.sum())
        if total <= 0.0:
            return None
        yy, xx = np.indices(window.shape)
        return (
            x0 + float((window * xx).sum() / total),
            y0 + float((window * yy).sum() / total),
        )
