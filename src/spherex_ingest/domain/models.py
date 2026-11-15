"""Domain models, value objects, and data structures for the SPHEREx ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntFlag
from typing import Any

import numpy as np
from astropy.wcs import WCS
from pydantic import BaseModel, ConfigDict, Field

BUNDLE_SCHEMA_VERSION = "1.0.0"


class SPHERExFlagBits(IntFlag):
    """Bitmask definitions for the SPHEREx Level 2b FLAGS extension.

    Reference:
        SPHEREx Explanatory Supplement & Akeson et al. (2026), ApJS, 285, 67, Section 4.2b.
    """

    TRANSIENT = 1 << 0          # Cosmic ray / energetic particle jump detected on board
    OVERFLOW = 1 << 1           # Pixel reached saturation / overflow threshold in SUR
    SUR_ERROR = 1 << 2          # Sample-up-the-ramp processing error
    NONFUNC = 1 << 6            # Permanently nonfunctional / dead pixel
    DICHROIC = 1 << 7           # >= 50% flux attenuation from dichroic beam splitter edge
    MISSING_DATA = 1 << 9       # Telemetry packet missing in exposure
    HOT = 1 << 10               # Abnormally high dark current pixel
    COLD = 1 << 11              # Abnormally low responsivity pixel
    FULLSAMPLE = 1 << 12        # Full sample history available (informational)
    PHANMISS = 1 << 14          # Phantom drift correction not applied
    NONLINEAR = 1 << 15         # Nonlinear regime (saturation warning)
    PERSIST = 1 << 17           # Significant persistent charge from prior bright exposure
    OUTLIER = 1 << 19           # Ground pipeline sigma-clipped transient outlier
    CROSSTALK = 1 << 20         # Electronic crosstalk
    SOURCE = 1 << 21            # Reference catalogue source (informational)
    GHOST = 1 << 22             # Internal optical ghost
    GHOST_FPA = 1 << 23         # Inter-detector ghost
    GHOST_EXT = 1 << 24         # Out-of-FOV optical ghost
    STREAK = 1 << 25            # Satellite / asteroid streak
    BLOOM = 1 << 26             # Saturated star charge bloom
    SNOWBALL = 1 << 27          # Large energetic cosmic ray hit
    HALO = 1 << 28              # Transient / bloom halo

    # Compatibility aliases
    HOT_PIXEL = HOT
    COLD_PIXEL = COLD
    PERSISTENCE = PERSIST
    SOURCE_MASK = SOURCE

    @classmethod
    def bad_artifact_mask(cls) -> int:
        """Bitmask of artifacts that corrupt pixel validity (excluding saturation/source masks)."""
        return int(
            cls.TRANSIENT
            | cls.SUR_ERROR
            | cls.NONFUNC
            | cls.MISSING_DATA
            | cls.HOT
            | cls.COLD
            | cls.PERSIST
            | cls.OUTLIER
            | cls.SNOWBALL
        )

    @classmethod
    def saturation_mask(cls) -> int:
        """Bitmask indicating detector saturation / nonlinear overflow."""
        return int(cls.OVERFLOW | cls.NONLINEAR | cls.BLOOM)


class TargetSpec(BaseModel):
    """Astrometric and query specification for an astronomical target."""

    model_config = ConfigDict(frozen=True)

    target_id: str = Field(
        ..., description="Slug identifier for the target (e.g., 'barnards_star')"
    )
    name: str = Field(..., description="Human-readable name of the target")
    category: str = Field(
        default="custom",
        description=(
            "Scientific category ('high_proper_motion', 'brown_dwarf', "
            "'variable_star', 'custom')"
        ),
    )
    ra_deg: float = Field(..., ge=0.0, lt=360.0, description="Right Ascension in degrees (ICRS)")
    dec_deg: float = Field(..., ge=-90.0, le=90.0, description="Declination in degrees (ICRS)")
    ref_epoch_jyear: float = Field(
        default=2016.0,
        description=(
            "Reference epoch in Julian years for the catalog RA/Dec "
            "(Gaia DR3 = 2016.0, J2000 = 2000.0)"
        ),
    )
    pm_ra_cosdec_mas_yr: float = Field(
        default=0.0,
        description="Proper motion in RA (mu_alpha * cos(dec)) in milliarcseconds per year",
    )
    pm_dec_mas_yr: float = Field(
        default=0.0,
        description="Proper motion in Dec (mu_delta) in milliarcseconds per year",
    )
    parallax_mas: float = Field(
        default=0.0,
        ge=0.0,
        description="Trigonometric parallax in milliarcseconds",
    )
    radial_velocity_km_s: float = Field(
        default=0.0,
        description="Radial velocity in km/s",
    )
    cutout_size_arcsec: float = Field(
        default=180.0,
        gt=12.0,
        le=1800.0,
        description="Angular side length of the square cutout in arcseconds",
    )
    collections: tuple[str, ...] = Field(
        default=("spherex_dr1", "spherex_qr3"),
        description="IRSA SPHEREx SIAv2 collections to query (never use qr2)",
    )
    priority_bands: tuple[int, ...] = Field(
        default=(),
        description="Preferred detector bands to prioritize when slicing under frame limits",
    )
    notes: str = Field(
        default="",
        description="Scientific and data handling notes for this object",
    )


@dataclass(frozen=True)
class RawCutoutFrame:
    """In-memory representation of a single SPHEREx Level 2b Multi-Extension FITS cutout."""

    frame_id: str
    collection: str
    detector_band: int
    mjd_avg: float
    obs_time_iso: str
    sps_epa_deg: float
    finast_flag: int
    image_mjy_sr: np.ndarray
    flags_bitmask: np.ndarray
    variance_mjy2_sr2: np.ndarray
    zodi_mjy_sr: np.ndarray
    spatial_wcs: WCS
    wavelength_um_at_target: float
    bandwidth_um_at_target: float
    wavelength_map_um: np.ndarray | None = None
    bandwidth_map_um: np.ndarray | None = None
    source_url: str = ""
    raw_header_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProcessedBlinkFrame:
    """Processed, Zodi-subtracted, North-up reprojected SPHEREx frame ready for blinking."""

    frame_id: str
    collection: str
    detector_band: int
    mjd_avg: float
    obs_time_iso: str
    sps_epa_deg: float
    wavelength_um: float
    bandwidth_um: float
    reprojected_image_mjy_sr: np.ndarray
    reprojected_variance: np.ndarray
    reprojected_zodi_mjy_sr: np.ndarray
    saturation_mask: np.ndarray
    bad_pixel_mask: np.ndarray
    footprint_mask: np.ndarray
    predicted_ra_deg: float
    predicted_dec_deg: float
    predicted_pixel_x: float
    predicted_pixel_y: float
    measured_centroid_x: float | None = None
    measured_centroid_y: float | None = None
    measured_ra_deg: float | None = None
    measured_dec_deg: float | None = None
    centroid_offset_arcsec: float | None = None
    aperture_flux_ujy: float | None = None
    aperture_flux_err_ujy: float | None = None
    snr: float | None = None
    is_saturated_core: bool = False
    repaired_image_mjy_sr: np.ndarray | None = None
    png_base64: str | None = None
    source_url: str = ""


class FrameMetadataDTO(BaseModel):
    """Serializable metadata and image payload for a single blink frame."""

    frame_id: str
    collection: str
    detector_band: int
    mjd_avg: float
    obs_time_iso: str
    sps_epa_deg: float
    wavelength_um: float
    bandwidth_um: float
    predicted_ra_deg: float
    predicted_dec_deg: float
    predicted_pixel_x: float
    predicted_pixel_y: float
    measured_centroid_x: float | None = None
    measured_centroid_y: float | None = None
    measured_ra_deg: float | None = None
    measured_dec_deg: float | None = None
    centroid_offset_arcsec: float | None = None
    aperture_flux_ujy: float | None = None
    aperture_flux_err_ujy: float | None = None
    snr: float | None = None
    is_saturated_core: bool = False
    saturated_pixel_count: int = 0
    bad_artifact_pixel_count: int = 0
    valid_pixel_fraction: float = 1.0
    matrix_mjy_sr: list[list[float | None]]
    saturation_mask: list[list[bool]]
    bad_pixel_mask: list[list[bool]]
    png_base64: str | None = None
    source_url: str = ""


class DifferenceMapDTO(BaseModel):
    """Difference image (I_t2 - I_t1) within the same spectral band to highlight changes."""

    detector_band: int
    frame_id_early: str
    frame_id_late: str
    mjd_early: float
    mjd_late: float
    baseline_days: float
    mean_wavelength_um: float
    early_wavelength_um: float = 0.0
    late_wavelength_um: float = 0.0
    delta_wavelength_um: float = 0.0
    diff_matrix_mjy_sr: list[list[float | None]]
    png_base64: str | None = None


class DroppedFrameDTO(BaseModel):
    """Record of a frame dropped during cutout retrieval or quality filtering."""

    frame_id: str
    reason: str
    attempted_band: int | None = None
    obs_date: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class CutoutFetchResult:
    """The frames and retrieval diagnostics from one ingestion request."""

    frames: tuple[RawCutoutFrame, ...]
    dropped_frames: tuple[DroppedFrameDTO, ...] = ()


class CommonGridSpecDTO(BaseModel):
    """Metadata describing the common North-up celestial grid shared by all frames in a bundle."""

    center_ra_deg: float
    center_dec_deg: float
    pixel_scale_arcsec: float
    width_px: int
    height_px: int
    orientation: str = "North-up, East-left (ICRS TAN)"


class BlinkBundleDTO(BaseModel):
    """Complete frontend-ready data bundle for a target across all SPHEREx passes and bands."""

    schema_version: str = BUNDLE_SCHEMA_VERSION
    target: TargetSpec
    propagated_current_ra_deg: float
    propagated_current_dec_deg: float
    grid: CommonGridSpecDTO
    total_frames: int
    available_bands: list[int]
    frames_chronological: list[FrameMetadataDTO]
    frames_by_band: dict[str, list[FrameMetadataDTO]]
    difference_maps: list[DifferenceMapDTO]
    dropped_frames: list[DroppedFrameDTO] = Field(default_factory=list)
    scientific_warnings: list[str]
    citations: list[str]
