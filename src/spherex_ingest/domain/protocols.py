"""SOLID Protocol interfaces (DIP & ISP) for SPHEREx data ingestion."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from astropy.wcs import WCS

from spherex_ingest.domain.models import (
    BlinkBundleDTO,
    DroppedFrameDTO,
    ProcessedBlinkFrame,
    RawCutoutFrame,
    TargetSpec,
)


@runtime_checkable
class CutoutProviderProtocol(Protocol):
    """Interface for discovering and fetching SPHEREx Level 2b Multi-Extension FITS cutouts."""

    def fetch_cutouts(
        self,
        target: TargetSpec,
        max_frames_per_collection: int | None = None,
    ) -> list[RawCutoutFrame]:
        """Discover and retrieve raw SPHEREx Level 2b cutouts covering the target coordinates."""
        ...


@runtime_checkable
class AstrometricCatalogProtocol(Protocol):
    """Interface for resolving target names and retrieving proper motion / parallax metadata."""

    def resolve_target(
        self,
        name_or_coord: str,
        cutout_size_arcsec: float = 180.0,
    ) -> TargetSpec:
        """Resolve an astronomical object name or coordinate string into a full TargetSpec."""
        ...


@runtime_checkable
class FrameProcessorProtocol(Protocol):
    """Interface for transforming raw cutouts into reprojected, Zodi-cleaned blink frames."""

    def process_frames(
        self,
        raw_frames: Sequence[RawCutoutFrame],
        target: TargetSpec,
    ) -> tuple[list[ProcessedBlinkFrame], WCS, tuple[int, int]]:
        """Clean, reproject onto a common North-up WCS grid, and measure kinematics/photometry."""
        ...


@runtime_checkable
class BundleExporterProtocol(Protocol):
    """Interface for serializing processed blink frames into a frontend-ready bundle."""

    def build_bundle(
        self,
        target: TargetSpec,
        processed_frames: Sequence[ProcessedBlinkFrame],
        common_wcs: WCS,
        grid_shape: tuple[int, int],
        dropped_frames: Sequence[DroppedFrameDTO] = (),
    ) -> BlinkBundleDTO:
        """Assemble the complete BlinkBundleDTO including difference maps and warnings."""
        ...

    def save_bundle(
        self,
        bundle: BlinkBundleDTO,
        output_dir: Path,
    ) -> Path:
        """Write the bundle JSON and accompanying image assets to disk."""
        ...
