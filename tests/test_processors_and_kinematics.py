"""Tests for ZodiAndFlagCleaner, NorthUpCommonReprojector, and KinematicsAndPhotometryAnalyzer."""

from __future__ import annotations

from collections.abc import Callable

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from photutils.centroids import centroid_com

from spherex_ingest.domain.models import RawCutoutFrame, TargetSpec
from spherex_ingest.domain.targets import BENCHMARK_TARGETS
from spherex_ingest.processors.cleaners import ZodiAndFlagCleaner
from spherex_ingest.processors.kinematics import KinematicsAndPhotometryAnalyzer
from spherex_ingest.processors.reprojector import NorthUpCommonReprojector


def test_zodi_and_flag_cleaner_subtracts_zodi_and_repairs_saturated_core(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify Zodi subtraction, cosmic ray interpolation, and saturated NaN core repair."""
    raw = raw_cutout_factory(
        frame_id="sat_test",
        zodi_level_mjy_sr=50.0,
        peak_flux_mjy_sr=400.0,
        saturate_core=True,
        transient_pixel=(4, 4),
    )
    cleaner = ZodiAndFlagCleaner(subtract_residual_bg=True)
    result = cleaner.clean(raw)

    # 1. Transient pixel at (4, 4) had value 9999.0; interpolated value should be near background
    assert result.bad_pixel_mask[4, 4]
    assert abs(result.clean_image_mjy_sr[4, 4]) < 15.0

    # 2. Saturated core was NaN in raw image; saturation_mask flags it and repaired_image is finite
    assert np.any(result.saturation_mask)
    assert np.all(np.isfinite(result.repaired_image_mjy_sr))
    sat_peak = float(np.max(result.repaired_image_mjy_sr[result.saturation_mask]))
    assert sat_peak > 50.0


def test_north_up_reprojector_eliminates_180_degree_roll_flip(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify two exposures with SPS_EPA=0 and SPS_EPA=180 align to < 0.1 px after reprojection."""
    center_ra = 331.07645
    center_dec = -56.79382
    # Place stationary test star slightly off-center in sky coordinates
    star_ra = center_ra + 0.004
    star_dec = center_dec - 0.003

    raw_pass1 = raw_cutout_factory(
        frame_id="pass1_epa0",
        center_ra_deg=center_ra,
        center_dec_deg=center_dec,
        star_ra_deg=star_ra,
        star_dec_deg=star_dec,
        sps_epa_deg=0.0,
        transient_pixel=None,
    )
    raw_pass2 = raw_cutout_factory(
        frame_id="pass2_epa180",
        center_ra_deg=center_ra,
        center_dec_deg=center_dec,
        star_ra_deg=star_ra,
        star_dec_deg=star_dec,
        sps_epa_deg=180.0,
        transient_pixel=None,
    )

    # Before reprojection, the star lands on completely different detector pixels (> 4 px apart)
    raw_x1, raw_y1 = centroid_com(np.clip(raw_pass1.image_mjy_sr - raw_pass1.zodi_mjy_sr, 0, None))
    raw_x2, raw_y2 = centroid_com(np.clip(raw_pass2.image_mjy_sr - raw_pass2.zodi_mjy_sr, 0, None))
    raw_pixel_jump = float(np.hypot(raw_x2 - raw_x1, raw_y2 - raw_y1))
    assert raw_pixel_jump > 4.0

    cleaner = ZodiAndFlagCleaner()
    reprojector = NorthUpCommonReprojector(default_pixel_scale_arcsec=6.15)
    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=center_ra,
        center_dec_deg=center_dec,
        cutout_size_arcsec=180.0,
    )

    reproj1 = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw_pass1),
        input_wcs=raw_pass1.spatial_wcs,
        variance_mjy2_sr2=raw_pass1.variance_mjy2_sr2,
        zodi_mjy_sr=raw_pass1.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )
    reproj2 = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw_pass2),
        input_wcs=raw_pass2.spatial_wcs,
        variance_mjy2_sr2=raw_pass2.variance_mjy2_sr2,
        zodi_mjy_sr=raw_pass2.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )

    cx1, cy1 = centroid_com(
        np.clip(np.nan_to_num(reproj1.reprojected_image_mjy_sr, nan=0.0), 0, None)
    )
    cx2, cy2 = centroid_com(
        np.clip(np.nan_to_num(reproj2.reprojected_image_mjy_sr, nan=0.0), 0, None)
    )
    reprojected_offset_px = float(np.hypot(cx2 - cx1, cy2 - cy1))
    assert reprojected_offset_px < 0.1


def test_kinematics_barnards_star_gaia_dr3_propagation() -> None:
    """Verify Barnard's Star moves ~10.39 arcsec/yr (~1.69 SPHEREx px/yr) matching Gaia DR3."""
    barnard = BENCHMARK_TARGETS["barnards_star"]
    analyzer = KinematicsAndPhotometryAnalyzer(pixel_scale_arcsec=6.15)

    # Compare 1-year baseline (same orbital phase to isolate proper motion from annual parallax)
    mjd_t0 = 60800.0
    mjd_t1 = mjd_t0 + 365.25

    ra0, dec0 = analyzer.propagate_position(barnard, mjd_t0)
    ra1, dec1 = analyzer.propagate_position(barnard, mjd_t1)

    c0 = SkyCoord(ra=ra0 * u.deg, dec=dec0 * u.deg, frame="icrs")
    c1 = SkyCoord(ra=ra1 * u.deg, dec=dec1 * u.deg, frame="icrs")
    sep_arcsec = float(c0.separation(c1).arcsec)
    sep_pixels = sep_arcsec / 6.15

    assert sep_arcsec == pytest.approx(10.39, abs=0.15)
    assert sep_pixels == pytest.approx(1.69, abs=0.05)


def test_kinematics_annual_parallax_displacement() -> None:
    """Verify annual parallax reflex displacement and seasonal scaling (Finding 5)."""
    analyzer = KinematicsAndPhotometryAnalyzer(pixel_scale_arcsec=6.15)
    barnard = BENCHMARK_TARGETS["barnards_star"]

    mjd_obs = 60800.0  # Spring 2025
    barnard_zero_plx = TargetSpec(
        target_id="barnard_zero_plx",
        name="Barnard Zero Parallax",
        ra_deg=barnard.ra_deg,
        dec_deg=barnard.dec_deg,
        ref_epoch_jyear=barnard.ref_epoch_jyear,
        pm_ra_cosdec_mas_yr=barnard.pm_ra_cosdec_mas_yr,
        pm_dec_mas_yr=barnard.pm_dec_mas_yr,
        parallax_mas=0.0,
        radial_velocity_km_s=barnard.radial_velocity_km_s,
    )

    ra_with_plx, dec_with_plx = analyzer.propagate_position(barnard, mjd_obs)
    ra_no_plx, dec_no_plx = analyzer.propagate_position(barnard_zero_plx, mjd_obs)

    c_plx = SkyCoord(ra=ra_with_plx * u.deg, dec=dec_with_plx * u.deg, frame="icrs")
    c_bary = SkyCoord(ra=ra_no_plx * u.deg, dec=dec_no_plx * u.deg, frame="icrs")
    shift_arcsec = float(c_plx.separation(c_bary).arcsec)

    # For Barnard's star (pi = 546.98 mas), reflex displacement is between 0.2 and 0.55 arcsec
    assert 0.2 < shift_arcsec < 0.55

    # Test that seasonal reflex motion scales linearly with parallax for zero-PM sources
    # at the North Ecliptic Pole across 6 months (Earth moving 2 AU across the Sun)
    mjd_t0 = 60800.0
    mjd_t1 = mjd_t0 + 182.625  # exactly half year later

    plx_1000 = TargetSpec(
        target_id="nep_1000mas",
        name="NEP 1000 mas",
        ra_deg=270.0,
        dec_deg=66.56,
        ref_epoch_jyear=2016.0,
        pm_ra_cosdec_mas_yr=0.0,
        pm_dec_mas_yr=0.0,
        parallax_mas=1000.0,
    )
    plx_500 = TargetSpec(
        target_id="nep_500mas",
        name="NEP 500 mas",
        ra_deg=270.0,
        dec_deg=66.56,
        ref_epoch_jyear=2016.0,
        pm_ra_cosdec_mas_yr=0.0,
        pm_dec_mas_yr=0.0,
        parallax_mas=500.0,
    )

    ra_1000_t0, dec_1000_t0 = analyzer.propagate_position(plx_1000, mjd_t0)
    ra_1000_t1, dec_1000_t1 = analyzer.propagate_position(plx_1000, mjd_t1)
    sep_1000 = float(
        SkyCoord(ra=ra_1000_t0 * u.deg, dec=dec_1000_t0 * u.deg)
        .separation(SkyCoord(ra=ra_1000_t1 * u.deg, dec=dec_1000_t1 * u.deg))
        .arcsec
    )

    ra_500_t0, dec_500_t0 = analyzer.propagate_position(plx_500, mjd_t0)
    ra_500_t1, dec_500_t1 = analyzer.propagate_position(plx_500, mjd_t1)
    sep_500 = float(
        SkyCoord(ra=ra_500_t0 * u.deg, dec=dec_500_t0 * u.deg)
        .separation(SkyCoord(ra=ra_500_t1 * u.deg, dec=dec_500_t1 * u.deg))
        .arcsec
    )

    # 1000 mas plx should shift by ~2.0 arcsec over 2 AU baseline
    assert sep_1000 == pytest.approx(2.0, abs=0.05)
    # 500 mas plx should shift by half as much (~1.0 arcsec)
    assert sep_500 == pytest.approx(1.0, abs=0.05)
    # Linear scaling: sep_1000 / sep_500 should be 2.0 within 1%
    assert (sep_1000 / sep_500) == pytest.approx(2.0, rel=0.01)

    # Static target with 0 PM and 0 parallax returns exact coordinates unchanged
    static_target = TargetSpec(
        target_id="static_distant",
        name="Static Distant Star",
        ra_deg=100.0,
        dec_deg=20.0,
        pm_ra_cosdec_mas_yr=0.0,
        pm_dec_mas_yr=0.0,
        parallax_mas=0.0,
    )
    stat_ra, stat_dec = analyzer.propagate_position(static_target, mjd_t1)
    assert stat_ra == 100.0
    assert stat_dec == 20.0


def test_kinematics_measures_subpixel_centroid_and_aperture_flux(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify sub-pixel centroiding and positive uJy aperture photometry on Epsilon Indi B."""
    eps_indi = BENCHMARK_TARGETS["epsilon_indi_b"]
    analyzer = KinematicsAndPhotometryAnalyzer(pixel_scale_arcsec=6.15)
    cleaner = ZodiAndFlagCleaner()
    reprojector = NorthUpCommonReprojector(default_pixel_scale_arcsec=6.15)

    mjd_obs = 60850.0
    pred_ra, pred_dec = analyzer.propagate_position(eps_indi, mjd_obs)

    raw = raw_cutout_factory(
        frame_id="eps_indi_pass1",
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        star_ra_deg=pred_ra,
        star_dec_deg=pred_dec,
        mjd_avg=mjd_obs,
        peak_flux_mjy_sr=300.0,
        saturate_core=False,
    )

    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        cutout_size_arcsec=180.0,
    )
    reproj = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw),
        input_wcs=raw.spatial_wcs,
        variance_mjy2_sr2=raw.variance_mjy2_sr2,
        zodi_mjy_sr=raw.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )

    meas = analyzer.measure_centroid_and_photometry(
        target=eps_indi,
        mjd=mjd_obs,
        reprojected=reproj,
        common_wcs=common_wcs,
    )

    assert meas.measured_centroid_x is not None
    assert meas.measured_centroid_y is not None
    assert abs(meas.measured_centroid_x - meas.predicted_pixel_x) < 0.25
    assert abs(meas.measured_centroid_y - meas.predicted_pixel_y) < 0.25
    assert meas.centroid_offset_arcsec is not None and meas.centroid_offset_arcsec < 1.5
    assert meas.aperture_flux_ujy is not None and meas.aperture_flux_ujy > 0.0
    assert meas.snr is not None and meas.snr > 10.0
    assert not meas.is_saturated_core
