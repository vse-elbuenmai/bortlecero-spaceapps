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

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from spherex_ingest import __version__
from spherex_ingest.domain.models import BUNDLE_SCHEMA_VERSION, BlinkBundleDTO, TargetSpec
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target
from spherex_ingest.result_storage import ResultKey, get_result_store
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
    cds_mirror_active: bool = Field(
        default=True,
        description=(
            "Whether Harvard CFA Sesame/VizieR mirrors are used to bypass CDS Strasbourg outage"
        ),
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


ServiceDep = Annotated[SPHERExBlinkIngestionService, Depends(get_default_service)]
OutputDirDep = Annotated[Path, Depends(get_output_dir)]


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
