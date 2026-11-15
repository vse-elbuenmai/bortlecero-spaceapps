"""End-to-end tests for SPHERExFrameProcessor and FrontendBundleExporter."""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from spherex_ingest.domain.models import ProcessedBlinkFrame, RawCutoutFrame
from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.exporters.bundle_exporter import FrontendBundleExporter
from spherex_ingest.processors.kinematics import KinematicsAndPhotometryAnalyzer
from spherex_ingest.processors.pipeline_processor import SPHERExFrameProcessor


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

