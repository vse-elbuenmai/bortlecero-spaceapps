"""Domain package for SPHEREx data ingestion."""

from spherex_ingest.domain.models import (
    BlinkBundleDTO,
    CommonGridSpecDTO,
    DifferenceMapDTO,
    FrameMetadataDTO,
    ProcessedBlinkFrame,
    RawCutoutFrame,
    SPHERExFlagBits,
    TargetSpec,
)
from spherex_ingest.domain.protocols import (
    AstrometricCatalogProtocol,
    BundleExporterProtocol,
    CutoutProviderProtocol,
    FrameProcessorProtocol,
)
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target

__all__ = [
    "AstrometricCatalogProtocol",
    "BENCHMARK_TARGETS",
    "BlinkBundleDTO",
    "BundleExporterProtocol",
    "CommonGridSpecDTO",
    "CutoutProviderProtocol",
    "DifferenceMapDTO",
    "FrameMetadataDTO",
    "FrameProcessorProtocol",
    "ProcessedBlinkFrame",
    "RawCutoutFrame",
    "SPHERExFlagBits",
    "TargetSpec",
    "get_benchmark_target",
]
