"""Tests for SPHERExBlinkIngestionService and FastAPI endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from spherex_ingest.api import app, get_default_service, get_output_dir
from spherex_ingest.domain.models import RawCutoutFrame, TargetSpec
from spherex_ingest.exporters.bundle_exporter import FrontendBundleExporter
from spherex_ingest.infrastructure.catalog_provider import HarvardSimbadCatalogProvider
from spherex_ingest.processors.pipeline_processor import SPHERExFrameProcessor
from spherex_ingest.service import SPHERExBlinkIngestionService


class _StubCutoutProvider:
    """In-memory stub implementing CutoutProviderProtocol for fast API testing."""

    def __init__(self, frames: list[RawCutoutFrame]) -> None:
        self._frames = frames

    def fetch_cutouts(
        self,
        target: TargetSpec,
        max_frames_per_collection: int | None = None,
    ) -> list[RawCutoutFrame]:
        return list(self._frames[:max_frames_per_collection])


def test_service_and_fastapi_endpoints(raw_cutout_factory, tmp_path: Path) -> None:
    """Verify SPHERExBlinkIngestionService and FastAPI endpoints end-to-end."""
    f1 = raw_cutout_factory(mjd_avg=60800.0, sps_epa_deg=0.0, detector_band=6, frame_id="exp_1")
    f2 = raw_cutout_factory(mjd_avg=60980.0, sps_epa_deg=180.0, detector_band=6, frame_id="exp_2")

    service = SPHERExBlinkIngestionService(
        cutout_provider=_StubCutoutProvider([f1, f2]),
        catalog_provider=HarvardSimbadCatalogProvider(),
        frame_processor=SPHERExFrameProcessor(),
        bundle_exporter=FrontendBundleExporter(),
    )

    app.dependency_overrides[get_default_service] = lambda: service
    app.dependency_overrides[get_output_dir] = lambda: tmp_path
    try:
        client = TestClient(app)

        # 1. Health endpoint
        resp_health = client.get("/api/v1/health")
        assert resp_health.status_code == 200
        assert resp_health.json()["status"] == "ok"

        # 2. Benchmarks endpoint
        resp_bench = client.get("/api/v1/benchmarks")
        assert resp_bench.status_code == 200
        benchmarks = resp_bench.json()
        assert len(benchmarks) == 5
        ids = {b["target_id"] for b in benchmarks}
        assert "barnards_star" in ids
        assert "wise_0855_0714" in ids

        # 3. Blink benchmark endpoint
        resp_blink = client.get("/api/v1/blink/epsilon_indi_b")
        assert resp_blink.status_code == 200
        bundle = resp_blink.json()
        assert bundle["target"]["target_id"] == "epsilon_indi_b"
        assert bundle["total_frames"] == 2
        assert "6" in bundle["frames_by_band"]
        assert len(bundle["difference_maps"]) == 1

        # 4. Arbitrary coordinate query endpoint
        resp_coord = client.get("/api/v1/blink?ra=331.076&dec=-56.794&size_arcsec=180")
        assert resp_coord.status_code == 200
        assert resp_coord.json()["total_frames"] == 2
    finally:
        app.dependency_overrides.clear()


def test_cloud_health_and_live_query_gate(monkeypatch, tmp_path: Path) -> None:
    """Health and a disabled live query must never invoke ingestion."""
    monkeypatch.setenv("SPHEREX_LEGACY_SYNC_ENABLED", "false")
    monkeypatch.setenv("SPHEREX_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("K_REVISION", "spherex-test-00001")

    class UnavailableIngestion:
        def ingest_target(self, **kwargs):
            raise AssertionError("Ingestion must remain disabled")

    app.dependency_overrides[get_default_service] = UnavailableIngestion
    try:
        client = TestClient(app)
        status = client.get("/api/v1/health").json()
        assert status["revision"] == "spherex-test-00001"
        assert status["legacy_sync_enabled"] is False
        assert "cds_mirror_active" not in status

        corrupted = tmp_path / "epsilon_indi_b" / "bundle.json"
        corrupted.parent.mkdir()
        corrupted.write_text("incomplete JSON", encoding="utf-8")

        for endpoint in (
            "/api/v1/blink?ra=331&dec=-56",
            "/api/v1/blink/epsilon_indi_b?force_refresh=true",
            "/api/v1/blink/epsilon_indi_b",
            "/api/v1/blink/barnards_star",
        ):
            response = client.get(endpoint)
            assert response.status_code == 503
            assert response.json()["detail"] == "Live SPHEREx ingestion is disabled."
    finally:
        app.dependency_overrides.clear()
