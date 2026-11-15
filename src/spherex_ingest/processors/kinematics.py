"""Epoch propagation (proper motion + parallax), sub-pixel centroiding, and aperture photometry."""

from __future__ import annotations

from dataclasses import dataclass

import astropy.units as u
import numpy as np
from astropy.coordinates import Distance, SkyCoord, get_body_barycentric
from astropy.time import Time
from astropy.wcs import WCS
from photutils.aperture import CircularAperture, aperture_photometry
from photutils.centroids import centroid_com

from spherex_ingest.domain.models import TargetSpec
from spherex_ingest.processors.reprojector import ReprojectedFrameResult

ARCSEC_PER_RADIAN = 206264.80624709636
MJY_TO_UJY = 1e12


@dataclass(frozen=True)
class KinematicsPhotometryResult:
    """Astrometric and photometric measurement for a single reprojected frame."""

    predicted_ra_deg: float
    predicted_dec_deg: float
    predicted_pixel_x: float
    predicted_pixel_y: float
    measured_centroid_x: float | None
    measured_centroid_y: float | None
    measured_ra_deg: float | None
    measured_dec_deg: float | None
    centroid_offset_arcsec: float | None
    aperture_flux_ujy: float | None
    aperture_flux_err_ujy: float | None
    snr: float | None
    is_saturated_core: bool


class KinematicsAndPhotometryAnalyzer:
    """Propagates catalog astrometry to observation epoch and measures centroids and flux."""

    def __init__(
        self,
        stamp_half_size_px: int = 3,
        aperture_radius_px: float = 2.0,
        detection_sigma: float = 3.5,
        pixel_scale_arcsec: float = 6.15,
    ) -> None:
        self._stamp_half_size_px = stamp_half_size_px
        self._aperture_radius_px = aperture_radius_px
        self._detection_sigma = detection_sigma
        self._pixel_scale_arcsec = pixel_scale_arcsec

    def propagate_position(self, target: TargetSpec, mjd: float) -> tuple[float, float]:
        """Propagate catalog coordinates to epoch MJD using proper motion and annual parallax."""
        has_pm = (abs(target.pm_ra_cosdec_mas_yr) > 1e-6) or (abs(target.pm_dec_mas_yr) > 1e-6)
        has_plx = target.parallax_mas > 1e-4
        if not has_pm and not has_plx:
            return float(target.ra_deg), float(target.dec_deg)

        ref_time = Time(target.ref_epoch_jyear, format="jyear", scale="tcb")
        obs_time = Time(mjd, format="mjd", scale="utc")

        distance = (
            Distance(parallax=target.parallax_mas * u.mas)
            if target.parallax_mas > 0.0
            else None
        )
        coord = SkyCoord(
            ra=target.ra_deg * u.deg,
            dec=target.dec_deg * u.deg,
            pm_ra_cosdec=target.pm_ra_cosdec_mas_yr * u.mas / u.yr,
            pm_dec=target.pm_dec_mas_yr * u.mas / u.yr,
            distance=distance,
            radial_velocity=target.radial_velocity_km_s * u.km / u.s,
            obstime=ref_time,
            frame="icrs",
        )
        bary = coord.apply_space_motion(new_obstime=obs_time)
        if distance is not None:
            earth_pos = get_body_barycentric("earth", obs_time)
            # Reflex displacement: vector from Earth to star = star barycentric - Earth barycentric
            geo_cart = bary.cartesian.xyz - earth_pos.xyz
            geo_coord = SkyCoord(
                geo_cart[0],
                geo_cart[1],
                geo_cart[2],
                representation_type="cartesian",
                frame="icrs",
            ).represent_as("spherical")
            return float(geo_coord.lon.deg), float(geo_coord.lat.deg)

        return float(bary.ra.deg), float(bary.dec.deg)

    def measure_centroid_and_photometry(
        self,
        target: TargetSpec,
        mjd: float,
        reprojected: ReprojectedFrameResult,
        common_wcs: WCS,
    ) -> KinematicsPhotometryResult:
        """Compute predicted pixel coords, sub-pixel PSF/halo centroid, and aperture flux."""
        pred_ra, pred_dec = self.propagate_position(target, mjd)
        pred_x_arr, pred_y_arr = common_wcs.world_to_pixel_values(pred_ra, pred_dec)
        pred_x = float(pred_x_arr)
        pred_y = float(pred_y_arr)

        ny, nx = reprojected.reprojected_image_mjy_sr.shape
        cx_i = int(np.round(pred_x))
        cy_i = int(np.round(pred_y))
        r = self._stamp_half_size_px
        y0, y1 = max(0, cy_i - r), min(ny, cy_i + r + 1)
        x0, x1 = max(0, cx_i - r), min(nx, cx_i + r + 1)

        if y1 <= y0 or x1 <= x0:
            return KinematicsPhotometryResult(
                predicted_ra_deg=pred_ra,
                predicted_dec_deg=pred_dec,
                predicted_pixel_x=pred_x,
                predicted_pixel_y=pred_y,
                measured_centroid_x=None,
                measured_centroid_y=None,
                measured_ra_deg=None,
                measured_dec_deg=None,
                centroid_offset_arcsec=None,
                aperture_flux_ujy=None,
                aperture_flux_err_ujy=None,
                snr=None,
                is_saturated_core=False,
            )

        sat_stamp = reprojected.saturation_mask[y0:y1, x0:x1]
        clean_stamp = reprojected.reprojected_image_mjy_sr[y0:y1, x0:x1]

        # Only flag core saturation if saturation/NaN falls within stellar core radius (<1.5 px)
        yy, xx = np.mgrid[y0:y1, x0:x1]
        dist_to_pred = np.hypot(xx - pred_x, yy - pred_y)
        core_region = dist_to_pred < 1.5
        is_saturated_core = bool(
            np.any(sat_stamp[core_region]) or np.any(~np.isfinite(clean_stamp[core_region]))
        )

        working_img = (
            reprojected.repaired_image_mjy_sr
            if is_saturated_core
            else reprojected.reprojected_image_mjy_sr
        )
        stamp = np.array(working_img[y0:y1, x0:x1], dtype=np.float64, copy=True)
        var_stamp = np.array(reprojected.reprojected_variance[y0:y1, x0:x1], dtype=np.float64)

        finite_all = np.isfinite(working_img) & (~reprojected.bad_pixel_mask)
        var_finite = reprojected.reprojected_variance[
            np.isfinite(reprojected.reprojected_variance)
            & (reprojected.reprojected_variance > 0.0)
        ]
        var_sigma = (
            float(np.sqrt(np.nanmedian(var_finite))) if var_finite.size > 0 else 0.0
        )

        if np.any(finite_all):
            bg_med = float(np.nanmedian(working_img[finite_all]))
            bg_mad = float(np.nanmedian(np.abs(working_img[finite_all] - bg_med)))
            noise_sigma = max(1.4826 * bg_mad, var_sigma, 0.1)
        else:
            bg_med = 0.0
            noise_sigma = max(var_sigma, 1.0)

        stamp_sub = np.nan_to_num(stamp - bg_med, nan=0.0)
        stamp_positive = np.clip(stamp_sub, a_min=0.0, a_max=None)
        peak_val = float(np.max(stamp_positive)) if stamp_positive.size > 0 else 0.0

        measured_x: float | None = None
        measured_y: float | None = None
        measured_ra: float | None = None
        measured_dec: float | None = None
        offset_arcsec: float | None = None

        if peak_val >= self._detection_sigma * noise_sigma and np.sum(stamp_positive) > 0.0:
            local_peak_y, local_peak_x = np.unravel_index(
                np.argmax(stamp_positive), stamp_positive.shape
            )
            peak_x = float(x0 + local_peak_x)
            peak_y = float(y0 + local_peak_y)
            peak_dist_px = float(np.hypot(peak_x - pred_x, peak_y - pred_y))

            local_cx, local_cy = centroid_com(stamp_positive)
            if np.isfinite(local_cx) and np.isfinite(local_cy):
                candidate_x = float(x0 + local_cx)
                candidate_y = float(y0 + local_cy)
                cand_dist_px = float(np.hypot(candidate_x - pred_x, candidate_y - pred_y))

                ra_val, dec_val = common_wcs.pixel_to_world_values(candidate_x, candidate_y)
                cand_ra = float(ra_val)
                cand_dec = float(dec_val)
                pred_coord = SkyCoord(ra=pred_ra * u.deg, dec=pred_dec * u.deg, frame="icrs")
                meas_coord = SkyCoord(
                    ra=cand_ra * u.deg,
                    dec=cand_dec * u.deg,
                    frame="icrs",
                )
                cand_offset_arcsec = float(pred_coord.separation(meas_coord).arcsec)

                max_offset_px = 2.0
                max_offset_arcsec = 15.0
                if (
                    peak_dist_px <= max_offset_px
                    and cand_dist_px <= max_offset_px
                    and cand_offset_arcsec < max_offset_arcsec
                ):
                    measured_x = candidate_x
                    measured_y = candidate_y
                    measured_ra = cand_ra
                    measured_dec = cand_dec
                    offset_arcsec = cand_offset_arcsec

        ap_center_x = measured_x if measured_x is not None else pred_x
        ap_center_y = measured_y if measured_y is not None else pred_y

        aperture_flux_ujy: float | None = None
        aperture_flux_err_ujy: float | None = None
        snr_val: float | None = None

        if 0.0 <= ap_center_x < nx and 0.0 <= ap_center_y < ny:
            omega_pix_sr = (self._pixel_scale_arcsec / ARCSEC_PER_RADIAN) ** 2
            scale_factor = omega_pix_sr * MJY_TO_UJY

            ap = CircularAperture((ap_center_x, ap_center_y), r=self._aperture_radius_px)
            data_sub = np.nan_to_num(working_img - bg_med, nan=0.0)
            var_clean = np.nan_to_num(reprojected.reprojected_variance, nan=0.0)
            err_arr = np.sqrt(np.clip(var_clean, 0.0, None))
            if np.all(err_arr == 0.0) and np.any(np.isfinite(var_stamp)):
                err_arr = np.full_like(data_sub, noise_sigma)

            phot_table = aperture_photometry(data_sub, ap, error=err_arr)
            raw_sum = float(phot_table["aperture_sum"][0])
            raw_err = float(phot_table["aperture_sum_err"][0])

            # Enforce noise floor to prevent division-by-zero or unrealistic SNR spikes
            npix = float(getattr(ap, "area", np.pi * (self._aperture_radius_px**2)))
            noise_floor_err = float(noise_sigma * np.sqrt(max(1.0, npix)))
            if not np.isfinite(raw_err) or raw_err < noise_floor_err:
                raw_err = noise_floor_err

            if np.isfinite(raw_sum):
                aperture_flux_ujy = raw_sum * scale_factor
                if np.isfinite(raw_err) and raw_err > 0.0:
                    aperture_flux_err_ujy = raw_err * scale_factor
                    raw_snr = float(raw_sum / raw_err)
                    snr_val = float(min(max(raw_snr, -99999.0), 99999.0))

        return KinematicsPhotometryResult(
            predicted_ra_deg=pred_ra,
            predicted_dec_deg=pred_dec,
            predicted_pixel_x=pred_x,
            predicted_pixel_y=pred_y,
            measured_centroid_x=measured_x,
            measured_centroid_y=measured_y,
            measured_ra_deg=measured_ra,
            measured_dec_deg=measured_dec,
            centroid_offset_arcsec=offset_arcsec,
            aperture_flux_ujy=aperture_flux_ujy,
            aperture_flux_err_ujy=aperture_flux_err_ujy,
            snr=snr_val,
            is_saturated_core=is_saturated_core,
        )
