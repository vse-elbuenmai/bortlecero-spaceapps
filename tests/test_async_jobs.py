"""Comprehensive tests for durable asynchronous ingestion (Issue #20)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spherex_ingest.api import (
    app,
    get_api_result_store,
    get_async_worker,
    get_default_service,
    get_job_coordinator,
    get_job_dispatcher,
    get_job_store,
    get_public_limits,
    get_worker_auth_verifier,
)
from spherex_ingest.domain.jobs import (
    JobRecord,
    JobSubmissionRequest,
)
from spherex_ingest.domain.models import CutoutFetchResult, RawCutoutFrame, TargetSpec
from spherex_ingest.exporters.bundle_exporter import FrontendBundleExporter
from spherex_ingest.infrastructure.catalog_provider import HarvardSimbadCatalogProvider
from spherex_ingest.infrastructure.job_queue import (
    CloudTasksJobDispatcher,
    LocalThreadPoolJobDispatcher,
    OIDCWorkerAuthVerifier,
)
from spherex_ingest.infrastructure.job_store import FirestoreJobStore, LocalSQLiteJobStore
from spherex_ingest.infrastructure.result_objects import LocalResultObjects
from spherex_ingest.job_service import AsyncIngestionWorker, AsyncJobCoordinator
from spherex_ingest.limits import PublicLimits
from spherex_ingest.processors.pipeline_processor import SPHERExFrameProcessor
from spherex_ingest.result_storage import ResultStore
from spherex_ingest.service import SPHERExBlinkIngestionService


@pytest.fixture(autouse=True)
def isolated_async_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPHEREX_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("SPHEREX_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.delenv("SPHEREX_RESULTS_BUCKET", raising=False)
    monkeypatch.delenv("SPHEREX_WORKER_OIDC_AUDIENCE", raising=False)
    monkeypatch.delenv("SPHEREX_WORKER_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("SPHEREX_ASYNC_JOBS_ENABLED", "true")


class _StubCutoutProvider:
    """Configurable cutout provider stub for async pipeline tests."""

    def __init__(
        self,
        frames: list[RawCutoutFrame] | None = None,
        *,
        error: Exception | None = None,
        gate: Event | None = None,
        fail_first_n: int = 0,
    ) -> None:
        self._frames = frames or []
        self._error = error
        self._gate = gate
        self._fail_first_n = fail_first_n
        self.calls = 0

    def fetch_cutouts(
        self,
        target: TargetSpec,
        max_frames_per_collection: int | None = None,
    ) -> CutoutFetchResult:
        del target
        self.calls += 1
        if self._gate is not None:
            self._gate.wait(timeout=5.0)
        if self._error is not None:
            raise self._error
        if self.calls <= self._fail_first_n:
            raise RuntimeError("transient upstream connection reset")
        return CutoutFetchResult(frames=tuple(self._frames[:max_frames_per_collection]))


class _RecordingDispatcher:
    """Manual dispatcher recording jobs without executing them automatically."""

    def __init__(self) -> None:
        self.dispatched: list[JobRecord] = []

    def dispatch(self, job: JobRecord) -> None:
        self.dispatched.append(job)


def _make_service(provider: _StubCutoutProvider) -> SPHERExBlinkIngestionService:
    return SPHERExBlinkIngestionService(
        cutout_provider=provider,
        catalog_provider=HarvardSimbadCatalogProvider(),
        frame_processor=SPHERExFrameProcessor(),
        bundle_exporter=FrontendBundleExporter(),
    )


def _make_stores(tmp_path: Path) -> tuple[LocalSQLiteJobStore, ResultStore]:
    job_store = LocalSQLiteJobStore(tmp_path / "jobs" / "jobs.sqlite3")
    objects = LocalResultObjects(tmp_path / "results" / "results.sqlite3")
    result_store = ResultStore(objects, "a" * 40)
    return job_store, result_store


def test_submit_202_slow_job_flow_and_cached_200_hit(raw_cutout_factory, tmp_path: Path) -> None:
    """Verify 202 queued -> 409 not ready -> succeeded -> 200 result -> 200 cached hit."""
    f1 = raw_cutout_factory(mjd_avg=60800.0, sps_epa_deg=0.0, detector_band=6, frame_id="exp_1")
    f2 = raw_cutout_factory(mjd_avg=60980.0, sps_epa_deg=180.0, detector_band=6, frame_id="exp_2")
    gate = Event()
    provider = _StubCutoutProvider([f1, f2], gate=gate)
    service = _make_service(provider)
    job_store, result_store = _make_stores(tmp_path)
    limits = PublicLimits()
    worker = AsyncIngestionWorker(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        limits=limits,
    )
    dispatcher = LocalThreadPoolJobDispatcher(worker.execute, max_workers=1)
    coordinator = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
    )

    app.dependency_overrides[get_default_service] = lambda: service
    app.dependency_overrides[get_job_store] = lambda: job_store
    app.dependency_overrides[get_api_result_store] = lambda: result_store
    app.dependency_overrides[get_job_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_job_coordinator] = lambda: coordinator
    try:
        client = TestClient(app)

        # 1. Submit while worker is blocked on `gate` -> immediate HTTP 202.
        resp = client.post(
            "/api/v1/jobs",
            json={"ra": 331.0764, "dec": -56.7938, "size_arcsec": 180.0, "max_frames": 12},
        )
        assert resp.status_code == 202
        body = resp.json()
        job_id = body["job_id"]
        assert body["status"] == "queued"
        assert body["status_url"] == f"/api/v1/jobs/{job_id}"
        assert body["result_url"] == f"/api/v1/jobs/{job_id}/result"

        # 2. Result endpoint returns 409 while still queued/running.
        not_ready = client.get(body["result_url"])
        assert not_ready.status_code == 409
        assert not_ready.json()["detail"]["code"] == "job_not_ready"

        # 3. Unblock worker and wait for completion.
        gate.set()
        dispatcher.wait_for_idle(timeout=5.0)

        status_resp = client.get(body["status_url"])
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "succeeded"

        result_resp = client.get(body["result_url"])
        assert result_resp.status_code == 200
        assert result_resp.json()["total_frames"] == 2
        assert provider.calls == 1

        # 4. Subsequent identical submission returns HTTP 200 cached hit immediately.
        cached_resp = client.post(
            "/api/v1/jobs",
            json={"ra": 331.0764, "dec": -56.7938, "size_arcsec": 180.0, "max_frames": 12},
        )
        assert cached_resp.status_code == 200
        cached_body = cached_resp.json()
        assert cached_body["cached"] is True
        assert cached_body["status"] == "succeeded"
        assert cached_body["result"]["total_frames"] == 2
        assert provider.calls == 1
    finally:
        dispatcher.shutdown(wait=True)
        app.dependency_overrides.clear()


def test_deduplication_and_duplicate_worker_delivery(raw_cutout_factory, tmp_path: Path) -> None:
    """Equivalent requests share one job_id and duplicate worker deliveries are idempotent."""
    f1 = raw_cutout_factory(mjd_avg=60800.0, sps_epa_deg=0.0, detector_band=6, frame_id="exp_1")
    provider = _StubCutoutProvider([f1])
    service = _make_service(provider)
    job_store, result_store = _make_stores(tmp_path)
    limits = PublicLimits()
    dispatcher = _RecordingDispatcher()
    coordinator = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
    )
    worker = AsyncIngestionWorker(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        limits=limits,
    )

    req = JobSubmissionRequest(ra=331.0764, dec=-56.7938, size_arcsec=180.0, max_frames=8)
    first_dto, first_code = coordinator.submit_job(req)
    second_dto, second_code = coordinator.submit_job(req)

    assert first_code == 202
    assert second_code == 202
    assert first_dto.job_id == second_dto.job_id
    assert first_dto.request_key == second_dto.request_key
    assert len(dispatcher.dispatched) == 1

    # Simulate duplicate worker delivery after completion.
    res1 = worker.execute(first_dto.job_id)
    res2 = worker.execute(first_dto.job_id)
    assert res1.http_status == 200
    assert res1.status == "succeeded"
    assert res2.http_status == 200
    assert res2.status == "succeeded"
    assert provider.calls == 1

    # Simulate concurrent duplicate delivery while another worker holds an active lease.
    now = datetime.now(UTC)
    running_job = JobRecord(
        job_id="active-lease-job",
        request_key="k" * 64,
        target=first_dto_target(job_store, first_dto.job_id),
        max_frames=8,
        status="running",
        attempts=1,
        max_attempts=3,
        correlation_id="corr-lease",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        lease_expires_at=now + timedelta(minutes=2),
        worker_id="worker-1",
    )
    job_store.create_or_deduplicate_job(running_job, limits)
    concurrent = worker.execute("active-lease-job")
    assert concurrent.http_status == 409
    assert concurrent.status == "already_running"


def first_dto_target(job_store: LocalSQLiteJobStore, job_id: str) -> TargetSpec:
    rec = job_store.get_job(job_id)
    assert rec is not None
    return rec.target


def test_worker_restart_recovery_after_expired_lease(raw_cutout_factory, tmp_path: Path) -> None:
    """A new worker instance recovers a job whose previous worker crashed and lease expired."""
    f1 = raw_cutout_factory(mjd_avg=60800.0, sps_epa_deg=0.0, detector_band=6, frame_id="exp_1")
    provider = _StubCutoutProvider([f1])
    service = _make_service(provider)
    db_path = tmp_path / "jobs" / "jobs.sqlite3"
    res_path = tmp_path / "results" / "results.sqlite3"

    store_before_crash = LocalSQLiteJobStore(db_path)
    result_store_1 = ResultStore(LocalResultObjects(res_path), "b" * 40)
    dispatcher = _RecordingDispatcher()
    limits = PublicLimits()
    coord_1 = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=store_before_crash,
        result_store=result_store_1,
        dispatcher=dispatcher,
        limits=limits,
    )
    dto, code = coord_1.submit_job(JobSubmissionRequest(ra=331.0764, dec=-56.7938))
    assert code == 202

    # Worker 1 claims the job with a 0-second lease (simulating crash/timeout).
    claim = store_before_crash.claim_for_execution(
        dto.job_id, worker_id="crashed-worker", max_attempts=3, lease_seconds=-1
    )
    assert claim.status == "claimed"

    # Simulated process restart: brand new store/worker/coordinator instances reading same disk.
    store_after_restart = LocalSQLiteJobStore(db_path)
    result_store_2 = ResultStore(LocalResultObjects(res_path), "b" * 40)
    worker_2 = AsyncIngestionWorker(
        ingestion_service=service,
        job_store=store_after_restart,
        result_store=result_store_2,
        limits=limits,
        worker_id="restarted-worker",
    )
    coord_2 = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=store_after_restart,
        result_store=result_store_2,
        dispatcher=dispatcher,
        limits=limits,
    )

    res = worker_2.execute(dto.job_id)
    assert res.http_status == 200
    assert res.status == "succeeded"

    status = coord_2.get_job_status(dto.job_id)
    assert status.status == "succeeded"
    assert status.attempts == 2
    assert coord_2.get_job_result(dto.job_id).total_frames == 1


def test_retry_exhaustion_and_sanitized_failure(tmp_path: Path) -> None:
    """Transient errors retry up to max_attempts, then fail with sanitized error & 200 to queue."""
    provider = _StubCutoutProvider(error=RuntimeError("SECRET_INTERNAL_TRACEBACK_DETAIL"))
    service = _make_service(provider)
    job_store, result_store = _make_stores(tmp_path)
    limits = PublicLimits()
    dispatcher = _RecordingDispatcher()
    coordinator = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
        max_attempts=2,
    )
    worker = AsyncIngestionWorker(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        limits=limits,
        max_attempts=2,
    )

    dto, _ = coordinator.submit_job(JobSubmissionRequest(ra=10.0, dec=20.0))

    attempt1 = worker.execute(dto.job_id)
    assert attempt1.http_status == 503
    assert attempt1.should_retry is True
    assert coordinator.get_job_status(dto.job_id).status == "queued"

    attempt2 = worker.execute(dto.job_id)
    assert attempt2.http_status == 200
    assert attempt2.should_retry is False
    assert attempt2.status == "failed"

    status = coordinator.get_job_status(dto.job_id)
    assert status.status == "failed"
    assert status.error_code == "internal_error"
    assert status.error_message is not None
    assert "SECRET_INTERNAL_TRACEBACK_DETAIL" not in status.error_message
    assert status.correlation_id


def test_permanent_failures_are_not_retried(tmp_path: Path) -> None:
    """Validation errors return 422 at submit; NoObservations fails permanently without retry."""
    provider = _StubCutoutProvider(frames=[])
    service = _make_service(provider)
    job_store, result_store = _make_stores(tmp_path)
    limits = PublicLimits()
    dispatcher = _RecordingDispatcher()
    coordinator = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
        max_attempts=3,
    )
    worker = AsyncIngestionWorker(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        limits=limits,
        max_attempts=3,
    )

    app.dependency_overrides[get_job_coordinator] = lambda: coordinator
    try:
        client = TestClient(app)
        # Missing coordinates/query -> 422
        assert client.post("/api/v1/jobs", json={}).status_code == 422
        # force_refresh=True -> 422
        resp_refresh = client.post(
            "/api/v1/jobs",
            json={"ra": 10.0, "dec": 10.0, "force_refresh": True},
        )
        assert resp_refresh.status_code == 422
        # Exceeds max_exposures -> 422
        resp_frames = client.post(
            "/api/v1/jobs",
            json={"ra": 10.0, "dec": 10.0, "max_frames": 99},
        )
        assert resp_frames.status_code == 422
    finally:
        app.dependency_overrides.clear()

    # NoObservations during worker execution: fails immediately on attempt 1 with HTTP 200.
    dto, code = coordinator.submit_job(JobSubmissionRequest(ra=10.0, dec=10.0))
    assert code == 202
    res = worker.execute(dto.job_id)
    assert res.http_status == 200
    assert res.status == "failed"
    assert res.should_retry is False
    status = coordinator.get_job_status(dto.job_id)
    assert status.attempts == 1
    assert status.error_code == "no_observations"


def test_unauthenticated_worker_rejection_and_oidc_verification(
    raw_cutout_factory, tmp_path: Path
) -> None:
    """Private worker rejects bad OIDC tokens and accepts valid Cloud Tasks OIDC."""
    f1 = raw_cutout_factory(mjd_avg=60800.0, sps_epa_deg=0.0, detector_band=6, frame_id="exp_1")
    provider = _StubCutoutProvider([f1])
    service = _make_service(provider)
    job_store, result_store = _make_stores(tmp_path)
    limits = PublicLimits()
    dispatcher = _RecordingDispatcher()
    coordinator = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
    )
    worker = AsyncIngestionWorker(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        limits=limits,
    )

    def _fake_verify(token: str, audience: str) -> dict[str, Any]:
        if token == "valid-token" and audience == "https://worker.example.run.app":
            return {"email": "tasks-invoker@proj.iam.gserviceaccount.com", "email_verified": True}
        if token == "wrong-sa-token":
            return {"email": "attacker@proj.iam.gserviceaccount.com", "email_verified": True}
        raise ValueError("bad signature")

    verifier = OIDCWorkerAuthVerifier(
        expected_audience="https://worker.example.run.app",
        expected_service_account_email="tasks-invoker@proj.iam.gserviceaccount.com",
        require_cloud_tasks_header=True,
        token_verifier=_fake_verify,
    )

    dto, _ = coordinator.submit_job(JobSubmissionRequest(ra=331.0764, dec=-56.7938))

    app.dependency_overrides[get_async_worker] = lambda: worker
    app.dependency_overrides[get_worker_auth_verifier] = lambda: verifier
    try:
        client = TestClient(app)

        # Missing header & bearer -> 403 / 401
        r_no_auth = client.post("/internal/worker/ingest", json={"job_id": dto.job_id})
        assert r_no_auth.status_code in (401, 403)

        r_no_bearer = client.post(
            "/internal/worker/ingest",
            json={"job_id": dto.job_id},
            headers={"X-CloudTasks-TaskName": "task-1"},
        )
        assert r_no_bearer.status_code == 401

        r_bad_token = client.post(
            "/internal/worker/ingest",
            json={"job_id": dto.job_id},
            headers={
                "X-CloudTasks-TaskName": "task-1",
                "Authorization": "Bearer invalid",
            },
        )
        assert r_bad_token.status_code == 401

        r_wrong_sa = client.post(
            "/internal/worker/ingest",
            json={"job_id": dto.job_id},
            headers={
                "X-CloudTasks-TaskName": "task-1",
                "Authorization": "Bearer wrong-sa-token",
            },
        )
        assert r_wrong_sa.status_code == 403

        r_ok = client.post(
            "/internal/worker/ingest",
            json={"job_id": dto.job_id},
            headers={
                "X-CloudTasks-TaskName": "task-1",
                "Authorization": "Bearer valid-token",
            },
        )
        assert r_ok.status_code == 200
        assert r_ok.json()["status"] == "succeeded"
    finally:
        app.dependency_overrides.clear()


def test_admission_limits_and_expiration(tmp_path: Path) -> None:
    """Queue full returns 429 with Retry-After; expired jobs transition to expired (410)."""
    service = _make_service(_StubCutoutProvider())
    job_store, result_store = _make_stores(tmp_path)
    limits = PublicLimits(max_outstanding_jobs=1, max_new_jobs_per_minute=10)
    dispatcher = _RecordingDispatcher()
    coordinator = AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
        job_ttl_seconds=1,
    )

    app.dependency_overrides[get_job_coordinator] = lambda: coordinator
    app.dependency_overrides[get_public_limits] = lambda: limits
    try:
        client = TestClient(app)
        r1 = client.post("/api/v1/jobs", json={"ra": 10.0, "dec": 10.0})
        assert r1.status_code == 202

        r2 = client.post("/api/v1/jobs", json={"ra": 20.0, "dec": 20.0})
        assert r2.status_code == 429
        assert "Retry-After" in r2.headers
    finally:
        app.dependency_overrides.clear()

    # Test expiration transition
    past = datetime.now(UTC) - timedelta(seconds=10)
    expired_job = JobRecord(
        job_id="expired-job-1",
        request_key="e" * 64,
        target=TargetSpec(target_id="t", name="t", ra_deg=1.0, dec_deg=1.0),
        max_frames=4,
        status="queued",
        attempts=0,
        max_attempts=3,
        correlation_id="corr-exp",
        created_at=past - timedelta(seconds=60),
        updated_at=past - timedelta(seconds=60),
        expires_at=past,
    )
    job_store.save_cached_job(expired_job)
    assert coordinator.get_job_status("expired-job-1").status == "expired"


def test_cloud_tasks_dispatcher_and_firestore_adapter_contract() -> None:
    """Verify CloudTasksJobDispatcher payload and FirestoreJobStore transaction contract."""

    class _FakeTasksClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def create_task(self, *, parent: str, task: dict[str, Any]) -> None:
            self.calls.append((parent, task))

    tasks_client = _FakeTasksClient()
    cloud_dispatcher = CloudTasksJobDispatcher(
        queue_path="projects/p/locations/us-central1/queues/spherex",
        worker_url="https://api.example.run.app/internal/worker/ingest",
        service_account_email="tasks@p.iam.gserviceaccount.com",
        dispatch_deadline_seconds=180,
        tasks_client=tasks_client,
    )
    now = datetime.now(UTC)
    job = JobRecord(
        job_id="job-cloud-1",
        request_key="f" * 64,
        target=TargetSpec(target_id="t", name="t", ra_deg=1.0, dec_deg=1.0),
        max_frames=6,
        status="queued",
        attempts=0,
        max_attempts=3,
        correlation_id="corr-cloud-1",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
    )
    cloud_dispatcher.dispatch(job)
    assert len(tasks_client.calls) == 1
    parent, task = tasks_client.calls[0]
    assert parent.endswith("/queues/spherex")
    assert task["http_request"]["oidc_token"]["service_account_email"] == (
        "tasks@p.iam.gserviceaccount.com"
    )
    assert b"job-cloud-1" in task["http_request"]["body"]

    # In-memory fake Firestore client verifying FirestoreJobStore state transitions.
    db: dict[tuple[str, str], dict[str, Any]] = {}

    class _FakeSnapshot:
        def __init__(self, data: dict[str, Any] | None) -> None:
            self._data = data
            self.exists = data is not None

        def to_dict(self) -> dict[str, Any] | None:
            return dict(self._data) if self._data is not None else None

    class _FakeDocRef:
        def __init__(self, key: tuple[str, str]) -> None:
            self._key = key

        def get(self, transaction: Any = None) -> _FakeSnapshot:
            del transaction
            return _FakeSnapshot(db.get(self._key))

        def set(self, data: dict[str, Any]) -> None:
            db[self._key] = dict(data)

    class _FakeCollection:
        def __init__(self, name: str) -> None:
            self._name = name

        def document(self, doc_id: str) -> _FakeDocRef:
            return _FakeDocRef((self._name, doc_id))

    class _FakeTransaction:
        def set(self, ref: _FakeDocRef, data: dict[str, Any]) -> None:
            ref.set(data)

    class _FakeFirestoreClient:
        def collection(self, name: str) -> _FakeCollection:
            return _FakeCollection(name)

        def transaction(self) -> _FakeTransaction:
            return _FakeTransaction()

    fs_store = FirestoreJobStore(client=_FakeFirestoreClient())
    created, is_new = fs_store.create_or_deduplicate_job(job, PublicLimits())
    assert is_new is True
    assert created.job_id == "job-cloud-1"

    dedup, is_new_2 = fs_store.create_or_deduplicate_job(job, PublicLimits())
    assert is_new_2 is False
    assert dedup.job_id == "job-cloud-1"

    claim = fs_store.claim_for_execution("job-cloud-1", "w1", max_attempts=3, lease_seconds=60)
    assert claim.status == "claimed"
    assert claim.record is not None
    assert claim.record.attempts == 1

    done = fs_store.mark_succeeded("job-cloud-1", job.request_key)
    assert done.status == "succeeded"
