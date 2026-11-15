"""Regression tests for ZodiAndFlagCleaner on two real SPHEREx Level 2b cutouts (issue #13).

The synthetic fixtures cannot show these faults: on a real saturated star the archive sets
TRANSIENT and SUR_ERROR on the bloom ring around the core, and a real cutout can hold a dead
pixel that carries OVERFLOW far from the target.

`tests/data/real_cutouts.npz` keeps only the IMAGE, FLAGS and ZODI planes (29 x 29 px each) of
two IRSA cutouts; `tests/data/real_cutouts.json` records where each one came from.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from astropy.wcs import WCS

from spherex_ingest.domain.models import RawCutoutFrame, SPHERExFlagBits
from spherex_ingest.processors.cleaners import ZodiAndFlagCleaner

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture(scope="module")
def real_cutouts() -> dict[str, tuple[RawCutoutFrame, dict[str, object]]]:
    """Load the two real cutouts as RawCutoutFrame objects, with their provenance records."""
    arrays = np.load(DATA_DIR / "real_cutouts.npz")
    meta = json.loads((DATA_DIR / "real_cutouts.json").read_text(encoding="utf-8"))
    frames: dict[str, tuple[RawCutoutFrame, dict[str, object]]] = {}
    for key, info in meta.items():
        image = arrays[f"{key}_image"]
        frames[key] = (
            RawCutoutFrame(
                frame_id=str(info["frame_id"]),
                collection=str(info["collection"]),
                detector_band=int(info["detector"]),
                mjd_avg=61000.0,
                obs_time_iso=str(info["obs_time_utc"]),
                sps_epa_deg=0.0,
                finast_flag=0,
                image_mjy_sr=image,
                flags_bitmask=arrays[f"{key}_flags"],
                variance_mjy2_sr2=np.zeros_like(image),
                zodi_mjy_sr=arrays[f"{key}_zodi"],
                spatial_wcs=WCS(naxis=2),
                wavelength_um_at_target=float(info["wavelength_um"]),
                bandwidth_um_at_target=0.03,
                source_url=str(info["source_url"]),
            ),
            info,
        )
    return frames


def _distance_from_star(shape: tuple[int, int], info: dict[str, object]) -> np.ndarray:
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    return np.hypot(xx - float(info["star_x"]), yy - float(info["star_y"]))


def test_saturated_star_keeps_its_bloom_ring_on_a_real_cutout(
    real_cutouts: dict[str, tuple[RawCutoutFrame, dict[str, object]]],
) -> None:
    """Barnard's Star: BLOOM pixels that also carry TRANSIENT/SUR_ERROR keep their flux."""
    raw, info = real_cutouts["barnard"]
    flags = raw.flags_bitmask.astype(np.int64)
    result = ZodiAndFlagCleaner().clean(raw)

    expected = (
        raw.image_mjy_sr.astype(np.float64) - raw.zodi_mjy_sr - result.residual_bg_mjy_sr
    )
    finite = np.isfinite(expected)
    bloom_with_defect_bit = (
        ((flags & SPHERExFlagBits.BLOOM) != 0)
        & ((flags & (SPHERExFlagBits.TRANSIENT | SPHERExFlagBits.SUR_ERROR)) != 0)
        & finite
    )

    # The cutout really shows the pattern this test is about.
    assert np.count_nonzero(bloom_with_defect_bit) >= 30
    assert float(np.max(expected[bloom_with_defect_bit])) > 1000.0

    # 1. None of those pixels is treated as a defect, and none changes value.
    assert not np.any(result.bad_pixel_mask & bloom_with_defect_bit)
    np.testing.assert_allclose(
        result.clean_image_mjy_sr[bloom_with_defect_bit],
        expected[bloom_with_defect_bit],
        atol=1e-6,
    )

    # 2. The star keeps its light: nothing within 4 px of it is emptied.
    near_star = (_distance_from_star(expected.shape, info) <= 4.0) & finite
    light_before = float(np.sum(np.clip(expected[near_star], 0.0, None)))
    light_after = float(np.sum(np.clip(result.clean_image_mjy_sr[near_star], 0.0, None)))
    assert light_after >= 0.99 * light_before

    # 3. Only the core counts as saturated: a handful of pixels, all on the star.
    saturated = result.saturation_mask
    assert 1 <= np.count_nonzero(saturated) <= 12
    assert float(np.max(_distance_from_star(expected.shape, info)[saturated])) <= 2.5
    assert np.all(np.isfinite(result.repaired_image_mjy_sr[saturated]))


def test_dead_pixel_far_from_the_target_is_not_saturation_on_a_real_cutout(
    real_cutouts: dict[str, tuple[RawCutoutFrame, dict[str, object]]],
) -> None:
    """Epsilon Indi B: one NONFUNC pixel with OVERFLOW must not mark the frame as saturated."""
    raw, info = real_cutouts["epsilon_indi_b"]
    flags = raw.flags_bitmask.astype(np.int64)
    result = ZodiAndFlagCleaner().clean(raw)

    dead = (flags & SPHERExFlagBits.NONFUNC) != 0
    dist = _distance_from_star(raw.image_mjy_sr.shape, info)

    # The cutout really shows the pattern: the only OVERFLOW pixel is a dead one, it is NaN,
    # and it sits more than 10 px from the target.
    overflow = (flags & SPHERExFlagBits.OVERFLOW) != 0
    assert np.count_nonzero(overflow) == 1
    assert np.all(dead[overflow])
    assert np.all(~np.isfinite(raw.image_mjy_sr[overflow]))
    assert float(dist[overflow][0]) > 10.0

    # 1. Nothing in this frame is saturated: the target is a faint brown dwarf.
    assert not np.any(result.saturation_mask)

    # 2. Dead pixels are repaired as defects, from their neighbours.
    assert np.all(result.bad_pixel_mask[dead])
    assert np.all(np.isfinite(result.clean_image_mjy_sr[dead]))

    # 3. The target itself is left alone.
    expected = (
        raw.image_mjy_sr.astype(np.float64) - raw.zodi_mjy_sr - result.residual_bg_mjy_sr
    )
    on_star = dist <= 2.0
    np.testing.assert_allclose(
        result.clean_image_mjy_sr[on_star], expected[on_star], atol=1e-6
    )
