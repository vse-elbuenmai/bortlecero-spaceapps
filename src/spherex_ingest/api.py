"""FastAPI REST application for the SPHEREx Multi-Epoch Blink Comparator backend.

Provides a CORS-enabled API proxy and preprocessing service that shields the web
frontend from IRSA SIAv2/cutout CORS restrictions and CDS Strasbourg outages while
serving scientifically calibrated, North-up reprojected SPHEREx blink bundles.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from spherex_ingest import __version__
from spherex_ingest.domain.jobs import (
    AdmissionLimitExceeded,
    JobDispatcherProtocol,
    JobStatusDTO,
    JobStoreProtocol,
    JobSubmissionRequest,
    WorkerAuthVerifierProtocol,
    WorkerTaskPayload,
)
from spherex_ingest.domain.models import BUNDLE_SCHEMA_VERSION, BlinkBundleDTO, TargetSpec
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target
from spherex_ingest.infrastructure.job_queue import (
    CloudTasksJobDispatcher,
    LocalDevWorkerAuthVerifier,
    LocalThreadPoolJobDispatcher,
    OIDCWorkerAuthVerifier,
    WorkerAuthError,
)
from spherex_ingest.infrastructure.job_store import FirestoreJobStore, LocalSQLiteJobStore
from spherex_ingest.job_service import (
    AsyncIngestionWorker,
    AsyncJobCoordinator,
    JobExpiredError,
    JobFailedError,
    JobNotFoundError,
    JobNotReadyError,
)
from spherex_ingest.limits import PublicLimits, WorkLimitExceeded
from spherex_ingest.result_storage import ResultKey, ResultStore, get_result_store
from spherex_ingest.service import SPHERExBlinkIngestionService

logger = logging.getLogger(__name__)


class HealthResponseDTO(BaseModel):
    """Health status and operational metadata for the SPHEREx ingestion API."""

    status: str = Field(default="ok", description="Service health status")
    service: str = Field(default="spherex-ingest", description="Service identifier")
    version: str = Field(default=__version__, description="Package semantic version")
    cors_enabled: bool = Field(
        default=True,
        description="Whether wildcard CORS headers are enabled for browser clients",
    )
    revision: str | None = Field(
        default=None,
        description="Cloud Run revision identifier when available",
    )
    legacy_sync_enabled: bool = Field(
        description="Whether legacy v1 synchronous ingestion is enabled",
    )
    async_jobs_enabled: bool = Field(
        description="Whether asynchronous queued ingestion is enabled",
    )
    benchmark_count: int = Field(
        default=len(BENCHMARK_TARGETS),
        description="Number of curated NASA Space Apps benchmark targets available",
    )


@lru_cache(maxsize=1)
def get_default_service() -> SPHERExBlinkIngestionService:
    """Return a singleton default SPHERExBlinkIngestionService instance."""
    cache_dir = Path(os.environ.get("SPHEREX_CACHE_DIR", ".cache/fits"))
    return SPHERExBlinkIngestionService.create_default(cache_dir=cache_dir)


def get_output_dir() -> Path:
    """Return the directory where precomputed blink bundles are stored."""
    return Path(os.environ.get("SPHEREX_OUTPUT_DIR", "output"))


def legacy_sync_enabled() -> bool:
    """Use local live ingestion by default and honor the deployed capability flag."""
    return os.environ.get("SPHEREX_LEGACY_SYNC_ENABLED", "true").lower() == "true"


def require_legacy_sync() -> None:
    """Reject live reads before requesting any upstream observations."""
    if not legacy_sync_enabled():
        raise HTTPException(status_code=503, detail="Live SPHEREx ingestion is disabled.")


def async_jobs_enabled() -> bool:
    """Enable durable async job submission unless explicitly disabled."""
    return os.environ.get("SPHEREX_ASYNC_JOBS_ENABLED", "true").lower() == "true"


def require_async_jobs() -> None:
    """Reject async job submission when the queue capability flag is disabled."""
    if not async_jobs_enabled():
        raise HTTPException(status_code=503, detail="Asynchronous SPHEREx ingestion is disabled.")


def get_public_limits() -> PublicLimits:
    """Load public queue and worker admission limits from environment."""
    return PublicLimits.from_environment()


def get_api_result_store() -> ResultStore:
    """Provide the configured ResultStore for dependency injection."""
    return get_result_store()


def get_job_store() -> JobStoreProtocol:
    """Provide durable Firestore or local SQLite job state storage."""
    if os.environ.get("SPHEREX_JOBS_BACKEND", "sqlite").lower() == "firestore":
        return FirestoreJobStore.from_project(
            project_id=os.environ.get("SPHEREX_FIRESTORE_PROJECT"),
            collection_name=os.environ.get("SPHEREX_JOBS_COLLECTION", "spherex_jobs"),
        )
    scratch = Path(os.getenv("SPHEREX_CACHE_DIR", ".cache/fits")).parent
    jobs_dir = Path(os.environ.get("SPHEREX_JOBS_DIR", scratch / "jobs")).resolve()
    return LocalSQLiteJobStore(jobs_dir / "jobs.sqlite3")


def get_async_worker(
    service: Annotated[SPHERExBlinkIngestionService, Depends(get_default_service)],
    job_store: Annotated[JobStoreProtocol, Depends(get_job_store)],
    result_store: Annotated[ResultStore, Depends(get_api_result_store)],
    limits: Annotated[PublicLimits, Depends(get_public_limits)],
) -> AsyncIngestionWorker:
    """Construct the idempotent async ingestion worker."""
    max_attempts = int(os.environ.get("SPHEREX_JOB_MAX_ATTEMPTS", "3"))
    return AsyncIngestionWorker(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        limits=limits,
        max_attempts=max_attempts,
    )


def get_job_dispatcher(
    worker: Annotated[AsyncIngestionWorker, Depends(get_async_worker)],
    limits: Annotated[PublicLimits, Depends(get_public_limits)],
) -> JobDispatcherProtocol:
    """Provide Cloud Tasks dispatcher in cloud mode or local thread-pool dispatcher."""
    if os.environ.get("SPHEREX_JOBS_DISPATCHER", "local").lower() == "cloud_tasks":
        return CloudTasksJobDispatcher.from_environment(
            project_id=os.environ["SPHEREX_TASKS_PROJECT"],
            location=os.environ["SPHEREX_TASKS_LOCATION"],
            queue_id=os.environ["SPHEREX_TASKS_QUEUE"],
            worker_base_url=os.environ["SPHEREX_WORKER_BASE_URL"],
            service_account_email=os.environ["SPHEREX_TASKS_SERVICE_ACCOUNT"],
            audience=os.environ.get("SPHEREX_WORKER_OIDC_AUDIENCE"),
            dispatch_deadline_seconds=limits.max_elapsed_seconds + 60,
        )
    return LocalThreadPoolJobDispatcher(worker.execute)


def get_job_coordinator(
    service: Annotated[SPHERExBlinkIngestionService, Depends(get_default_service)],
    job_store: Annotated[JobStoreProtocol, Depends(get_job_store)],
    result_store: Annotated[ResultStore, Depends(get_api_result_store)],
    dispatcher: Annotated[JobDispatcherProtocol, Depends(get_job_dispatcher)],
    limits: Annotated[PublicLimits, Depends(get_public_limits)],
) -> AsyncJobCoordinator:
    """Construct the AsyncJobCoordinator for submission, status, and results."""
    return AsyncJobCoordinator(
        ingestion_service=service,
        job_store=job_store,
        result_store=result_store,
        dispatcher=dispatcher,
        limits=limits,
        max_attempts=int(os.environ.get("SPHEREX_JOB_MAX_ATTEMPTS", "3")),
        job_ttl_seconds=int(os.environ.get("SPHEREX_JOB_TTL_SECONDS", "86400")),
    )


def get_worker_auth_verifier() -> WorkerAuthVerifierProtocol:
    """Provide OIDC token verification for the private worker endpoint."""
    audience = os.environ.get("SPHEREX_WORKER_OIDC_AUDIENCE")
    if audience:
        return OIDCWorkerAuthVerifier(
            expected_audience=audience,
            expected_service_account_email=os.environ.get("SPHEREX_TASKS_SERVICE_ACCOUNT"),
            require_cloud_tasks_header=(
                os.environ.get("SPHEREX_REQUIRE_CLOUD_TASKS_HEADER", "false").lower() == "true"
            ),
        )
    require_auth = (
        bool(os.environ.get("K_SERVICE"))
        or os.environ.get("SPHEREX_WORKER_AUTH_REQUIRED", "false").lower() == "true"
    )
    return LocalDevWorkerAuthVerifier(allow_unauthenticated=not require_auth)


ServiceDep = Annotated[SPHERExBlinkIngestionService, Depends(get_default_service)]
OutputDirDep = Annotated[Path, Depends(get_output_dir)]
CoordinatorDep = Annotated[AsyncJobCoordinator, Depends(get_job_coordinator)]
WorkerDep = Annotated[AsyncIngestionWorker, Depends(get_async_worker)]
WorkerAuthDep = Annotated[WorkerAuthVerifierProtocol, Depends(get_worker_auth_verifier)]


def _get_or_ingest_result(
    service: SPHERExBlinkIngestionService,
    target_input: TargetSpec | str,
    size_arcsec: float,
    max_frames: int,
    *,
    force_refresh: bool = False,
) -> BlinkBundleDTO:
    target = service.resolve_target(target_input, cutout_size_arcsec=size_arcsec)
    if force_refresh:
        return service.ingest_target(
            target_or_query=target,
            cutout_size_arcsec=size_arcsec,
            max_frames_per_collection=max_frames,
        )
    key = ResultKey.from_target(target, max_frames)
    store = get_result_store()
    cached = store.lookup(key)
    if cached is not None:
        return cached
    bundle = service.ingest_target(
        target_or_query=target,
        cutout_size_arcsec=size_arcsec,
        max_frames_per_collection=max_frames,
    )
    return store.publish(key, bundle)


app = FastAPI(
    title="Bortle Cero · SPHEREx Blink Comparator Ingestion API",
    description=(
        "SOLID data ingestion, WCS reprojection, Zodi subtraction, saturation repair, "
        "and Gaia DR3 kinematic validation pipeline for the NASA Space Apps 2026 "
        "'Planet X and SPHEREx' challenge."
    ),
    version=__version__,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/api/v1/health",
    response_model=HealthResponseDTO,
    tags=["system"],
    summary="Health check and service metadata",
)
def health_check() -> HealthResponseDTO:
    """Report process liveness and deployment metadata without polling upstream services."""
    return HealthResponseDTO(
        revision=os.environ.get("K_REVISION"),
        legacy_sync_enabled=legacy_sync_enabled(),
        async_jobs_enabled=async_jobs_enabled(),
    )


@app.get(
    "/api/v1/benchmarks",
    response_model=list[TargetSpec],
    tags=["benchmarks"],
    summary="List the 5 curated NASA Space Apps benchmark targets",
)
def list_benchmarks(service: ServiceDep) -> list[TargetSpec]:
    """Return all 5 official challenge benchmark targets with Gaia DR3 / 2025.5 astrometry."""
    return service.list_benchmarks()


@app.get(
    "/api/v1/blink/{target_id}",
    response_model=BlinkBundleDTO,
    tags=["blink"],
    summary="Retrieve or compute the SPHEREx blink bundle for a benchmark target",
)
def get_benchmark_blink_bundle(
    target_id: str,
    service: ServiceDep,
    output_dir: OutputDirDep,
    size_arcsec: Annotated[
        float,
        Query(
            gt=12.0,
            le=1800.0,
            description="Angular cutout size in arcseconds",
        ),
    ] = 180.0,
    max_frames: Annotated[
        int,
        Query(
            ge=1,
            le=120,
            description="Maximum exposures to fetch per SPHEREx SIAv2 collection",
        ),
    ] = 24,
    force_refresh: Annotated[
        bool,
        Query(
            description="Bypass precomputed bundle on disk and run live ingestion pipeline",
        ),
    ] = False,
) -> BlinkBundleDTO:
    """Serve the curated default bundle or a separately stored live query result."""
    target = get_benchmark_target(target_id)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown benchmark target '{target_id}'. "
                f"Available targets: {', '.join(BENCHMARK_TARGETS.keys())}"
            ),
        )

    precomputed_path = output_dir / target.target_id / "bundle.json"
    if (
        not force_refresh
        and size_arcsec == 180.0
        and max_frames == 24
        and precomputed_path.is_file()
    ):
        try:
            curated = BlinkBundleDTO.model_validate_json(precomputed_path.read_bytes())
            if (
                curated.target.target_id == target.target_id
                and curated.target.cutout_size_arcsec == size_arcsec
                and curated.schema_version == BUNDLE_SCHEMA_VERSION
            ):
                return curated
            logger.warning("Precomputed bundle has unexpected parameters at %s", precomputed_path)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Failed to load precomputed bundle at %s, falling back to live pipeline: %s",
                precomputed_path,
                exc,
            )

    require_legacy_sync()
    try:
        return _get_or_ingest_result(
            service, target, size_arcsec, max_frames, force_refresh=force_refresh
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Live ingestion failed for target '%s'", target.target_id)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream SPHEREx ingestion failed for '{target.target_id}': {exc}",
        ) from exc


@app.get(
    "/api/v1/blink",
    response_model=BlinkBundleDTO,
    tags=["blink"],
    summary="Query arbitrary sky coordinates (RA/Dec) or resolve an object name",
)
def query_custom_blink_bundle(
    service: ServiceDep,
    ra: Annotated[
        float | None,
        Query(
            ge=0.0,
            lt=360.0,
            description="Right Ascension in decimal degrees (ICRS)",
        ),
    ] = None,
    dec: Annotated[
        float | None,
        Query(
            ge=-90.0,
            le=90.0,
            description="Declination in decimal degrees (ICRS)",
        ),
    ] = None,
    query: Annotated[
        str | None,
        Query(
            description=(
                "Object name or coordinate string (e.g., 'Barnard\\'s Star' or '331.0764 -56.7938')"
            ),
        ),
    ] = None,
    size_arcsec: Annotated[
        float,
        Query(
            gt=12.0,
            le=1800.0,
            description="Angular cutout size in arcseconds",
        ),
    ] = 180.0,
    max_frames: Annotated[
        int,
        Query(
            ge=1,
            le=120,
            description="Maximum exposures to fetch per SPHEREx SIAv2 collection",
        ),
    ] = 18,
) -> BlinkBundleDTO:
    """Execute the SPHEREx ingestion pipeline for custom coordinates or an object name."""
    require_legacy_sync()
    if ra is not None and dec is not None:
        slug = f"coord_{ra:.5f}_{dec:+.5f}".replace("+", "p").replace("-", "m").replace(".", "d")
        target_input: TargetSpec | str = TargetSpec(
            target_id=slug,
            name=query.strip() if query and query.strip() else f"RA {ra:.5f}d, Dec {dec:+.5f}d",
            category="custom",
            ra_deg=ra,
            dec_deg=dec,
            cutout_size_arcsec=size_arcsec,
        )
    elif query is not None and query.strip():
        target_input = query.strip()
    else:
        raise HTTPException(
            status_code=422,
            detail=(
                "Provide either both 'ra' and 'dec' in degrees, or a non-empty 'query' parameter."
            ),
        )

    try:
        return _get_or_ingest_result(service, target_input, size_arcsec, max_frames)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Custom blink query failed for input=%s", target_input)
        raise HTTPException(
            status_code=502,
            detail=f"SPHEREx ingestion failed: {exc}",
        ) from exc


@app.post(
    "/api/v1/jobs",
    response_model=JobStatusDTO,
    tags=["jobs"],
    summary="Submit an asynchronous SPHEREx blink ingestion job",
)
def submit_async_job(
    payload: JobSubmissionRequest,
    coordinator: CoordinatorDep,
    response: Response,
) -> JobStatusDTO:
    """Return a cached result (200) or enqueue/deduplicate a durable async job (202)."""
    require_async_jobs()
    try:
        dto, status_code = coordinator.submit_job(payload)
    except AdmissionLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": exc.code, "message": "Public ingestion queue capacity reached."},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except WorkLimitExceeded as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": "Requested parameters exceed public limits."},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_request", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "dispatch_failed", "message": "Unable to queue ingestion job."},
        ) from exc

    response.status_code = status_code
    return dto


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobStatusDTO,
    tags=["jobs"],
    summary="Poll the status of an asynchronous SPHEREx ingestion job",
)
def get_async_job_status(job_id: str, coordinator: CoordinatorDep) -> JobStatusDTO:
    """Return durable job state, sanitized error metadata, and result links."""
    try:
        return coordinator.get_job_status(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": f"Unknown job '{job_id}'."},
        ) from exc


@app.get(
    "/api/v1/jobs/{job_id}/result",
    response_model=BlinkBundleDTO,
    tags=["jobs"],
    summary="Retrieve the completed BlinkBundleDTO for a succeeded async job",
)
def get_async_job_result(job_id: str, coordinator: CoordinatorDep) -> BlinkBundleDTO:
    """Return the published BlinkBundleDTO or a status-specific HTTP error."""
    try:
        return coordinator.get_job_result(job_id)
    except JobNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "job_not_found", "message": f"Unknown job '{job_id}'."},
        ) from exc
    except JobNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_ready",
                "status": exc.status,
                "message": f"Job '{job_id}' is currently '{exc.status}'.",
            },
        ) from exc
    except JobExpiredError as exc:
        raise HTTPException(
            status_code=410,
            detail={"code": "job_expired", "message": f"Job '{job_id}' has expired."},
        ) from exc
    except JobFailedError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.error_code,
                "message": exc.error_message,
                "correlation_id": exc.correlation_id,
            },
        ) from exc


@app.post(
    "/internal/worker/ingest",
    tags=["internal"],
    summary="Private worker endpoint invoked by Cloud Tasks to execute an async job",
    include_in_schema=False,
)
def run_internal_worker_ingest(
    payload: WorkerTaskPayload,
    request: Request,
    worker: WorkerDep,
    auth_verifier: WorkerAuthDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Authenticate worker invocation via OIDC and execute the job idempotently."""
    try:
        auth_verifier.verify(authorization, request.headers)
    except WorkerAuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "unauthorized_worker", "message": str(exc)},
        ) from exc

    result = worker.execute(payload.job_id)
    return JSONResponse(
        status_code=result.http_status,
        content={"job_id": result.job_id, "status": result.status},
    )
