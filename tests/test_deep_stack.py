"""Tests for the target-tracked deep stack (co-addition of exposures)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from spherex_ingest.domain.models import BUNDLE_SCHEMA_VERSION, BlinkBundleDTO, ProcessedBlinkFrame
from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.exporters import FrontendBundleExporter
from spherex_ingest.processors import NorthUpCommonReprojector, TargetTrackedStacker
from spherex_ingest.processors.stacker import SKIP_TARGET_SATURATED, SKIP_TOO_FEW_FRAMES

GRID = 31
PIXEL_SCALE_ARCSEC = 6.15


def _frame(
    index: int,
    rng: np.random.Generator,
    predicted_xy: tuple[float, float] = (15.0, 15.0),
    source_xy: tuple[float, float] | None = None,
    source_peak: float = 0.0,
    noise: float = 1.0,
    band: int = 5,
    saturated_core: bool = False,
) -> ProcessedBlinkFrame:
    """One synthetic reprojected exposure: Gaussian noise plus an optional point source."""
    image = rng.normal(0.0, noise, size=(GRID, GRID))
    if source_xy is not None:
        yy, xx = np.indices(image.shape)
        image += source_peak * np.exp(
            -((xx - source_xy[0]) ** 2 + (yy - source_xy[1]) ** 2) / (2.0 * 0.9**2)
        )
    empty = np.zeros((GRID, GRID), dtype=bool)
    return ProcessedBlinkFrame(
        frame_id=f"frame_{index:02d}",
        collection="spherex_dr1",
        detector_band=band,
        mjd_avg=60800.0 + 30.0 * index,
        obs_time_iso=f"2025-05-{index + 1:02d}T00:00:00",
        sps_epa_deg=0.0,
        wavelength_um=3.9 + 0.05 * index,
        bandwidth_um=0.03,
        reprojected_image_mjy_sr=image,
        reprojected_variance=np.full((GRID, GRID), noise**2),
        reprojected_zodi_mjy_sr=np.zeros((GRID, GRID)),
        saturation_mask=empty.copy(),
        bad_pixel_mask=empty.copy(),
        footprint_mask=~empty,
        predicted_ra_deg=133.76,
        predicted_dec_deg=-7.2422,
        predicted_pixel_x=predicted_xy[0],
        predicted_pixel_y=predicted_xy[1],
        is_saturated_core=saturated_core,
    )


def _moving_track(n_frames: int) -> list[tuple[float, float]]:
    """Predicted positions drifting about five pixels across the series."""
    return [
        (13.2 + 4.4 * i / (n_frames - 1), 14.1 + 2.3 * i / (n_frames - 1))
        for i in range(n_frames)
    ]


def test_faint_moving_source_is_detected_only_in_the_stack() -> None:
    """A source below the single-exposure limit appears when the motion is followed."""
    rng = np.random.default_rng(855)
    track = _moving_track(12)
    frames = [
        _frame(i, rng, predicted_xy=xy, source_xy=xy, source_peak=2.5)
        for i, xy in enumerate(track)
    ]

    stack, skipped = TargetTrackedStacker().stack(frames, PIXEL_SCALE_ARCSEC)

    assert skipped is None
    assert stack is not None
    assert len(stack.frame_ids) == 12
    assert stack.detected
    assert stack.peak_snr is not None and stack.peak_snr > 6.0
    # The control that ignores the motion smears the source along its track.
    assert stack.sky_fixed_peak_snr is not None
    assert stack.sky_fixed_peak_snr < stack.peak_snr - 1.5
    # The source lands on the centre of the grid, where the prediction was moved to.
    assert stack.target_pixel_x == pytest.approx(15.0)
    assert stack.target_pixel_y == pytest.approx(15.0)
    assert stack.centroid_offset_arcsec is not None
    assert stack.centroid_offset_arcsec < 0.5 * PIXEL_SCALE_ARCSEC
    # The last exposure is the farthest from the grid centre: (17.6, 16.4) against (15, 15).
    assert stack.max_tracking_shift_px == pytest.approx(math.hypot(2.6, 1.4), abs=0.01)
    assert stack.wavelength_min_um == pytest.approx(3.9)
    assert stack.wavelength_max_um == pytest.approx(4.45)


def test_noise_averages_down_and_empty_sky_gives_no_detection() -> None:
    """Twelve exposures of pure noise lower the noise by about sqrt(12) and detect nothing."""
    rng = np.random.default_rng(2026)
    frames = [_frame(i, rng) for i in range(12)]

    stack, _ = TargetTrackedStacker().stack(frames, PIXEL_SCALE_ARCSEC)

    assert stack is not None
    assert stack.single_frame_noise_mjy_sr == pytest.approx(1.0, rel=0.1)
    assert stack.noise_reduction_factor == pytest.approx(math.sqrt(12), rel=0.15)
    assert not stack.detected
    assert stack.measured_centroid_x is None
    assert stack.centroid_offset_arcsec is None


def test_noisier_exposures_weigh_less() -> None:
    """A very noisy exposure must not spoil the stack of the good ones."""
    rng = np.random.default_rng(7)
    good = [_frame(i, rng) for i in range(8)]
    with_bad = [*good, _frame(8, rng, noise=20.0)]

    clean_stack, _ = TargetTrackedStacker().stack(good, PIXEL_SCALE_ARCSEC)
    mixed_stack, _ = TargetTrackedStacker().stack(with_bad, PIXEL_SCALE_ARCSEC)

    assert clean_stack is not None and mixed_stack is not None
    assert mixed_stack.noise_mjy_sr == pytest.approx(clean_stack.noise_mjy_sr, rel=0.05)


def test_cosmic_ray_or_flagged_pixel_cannot_fake_a_detection() -> None:
    """A hit in one exposure is rejected; a flagged pixel never enters the sum."""
    rng = np.random.default_rng(31)
    frames = [_frame(i, rng) for i in range(10)]
    frames[3].reprojected_image_mjy_sr[15, 15] = 80.0  # unflagged cosmic ray on the target
    frames[6].reprojected_image_mjy_sr[15, 16] = 500.0  # defect the archive did flag
    frames[6].bad_pixel_mask[15, 16] = True

    stack, _ = TargetTrackedStacker().stack(frames, PIXEL_SCALE_ARCSEC)

    assert stack is not None
    assert stack.rejected_pixel_count >= 1
    assert not stack.detected
    assert stack.coverage[15, 15] == 9
    assert stack.coverage[15, 16] == 9


def test_saturated_or_scarce_exposures_are_reported_not_stacked() -> None:
    """Adding exposures cannot fix a saturated core, and two exposures are not a stack."""
    rng = np.random.default_rng(3)
    stacker = TargetTrackedStacker()

    saturated = [_frame(i, rng, saturated_core=True) for i in range(6)]
    assert stacker.stack(saturated, PIXEL_SCALE_ARCSEC) == (None, SKIP_TARGET_SATURATED)

    two = [_frame(i, rng) for i in range(2)]
    assert stacker.stack(two, PIXEL_SCALE_ARCSEC) == (None, SKIP_TOO_FEW_FRAMES)

    # Unsaturated exposures are still stacked when enough of them remain.
    mixed = [*saturated[:2], *[_frame(10 + i, rng) for i in range(4)]]
    stack, skipped = stacker.stack(mixed, PIXEL_SCALE_ARCSEC)
    assert skipped is None
    assert stack is not None and len(stack.frame_ids) == 4


def test_bundle_carries_the_deep_stack_in_display_orientation() -> None:
    """The exporter publishes the stack north-up, like the frames, and survives JSON."""
    target = BENCHMARK_TARGETS["wise_0855_0714"]
    common_wcs, shape = NorthUpCommonReprojector().build_common_wcs(
        center_ra_deg=target.ra_deg,
        center_dec_deg=target.dec_deg,
        cutout_size_arcsec=180.0,
    )
    assert shape == (GRID, GRID)
    rng = np.random.default_rng(11)
    # The source sits two rows north of the prediction (higher array row).
    frames = [
        _frame(i, rng, predicted_xy=(15.0, 15.0), source_xy=(15.0, 17.0), source_peak=40.0)
        for i in range(6)
    ]

    bundle = FrontendBundleExporter().build_bundle(target, frames, common_wcs, shape)

    assert bundle.schema_version == BUNDLE_SCHEMA_VERSION == "1.1.0"
    assert bundle.deep_stack_skipped_reason is None
    stack = bundle.deep_stack
    assert stack is not None
    assert stack.frame_count == 6
    assert stack.detector_bands == [5]
    assert stack.target_pixel_x == pytest.approx(15.0)
    assert stack.target_pixel_y == pytest.approx(15.0)
    assert stack.png_base64 is not None and stack.png_base64.startswith("data:image/png;base64,")
    # Display rows run north to south, so the bright source is on row 30 - 17 = 13.
    matrix = np.array(stack.matrix_mjy_sr, dtype=float)
    assert matrix.shape == (GRID, GRID)
    assert np.unravel_index(np.nanargmax(matrix), matrix.shape) == (13, 15)
    assert any("deep stack" in warning for warning in bundle.scientific_warnings)

    restored = BlinkBundleDTO.model_validate_json(bundle.model_dump_json())
    assert restored.deep_stack == stack


def test_bundle_explains_a_missing_stack() -> None:
    """A saturated target yields no stack and a reason the viewer can show."""
    target = BENCHMARK_TARGETS["barnards_star"]
    common_wcs, shape = NorthUpCommonReprojector().build_common_wcs(
        center_ra_deg=target.ra_deg,
        center_dec_deg=target.dec_deg,
        cutout_size_arcsec=180.0,
    )
    rng = np.random.default_rng(5)
    frames = [_frame(i, rng, saturated_core=True) for i in range(5)]

    bundle = FrontendBundleExporter().build_bundle(target, frames, common_wcs, shape)

    assert bundle.deep_stack is None
    assert bundle.deep_stack_skipped_reason == SKIP_TARGET_SATURATED
    assert any("No deep stack" in warning for warning in bundle.scientific_warnings)
