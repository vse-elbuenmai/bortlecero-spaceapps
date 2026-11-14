"""Image cleaning, WCS reprojection, and astrometric/photometric processors for SPHEREx cutouts."""

from spherex_ingest.processors.cleaners import CleanedFrameResult, ZodiAndFlagCleaner
from spherex_ingest.processors.kinematics import (
    KinematicsAndPhotometryAnalyzer,
    KinematicsPhotometryResult,
)
from spherex_ingest.processors.pipeline_processor import SPHERExFrameProcessor
from spherex_ingest.processors.reprojector import (
    NorthUpCommonReprojector,
    ReprojectedFrameResult,
)

__all__ = [
    "CleanedFrameResult",
    "KinematicsAndPhotometryAnalyzer",
    "KinematicsPhotometryResult",
    "NorthUpCommonReprojector",
    "ReprojectedFrameResult",
    "SPHERExFrameProcessor",
    "ZodiAndFlagCleaner",
]
