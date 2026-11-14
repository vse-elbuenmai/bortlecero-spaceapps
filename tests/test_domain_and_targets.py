"""Tests for SPHEREx domain models, flag bitmasks, and benchmark targets."""

from __future__ import annotations

import pytest

from spherex_ingest.domain.models import SPHERExFlagBits, TargetSpec
from spherex_ingest.domain.targets import BENCHMARK_TARGETS, get_benchmark_target


def test_all_five_benchmark_targets_present_and_qr2_free() -> None:
    """Verify all 5 NASA Space Apps challenge benchmark objects exist and forbid QR2."""
    expected_ids = {
        "barnards_star",
        "epsilon_indi_b",
        "wise_0855_0714",
        "rw_aurigae",
        "r_draconis",
    }
    assert set(BENCHMARK_TARGETS.keys()) == expected_ids

    for target_id, spec in BENCHMARK_TARGETS.items():
        assert spec.target_id == target_id
        assert len(spec.collections) >= 2
        for coll in spec.collections:
            assert "qr2" not in coll.lower(), f"Forbidden QR2 collection found in {target_id}"
        assert "spherex_dr1" in spec.collections
        assert "spherex_qr3" in spec.collections


def test_wise_0855_uses_propagated_2025_coordinates() -> None:
    """Verify WISE 0855-0714 uses its ~2025.5 epoch coordinate (~133.760, -7.2422), not 2010."""
    wise = BENCHMARK_TARGETS["wise_0855_0714"]
    assert wise.ra_deg == pytest.approx(133.7600, abs=0.005)
    assert wise.dec_deg == pytest.approx(-7.2422, abs=0.005)
    assert wise.ref_epoch_jyear == pytest.approx(2025.5, abs=0.5)
    # Ensure it is ~20 pixels (~125 arcsec) West of the 2010 discovery RA (~133.795)
    assert wise.ra_deg < 133.775


def test_r_draconis_includes_deep_field_collections() -> None:
    """Verify R Draconis queries the North Ecliptic Pole deep-field SPHEREx collections."""
    r_dra = BENCHMARK_TARGETS["r_draconis"]
    assert "spherex_dr1_deep" in r_dra.collections
    assert "spherex_qr3_deep" in r_dra.collections


def test_get_benchmark_target_lookup_variations() -> None:
    """Verify case-insensitive and punctuation-tolerant benchmark lookups."""
    assert get_benchmark_target("Barnard's Star") == BENCHMARK_TARGETS["barnards_star"]
    assert get_benchmark_target("EPSILON INDI B") == BENCHMARK_TARGETS["epsilon_indi_b"]
    assert get_benchmark_target("wise-0855-0714") == BENCHMARK_TARGETS["wise_0855_0714"]
    assert get_benchmark_target("RW Aurigae") == BENCHMARK_TARGETS["rw_aurigae"]
    assert get_benchmark_target("r_draconis") == BENCHMARK_TARGETS["r_draconis"]
    assert get_benchmark_target("nonexistent_galaxy_xyz") is None


def test_spherex_flag_bits_masks() -> None:
    """Verify SPHEREx Level 2b bitmask definitions match the Explanatory Supplement."""
    assert int(SPHERExFlagBits.TRANSIENT) == (1 << 0)
    assert int(SPHERExFlagBits.OVERFLOW) == (1 << 1)
    assert int(SPHERExFlagBits.SUR_ERROR) == (1 << 2)
    assert int(SPHERExFlagBits.NONFUNC) == (1 << 6)
    assert int(SPHERExFlagBits.OUTLIER) == (1 << 14)
    assert int(SPHERExFlagBits.SOURCE_MASK) == (1 << 19)

    bad_mask = SPHERExFlagBits.bad_artifact_mask()
    sat_mask = SPHERExFlagBits.saturation_mask()

    # Saturation and source mask are not treated as dead/corrupt transient artifacts
    assert (bad_mask & sat_mask) == 0
    assert (bad_mask & int(SPHERExFlagBits.SOURCE_MASK)) == 0
    assert (bad_mask & int(SPHERExFlagBits.TRANSIENT)) != 0


def test_target_spec_validation() -> None:
    """Verify TargetSpec enforces valid celestial coordinate bounds."""
    valid = TargetSpec(target_id="test_obj", name="Test Object", ra_deg=180.0, dec_deg=-45.0)
    assert valid.ra_deg == 180.0
    assert valid.dec_deg == -45.0

    with pytest.raises( ValueError ):
        TargetSpec(target_id="bad_ra", name="Bad RA", ra_deg=365.0, dec_deg=0.0)

    with pytest.raises( ValueError ):
        TargetSpec(target_id="bad_dec", name="Bad Dec", ra_deg=10.0, dec_deg=-95.0)
