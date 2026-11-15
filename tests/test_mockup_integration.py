"""Integration tests verifying Frontend Mockup live-IRSA API & hosting contracts."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spherex_ingest.api import app, get_output_dir
from spherex_ingest.domain.models import (
    BlinkBundleDTO,
    CommonGridSpecDTO,
    FrameMetadataDTO,
    TargetSpec,
)
from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.result_storage import ResultKey, get_result_store

BENCHMARK_IDS = [
    "barnards_star",
    "epsilon_indi_b",
    "wise_0855_0714",
    "rw_aurigae",
    "r_draconis",
]


def _load_build_hosting():
    script_path = Path("scripts/build_hosting.py").resolve()
    spec = importlib.util.spec_from_file_location("build_hosting", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_hosting


def test_mockup_has_no_local_data_or_preparation_script() -> None:
    """Verify mockup/ contains no local snapshot data or prepare_barnard.py."""
    assert not Path("mockup/data").exists(), "mockup/data directory must be removed"
    assert not Path("mockup/prepare_barnard.py").exists(), (
        "mockup/prepare_barnard.py must be removed"
    )
    assert Path("mockup/sky/sky.json").is_file(), "3D sky backdrop assets must remain"


def test_viewer_data_uses_live_irsa_api_without_local_data_fallbacks() -> None:
    """Verify mockup/viewer-data.js routes benchmarks and coordinates through the API."""
    viewer_data = Path("mockup/viewer-data.js").read_text(encoding="utf-8")
    assert "api/v1/jobs" in viewer_data
    assert "api/v1/blink" in viewer_data
    assert "benchmark-manifest.json" not in viewer_data
    assert "releases/" not in viewer_data
    assert "data/barnard" not in viewer_data
    assert "bundle.json" not in viewer_data


def test_build_hosting_stages_live_irsa_manifest(tmp_path: Path) -> None:
    """Verify build_hosting emits a live_irsa manifest with no local releases/ bundles."""
    build_hosting = _load_build_hosting()
    dest = tmp_path / "hosting"
    version = build_hosting(Path("mockup"), dest)
    assert version

    assert not (dest / "releases").exists()
    manifest = json.loads((dest / "benchmark-manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == version
    assert manifest["commit_sha"]
    assert manifest["mode"] == "live_irsa"
    assert manifest["bundles"] == {}


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
    """Verify mockup/mockup.js integration logic without local data/ paths."""
    js_path = Path("mockup/mockup.js")
    assert js_path.exists()
    js_code = js_path.read_text(encoding="utf-8")

    # Benchmark mapping for all 5 targets
    for target_id in BENCHMARK_IDS:
        assert target_id in js_code, f"{target_id} must be in mockup.js benchmark map"

    # No local data/barnard/ fallback paths
    assert "data/barnard/" not in js_code

    # Base64 Data URI handling
    assert "f.png_base64" in js_code

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


def test_fastapi_benchmark_endpoint_serves_result_store_cache_when_legacy_sync_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify GET /api/v1/blink/{target_id} returns ResultStore cache if legacy sync disabled."""
    target: TargetSpec = BENCHMARK_TARGETS["barnards_star"]
    frame = FrameMetadataDTO(
        frame_id="barnard_test_1",
        collection="spherex_dr1",
        detector_band=2,
        mjd_avg=60800.0,
        obs_time_iso="2025-05-05T00:00:00Z",
        sps_epa_deg=0.0,
        wavelength_um=1.5,
        bandwidth_um=0.05,
        predicted_ra_deg=target.ra_deg,
        predicted_dec_deg=target.dec_deg,
        predicted_pixel_x=15.0,
        predicted_pixel_y=15.0,
        matrix_mjy_sr=[[1.0]],
        saturation_mask=[[False]],
        bad_pixel_mask=[[False]],
        png_base64="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=",
    )
    bundle = BlinkBundleDTO(
        target=target,
        propagated_current_ra_deg=target.ra_deg,
        propagated_current_dec_deg=target.dec_deg,
        grid=CommonGridSpecDTO(
            center_ra_deg=target.ra_deg,
            center_dec_deg=target.dec_deg,
            pixel_scale_arcsec=6.15,
            width_px=31,
            height_px=31,
        ),
        total_frames=1,
        available_bands=[2],
        frames_chronological=[frame],
        frames_by_band={"2": [frame]},
        difference_maps=[],
        scientific_warnings=[],
        citations=[],
    )

    monkeypatch.setenv("SPHEREX_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.delenv("SPHEREX_RESULTS_BUCKET", raising=False)
    monkeypatch.setenv("SPHEREX_LEGACY_SYNC_ENABLED", "false")
    monkeypatch.setitem(app.dependency_overrides, get_output_dir, lambda: tmp_path / "empty_output")

    get_result_store().publish(ResultKey.from_target(target, 12), bundle)
    client = TestClient(app)
    response = client.get("/api/v1/blink/barnards_star")
    assert response.status_code == 200
    api_bundle = BlinkBundleDTO.model_validate(response.json())
    assert api_bundle.target.target_id == "barnards_star"
    assert api_bundle.grid.width_px == 31
