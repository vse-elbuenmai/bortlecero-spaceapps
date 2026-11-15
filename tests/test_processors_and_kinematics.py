"""Tests for ZodiAndFlagCleaner, NorthUpCommonReprojector, and KinematicsAndPhotometryAnalyzer."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import astropy.units as u
import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from photutils.centroids import centroid_com

from spherex_ingest.domain.models import RawCutoutFrame, SPHERExFlagBits, TargetSpec
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


def test_zodi_and_flag_cleaner_protects_stellar_halo_from_cosmic_ray_replacement(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify bright star halo pixels with OUTLIER/BLOOM are not wiped as cosmic rays."""
    raw = raw_cutout_factory(
        frame_id="halo_protection_test",
        zodi_level_mjy_sr=50.0,
        peak_flux_mjy_sr=500.0,
        saturate_core=True,
        transient_pixel=(3, 3),
    )

    # Inject OUTLIER / BLOOM flags into the stellar halo around the core (core is at ~16, 16)
    # The halo pixels have legitimate bright stellar flux (~100-300 mJy/sr)
    halo_coords = [(15, 14), (16, 14), (17, 14), (14, 15), (18, 15)]
    flags_copy = np.array(raw.flags_bitmask, copy=True)
    img_copy = np.array(raw.image_mjy_sr, copy=True)
    zodi_copy = np.array(raw.zodi_mjy_sr, copy=True)

    for hy, hx in halo_coords:
        flags_copy[hy, hx] |= int(SPHERExFlagBits.OUTLIER)

    raw_modified = dataclasses.replace(raw, flags_bitmask=flags_copy)

    cleaner = ZodiAndFlagCleaner(subtract_residual_bg=True)
    result = cleaner.clean(raw_modified)

    # 1. The genuine isolated cosmic ray at (3, 3) must be marked as bad pixel and interpolated
    assert result.bad_pixel_mask[3, 3]
    assert abs(result.clean_image_mjy_sr[3, 3]) < 15.0

    # 2. Stellar halo pixels with OUTLIER must NOT be marked in bad_pixel_mask
    for hy, hx in halo_coords:
        assert not result.bad_pixel_mask[hy, hx], (
            f"Halo pixel at ({hy}, {hx}) falsely marked as bad"
        )
        # Flux must be preserved (not replaced with local background)
        expected_flux = img_copy[hy, hx] - zodi_copy[hy, hx] - result.residual_bg_mjy_sr
        assert abs(result.clean_image_mjy_sr[hy, hx] - expected_flux) < 1e-3


def test_kinematics_centroid_rejection_on_empty_and_distant_fields(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify that centroids are rejected (None) on empty noise fields and distant sources."""
    eps_indi = BENCHMARK_TARGETS["epsilon_indi_b"]
    cleaner = ZodiAndFlagCleaner(subtract_residual_bg=True)
    analyzer = KinematicsAndPhotometryAnalyzer(detection_sigma=3.5)
    reprojector = NorthUpCommonReprojector(default_pixel_scale_arcsec=6.15)

    mjd_obs = 60850.0
    pred_ra, pred_dec = analyzer.propagate_position(eps_indi, mjd_obs)

    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        cutout_size_arcsec=180.0,
    )

    # Case 1: Empty field with zero stellar flux (noise only, SNR < 3.5 sigma)
    raw_empty = raw_cutout_factory(
        frame_id="empty_field",
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        star_ra_deg=pred_ra,
        star_dec_deg=pred_dec,
        mjd_avg=mjd_obs,
        peak_flux_mjy_sr=0.0,
        saturate_core=False,
    )
    reproj_empty = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw_empty),
        input_wcs=raw_empty.spatial_wcs,
        variance_mjy2_sr2=raw_empty.variance_mjy2_sr2,
        zodi_mjy_sr=raw_empty.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )
    meas_empty = analyzer.measure_centroid_and_photometry(
        target=eps_indi,
        mjd=mjd_obs,
        reprojected=reproj_empty,
        common_wcs=common_wcs,
    )
    assert meas_empty.measured_centroid_x is None
    assert meas_empty.measured_centroid_y is None
    assert meas_empty.measured_ra_deg is None
    assert meas_empty.measured_dec_deg is None
    assert meas_empty.centroid_offset_arcsec is None

    # Case 2: Field with a bright source shifted 3.5 px away from predicted coordinates
    # (Exceeds maximum allowed radius of 2.0 px / 15.0 arcsec)
    distant_ra = pred_ra + (3.5 * 6.15 / 3600.0) / np.cos(np.radians(pred_dec))
    distant_dec = pred_dec + (3.5 * 6.15 / 3600.0)

    raw_distant = raw_cutout_factory(
        frame_id="distant_source_field",
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        star_ra_deg=distant_ra,
        star_dec_deg=distant_dec,
        mjd_avg=mjd_obs,
        peak_flux_mjy_sr=300.0,
        saturate_core=False,
    )
    reproj_distant = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw_distant),
        input_wcs=raw_distant.spatial_wcs,
        variance_mjy2_sr2=raw_distant.variance_mjy2_sr2,
        zodi_mjy_sr=raw_distant.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )
    meas_distant = analyzer.measure_centroid_and_photometry(
        target=eps_indi,
        mjd=mjd_obs,
        reprojected=reproj_distant,
        common_wcs=common_wcs,
    )
    # Centroid must be rejected to prevent locking onto the distant source
    assert meas_distant.measured_centroid_x is None
    assert meas_distant.measured_centroid_y is None
    assert meas_distant.measured_ra_deg is None
    assert meas_distant.measured_dec_deg is None
    assert meas_distant.centroid_offset_arcsec is None


def test_cleaner_masks_transients_from_saturation_mask_near_saturated_core(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify reviewer_m3_2: transient pixels near a saturated core are excluded from sat mask."""
    # Saturated core frame (core at 16, 16)
    raw = raw_cutout_factory(
        frame_id="sat_transient_test",
        saturate_core=True,
    )
    # Inject a TRANSIENT pixel at (16, 17) - immediately adjacent to the core
    flags = np.array(raw.flags_bitmask, copy=True)
    flags[16, 17] = int(SPHERExFlagBits.TRANSIENT)
    raw_mod = dataclasses.replace(raw, flags_bitmask=flags)

    cleaner = ZodiAndFlagCleaner()
    res = cleaner.clean(raw_mod)

    # The adjacent transient must NOT be in saturation_mask because ~is_transient masks it out
    assert not res.saturation_mask[16, 17], (
        "Transient adjacent to core was incorrectly marked as saturated"
    )
    # The transient must be captured in bad_pixel_mask for interpolation
    assert res.bad_pixel_mask[16, 17], (
        "Transient adjacent to core was not included in bad_pixel_mask"
    )


def test_core_saturation_only_flagged_within_stellar_core_radius(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify Finding 11: saturation at distance >= 1.5 px does NOT flag is_saturated_core."""
    eps_indi = BENCHMARK_TARGETS["epsilon_indi_b"]
    cleaner = ZodiAndFlagCleaner(subtract_residual_bg=True)
    analyzer = KinematicsAndPhotometryAnalyzer()
    reprojector = NorthUpCommonReprojector()

    mjd_obs = 60800.0
    pred_ra, pred_dec = analyzer.propagate_position(eps_indi, mjd_obs)
    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        cutout_size_arcsec=180.0,
    )

    # 1. Target with saturation flag at pixel distance = 2.5 px from star center (not inside core)
    raw_edge_sat = raw_cutout_factory(
        frame_id="edge_sat_frame",
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        star_ra_deg=pred_ra,
        star_dec_deg=pred_dec,
        mjd_avg=mjd_obs,
        peak_flux_mjy_sr=200.0,
        saturate_core=False,
    )
    reproj_edge = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw_edge_sat),
        input_wcs=raw_edge_sat.spatial_wcs,
        variance_mjy2_sr2=raw_edge_sat.variance_mjy2_sr2,
        zodi_mjy_sr=raw_edge_sat.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )

    # Inject saturation mask at (16, 19) in reprojected frame (~3 px from core at 16, 16)
    sat_mask_edge = np.array(reproj_edge.saturation_mask, copy=True)
    sat_mask_edge[16, 19] = True
    reproj_edge_mod = dataclasses.replace(reproj_edge, saturation_mask=sat_mask_edge)

    meas_edge = analyzer.measure_centroid_and_photometry(
        target=eps_indi,
        mjd=mjd_obs,
        reprojected=reproj_edge_mod,
        common_wcs=common_wcs,
    )
    assert not meas_edge.is_saturated_core, "Saturation at 3 px falsely flagged is_saturated_core"
    assert meas_edge.aperture_flux_ujy is not None

    # 2. Inject saturation at center pixel (16, 16) -> must flag is_saturated_core=True
    sat_mask_core = np.array(reproj_edge.saturation_mask, copy=True)
    sat_mask_core[16, 16] = True
    reproj_core_mod = dataclasses.replace(reproj_edge, saturation_mask=sat_mask_core)

    meas_core = analyzer.measure_centroid_and_photometry(
        target=eps_indi,
        mjd=mjd_obs,
        reprojected=reproj_core_mod,
        common_wcs=common_wcs,
    )
    assert meas_core.is_saturated_core, "Core saturation at center pixel was not flagged"
    assert meas_core.aperture_flux_ujy is None
    assert meas_core.aperture_flux_err_ujy is None
    assert meas_core.snr is None


def test_kinematics_saturated_core_measures_halo_centroid_with_none_photometry(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify saturated cores still yield valid halo centroids while photometry stays None."""
    barnard = BENCHMARK_TARGETS["barnards_star"]
    cleaner = ZodiAndFlagCleaner(subtract_residual_bg=True)
    analyzer = KinematicsAndPhotometryAnalyzer(pixel_scale_arcsec=6.15)
    reprojector = NorthUpCommonReprojector(default_pixel_scale_arcsec=6.15)

    mjd_obs = 60800.0
    pred_ra, pred_dec = analyzer.propagate_position(barnard, mjd_obs)
    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        cutout_size_arcsec=180.0,
    )

    raw = raw_cutout_factory(
        frame_id="barnard_saturated_halo",
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        star_ra_deg=pred_ra,
        star_dec_deg=pred_dec,
        mjd_avg=mjd_obs,
        peak_flux_mjy_sr=400.0,
        saturate_core=True,
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
        target=barnard,
        mjd=mjd_obs,
        reprojected=reproj,
        common_wcs=common_wcs,
    )

    assert meas.is_saturated_core is True
    assert meas.measured_centroid_x is not None
    assert meas.measured_centroid_y is not None
    assert meas.measured_ra_deg is not None
    assert meas.measured_dec_deg is not None
    assert meas.centroid_offset_arcsec is not None
    assert abs(meas.measured_centroid_x - meas.predicted_pixel_x) < 0.5
    assert abs(meas.measured_centroid_y - meas.predicted_pixel_y) < 0.5
    assert meas.aperture_flux_ujy is None
    assert meas.aperture_flux_err_ujy is None
    assert meas.snr is None


def test_kinematics_noise_floor_bounds_snr_and_prevents_zero_division(
    raw_cutout_factory: Callable[..., RawCutoutFrame],
) -> None:
    """Verify Finding 11: noise floor prevents SNR division-by-zero or explosion to >100,000."""
    eps_indi = BENCHMARK_TARGETS["epsilon_indi_b"]
    cleaner = ZodiAndFlagCleaner(subtract_residual_bg=True)
    analyzer = KinematicsAndPhotometryAnalyzer()
    reprojector = NorthUpCommonReprojector()

    mjd_obs = 60800.0
    pred_ra, pred_dec = analyzer.propagate_position(eps_indi, mjd_obs)
    common_wcs, shape_out = reprojector.build_common_wcs(
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        cutout_size_arcsec=180.0,
    )

    raw = raw_cutout_factory(
        frame_id="noise_floor_test",
        center_ra_deg=pred_ra,
        center_dec_deg=pred_dec,
        star_ra_deg=pred_ra,
        star_dec_deg=pred_dec,
        mjd_avg=mjd_obs,
        peak_flux_mjy_sr=100.0,
        saturate_core=False,
    )
    reproj = reprojector.reproject_frame(
        cleaned=cleaner.clean(raw),
        input_wcs=raw.spatial_wcs,
        variance_mjy2_sr2=raw.variance_mjy2_sr2,
        zodi_mjy_sr=raw.zodi_mjy_sr,
        common_wcs=common_wcs,
        shape_out=shape_out,
    )

    # Set all reprojected variance to zero to simulate extreme/missing error map
    zero_var = np.zeros_like(reproj.reprojected_variance)
    reproj_zero_var = dataclasses.replace(reproj, reprojected_variance=zero_var)

    meas = analyzer.measure_centroid_and_photometry(
        target=eps_indi,
        mjd=mjd_obs,
        reprojected=reproj_zero_var,
        common_wcs=common_wcs,
    )
    assert meas.aperture_flux_err_ujy is not None
    assert meas.aperture_flux_err_ujy > 0.0
    assert meas.snr is not None
    # SNR should be reasonable (finite, positive, < 10,000)
    assert 0.0 < meas.snr < 10000.0

