"""Integration tests verifying Frontend Mockup & Blink Bundle contracts (Milestone 5)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spherex_ingest.api import app
from spherex_ingest.domain.models import BlinkBundleDTO
from spherex_ingest.domain.targets import BENCHMARK_TARGETS

BENCHMARK_IDS = [
    "barnards_star",
    "epsilon_indi_b",
    "wise_0855_0714",
    "rw_aurigae",
    "r_draconis",
]


def test_benchmark_bundles_exist_and_validate_dto() -> None:
    """Verify all 5 benchmark targets have valid BlinkBundleDTO JSON bundles in mockup/data/."""
    mockup_data = Path("mockup/data")
    assert mockup_data.exists(), "mockup/data directory must exist"

    for target_id in BENCHMARK_IDS:
        bundle_path = mockup_data / target_id / "bundle.json"
        assert bundle_path.exists(), f"Benchmark bundle missing at {bundle_path}"

        raw_json = bundle_path.read_text(encoding="utf-8")
        bundle = BlinkBundleDTO.model_validate_json(raw_json)

        # 1. Target and Grid specification
        expected_target = BENCHMARK_TARGETS[target_id]
        assert bundle.target.target_id == target_id
        assert bundle.target.ra_deg == pytest.approx(expected_target.ra_deg, abs=1e-6)
        assert bundle.target.dec_deg == pytest.approx(expected_target.dec_deg, abs=1e-6)
        assert bundle.target.pm_ra_cosdec_mas_yr == pytest.approx(
            expected_target.pm_ra_cosdec_mas_yr, abs=1e-4
        )
        assert bundle.target.pm_dec_mas_yr == pytest.approx(
            expected_target.pm_dec_mas_yr, abs=1e-4
        )
        assert bundle.target.parallax_mas == pytest.approx(
            expected_target.parallax_mas, abs=1e-4
        )
        assert bundle.grid.width_px > 0
        assert bundle.grid.height_px > 0
        assert "North-up" in bundle.grid.orientation

        # 2. Chronological and band frames
        assert len(bundle.frames_chronological) >= 3, f"{target_id} must have >= 3 frames"
        assert len(bundle.available_bands) >= 1
        for band in bundle.available_bands:
            band_key = str(band)
            assert band_key in bundle.frames_by_band
            assert len(bundle.frames_by_band[band_key]) >= 1

        # 3. Base64 Data URIs and astrometry
        for f in bundle.frames_chronological:
            assert f.png_base64 is not None
            assert f.png_base64.startswith("data:image/png;base64,")
            assert 0.0 <= f.predicted_pixel_x <= bundle.grid.width_px
            assert 0.0 <= f.predicted_pixel_y <= bundle.grid.height_px
            if target_id == "barnards_star":
                assert 10.0 <= f.predicted_pixel_x <= 21.0
                assert 10.0 <= f.predicted_pixel_y <= 21.0
            if f.measured_centroid_x is not None:
                assert 0.0 <= f.measured_centroid_x <= bundle.grid.width_px
                assert f.measured_centroid_y is not None
                assert 0.0 <= f.measured_centroid_y <= bundle.grid.height_px

        # 4. Difference maps contract (if multi-epoch in same band)
        raw_dict = json.loads(raw_json)
        raw_diff_maps = raw_dict.get("difference_maps", [])
        assert len(bundle.difference_maps) == len(raw_diff_maps)
        for diff, raw_dm in zip(bundle.difference_maps, raw_diff_maps, strict=False):
            assert diff.png_base64 is not None
            assert diff.png_base64.startswith("data:image/png;base64,")
            assert diff.baseline_days >= 0.0
            assert diff.detector_band in bundle.available_bands
            assert diff.early_wavelength_um > 0.0
            assert diff.late_wavelength_um > 0.0
            assert diff.delta_wavelength_um >= 0.0
            assert "delta_wavelength_um" in raw_dm, f"Missing delta_wavelength_um in {bundle_path}"
            assert "early_wavelength_um" in raw_dm, f"Missing early_wavelength_um in {bundle_path}"
            assert "late_wavelength_um" in raw_dm, f"Missing late_wavelength_um in {bundle_path}"

        # 5. Scientific warnings and citations
        assert len(bundle.scientific_warnings) >= 1
        assert len(bundle.citations) >= 4


def test_mockup_html_has_required_modal_elements() -> None:
    """Verify mockup/index.html includes required elements for Milestone 5."""
    html_path = Path("mockup/index.html")
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")

    # Required control IDs
    assert 'id="band-select"' in content, "Missing #band-select in index.html"
    assert 'id="diff-toggle"' in content, "Missing #diff-toggle button in index.html"
    assert 'id="panel-warnings"' in content, "Missing #panel-warnings in index.html"
    assert 'id="warnings-list"' in content, "Missing #warnings-list in index.html"
    assert 'id="panel-citations"' in content, "Missing #panel-citations in index.html"
    assert 'id="citations-list"' in content, "Missing #citations-list in index.html"

    # Core viewer elements
    assert 'id="viewer-modal"' in content
    assert 'id="modal-empty"' in content
    assert 'id="frame-img"' in content
    assert 'id="overlay"' in content
    assert 'id="timeline-dots"' in content
    assert 'id="summary"' in content


def test_mockup_js_implementation_contracts() -> None:
    """Verify mockup/mockup.js implements all required integration logic."""
    js_path = Path("mockup/mockup.js")
    assert js_path.exists()
    js_code = js_path.read_text(encoding="utf-8")

    # Benchmark mapping for all 5 targets
    for target_id in BENCHMARK_IDS:
        assert target_id in js_code, f"{target_id} must be in mockup.js benchmark map"

    # Base64 Data URI handling
    assert "f.png_base64" in js_code
    assert "data:image/png;base64" in js_code or "startsWith(\"data:\")" in js_code

    # Astrometric coordinate pixel-center formula: [p.x + 0.5, p.y + 0.5]
    assert re.search(r"p\.x\s*\+\s*0\.5", js_code) is not None
    assert re.search(r"p\.y\s*\+\s*0\.5", js_code) is not None

    # Band selection and difference map toggle functions
    assert "buildBandOptions" in js_code
    assert "selectBand" in js_code
    assert "diffMode" in js_code
    assert "setDiffMode" in js_code
    assert "diff-toggle" in js_code
    assert "delta_wavelength_um" in js_code

    # Scientific warnings and citations rendering
    assert "panel-warnings" in js_code
    assert "warnings-list" in js_code
    assert "panel-citations" in js_code
    assert "citations-list" in js_code

    # Graceful null centroid handling
    assert "measured_centroid_x" in js_code
    assert "null" in js_code

    # Event listener for external navigation
    assert "viewer:load-target" in js_code


def test_sky_js_target_router_connection() -> None:
    """Verify mockup/sky.js routes all 5 benchmark objects to viewer modal."""
    sky_path = Path("mockup/sky.js")
    assert sky_path.exists()
    sky_code = sky_path.read_text(encoding="utf-8")

    # Benchmark objects in OBJECTS
    assert "barnards_star" in sky_code
    assert "epsilon_indi_b" in sky_code
    assert "wise_0855_0714" in sky_code
    assert "rw_aurigae" in sky_code
    assert "r_draconis" in sky_code

    # Router functions and custom event dispatch
    assert "findPreparedBenchmark" in sky_code
    assert "viewer:load-target" in sky_code
    assert "openModal" in sky_code

    # Free object names are resolved from the browser and have their own field
    assert "resolveName" in sky_code
    assert 'id="name"' in Path("mockup/index.html").read_text(encoding="utf-8")


def test_fastapi_blink_and_static_bundle_parity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the API reads the tracked static bundle without contacting IRSA."""
    monkeypatch.setenv("SPHEREX_OUTPUT_DIR", str(Path("mockup/data").resolve()))
    client = TestClient(app)
    response = client.get("/api/v1/blink/barnards_star")
    assert response.status_code == 200

    api_bundle = BlinkBundleDTO.model_validate(response.json())
    assert api_bundle.target.target_id == "barnards_star"
    assert len(api_bundle.frames_chronological) >= 3

    static_path = Path("mockup/data/barnards_star/bundle.json")
    static_bundle = BlinkBundleDTO.model_validate_json(static_path.read_text(encoding="utf-8"))
    assert static_bundle.target.target_id == api_bundle.target.target_id
    assert static_bundle.grid.width_px == api_bundle.grid.width_px


def test_legacy_barnard_backward_compatibility() -> None:
    """Verify mockup/data/barnard/frames.json is preserved for backward compatibility."""
    legacy_path = Path("mockup/data/barnard/frames.json")
    assert legacy_path.exists(), "Legacy frames.json must be preserved"
    data = json.loads(legacy_path.read_text(encoding="utf-8"))
    assert "frames" in data
    assert len(data["frames"]) == 3
    assert "grid" in data
