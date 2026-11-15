"""Application coordinator and idempotent worker for durable async ingestion."""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta

from spherex_ingest.domain.jobs import (
    JobDispatcherProtocol,
    JobRecord,
    JobStatusDTO,
    JobStoreProtocol,
    JobSubmissionRequest,
    WorkerExecutionResult,
)
from spherex_ingest.domain.models import BlinkBundleDTO, TargetSpec
from spherex_ingest.limits import PublicLimits, WorkLimitExceeded, bounded_ingestion
from spherex_ingest.result_storage import ResultKey, ResultStore
from spherex_ingest.service import (
    NoObservations,
    SPHERExBlinkIngestionService,
    UpstreamUnavailable,
)

logger = logging.getLogger(__name__)


class JobNotFoundError(KeyError):
    """Raised when a requested job_id does not exist."""


class JobNotReadyError(RuntimeError):
    """Raised when a job's result is requested before completion."""

    def __init__(self, job_id: str, status: str) -> None:
        super().__init__(f"Job '{job_id}' is currently '{status}'.")
        self.job_id = job_id
        self.status = status


class JobExpiredError(RuntimeError):
    """Raised when a job or its stored result has expired."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Job '{job_id}' has expired.")
        self.job_id = job_id


class JobFailedError(RuntimeError):
    """Raised when a job's result is requested after permanent failure."""

    def __init__(
        self,
        job_id: str,
        error_code: str,
        error_message: str,
        correlation_id: str,
    ) -> None:
        super().__init__(error_message)
        self.job_id = job_id
        self.error_code = error_code
        self.error_message = error_message
        self.correlation_id = correlation_id


def build_target_input(request: JobSubmissionRequest) -> TargetSpec | str:
    """Normalize a JobSubmissionRequest into a canonical TargetSpec or query string."""
    if request.ra is not None and request.dec is not None:
        slug = (
            f"coord_{request.ra:.5f}_{request.dec:+.5f}"
            .replace("+", "p")
            .replace("-", "m")
            .replace(".", "d")
        )
        return TargetSpec(
            target_id=slug,
            name=f"RA {request.ra:.5f}d, Dec {request.dec:+.5f}d",
            category="custom",
            ra_deg=request.ra,
            dec_deg=request.dec,
            cutout_size_arcsec=request.size_arcsec,
        )
    if request.query is not None and request.query.strip():
        return request.query.strip()
    raise ValueError(
        "Provide either both 'ra' and 'dec' in degrees, or a non-empty 'query' parameter."
    )


class AsyncIngestionWorker:
    """Idempotent worker executing claimed async ingestion jobs within PublicLimits."""

    def __init__(
        self,
        *,
        ingestion_service: SPHERExBlinkIngestionService,
        job_store: JobStoreProtocol,
        result_store: ResultStore,
        limits: PublicLimits,
        max_attempts: int = 3,
        lease_seconds: int | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.job_store = job_store
        self.result_store = result_store
        self.limits = limits
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds or (limits.max_elapsed_seconds + 30)
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"

    def execute(self, job_id: str) -> WorkerExecutionResult:
        """Claim and execute a job idempotently, returning HTTP/retry semantics."""
        claim = self.job_store.claim_for_execution(
            job_id=job_id,
            worker_id=self.worker_id,
            max_attempts=self.max_attempts,
            lease_seconds=self.lease_seconds,
        )
        if claim.status in ("already_succeeded", "already_terminal", "expired", "exhausted"):
            return WorkerExecutionResult(
                job_id=job_id,
                status=claim.record.status if claim.record else claim.status,
                http_status=200,
                should_retry=False,
            )
        if claim.status == "not_found":
            return WorkerExecutionResult(
                job_id=job_id, status="not_found", http_status=404, should_retry=False
            )
        if claim.status == "already_running":
            return WorkerExecutionResult(
                job_id=job_id, status="already_running", http_status=409, should_retry=True
            )

        record = claim.record
        assert record is not None
        key = ResultKey.from_target(record.target, record.max_frames)

        existing = self.result_store.lookup(key)
        if existing is not None:
            self.job_store.mark_succeeded(job_id, key.digest)
            return WorkerExecutionResult(
                job_id=job_id, status="succeeded", http_status=200, should_retry=False
            )

        try:
            with bounded_ingestion(self.limits, record.max_frames):
                bundle = self.ingestion_service.ingest_target(
                    target_or_query=record.target,
                    cutout_size_arcsec=record.target.cutout_size_arcsec,
                    max_frames_per_collection=record.max_frames,
                )
            if not bundle.total_frames:
                self.job_store.mark_permanent_failure(
                    job_id,
                    "no_observations",
                    "No valid SPHEREx frames overlapped the requested cutout.",
                )
                return WorkerExecutionResult(
                    job_id=job_id, status="failed", http_status=200, should_retry=False
                )
            self.result_store.publish(key, bundle)
        except NoObservations:
            self.job_store.mark_permanent_failure(
                job_id,
                "no_observations",
                "No SPHEREx Level 2b cutouts found for the requested coordinates.",
            )
            return WorkerExecutionResult(
                job_id=job_id, status="failed", http_status=200, should_retry=False
            )
        except WorkLimitExceeded as exc:
            if exc.code == "timeout":
                updated = self.job_store.mark_retryable_failure(
                    job_id, "timeout", "Ingestion attempt exceeded its processing deadline."
                )
                return self._retry_result(updated)
            self.job_store.mark_permanent_failure(
                job_id, exc.code, f"Ingestion exceeded public limit: {exc.code}."
            )
            return WorkerExecutionResult(
                job_id=job_id, status="failed", http_status=200, should_retry=False
            )
        except ValueError:
            self.job_store.mark_permanent_failure(
                job_id, "invalid_request", "Invalid ingestion request parameters."
            )
            return WorkerExecutionResult(
                job_id=job_id, status="failed", http_status=200, should_retry=False
            )
        except UpstreamUnavailable:
            logger.warning(
                "Upstream SPHEREx unavailable for job_id=%s correlation_id=%s",
                job_id,
                record.correlation_id,
            )
            updated = self.job_store.mark_retryable_failure(
                job_id,
                "upstream_unavailable",
                "Upstream SPHEREx service is temporarily unavailable.",
            )
            return self._retry_result(updated)
        except Exception:
            logger.exception(
                "Unexpected failure executing job_id=%s correlation_id=%s",
                job_id,
                record.correlation_id,
            )
            updated = self.job_store.mark_retryable_failure(
                job_id,
                "internal_error",
                "Unexpected ingestion failure.",
            )
            return self._retry_result(updated)

        self.job_store.mark_succeeded(job_id, key.digest)
        return WorkerExecutionResult(
            job_id=job_id, status="succeeded", http_status=200, should_retry=False
        )

    @staticmethod
    def _retry_result(record: JobRecord) -> WorkerExecutionResult:
        if record.status == "failed":
            # Retry budget exhausted: return 200 so Cloud Tasks stops redelivering.
            return WorkerExecutionResult(
                job_id=record.job_id,
                status="failed",
                http_status=200,
                should_retry=False,
            )
        return WorkerExecutionResult(
            job_id=record.job_id,
            status="queued",
            http_status=503,
            should_retry=True,
        )


class AsyncJobCoordinator:
    """Public submission, deduplication, status polling, and result retrieval."""

    def __init__(
        self,
        *,
        ingestion_service: SPHERExBlinkIngestionService,
        job_store: JobStoreProtocol,
        result_store: ResultStore,
        dispatcher: JobDispatcherProtocol,
        limits: PublicLimits,
        max_attempts: int = 3,
        job_ttl_seconds: int = 86_400,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.job_store = job_store
        self.result_store = result_store
        self.dispatcher = dispatcher
        self.limits = limits
        self.max_attempts = max_attempts
        self.job_ttl_seconds = job_ttl_seconds

    def submit_job(self, request: JobSubmissionRequest) -> tuple[JobStatusDTO, int]:
        """Validate, check cache/dedup, persist, and dispatch an async job."""
        if request.force_refresh:
            raise ValueError("force_refresh is not permitted on the public async queue.")

        self.limits.validate_request(request.size_arcsec, request.max_frames)
        target_input = build_target_input(request)
        target = self.ingestion_service.resolve_target(
            target_input, cutout_size_arcsec=request.size_arcsec
        )
        key = ResultKey.from_target(target, request.max_frames)
        request_key = key.digest

        cached_bundle = self.result_store.lookup(key)
        if cached_bundle is not None:
            now = datetime.now(UTC)
            existing = self.job_store.get_active_or_succeeded_by_key(request_key)
            if existing is not None and existing.status == "succeeded":
                return (
                    JobStatusDTO.from_record(existing, cached=True, result=cached_bundle),
                    200,
                )
            synthetic = JobRecord(
                job_id=uuid.uuid4().hex,
                request_key=request_key,
                target=target,
                max_frames=request.max_frames,
                status="succeeded",
                attempts=0,
                max_attempts=self.max_attempts,
                correlation_id=uuid.uuid4().hex,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=self.job_ttl_seconds),
                result_digest=request_key,
            )
            self.job_store.save_cached_job(synthetic)
            return JobStatusDTO.from_record(synthetic, cached=True, result=cached_bundle), 200

        now = datetime.now(UTC)
        new_job = JobRecord(
            job_id=uuid.uuid4().hex,
            request_key=request_key,
            target=target,
            max_frames=request.max_frames,
            status="queued",
            attempts=0,
            max_attempts=self.max_attempts,
            correlation_id=uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(seconds=self.job_ttl_seconds),
        )

        record, created_new = self.job_store.create_or_deduplicate_job(new_job, self.limits)
        if not created_new:
            if record.status == "succeeded":
                bundle = self.result_store.lookup(key, allow_stale_partial=True)
                if bundle is not None:
                    return JobStatusDTO.from_record(record, cached=True, result=bundle), 200
            return JobStatusDTO.from_record(record), 202

        try:
            self.dispatcher.dispatch(record)
        except Exception:
            logger.exception(
                "Failed to dispatch job_id=%s correlation_id=%s",
                record.job_id,
                record.correlation_id,
            )
            self.job_store.mark_permanent_failure(
                record.job_id,
                "dispatch_failed",
                "Unable to enqueue ingestion job.",
            )
            raise

        return JobStatusDTO.from_record(record), 202

    def get_job_status(self, job_id: str) -> JobStatusDTO:
        """Return the current sanitized status of a job."""
        record = self.job_store.get_job(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        if record.status in ("queued", "running") and datetime.now(UTC) >= record.expires_at:
            record = self.job_store.mark_expired(job_id)
        return JobStatusDTO.from_record(record)

    def get_job_result(self, job_id: str) -> BlinkBundleDTO:
        """Return the completed BlinkBundleDTO for a succeeded job."""
        record = self.job_store.get_job(job_id)
        if record is None:
            raise JobNotFoundError(job_id)
        if record.status in ("queued", "running") and datetime.now(UTC) >= record.expires_at:
            record = self.job_store.mark_expired(job_id)

        if record.status in ("queued", "running"):
            raise JobNotReadyError(job_id, record.status)
        if record.status == "expired":
            raise JobExpiredError(job_id)
        if record.status == "failed":
            raise JobFailedError(
                job_id,
                record.error_code or "internal_error",
                record.error_message or "Ingestion job failed.",
                record.correlation_id,
            )

        key = ResultKey.from_target(record.target, record.max_frames)
        bundle = self.result_store.lookup(key, allow_stale_partial=True)
        if bundle is None:
            self.job_store.mark_expired(job_id)
            raise JobExpiredError(job_id)
        return bundle
