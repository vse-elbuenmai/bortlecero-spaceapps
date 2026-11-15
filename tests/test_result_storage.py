"""Versioned result publication, validation and cache routing tests."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import PreconditionFailed

from spherex_ingest import result_storage
from spherex_ingest.admission import InMemoryAdmissionController
from spherex_ingest.api import (
    app,
    get_admission_controller,
    get_default_service,
    get_output_dir,
    get_public_limits,
)
from spherex_ingest.domain.models import CutoutFetchResult, DroppedFrameDTO
from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.infrastructure.result_objects import CloudResultObjects, LocalResultObjects
from spherex_ingest.limits import PublicLimits
from spherex_ingest.result_storage import (
    ResultKey,
    ResultStore,
    StoredBlinkResult,
    benchmark_object_path,
)
from spherex_ingest.service import SPHERExBlinkIngestionService


@pytest.fixture
def service_and_calls(raw_cutout_factory, monkeypatch):
    service = SPHERExBlinkIngestionService.create_default()
    calls = []

    def fetch(target, max_frames_per_collection):
        calls.append((target, max_frames_per_collection))
        return CutoutFetchResult(
            frames=(raw_cutout_factory(center_ra_deg=target.ra_deg, center_dec_deg=target.dec_deg),)
        )

    monkeypatch.setattr(service.cutout_provider, "fetch_cutouts", fetch)
    return service, calls


@pytest.fixture
def bundle(service_and_calls):
    service, _ = service_and_calls
    return service.ingest_target("epsilon_indi_b")


def test_keys_capture_processing_parameters_and_coordinate_precision() -> None:
    target = BENCHMARK_TARGETS["epsilon_indi_b"]
    key = ResultKey.from_target(target, 12)
    changes = [
        {"max_frames_per_collection": 13},
        {"algorithm_version": "2"},
        {"catalog_version": "new-catalog"},
        {"bundle_schema_version": "2.0.0"},
    ]
    targets = [
        target.model_copy(update={"ra_deg": target.ra_deg + 1e-12}),
        target.model_copy(update={"cutout_size_arcsec": target.cutout_size_arcsec + 1e-9}),
        target.model_copy(update={"collections": tuple(reversed(target.collections))}),
        target.model_copy(update={"collections": ("spherex_dr1",)}),
        target.model_copy(update={"pm_ra_cosdec_mas_yr": target.pm_ra_cosdec_mas_yr + 1}),
    ]
    assert (
        len(
            {
                key.digest,
                *(key.model_copy(update=change).digest for change in changes),
                *(ResultKey.from_target(item, 12).digest for item in targets),
            }
        )
        == 10
    )
    positive = target.model_copy(update={"dec_deg": 0.0})
    negative = target.model_copy(update={"dec_deg": -0.0})
    assert ResultKey.from_target(positive, 12).digest == ResultKey.from_target(negative, 12).digest


def test_independent_publishers_share_one_complete_result(tmp_path: Path, bundle) -> None:
    database = tmp_path / "results.sqlite3"
    overlap = Barrier(2, timeout=10)
    key = ResultKey.from_target(bundle.target, 24)

    class SimultaneousPublishers(LocalResultObjects):
        def write_if_generation(self, name, data, expected_generation):
            if "/manifests/" in name and expected_generation == 0:
                overlap.wait()
            return super().write_if_generation(name, data, expected_generation)

    first = ResultStore(SimultaneousPublishers(database), code_sha="a" * 40)
    second = ResultStore(SimultaneousPublishers(database), code_sha="b" * 40)
    alternative = bundle.model_copy(update={"scientific_warnings": ["Alternative publication."]})

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(first.publish, key, bundle)
        b = executor.submit(second.publish, key, alternative)
        result_a, result_b = a.result(timeout=10), b.result(timeout=10)

    fresh = ResultStore(LocalResultObjects(database), code_sha="c" * 40)
    assert result_a == result_b == fresh.lookup(key)
    manifest = fresh.objects.read(fresh._manifest_path(key))
    payload = fresh.objects.read(fresh._asset_path(manifest.data.decode("ascii")))
    record = StoredBlinkResult.model_validate_json(payload.data)
    assert record.code_sha in {"a" * 40, "b" * 40}
    assert record.key == key
    assert record.generated_at < record.expires_at
    assert record.bundle.citations == bundle.citations


def test_interrupted_refresh_preserves_prior_manifest_and_partial_job_result(
    tmp_path: Path,
    bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clock(datetime):
        now_value = datetime(2026, 11, 15, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.now_value

    monkeypatch.setattr(result_storage, "datetime", Clock)
    objects = LocalResultObjects(tmp_path / "results.sqlite3")
    store = ResultStore(objects, code_sha="a" * 40)
    key = ResultKey.from_target(bundle.target, 24)
    partial = bundle.model_copy(
        update={
            "dropped_frames": [DroppedFrameDTO(frame_id="missing", reason="cutout_download_error")]
        }
    )
    store.publish(key, partial)
    assert store.lookup(key) == partial

    Clock.now_value += timedelta(minutes=5)
    assert store.lookup(key) is None
    assert store.lookup(key, allow_stale_partial=True) == partial
    original = objects.write_if_generation

    def fail_manifest(name, data, expected_generation):
        if "/manifests/" in name:
            raise OSError("Interrupted before switching manifest")
        return original(name, data, expected_generation)

    with monkeypatch.context() as patch:
        patch.setattr(objects, "write_if_generation", fail_manifest)
        with pytest.raises(OSError, match="Interrupted"):
            store.publish(key, bundle)
    assert store.lookup(key, allow_stale_partial=True) == partial
    assert store.publish(key, bundle) == bundle
    assert store.lookup(key) == bundle

    Clock.now_value += timedelta(days=1)
    assert store.lookup(key, allow_stale_partial=True) is None


def test_corrupt_and_stale_result_metadata_are_replaced(tmp_path: Path, bundle) -> None:
    store = ResultStore(LocalResultObjects(tmp_path / "results.sqlite3"), code_sha="a" * 40)
    key = ResultKey.from_target(bundle.target, 24)
    store.publish(key, bundle)
    objects = store.objects
    manifest_path = store._manifest_path(key)
    manifest = objects.read(manifest_path)
    digest = manifest.data.decode("ascii")
    original_path = store._asset_path(digest)
    original = objects.read(original_path)
    original_bytes = original.data

    assert objects.write_if_generation(original_path, b"broken", original.generation)
    assert store.lookup(key) is None

    old_schema = json.loads(original_bytes)
    old_schema["cache_schema_version"] = 0
    payload = json.dumps(old_schema).encode("utf-8")
    old_digest = hashlib.sha256(payload).hexdigest()
    assert objects.write_if_generation(store._asset_path(old_digest), payload, 0)
    assert objects.write_if_generation(
        manifest_path, old_digest.encode("ascii"), manifest.generation
    )
    assert store.lookup(key) is None

    assert store.publish(key, bundle) == bundle
    assert store.lookup(key) == bundle


def test_cloud_adapter_checks_object_generations() -> None:
    bucket = Mock()
    blob = bucket.get_blob.return_value
    blob.generation = 42
    blob.download_as_bytes.return_value = b"payload"
    store = CloudResultObjects(bucket)

    assert store.read("objects/one").data == b"payload"
    blob.download_as_bytes.assert_called_once_with(if_generation_match=42, timeout=15)
    writer = bucket.blob.return_value
    assert store.write_if_generation("objects/one", b"new", expected_generation=42)
    writer.upload_from_string.assert_called_once_with(
        b"new", content_type="application/octet-stream", if_generation_match=42, timeout=15
    )
    writer.upload_from_string.side_effect = PreconditionFailed("another writer won")
    assert not store.write_if_generation("objects/missing", b"new", expected_generation=0)


def test_live_api_results_are_cached_by_parameters_outside_curated_bundles(
    tmp_path: Path,
    service_and_calls,
    bundle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, calls = service_and_calls
    calls.clear()
    curated_dir = tmp_path / "curated"
    path = service.bundle_exporter.save_bundle(bundle, curated_dir)
    original = path.read_bytes()
    limits = PublicLimits(max_new_jobs_per_minute=20, max_outstanding_jobs=8)
    monkeypatch.setitem(app.dependency_overrides, get_default_service, lambda: service)
    monkeypatch.setitem(app.dependency_overrides, get_output_dir, lambda: curated_dir)
    monkeypatch.setitem(app.dependency_overrides, get_public_limits, lambda: limits)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_admission_controller,
        lambda: InMemoryAdmissionController(limits),
    )
    monkeypatch.setenv("SPHEREX_RESULTS_DIR", str(tmp_path / "private"))
    monkeypatch.delenv("SPHEREX_RESULTS_BUCKET", raising=False)

    with TestClient(app) as client:
        benchmark = "/api/v1/blink/epsilon_indi_b"
        assert client.get(benchmark).status_code == 200
        assert not calls
        for _ in range(2):
            response = client.get(benchmark, params={"max_frames": 11, "size_arcsec": 150})
            assert response.status_code == 200
            assert response.json()["target"]["cutout_size_arcsec"] == 150
        assert len(calls) == 1
        assert calls[-1][1] == 11
        response = client.get(benchmark, params={"max_frames": 12, "size_arcsec": 150})
        assert response.status_code == 200
        assert len(calls) == 2
        coords = {"ra": 330, "dec": -56}
        for _ in range(2):
            assert client.get("/api/v1/blink", params=coords).status_code == 200
        assert len(calls) == 3

    assert path.read_bytes() == original
    assert (tmp_path / "private" / "results.sqlite3").is_file()


def test_default_benchmark_is_served_without_ingestion(
    tmp_path: Path, service_and_calls, bundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, calls = service_and_calls
    calls.clear()
    key = ResultKey.from_target(bundle.target, 12)
    path = benchmark_object_path(key)
    assert path and path.startswith("benchmarks/v1/epsilon_indi_b/")
    assert benchmark_object_path(ResultKey.from_target(bundle.target, 11)) is None
    assert benchmark_object_path(
        ResultKey.from_target(service.resolve_target("epsilon_indi_b", 150), 12)
    ) is None
    assert benchmark_object_path(key.model_copy(update={"algorithm_version": "next"})) is None
    objects = LocalResultObjects(tmp_path / "benchmarks.sqlite3")
    assert objects.write_if_generation(path, bundle.model_dump_json().encode(), 0)
    monkeypatch.setattr(CloudResultObjects, "from_bucket_name", lambda _: objects)
    monkeypatch.setenv("SPHEREX_BENCHMARK_BUCKET", "test-benchmark-bucket")
    monkeypatch.setenv("SPHEREX_ASYNC_JOBS_ENABLED", "true")
    monkeypatch.setenv("SPHEREX_LEGACY_SYNC_ENABLED", "false")
    monkeypatch.setenv("SPHEREX_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("SPHEREX_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setitem(app.dependency_overrides, get_default_service, lambda: service)
    monkeypatch.setitem(app.dependency_overrides, get_output_dir, lambda: tmp_path / "output")

    with TestClient(app) as client:
        response = client.post("/api/v1/jobs", json={"query": "epsilon_indi_b"})
        assert response.status_code == 200
        job = response.json()
        assert job["cached"] and job["attempts"] == 0
        assert job["result"] == bundle.model_dump(mode="json")
        assert client.get(job["result_url"]).json() == job["result"]
        assert client.get("/api/v1/blink/epsilon_indi_b").json() == job["result"]
        assert client.get("/api/v1/blink/epsilon_indi_b?max_frames=11").status_code == 503

        store = result_storage.get_result_store()
        fallback = bundle.model_copy(update={"scientific_warnings": ["Local fallback."]})
        store.publish(key, fallback)
        entry = objects.read(path)
        assert entry is not None
        assert objects.write_if_generation(path, b"invalid", entry.generation)
        assert client.get("/api/v1/blink/epsilon_indi_b").json() == fallback.model_dump(mode="json")

    assert not calls
