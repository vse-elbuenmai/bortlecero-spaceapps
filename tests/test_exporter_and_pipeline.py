"""End-to-end tests for SPHERExFrameProcessor and FrontendBundleExporter."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import numpy as np
import pytest
from PIL import Image

from spherex_ingest._atomic_files import atomic_write_bytes
from spherex_ingest.domain.models import (
    BlinkBundleDTO,
    DroppedFrameDTO,
    ProcessedBlinkFrame,
    RawCutoutFrame,
)
from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.exporters.bundle_exporter import FrontendBundleExporter
from spherex_ingest.processors.kinematics import KinematicsAndPhotometryAnalyzer
from spherex_ingest.processors.pipeline_processor import SPHERExFrameProcessor


def test_readers_see_complete_bundles_during_concurrent_or_interrupted_writes(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = BENCHMARK_TARGETS["epsilon_indi_b"]
    exporter = FrontendBundleExporter()
    frame = raw_cutout_factory()
    bundle = exporter.build_bundle(
        target, *SPHERExFrameProcessor().process_frames([frame], target)
    )
    bundle_path = exporter.save_bundle(bundle, tmp_path)
    assert bundle.total_frames == 1
    original_bytes = bundle_path.read_bytes()
    changed = bundle.model_copy(update={"scientific_warnings": ["Updated warnings."]})
    overlap = Barrier(2, timeout=10)
    original_replace = Path.replace

    def concurrent_replace(path, destination):
        if destination == bundle_path:
            assert bundle_path.read_bytes() == original_bytes
            assert BlinkBundleDTO.model_validate_json(path.read_bytes()) == changed
            overlap.wait()
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", concurrent_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        writes = [executor.submit(exporter.save_bundle, changed, tmp_path) for _ in range(2)]
        assert [write.result(timeout=10) for write in writes] == [bundle_path, bundle_path]

    def interrupted_replace(path, destination):
        if destination == bundle_path:
            raise OSError("Publication interrupted")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", interrupted_replace)
    with pytest.raises(OSError, match="Publication interrupted"):
        exporter.save_bundle(bundle, tmp_path)

    persisted = BlinkBundleDTO.model_validate_json(bundle_path.read_bytes())
    assert persisted == changed
    assert persisted.frames_chronological[0].png_base64 is not None
    assert not list(tmp_path.rglob(".spherex-*.tmp"))


def test_atomic_write_bytes_retries_transient_permission_error_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify atomic_write_bytes retries transient WinError 5 PermissionError during replace."""
    destination = tmp_path / "bundle.json"
    payload = b'{"status":"ok"}\n'
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path: Path, target: Path) -> Path:
        nonlocal attempts
        if target == destination:
            attempts += 1
            if attempts <= 3:
                raise PermissionError("WinError 5")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    atomic_write_bytes(destination, payload)

    assert attempts == 4
    assert destination.read_bytes() == payload
    assert not list(tmp_path.rglob(".spherex-*.tmp"))


def test_atomic_write_bytes_reraises_persistent_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify atomic_write_bytes re-raises PermissionError after 10 attempts and cleans up .tmp."""
    destination = tmp_path / "bundle.json"
    attempts = 0
    sleep_calls: list[float] = []

    def always_locked(path: Path, target: Path) -> Path:
        nonlocal attempts
        attempts += 1
        raise PermissionError("WinError 5")

    monkeypatch.setattr(Path, "replace", always_locked)
    monkeypatch.setattr("spherex_ingest._atomic_files.time.sleep", sleep_calls.append)

    with pytest.raises(PermissionError, match="WinError 5"):
        atomic_write_bytes(destination, b"data")

    assert attempts == 10
    assert len(sleep_calls) == 9
    assert not destination.exists()
    assert not list(tmp_path.rglob(".spherex-*.tmp"))


def test_end_to_end_pipeline_and_bundle_exporter(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
    tmp_path: Path,
) -> None:
    """Verify full processing and bundle export across multiple passes and bands."""
    target = BENCHMARK_TARGETS["barnards_star"]
    analyzer = KinematicsAndPhotometryAnalyzer()

    mjd_early = 60750.0
    mjd_late = 60935.0  # ~6 months later

    ra_early, dec_early = analyzer.propagate_position(target, mjd_early)
    ra_late, dec_late = analyzer.propagate_position(target, mjd_late)

    raw_frames = [
        raw_cutout_factory(
            frame_id="barnard_d2_pass1",
            collection="spherex_dr1",
            center_ra_deg=ra_early,
            center_dec_deg=dec_early,
            star_ra_deg=ra_early,
            star_dec_deg=dec_early,
            detector_band=2,
            mjd_avg=mjd_early,
            obs_time_iso="2025-03-16T00:00:00",
            sps_epa_deg=0.0,
            saturate_core=True,
        ),
        raw_cutout_factory(
            frame_id="barnard_d2_pass2",
            collection="spherex_qr3",
            center_ra_deg=ra_early,
            center_dec_deg=dec_early,
            star_ra_deg=ra_late,
            star_dec_deg=dec_late,
            detector_band=2,
            mjd_avg=mjd_late,
            obs_time_iso="2025-09-17T00:00:00",
            sps_epa_deg=180.0,
            saturate_core=True,
        ),
        raw_cutout_factory(
            frame_id="barnard_d5_pass1",
            collection="spherex_dr1",
            center_ra_deg=ra_early,
            center_dec_deg=dec_early,
            star_ra_deg=ra_early,
            star_dec_deg=dec_early,
            detector_band=5,
            mjd_avg=mjd_early + 1.0,
            obs_time_iso="2025-03-17T00:00:00",
            sps_epa_deg=0.0,
            saturate_core=False,
        ),
    ]

    processor = SPHERExFrameProcessor()
    processed_frames, common_wcs, grid_shape = processor.process_frames(raw_frames, target)

    assert len(processed_frames) == 3
    assert grid_shape[0] % 2 == 1

    exporter = FrontendBundleExporter()
    bundle = exporter.build_bundle(
        target=target,
        processed_frames=processed_frames,
        common_wcs=common_wcs,
        grid_shape=grid_shape,
    )

    assert bundle.total_frames == 3
    assert bundle.available_bands == [2, 5]
    assert len(bundle.frames_by_band["2"]) == 2
    assert len(bundle.frames_by_band["5"]) == 1
    assert len(bundle.difference_maps) == 1
    assert bundle.difference_maps[0].detector_band == 2
    assert bundle.difference_maps[0].baseline_days == 185.0
    assert bundle.difference_maps[0].early_wavelength_um > 0.0
    assert bundle.difference_maps[0].late_wavelength_um > 0.0
    assert bundle.difference_maps[0].delta_wavelength_um >= 0.0
    assert bundle.difference_maps[0].png_base64 is not None
    assert bundle.difference_maps[0].png_base64.startswith("data:image/png;base64,")

    for frame_dto in bundle.frames_chronological:
        assert frame_dto.png_base64 is not None
        assert frame_dto.png_base64.startswith("data:image/png;base64,")

    # Verify scientific warnings cover 180-deg roll, multi-band LVF, and core saturation
    joined_warnings = " ".join(bundle.scientific_warnings)
    assert "SPS_EPA" in joined_warnings
    assert "Linear Variable Filters" in joined_warnings
    assert "saturation" in joined_warnings.lower()

    # Verify saving bundle to disk
    bundle_json_path = exporter.save_bundle(bundle, tmp_path)
    assert bundle_json_path.exists()
    parsed = json.loads(bundle_json_path.read_text(encoding="utf-8"))
    assert parsed["target"]["target_id"] == "barnards_star"
    assert (tmp_path / "barnards_star" / "frames" / "barnard_d2_pass1.png").exists()
    assert any((tmp_path / "barnards_star" / "differences").glob("*.png"))

    # Verify North-up coordinate and mask flipping across frames
    for orig, dto in zip(processed_frames, bundle.frames_chronological, strict=True):
        ny = orig.reprojected_image_mjy_sr.shape[0]
        expected_pred_y = round((ny - 1) - orig.predicted_pixel_y, 3)
        assert dto.predicted_pixel_y == expected_pred_y
        if orig.measured_centroid_y is not None:
            expected_meas_y = round((ny - 1) - orig.measured_centroid_y, 3)
            assert dto.measured_centroid_y == expected_meas_y

        disp = (
            orig.repaired_image_mjy_sr
            if orig.repaired_image_mjy_sr is not None
            else orig.reprojected_image_mjy_sr
        )
        # Check center pixel and overall row inversion
        mid_y = ny // 2
        mid_x = disp.shape[1] // 2
        assert dto.matrix_mjy_sr[mid_y][mid_x] == pytest.approx(disp[mid_y, mid_x], abs=1e-4)

        for r in (0, ny - 1):
            for c in (0, mid_x, disp.shape[1] - 1):
                disp_val = disp[r, c]
                dto_val = dto.matrix_mjy_sr[(ny - 1) - r][c]
                if np.isnan(disp_val):
                    assert dto_val is None
                else:
                    assert dto_val == pytest.approx(disp_val, abs=1e-4)
        assert dto.saturation_mask[0] == orig.saturation_mask[ny - 1].astype(bool).tolist()
        assert dto.bad_pixel_mask[0] == orig.bad_pixel_mask[ny - 1].astype(bool).tolist()


def test_bundle_exporter_north_up_orientation_and_coordinate_sync() -> None:
    """Verify that bundle exporter flips images/matrices North-up and syncs pixel coordinates."""
    ny, nx = 21, 21
    # Create an array where only the top row in FITS space (North, y=ny-1) is bright
    image = np.zeros((ny, nx), dtype=np.float32)
    image[ny - 1, 10] = 50.0  # North row in FITS space
    image[0, 10] = 1.0       # South row in FITS space

    sat_mask = np.zeros((ny, nx), dtype=bool)
    sat_mask[ny - 1, 10] = True

    bad_mask = np.zeros((ny, nx), dtype=bool)
    bad_mask[0, 10] = True

    fits_pred_x = 10.0
    fits_pred_y = 2.0  # In FITS space, near South
    fits_meas_x = 10.2
    fits_meas_y = 2.5

    frame = ProcessedBlinkFrame(
        frame_id="frame_test_orient",
        collection="spherex_dr1",
        detector_band=1,
        mjd_avg=60800.0,
        obs_time_iso="2025-05-05T12:00:00",
        sps_epa_deg=0.0,
        wavelength_um=1.0,
        bandwidth_um=0.02,
        reprojected_image_mjy_sr=image,
        reprojected_variance=np.ones((ny, nx), dtype=np.float32),
        reprojected_zodi_mjy_sr=np.zeros((ny, nx), dtype=np.float32),
        saturation_mask=sat_mask,
        bad_pixel_mask=bad_mask,
        footprint_mask=np.ones((ny, nx), dtype=bool),
        predicted_ra_deg=269.4485,
        predicted_dec_deg=4.7394,
        predicted_pixel_x=fits_pred_x,
        predicted_pixel_y=fits_pred_y,
        measured_centroid_x=fits_meas_x,
        measured_centroid_y=fits_meas_y,
        measured_ra_deg=269.4485,
        measured_dec_deg=4.7394,
        centroid_offset_arcsec=0.1,
        aperture_flux_ujy=100.0,
        aperture_flux_err_ujy=1.0,
        snr=100.0,
        is_saturated_core=False,
    )

    exporter = FrontendBundleExporter(upscale_factor=1)
    png_b64 = exporter._render_arcsinh_png_base64(
        image, vmin=0.0, vmax=50.0, softening=1.0, saturation_mask=sat_mask
    )
    dto = exporter._to_frame_dto(frame, png_b64=png_b64)

    # 1. Coordinates: transformed to display space (y_display = (ny - 1) - y_fits)
    assert dto.predicted_pixel_x == fits_pred_x
    assert dto.predicted_pixel_y == round((ny - 1) - fits_pred_y, 3)
    assert dto.predicted_pixel_y == 18.0  # (21 - 1) - 2.0 = 18.0

    assert dto.measured_centroid_x == fits_meas_x
    assert dto.measured_centroid_y == round((ny - 1) - fits_meas_y, 3)
    assert dto.measured_centroid_y == 17.5  # (21 - 1) - 2.5 = 17.5

    # 2. JSON matrix: row 0 is North (FITS row ny-1)
    assert dto.matrix_mjy_sr[0][10] == 50.0
    assert dto.matrix_mjy_sr[ny - 1][10] == 1.0

    # 3. Masks: row 0 is North
    assert dto.saturation_mask[0][10] is True
    assert dto.saturation_mask[ny - 1][10] is False
    assert dto.bad_pixel_mask[0][10] is False
    assert dto.bad_pixel_mask[ny - 1][10] is True

    # 4. Decoded PNG image: top row (row 0) has the brightest pixel
    png_data = base64.b64decode(png_b64.split(",", 1)[1])
    img = Image.open(io.BytesIO(png_data))
    img_arr = np.array(img)
    # Row 0 (North) should be brighter than bottom row (ny-1)
    assert int(img_arr[0, 10, 0]) > int(img_arr[ny - 1, 10, 0])

    # 5. Difference image diverging PNG & matrix
    diff = np.zeros((ny, nx), dtype=np.float32)
    diff[ny - 1, 10] = 10.0
    diff[0, 10] = -10.0
    diff_matrix = exporter._matrix_to_nullable_list(diff)
    assert diff_matrix[0][10] == 10.0
    assert diff_matrix[ny - 1][10] == -10.0

    diff_png_b64 = exporter._render_diverging_png_base64(diff)
    diff_png_data = base64.b64decode(diff_png_b64.split(",", 1)[1])
    diff_img = Image.open(io.BytesIO(diff_png_data))
    diff_arr = np.array(diff_img)
    # Top row should show positive color (orange/white: r > 200, b < 200)
    # Bottom row should show negative color (blue: b > 200)
    assert int(diff_arr[0, 10, 0]) > 150
    assert int(diff_arr[ny - 1, 10, 2]) > 150


def test_difference_map_wavelength_optimization_and_warning() -> None:
    """Verify difference maps pair frames minimizing |delta_lambda| and warn if > 0.05 um."""
    target = BENCHMARK_TARGETS["barnards_star"]
    exporter = FrontendBundleExporter(min_diff_baseline_days=5.0, upscale_factor=1)

    dummy_shape = (11, 11)
    dummy_img = np.ones(dummy_shape, dtype=np.float32)
    dummy_var = np.full(dummy_shape, 0.1, dtype=np.float32)
    dummy_mask = np.zeros(dummy_shape, dtype=bool)

    def make_frame(fid: str, mjd: float, lam: float) -> ProcessedBlinkFrame:
        return ProcessedBlinkFrame(
            frame_id=fid,
            collection="spherex_dr1",
            detector_band=3,
            mjd_avg=mjd,
            obs_time_iso="2025-01-01T00:00:00",
            sps_epa_deg=0.0,
            wavelength_um=lam,
            bandwidth_um=0.04,
            reprojected_image_mjy_sr=dummy_img,
            reprojected_variance=dummy_var,
            reprojected_zodi_mjy_sr=dummy_img,
            saturation_mask=dummy_mask,
            bad_pixel_mask=dummy_mask,
            footprint_mask=~dummy_mask,
            predicted_ra_deg=target.ra_deg,
            predicted_dec_deg=target.dec_deg,
            predicted_pixel_x=5.0,
            predicted_pixel_y=5.0,
        )

    f1 = make_frame("frame_1", 60000.0, 2.10)
    f2 = make_frame("frame_2", 60030.0, 2.25)
    f3 = make_frame("frame_3", 60060.0, 2.12)

    # Case A: 3 frames. Minimal delta_lambda pair is (f1, f3) with delta = 0.02 um
    diffs_optimized = exporter._build_difference_maps([f1, f2, f3])
    assert len(diffs_optimized) == 1
    diff = diffs_optimized[0]
    assert diff.frame_id_early == "frame_1"
    assert diff.frame_id_late == "frame_3"
    assert diff.early_wavelength_um == 2.10
    assert diff.late_wavelength_um == 2.12
    assert diff.delta_wavelength_um == 0.02
    assert diff.baseline_days == 60.0

    warnings_a = exporter._generate_scientific_warnings(
        target, [f1, f2, f3], difference_maps=diffs_optimized
    )
    assert not any("delta_lambda > 0.05" in w for w in warnings_a)

    # Case B: Only f1 and f2. delta_lambda = 0.15 um > 0.05 um
    diffs_large_delta = exporter._build_difference_maps([f1, f2])
    assert len(diffs_large_delta) == 1
    diff_large = diffs_large_delta[0]
    assert diff_large.delta_wavelength_um == 0.15
    assert diff_large.early_wavelength_um == 2.10
    assert diff_large.late_wavelength_um == 2.25

    warnings_b = exporter._generate_scientific_warnings(
        target, [f1, f2], difference_maps=diffs_large_delta
    )
    assert any("delta_lambda > 0.05 um" in w for w in warnings_b)


def test_bundle_exporter_tracks_low_coverage_frames() -> None:
    """Verify Finding 9: frames with valid_pixel_fraction < 0.40 are dropped and tracked."""
    target = BENCHMARK_TARGETS["barnards_star"]
    exporter = FrontendBundleExporter()
    reprojector = SPHERExFrameProcessor()._reprojector

    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=target.ra_deg,
        center_dec_deg=target.dec_deg,
        cutout_size_arcsec=180.0,
    )

    # Build one normal coverage frame (100% valid) and one low-coverage frame (10% valid)
    ny, nx = shape_out
    full_img = np.ones((ny, nx), dtype=np.float64)
    full_mask = np.zeros((ny, nx), dtype=bool)

    low_cov_img = np.full((ny, nx), np.nan, dtype=np.float64)
    # Only a 3x3 patch is valid out of 31x31 (9 / 961 = ~0.009 < 0.40)
    low_cov_img[14:17, 14:17] = 5.0
    low_cov_footprint = np.isfinite(low_cov_img)

    f_good = ProcessedBlinkFrame(
        frame_id="good_frame",
        collection="spherex_dr1",
        detector_band=1,
        mjd_avg=60800.0,
        obs_time_iso="2025-05-01T00:00:00",
        sps_epa_deg=0.0,
        wavelength_um=0.75,
        bandwidth_um=0.02,
        reprojected_image_mjy_sr=full_img,
        reprojected_variance=full_img * 0.1,
        reprojected_zodi_mjy_sr=full_img,
        saturation_mask=full_mask,
        bad_pixel_mask=full_mask,
        footprint_mask=~full_mask,
        predicted_ra_deg=target.ra_deg,
        predicted_dec_deg=target.dec_deg,
        predicted_pixel_x=15.0,
        predicted_pixel_y=15.0,
    )
    f_low = ProcessedBlinkFrame(
        frame_id="low_coverage_frame",
        collection="spherex_dr1",
        detector_band=1,
        mjd_avg=60810.0,
        obs_time_iso="2025-05-11T00:00:00",
        sps_epa_deg=0.0,
        wavelength_um=0.76,
        bandwidth_um=0.02,
        reprojected_image_mjy_sr=low_cov_img,
        reprojected_variance=np.nan_to_num(low_cov_img, nan=0.0),
        reprojected_zodi_mjy_sr=np.zeros_like(low_cov_img),
        saturation_mask=full_mask,
        bad_pixel_mask=~low_cov_footprint,
        footprint_mask=low_cov_footprint,
        predicted_ra_deg=target.ra_deg,
        predicted_dec_deg=target.dec_deg,
        predicted_pixel_x=15.0,
        predicted_pixel_y=15.0,
    )

    bundle = exporter.build_bundle(
        target=target,
        processed_frames=[f_good, f_low],
        common_wcs=common_wcs,
        grid_shape=shape_out,
    )

    # f_low must be excluded from frames_chronological
    assert bundle.total_frames == 1
    assert len(bundle.frames_chronological) == 1
    assert bundle.frames_chronological[0].frame_id == "good_frame"

    # f_low must be tracked in dropped_frames
    assert len(bundle.dropped_frames) == 1
    dropped = bundle.dropped_frames[0]
    assert dropped.frame_id == "low_coverage_frame"
    assert "low_valid_pixel_fraction" in dropped.reason
    assert "0.40 threshold" in (dropped.error_detail or "")

    # Scientific warning emitted
    assert any("dropped or excluded" in w for w in bundle.scientific_warnings)


def test_bundle_exporter_records_dropped_cutouts() -> None:
    """Verify Finding 9: dropped cutout metadata from SIA provider is included in bundle."""
    target = BENCHMARK_TARGETS["epsilon_indi_b"]
    exporter = FrontendBundleExporter()
    reprojector = SPHERExFrameProcessor()._reprojector

    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=target.ra_deg,
        center_dec_deg=target.dec_deg,
        cutout_size_arcsec=180.0,
    )

    ny, nx = shape_out
    full_img = np.ones((ny, nx), dtype=np.float64)
    full_mask = np.zeros((ny, nx), dtype=bool)

    f_good = ProcessedBlinkFrame(
        frame_id="eps_good_1",
        collection="spherex_dr1",
        detector_band=3,
        mjd_avg=60800.0,
        obs_time_iso="2025-05-01T00:00:00",
        sps_epa_deg=0.0,
        wavelength_um=1.85,
        bandwidth_um=0.03,
        reprojected_image_mjy_sr=full_img,
        reprojected_variance=full_img * 0.1,
        reprojected_zodi_mjy_sr=full_img,
        saturation_mask=full_mask,
        bad_pixel_mask=full_mask,
        footprint_mask=~full_mask,
        predicted_ra_deg=target.ra_deg,
        predicted_dec_deg=target.dec_deg,
        predicted_pixel_x=15.0,
        predicted_pixel_y=15.0,
    )

    incoming_dropped = [
        DroppedFrameDTO(
            frame_id="cutout_503_error.fits",
            reason="cutout_download_error",
            attempted_band=3,
            error_detail="503 Service Unavailable",
        )
    ]

    bundle = exporter.build_bundle(
        target=target,
        processed_frames=[f_good],
        common_wcs=common_wcs,
        grid_shape=shape_out,
        dropped_frames=incoming_dropped,
    )

    assert len(bundle.dropped_frames) == 1
    assert bundle.dropped_frames[0].frame_id == "cutout_503_error.fits"
    assert any("dropped or excluded" in w for w in bundle.scientific_warnings)


def test_unsaturated_target_does_not_trigger_spurious_core_saturation_warning() -> None:
    """Verify Finding 11: edge saturation artifacts do not trigger core saturation warning."""
    target = BENCHMARK_TARGETS["epsilon_indi_b"]
    exporter = FrontendBundleExporter()
    reprojector = SPHERExFrameProcessor()._reprojector

    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=target.ra_deg,
        center_dec_deg=target.dec_deg,
        cutout_size_arcsec=180.0,
    )

    ny, nx = shape_out
    full_img = np.ones((ny, nx), dtype=np.float64)
    bad_mask = np.zeros((ny, nx), dtype=bool)

    # Saturated pixel at the far edge of the frame (0, 0), NOT in stellar core
    sat_mask = np.zeros((ny, nx), dtype=bool)
    sat_mask[0, 0] = True

    frame = ProcessedBlinkFrame(
        frame_id="eps_edge_sat",
        collection="spherex_dr1",
        detector_band=2,
        mjd_avg=60800.0,
        obs_time_iso="2025-05-01T00:00:00",
        sps_epa_deg=0.0,
        wavelength_um=1.35,
        bandwidth_um=0.02,
        reprojected_image_mjy_sr=full_img,
        reprojected_variance=full_img * 0.1,
        reprojected_zodi_mjy_sr=full_img,
        saturation_mask=sat_mask,
        bad_pixel_mask=bad_mask,
        footprint_mask=~bad_mask,
        predicted_ra_deg=target.ra_deg,
        predicted_dec_deg=target.dec_deg,
        predicted_pixel_x=15.0,
        predicted_pixel_y=15.0,
        is_saturated_core=False,  # Un-saturated stellar core!
    )

    bundle = exporter.build_bundle(
        target=target,
        processed_frames=[frame],
        common_wcs=common_wcs,
        grid_shape=shape_out,
    )

    # Core saturation warning must NOT be present
    assert not any("Detector core saturation" in w for w in bundle.scientific_warnings)


