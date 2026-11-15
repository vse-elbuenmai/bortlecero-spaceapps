"""FastAPI REST application for the SPHEREx Multi-Epoch Blink Comparator backend.

Provides a CORS-enabled API proxy and preprocessing service that shields the web
frontend from IRSA SIAv2/cutout CORS restrictions and CDS Strasbourg outages while
serving scientifically calibrated, North-up reprojected SPHEREx blink bundles.
"""

from __future__ import annotations

import hmac
import logging
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from spherex_ingest import __version__
from spherex_ingest.admission import (
    AdmissionControllerProtocol,
    AdmissionDenied,
    InMemoryAdmissionController,
)
from spherex_ingest.domain.models import BlinkBundleDTO, TargetSpec
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target
from spherex_ingest.limits import PublicLimits, WorkLimitExceeded, bounded_ingestion
from spherex_ingest.service import (
    NoObservations,
    SPHERExBlinkIngestionService,
    UpstreamUnavailable,
)

logger = logging.getLogger(__name__)

_DISABLED_VALUES = frozenset({"0", "false", "no", "off"})


def is_live_queries_enabled() -> bool:
    """Return whether live upstream ingestion queries are enabled."""
    raw = os.environ.get("SPHEREX_LIVE_QUERIES_ENABLED", "true").strip().lower()
    return raw not in _DISABLED_VALUES


def _is_maintenance_authorized(token: str | None) -> bool:
    """Verify the optional maintenance token for privileged refresh requests."""
    configured = os.environ.get("SPHEREX_MAINTENANCE_TOKEN", "").strip()
    if not configured or not token:
        return False
    return hmac.compare_digest(token.strip(), configured)


class HealthResponseDTO(BaseModel):
    """Health status and operational metadata for the SPHEREx ingestion API."""

    status: str = Field(default="ok", description="Service health status")
    service: str = Field(default="spherex-ingest", description="Service identifier")
    version: str = Field(default=__version__, description="Package semantic version")
    cors_enabled: bool = Field(
        default=True,
        description="Whether wildcard CORS headers are enabled for browser clients",
    )
    cds_mirror_active: bool = Field(
        default=True,
        description=(
            "Whether Harvard CFA Sesame/VizieR mirrors are used to bypass CDS Strasbourg outage"
        ),
    )
    live_queries_enabled: bool = Field(
        default_factory=is_live_queries_enabled,
        description="Whether live upstream SPHEREx queries are currently enabled",
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


def get_public_limits() -> PublicLimits:
    """Return the active public ingestion resource limits."""
    return PublicLimits.from_environment()


@lru_cache(maxsize=1)
def get_admission_controller() -> AdmissionControllerProtocol:
    """Return the singleton admission controller for public live ingestion."""
    return InMemoryAdmissionController(limits=get_public_limits())


ServiceDep = Annotated[SPHERExBlinkIngestionService, Depends(get_default_service)]
OutputDirDep = Annotated[Path, Depends(get_output_dir)]
LimitsDep = Annotated[PublicLimits, Depends(get_public_limits)]
AdmissionDep = Annotated[AdmissionControllerProtocol, Depends(get_admission_controller)]
LiveEnabledDep = Annotated[bool, Depends(is_live_queries_enabled)]

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


def _error_http_exception(
    status_code: int,
    code: str,
    message: str,
    correlation_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTTPException:
    """Build a sanitized HTTPException with a stable error code and correlation ID."""
    cid = correlation_id or uuid.uuid4().hex[:12]
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "correlation_id": cid,
        },
        headers=headers,
    )


def _run_bounded_live_ingestion(
    *,
    service: SPHERExBlinkIngestionService,
    limits: PublicLimits,
    admission: AdmissionControllerProtocol,
    live_enabled: bool,
    target_or_query: TargetSpec | str,
    cutout_size_arcsec: float,
    max_frames: int,
    output_dir: Path | None = None,
) -> BlinkBundleDTO:
    """Enforce kill switch, request limits, admission control, and bounded execution."""
    correlation_id = uuid.uuid4().hex[:12]

    if not live_enabled:
        raise _error_http_exception(
            status_code=503,
            code="live_queries_disabled",
            message="Live SPHEREx queries are currently disabled.",
            correlation_id=correlation_id,
        )

    try:
        limits.validate_request(cutout_size_arcsec, max_frames)
    except WorkLimitExceeded as exc:
        raise _error_http_exception(
            status_code=400,
            code=exc.code,
            message="Requested cutout size or exposure count exceeds public limits.",
            correlation_id=correlation_id,
        ) from exc

    try:
        with admission.admit():
            with bounded_ingestion(limits, max_frames):
                return service.ingest_target(
                    target_or_query=target_or_query,
                    cutout_size_arcsec=cutout_size_arcsec,
                    max_frames_per_collection=max_frames,
                    output_dir=output_dir,
                )
    except AdmissionDenied as exc:
        raise _error_http_exception(
            status_code=429,
            code="rate_limited",
            message="Ingestion queue is busy; please retry later.",
            correlation_id=correlation_id,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except WorkLimitExceeded as exc:
        logger.warning(
            "Ingestion work limit '%s' exceeded (correlation_id=%s)",
            exc.code,
            correlation_id,
        )
        if exc.code == "timeout":
            status_code = 504
            message = "Ingestion exceeded the allowed time budget."
        elif exc.code in {"request_limit", "grid_limit"}:
            status_code = 400
            message = "Requested cutout size or exposure count exceeds public limits."
        else:
            status_code = 422
            message = "Ingestion exceeded the allowed resource budget."
        raise _error_http_exception(
            status_code=status_code,
            code=exc.code,
            message=message,
            correlation_id=correlation_id,
        ) from exc
    except NoObservations as exc:
        raise _error_http_exception(
            status_code=404,
            code="no_observations",
            message="No SPHEREx observations were found for the requested target.",
            correlation_id=correlation_id,
        ) from exc
    except UpstreamUnavailable as exc:
        logger.exception("Upstream SPHEREx failure (correlation_id=%s)", correlation_id)
        raise _error_http_exception(
            status_code=502,
            code="upstream_unavailable",
            message="Upstream astronomy services are temporarily unavailable.",
            correlation_id=correlation_id,
        ) from exc
    except ValueError as exc:
        logger.warning("Invalid ingestion request (correlation_id=%s): %s", correlation_id, exc)
        raise _error_http_exception(
            status_code=400,
            code="invalid_request",
            message="Invalid target or coordinate query.",
            correlation_id=correlation_id,
        ) from exc
    except Exception as exc:
        logger.exception("Unhandled ingestion failure (correlation_id=%s)", correlation_id)
        raise _error_http_exception(
            status_code=502,
            code="internal_error",
            message="SPHEREx ingestion failed.",
            correlation_id=correlation_id,
        ) from exc


@app.get(
    "/api/v1/health",
    response_model=HealthResponseDTO,
    tags=["system"],
    summary="Health check and service metadata",
)
def health_check() -> HealthResponseDTO:
    """Verify service readiness, version, and CORS/mirror configuration."""
    return HealthResponseDTO()


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
    limits: LimitsDep,
    admission: AdmissionDep,
    live_enabled: LiveEnabledDep,
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
    ] = 12,
    force_refresh: Annotated[
        bool,
        Query(
            description="Bypass precomputed bundle on disk (requires maintenance authorization)",
        ),
    ] = False,
    x_maintenance_token: Annotated[
        str | None,
        Header(alias="X-Maintenance-Token"),
    ] = None,
) -> BlinkBundleDTO:
    """Return the complete `BlinkBundleDTO` for one of the benchmark targets.

    Serves directly from `output/{target_id}/bundle.json` in <50ms when precomputed
    on disk, or executes the bounded live pipeline on demand.
    """
    target = get_benchmark_target(target_id)
    if target is None:
        raise _error_http_exception(
            status_code=404,
            code="unknown_target",
            message=(
                f"Unknown benchmark target '{target_id}'. "
                f"Available targets: {', '.join(BENCHMARK_TARGETS.keys())}"
            ),
        )

    if force_refresh and not _is_maintenance_authorized(x_maintenance_token):
        raise _error_http_exception(
            status_code=403,
            code="refresh_forbidden",
            message="Public force_refresh is disabled.",
        )

    precomputed_path = output_dir / target.target_id / "bundle.json"
    if not force_refresh and precomputed_path.is_file():
        try:
            return BlinkBundleDTO.model_validate_json(
                precomputed_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            logger.warning(
                "Failed to load precomputed bundle at %s, falling back to live pipeline: %s",
                precomputed_path,
                exc,
            )

    return _run_bounded_live_ingestion(
        service=service,
        limits=limits,
        admission=admission,
        live_enabled=live_enabled,
        target_or_query=target,
        cutout_size_arcsec=size_arcsec,
        max_frames=max_frames,
        output_dir=output_dir,
    )


@app.get(
    "/api/v1/blink",
    response_model=BlinkBundleDTO,
    tags=["blink"],
    summary="Query arbitrary sky coordinates (RA/Dec) or resolve an object name",
)
def query_custom_blink_bundle(
    service: ServiceDep,
    limits: LimitsDep,
    admission: AdmissionDep,
    live_enabled: LiveEnabledDep,
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
    ] = 12,
) -> BlinkBundleDTO:
    """Execute the bounded SPHEREx ingestion pipeline for custom coordinates or an object name."""
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
        raise _error_http_exception(
            status_code=422,
            code="invalid_request",
            message=(
                "Provide either both 'ra' and 'dec' in degrees, or a non-empty 'query' parameter."
            ),
        )

    return _run_bounded_live_ingestion(
        service=service,
        limits=limits,
        admission=admission,
        live_enabled=live_enabled,
        target_or_query=target_input,
        cutout_size_arcsec=size_arcsec,
        max_frames=max_frames,
    )
