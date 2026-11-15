"""Application service orchestrating the SOLID SPHEREx Blink Comparator ingestion pipeline."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from spherex_ingest.domain.models import BlinkBundleDTO, TargetSpec
from spherex_ingest.domain.protocols import (
    AstrometricCatalogProtocol,
    BundleExporterProtocol,
    CutoutProviderProtocol,
    FrameProcessorProtocol,
)
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target

logger = logging.getLogger(__name__)


class NoObservations(ValueError):
    """The upstream search succeeded but found no observations for the target."""


class UpstreamUnavailable(RuntimeError):
    """The upstream search or downloads failed before returning any cutouts."""


class SPHERExBlinkIngestionService:
    """Orchestrates SPHEREx target resolution, cutout fetching, processing, and exporting.

    Follows the Dependency Inversion Principle (DIP): depends strictly on domain protocols
    injected through the constructor, enabling fast offline unit testing with fakes or mocks.
    """

    def __init__(
        self,
        cutout_provider: CutoutProviderProtocol,
        catalog_provider: AstrometricCatalogProtocol,
        frame_processor: FrameProcessorProtocol,
        bundle_exporter: BundleExporterProtocol,
    ) -> None:
        self.cutout_provider = cutout_provider
        self.catalog_provider = catalog_provider
        self.frame_processor = frame_processor
        self.bundle_exporter = bundle_exporter

    @classmethod
    def create_default(
        cls,
        cache_dir: Path = Path(".cache/fits"),
    ) -> SPHERExBlinkIngestionService:
        """Factory wiring the default production infrastructure, processor, and exporter."""
        from spherex_ingest.exporters import FrontendBundleExporter
        from spherex_ingest.infrastructure import (
            HarvardSimbadCatalogProvider,
            IRSASiaCutoutProvider,
        )
        from spherex_ingest.processors import SPHERExFrameProcessor

        return cls(
            cutout_provider=IRSASiaCutoutProvider(
                cache_dir=Path(cache_dir),
                cutout_workers=int(os.environ.get("SPHEREX_IRSA_CUTOUT_WORKERS", "3")),
                sia_cache_ttl_sec=int(os.environ.get("SPHEREX_SIA_CACHE_TTL_SECONDS", "3600")),
            ),
            catalog_provider=HarvardSimbadCatalogProvider(),
            frame_processor=SPHERExFrameProcessor(),
            bundle_exporter=FrontendBundleExporter(),
        )

    def list_benchmarks(self) -> list[TargetSpec]:
        """Return the 5 curated NASA Space Apps benchmark targets."""
        return list(BENCHMARK_TARGETS.values())

    def ingest_target(
        self,
        target_or_query: TargetSpec | str,
        cutout_size_arcsec: float = 180.0,
        max_frames_per_collection: int | None = 24,
        output_dir: Path | None = None,
    ) -> BlinkBundleDTO:
        """Run the complete SPHEREx ingestion and preprocessing pipeline for a target.

        Args:
            target_or_query: A `TargetSpec` instance, benchmark target ID, object name,
                or coordinate query string.
            cutout_size_arcsec: Angular cutout width/height in arcseconds (default: 180.0).
            max_frames_per_collection: Optional cap on cutouts fetched per SPHEREx collection.
            output_dir: Optional root directory where `{output_dir}/{target_id}/bundle.json`
                and rendered PNG assets will be written.

        Returns:
            Complete `BlinkBundleDTO` ready for the web frontend.
        """
        target = self.resolve_target(target_or_query, cutout_size_arcsec=cutout_size_arcsec)
        logger.info(
            "Starting SPHEREx ingestion for '%s' (id=%s, RA=%.6f, Dec=%.6f, size=%.1f\")",
            target.name,
            target.target_id,
            target.ra_deg,
            target.dec_deg,
            target.cutout_size_arcsec,
        )

        fetched = self.cutout_provider.fetch_cutouts(
            target=target,
            max_frames_per_collection=max_frames_per_collection,
        )
        if not fetched.frames:
            if any(
                dropped.reason in {"collection_query_error", "cutout_download_error"}
                for dropped in fetched.dropped_frames
            ):
                raise UpstreamUnavailable(
                    "SPHEREx retrieval failed before any cutouts could be processed."
                )
            raise NoObservations(
                f"No SPHEREx Level 2b cutouts found for target '{target.name}' "
                f"(RA={target.ra_deg:.5f}, Dec={target.dec_deg:.5f})."
            )

        processed_frames, common_wcs, grid_shape = self.frame_processor.process_frames(
            raw_frames=fetched.frames,
            target=target,
        )

        bundle = self.bundle_exporter.build_bundle(
            target=target,
            processed_frames=processed_frames,
            common_wcs=common_wcs,
            grid_shape=grid_shape,
            dropped_frames=fetched.dropped_frames,
        )

        if output_dir is not None:
            saved_path = self.bundle_exporter.save_bundle(bundle, Path(output_dir))
            logger.info("Saved SPHEREx blink bundle to %s", saved_path)

        return bundle

    def resolve_target(
        self,
        target_or_query: TargetSpec | str,
        cutout_size_arcsec: float,
    ) -> TargetSpec:
        """Resolve a `TargetSpec` or string query into a normalized `TargetSpec`."""
        if isinstance(target_or_query, TargetSpec):
            if target_or_query.cutout_size_arcsec != cutout_size_arcsec:
                return target_or_query.model_copy(update={"cutout_size_arcsec": cutout_size_arcsec})
            return target_or_query

        query_str = target_or_query.strip()
        if not query_str:
            raise ValueError("Target query string cannot be empty.")

        benchmark = get_benchmark_target(query_str)
        if benchmark is not None:
            if benchmark.cutout_size_arcsec != cutout_size_arcsec:
                return benchmark.model_copy(update={"cutout_size_arcsec": cutout_size_arcsec})
            return benchmark

        return self.catalog_provider.resolve_target(
            name_or_coord=query_str,
            cutout_size_arcsec=cutout_size_arcsec,
        )
