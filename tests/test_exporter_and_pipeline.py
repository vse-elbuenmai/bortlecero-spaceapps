"""End-to-end tests for SPHERExFrameProcessor and FrontendBundleExporter."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from spherex_ingest.domain.models import RawCutoutFrame
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
