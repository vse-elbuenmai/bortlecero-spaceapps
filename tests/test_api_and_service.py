"""Tests for SPHERExBlinkIngestionService and FastAPI endpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from spherex_ingest.api import app, get_default_service, get_output_dir
from spherex_ingest.domain.models import (
    CutoutFetchResult,
    DroppedFrameDTO,
    RawCutoutFrame,
    TargetSpec,
)
from spherex_ingest.exporters.bundle_exporter import FrontendBundleExporter
from spherex_ingest.infrastructure.catalog_provider import HarvardSimbadCatalogProvider
from spherex_ingest.infrastructure.irsa_sia_provider import IRSASiaCutoutProvider
from spherex_ingest.processors.pipeline_processor import SPHERExFrameProcessor
from spherex_ingest.service import NoObservations, SPHERExBlinkIngestionService, UpstreamUnavailable


class _StubCutoutProvider:
    """In-memory stub implementing CutoutProviderProtocol for fast API testing."""

    def __init__(self, frames: list[RawCutoutFrame]) -> None:
        self._frames = frames

    def fetch_cutouts(
        self,
        target: TargetSpec,
        max_frames_per_collection: int | None = None,
    ) -> CutoutFetchResult:
        return CutoutFetchResult(frames=tuple(self._frames[:max_frames_per_collection]))


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
def test_overlapping_requests_keep_dropped_cutouts_separate(
    raw_cutout_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_request_paused = Event()
    allow_first_request_to_finish = Event()
    provider = IRSASiaCutoutProvider(cache_dir=tmp_path)

    def query_collection(collection, ra_deg, **kwargs):
        if collection != "spherex_dr1":
            return []
        names = ["a_failed", "a_ok"] if ra_deg < 331.1 else ["b_ok"]
        return [
            {"filename": name, "access_url": f"https://example.invalid/{name}", "band": 2}
            for name in names
        ]

    def download_and_parse(base_filename, target_ra_deg, target_dec_deg, **kwargs):
        if base_filename == "a_failed":
            raise ValueError("Test cutout failed.")
        if base_filename == "a_ok":
            first_request_paused.set()
            assert allow_first_request_to_finish.wait(timeout=10)
        return raw_cutout_factory(
            frame_id=base_filename, center_ra_deg=target_ra_deg, center_dec_deg=target_dec_deg
        )

    monkeypatch.setattr(provider, "_query_collection", query_collection)
    monkeypatch.setattr(provider, "_download_and_parse", download_and_parse)
    service = SPHERExBlinkIngestionService(
        cutout_provider=provider,
        catalog_provider=HarvardSimbadCatalogProvider(),
        frame_processor=SPHERExFrameProcessor(),
        bundle_exporter=FrontendBundleExporter(),
    )
    monkeypatch.setitem(app.dependency_overrides, get_default_service, lambda: service)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        request_a = executor.submit(client.get, "/api/v1/blink?ra=331.07&dec=-56.79")
        try:
            assert first_request_paused.wait(timeout=10)
            response_b = executor.submit(
                client.get, "/api/v1/blink?ra=331.11&dec=-56.79"
            ).result(timeout=10)
        finally:
            allow_first_request_to_finish.set()
        response_a = request_a.result(timeout=10)

    assert response_a.status_code == response_b.status_code == 200
    assert response_a.json()["total_frames"] == response_b.json()["total_frames"] == 1
    assert [item["frame_id"] for item in response_a.json()["dropped_frames"]] == ["a_failed"]
    assert response_b.json()["dropped_frames"] == []


@pytest.mark.parametrize(
    ("dropped", "expected_error"),
    [
        ((), NoObservations),
        (
            (DroppedFrameDTO(frame_id="spherex_dr1_query", reason="collection_query_error"),),
            UpstreamUnavailable,
        ),
        (
            (DroppedFrameDTO(frame_id="exposure", reason="cutout_download_error"),),
            UpstreamUnavailable,
        ),
    ],
)
def test_service_distinguishes_no_observations_from_upstream_failure(
    dropped, expected_error, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SPHERExBlinkIngestionService.create_default()
    monkeypatch.setattr(
        service.cutout_provider,
        "fetch_cutouts",
        lambda **kwargs: CutoutFetchResult(frames=(), dropped_frames=dropped),
    )
    with pytest.raises(expected_error):
        service.ingest_target("epsilon_indi_b")
