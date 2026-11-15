"""Curated benchmark targets for the NASA Space Apps 2026 'Planet X and SPHEREx' challenge.

All astrometric parameters are sourced from Gaia DR3 (Epoch J2016.0) or literature
astrometry (for WISE 0855-0714, Luhman & Esplin 2016 / Kirkpatrick et al. 2021),
including the critical coordinate propagation notes from AGENTS.md.
"""

from __future__ import annotations

from spherex_ingest.domain.models import TargetSpec

BENCHMARK_TARGETS: dict[str, TargetSpec] = {
    "barnards_star": TargetSpec(
        target_id="barnards_star",
        name="Barnard's Star",
        category="high_proper_motion",
        # Gaia DR3 4472832130942575872 (Epoch J2016.0)
        ra_deg=269.44850253,
        dec_deg=4.73942005,
        ref_epoch_jyear=2016.0,
        pm_ra_cosdec_mas_yr=-801.551,
        pm_dec_mas_yr=10362.394,
        parallax_mas=546.9759,
        radial_velocity_km_s=-110.51,
        cutout_size_arcsec=180.0,
        collections=("spherex_dr1", "spherex_qr3"),
        notes=(
            "Fastest proper-motion star (~10.39 arcsec/yr = ~1.69 SPHEREx px/yr, "
            "~0.84 px per 6-month survey). Saturates SPHEREx detector cores (NaN in core, "
            "OVERFLOW bit in FLAGS); centroiding and visual rendering must reconstruct or "
            "use the unsaturated PSF halo and verify shift against Gaia DR3."
        ),
    ),
    "epsilon_indi_b": TargetSpec(
        target_id="epsilon_indi_b",
        name="Epsilon Indi B",
        category="brown_dwarf",
        # Gaia DR3 6412596012146801152 (Epoch J2016.0)
        ra_deg=331.07645260,
        dec_deg=-56.79381207,
        ref_epoch_jyear=2016.0,
        pm_ra_cosdec_mas_yr=3981.98,
        pm_dec_mas_yr=-2466.83,
        parallax_mas=270.66,
        radial_velocity_km_s=-40.4,
        cutout_size_arcsec=180.0,
        collections=("spherex_dr1", "spherex_qr3"),
        notes=(
            "Binary T1+T6 brown dwarf system at 3.64 pc. Cleanest unsaturated "
            "high-proper-motion benchmark (~4.72 arcsec/yr = ~0.77 SPHEREx px/yr) "
            "with 4 observation passes across DR1 and QR3."
        ),
    ),
    "wise_0855_0714": TargetSpec(
        target_id="wise_0855_0714",
        name="WISE J085510.83-071442.5",
        category="brown_dwarf",
        # Propagated to 2025.5 / 2026.0 per AGENTS.md (~133.760, -7.2422, ~20 px West of 2010 pos)
        ra_deg=133.7600,
        dec_deg=-7.2422,
        ref_epoch_jyear=2025.5,
        pm_ra_cosdec_mas_yr=-8118.0,
        pm_dec_mas_yr=680.0,
        parallax_mas=439.0,
        radial_velocity_km_s=0.0,
        cutout_size_arcsec=180.0,
        collections=("spherex_dr1", "spherex_qr3"),
        notes=(
            "Coldest known Y dwarf (~250 K) at 2.28 pc. Challenge prompt coordinates "
            "(~133.795, -7.245) are from ~2010 discovery epoch; today it lies ~20 SPHEREx "
            "pixels West at RA ~133.760, Dec ~-7.2422. Only detectable at lambda > 3.9 um "
            "(SPHEREx Bands 5 and 6). Beware stationary background source 29 arcsec from "
            "the 2010 discovery coordinate."
        ),
    ),
    "rw_aurigae": TargetSpec(
        target_id="rw_aurigae",
        name="RW Aurigae",
        category="variable_star",
        # Gaia DR3 156430822114424576 (Epoch J2016.0)
        ra_deg=76.95608120,
        dec_deg=30.40120459,
        ref_epoch_jyear=2016.0,
        pm_ra_cosdec_mas_yr=2.641,
        pm_dec_mas_yr=-27.398,
        parallax_mas=6.406,
        radial_velocity_km_s=-20.94,
        cutout_size_arcsec=180.0,
        collections=("spherex_dr1", "spherex_qr3"),
        notes=(
            "Classical T Tauri variable star in Taurus-Auriga. Enters detector non-linear "
            "regime; brightness comparisons must be grouped strictly by spectral "
            "band/wavelength to avoid confusing its steep infrared disk excess SED with "
            "temporal variability."
        ),
    ),
    "r_draconis": TargetSpec(
        target_id="r_draconis",
        name="R Draconis",
        category="variable_star",
        # Gaia DR3 1648328016354496384 (Epoch J2016.0)
        ra_deg=248.16737837,
        dec_deg=66.75500675,
        ref_epoch_jyear=2016.0,
        pm_ra_cosdec_mas_yr=-20.643,
        pm_dec_mas_yr=6.149,
        parallax_mas=1.2509,
        radial_velocity_km_s=-132.8,
        cutout_size_arcsec=180.0,
        collections=("spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep"),
        notes=(
            "Mira-type pulsating red giant variable near the North Ecliptic Pole "
            "(SPHEREx Deep Field). Saturates detector cores (NaN in core, OVERFLOW flag "
            "in halo) and has nearly continuous cadence in spherex_dr1_deep and "
            "spherex_qr3_deep."
        ),
    ),
}


def get_benchmark_target(target_id_or_name: str) -> TargetSpec | None:
    """Lookup a curated benchmark target by ID or case-insensitive name."""
    key = target_id_or_name.strip().lower().replace(" ", "_").replace("-", "_").replace("'", "")
    if key in BENCHMARK_TARGETS:
        return BENCHMARK_TARGETS[key]
    for spec in BENCHMARK_TARGETS.values():
        if spec.name.lower() == target_id_or_name.strip().lower():
            return spec
        if key in spec.target_id:
            return spec
    return None
