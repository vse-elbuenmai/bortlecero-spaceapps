"""Domain models, state machine contracts, and protocols for durable async ingestion."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from spherex_ingest.domain.models import BlinkBundleDTO, TargetSpec
from spherex_ingest.limits import PublicLimits

JobStatus = Literal["queued", "running", "succeeded", "failed", "expired"]


class JobSubmissionRequest(BaseModel):
    """Public request payload for submitting an asynchronous SPHEREx blink job."""

    model_config = ConfigDict(extra="forbid")

    ra: float | None = Field(
        default=None,
        ge=0.0,
        lt=360.0,
        description="Right Ascension in decimal degrees (ICRS)",
    )
    dec: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Declination in decimal degrees (ICRS)",
    )
    query: str | None = Field(
        default=None,
        description="Object name or coordinate string",
    )
    size_arcsec: float = Field(
        default=180.0,
        gt=12.0,
        le=1800.0,
        description="Angular cutout size in arcseconds",
    )
    max_frames: int = Field(
        default=12,
        ge=1,
        le=120,
        description="Maximum exposures to fetch across SPHEREx collections",
    )
    force_refresh: bool = Field(
        default=False,
        description="Force bypass of cached results (rejected on public async queue)",
    )


class JobRecord(BaseModel):
    """Durable job state persisted in the job repository."""

    job_id: str
    request_key: str
    target: TargetSpec
    max_frames: int = Field(ge=1)
    status: JobStatus
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    correlation_id: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime
    lease_expires_at: AwareDatetime | None = None
    worker_id: str | None = None
    result_digest: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class JobStatusDTO(BaseModel):
    """Public API representation of an asynchronous ingestion job."""

    job_id: str
    request_key: str
    status: JobStatus
    status_url: str
    result_url: str
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime
    attempts: int
    max_attempts: int
    correlation_id: str
    cached: bool = False
    error_code: str | None = None
    error_message: str | None = None
    result: BlinkBundleDTO | None = None

    @classmethod
    def from_record(
        cls,
        record: JobRecord,
        *,
        cached: bool = False,
        result: BlinkBundleDTO | None = None,
    ) -> JobStatusDTO:
        """Build a sanitized public status DTO from an internal durable JobRecord."""
        return cls(
            job_id=record.job_id,
            request_key=record.request_key,
            status=record.status,
            status_url=f"/api/v1/jobs/{record.job_id}",
            result_url=f"/api/v1/jobs/{record.job_id}/result",
            created_at=record.created_at,
            updated_at=record.updated_at,
            expires_at=record.expires_at,
            attempts=record.attempts,
            max_attempts=record.max_attempts,
            correlation_id=record.correlation_id,
            cached=cached,
            error_code=record.error_code,
            error_message=record.error_message,
            result=result,
        )


class WorkerTaskPayload(BaseModel):
    """Payload delivered by Cloud Tasks or local dispatcher to the worker endpoint."""

    job_id: str
    request_key: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class ClaimOutcome:
    """Result of an atomic worker lease claim on a job."""

    status: Literal[
        "claimed",
        "already_succeeded",
        "already_terminal",
        "already_running",
        "exhausted",
        "not_found",
        "expired",
    ]
    record: JobRecord | None = None


@dataclass(frozen=True)
class WorkerExecutionResult:
    """Outcome returned by the async ingestion worker to HTTP or local callers."""

    job_id: str
    status: str
    http_status: int
    should_retry: bool = False


class AdmissionLimitExceeded(RuntimeError):
    """Raised when public queue capacity or admission rate limits are exceeded."""

    def __init__(self, code: str, retry_after_seconds: int = 30) -> None:
        super().__init__(code)
        self.code = code
        self.retry_after_seconds = max(1, retry_after_seconds)


class JobStoreProtocol(Protocol):
    """Durable repository for asynchronous ingestion job state and admission control."""

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def get_active_or_succeeded_by_key(self, request_key: str) -> JobRecord | None: ...

    def create_or_deduplicate_job(
        self, job: JobRecord, limits: PublicLimits
    ) -> tuple[JobRecord, bool]: ...

    def save_cached_job(self, job: JobRecord) -> None: ...

    def claim_for_execution(
        self,
        job_id: str,
        worker_id: str,
        max_attempts: int,
        lease_seconds: int,
    ) -> ClaimOutcome: ...

    def mark_succeeded(self, job_id: str, result_digest: str) -> JobRecord: ...

    def mark_retryable_failure(
        self, job_id: str, error_code: str, error_message: str
    ) -> JobRecord: ...

    def mark_permanent_failure(
        self, job_id: str, error_code: str, error_message: str
    ) -> JobRecord: ...

    def mark_expired(self, job_id: str) -> JobRecord: ...


class JobDispatcherProtocol(Protocol):
    """Dispatches a durably persisted job to a worker."""

    def dispatch(self, job: JobRecord) -> None: ...


class WorkerAuthVerifierProtocol(Protocol):
    """Verifies caller identity on the private worker invocation endpoint."""

    def verify(self, authorization: str | None, headers: Mapping[str, str]) -> None: ...
