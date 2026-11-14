"""End-to-end frame processing orchestrator implementing FrameProcessorProtocol."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from astropy.wcs import WCS

from spherex_ingest.domain.models import ProcessedBlinkFrame, RawCutoutFrame, TargetSpec
from spherex_ingest.processors.cleaners import ZodiAndFlagCleaner
from spherex_ingest.processors.kinematics import KinematicsAndPhotometryAnalyzer
from spherex_ingest.processors.reprojector import NorthUpCommonReprojector


class SPHERExFrameProcessor:
    """Orchestrates Zodi subtraction, North-up reprojection, and kinematic centroiding."""

    def __init__(
        self,
        cleaner: ZodiAndFlagCleaner | None = None,
        reprojector: NorthUpCommonReprojector | None = None,
        analyzer: KinematicsAndPhotometryAnalyzer | None = None,
        pixel_scale_arcsec: float = 6.15,
    ) -> None:
        self._pixel_scale_arcsec = pixel_scale_arcsec
        self._cleaner = cleaner or ZodiAndFlagCleaner()
        self._reprojector = reprojector or NorthUpCommonReprojector(
            default_pixel_scale_arcsec=pixel_scale_arcsec
        )
        self._analyzer = analyzer or KinematicsAndPhotometryAnalyzer(
            pixel_scale_arcsec=pixel_scale_arcsec
        )

    def process_frames(
        self,
        raw_frames: Sequence[RawCutoutFrame],
        target: TargetSpec,
    ) -> tuple[list[ProcessedBlinkFrame], WCS, tuple[int, int]]:
        """Clean, reproject onto a common North-up WCS grid, and measure kinematics/photometry."""
        sorted_raw = sorted(raw_frames, key=lambda f: (f.mjd_avg, f.detector_band, f.frame_id))
        if sorted_raw:
            mean_mjd = float(np.mean([f.mjd_avg for f in sorted_raw]))
        else:
            mean_mjd = 60900.0  # ~2025.62 fallback epoch

        center_ra, center_dec = self._analyzer.propagate_position(target, mean_mjd)
        common_wcs, grid_shape = self._reprojector.build_common_wcs(
            center_ra_deg=center_ra,
            center_dec_deg=center_dec,
            cutout_size_arcsec=target.cutout_size_arcsec,
            pixel_scale_arcsec=self._pixel_scale_arcsec,
        )

        processed_frames: list[ProcessedBlinkFrame] = []
        for raw in sorted_raw:
            cleaned = self._cleaner.clean(raw)
            reproj = self._reprojector.reproject_frame(
                cleaned=cleaned,
                input_wcs=raw.spatial_wcs,
                variance_mjy2_sr2=raw.variance_mjy2_sr2,
                zodi_mjy_sr=raw.zodi_mjy_sr,
                common_wcs=common_wcs,
                shape_out=grid_shape,
            )
            kin = self._analyzer.measure_centroid_and_photometry(
                target=target,
                mjd=raw.mjd_avg,
                reprojected=reproj,
                common_wcs=common_wcs,
            )

            processed_frames.append(
                ProcessedBlinkFrame(
                    frame_id=raw.frame_id,
                    collection=raw.collection,
                    detector_band=raw.detector_band,
                    mjd_avg=raw.mjd_avg,
                    obs_time_iso=raw.obs_time_iso,
                    sps_epa_deg=raw.sps_epa_deg,
                    wavelength_um=raw.wavelength_um_at_target,
                    bandwidth_um=raw.bandwidth_um_at_target,
                    reprojected_image_mjy_sr=reproj.reprojected_image_mjy_sr,
                    reprojected_variance=reproj.reprojected_variance,
                    reprojected_zodi_mjy_sr=reproj.reprojected_zodi_mjy_sr,
                    saturation_mask=reproj.saturation_mask,
                    bad_pixel_mask=reproj.bad_pixel_mask,
                    footprint_mask=reproj.footprint_mask,
                    predicted_ra_deg=kin.predicted_ra_deg,
                    predicted_dec_deg=kin.predicted_dec_deg,
                    predicted_pixel_x=kin.predicted_pixel_x,
                    predicted_pixel_y=kin.predicted_pixel_y,
                    measured_centroid_x=kin.measured_centroid_x,
                    measured_centroid_y=kin.measured_centroid_y,
                    measured_ra_deg=kin.measured_ra_deg,
                    measured_dec_deg=kin.measured_dec_deg,
                    centroid_offset_arcsec=kin.centroid_offset_arcsec,
                    aperture_flux_ujy=kin.aperture_flux_ujy,
                    aperture_flux_err_ujy=kin.aperture_flux_err_ujy,
                    snr=kin.snr,
                    is_saturated_core=kin.is_saturated_core,
                    repaired_image_mjy_sr=reproj.repaired_image_mjy_sr,
                    png_base64=None,
                    source_url=raw.source_url,
                )
            )

        return processed_frames, common_wcs, grid_shape
