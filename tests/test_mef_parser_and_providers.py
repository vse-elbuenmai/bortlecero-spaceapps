"""Tests for SPHERExMEFParser, IRSASiaCutoutProvider, and HarvardSimbadCatalogProvider."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from spherex_ingest.domain.models import SPHERExFlagBits
from spherex_ingest.infrastructure.catalog_provider import HarvardSimbadCatalogProvider
from spherex_ingest.infrastructure.irsa_sia_provider import IRSASiaCutoutProvider
from spherex_ingest.infrastructure.mef_parser import SPHERExMEFParser


def test_mef_parser_extracts_all_extensions_and_normalizes_sip(
    mef_factory: Callable[..., fits.HDUList],
    tmp_path: Path,
) -> None:
    """Verify SPHERExMEFParser extracts IMAGE, FLAGS, VARIANCE, ZODI, and fixes SIP headers."""
    hdul = mef_factory(
        center_ra_deg=269.452,
        center_dec_deg=4.693,
        detector_band=4,
        mjd_avg=60812.5,
        sps_epa_deg=180.0,
        zodi_level_mjy_sr=35.0,
        saturate_core=True,
        transient_pixel=(3, 4),
        include_sip_without_suffix=True,
    )
    fits_file = tmp_path / "synth_cutout_D4.fits"
    hdul.writeto(fits_file, overwrite=True)

    parser = SPHERExMEFParser()
    frame = parser.parse_file(
        fits_path=fits_file,
        target_ra_deg=269.452,
        target_dec_deg=4.693,
        collection="spherex_dr1",
        source_url="https://irsa.ipac.caltech.edu/SIA/synth_cutout_D4.fits",
    )

    assert frame.frame_id == "synth_cutout_D4"
    assert frame.collection == "spherex_dr1"
    assert frame.detector_band == 4
    assert frame.mjd_avg == pytest.approx(60812.5)
    assert frame.sps_epa_deg == pytest.approx(180.0)
    assert frame.image_mjy_sr.shape == (31, 31)
    assert frame.flags_bitmask.shape == (31, 31)
    assert frame.variance_mjy2_sr2.shape == (31, 31)
    assert frame.zodi_mjy_sr.shape == (31, 31)
    assert np.any(np.isnan(frame.image_mjy_sr))
    assert (frame.flags_bitmask[3, 4] & int(SPHERExFlagBits.TRANSIENT)) != 0
    assert frame.wavelength_um_at_target > 0.5
    assert frame.bandwidth_um_at_target > 0.0


def test_irsa_sia_provider_blocks_qr2_collections() -> None:
    """Verify IRSASiaCutoutProvider explicitly forbids deprecated QR2 collections."""
    IRSASiaCutoutProvider.validate_collections(("spherex_dr1", "spherex_qr3", "spherex_dr1_deep"))

    with pytest.raises(ValueError, match="QR2"):
        IRSASiaCutoutProvider.validate_collections(("spherex_dr1", "spherex_qr2"))

    with pytest.raises(ValueError, match="QR2"):
        IRSASiaCutoutProvider.validate_collections(("spherex_qr2_deep",))


def test_irsa_sia_provider_build_cutout_url() -> None:
    """Verify server-side cutout query parameter construction."""
    url = IRSASiaCutoutProvider.build_cutout_url(
        base_access_url="https://irsa.ipac.caltech.edu/ibe/data/spherex/qr3/level2/exp.fits",
        ra_deg=331.076454,
        dec_deg=-56.793818,
        size_arcsec=180.0,
    )
    assert "center=331.076454,-56.793818d" in url
    assert "size=180.0arcsec" in url


def test_harvard_simbad_provider_rejects_strasbourg_cds() -> None:
    """Verify HarvardSimbadCatalogProvider blocks cds.unistra.fr URLs per AGENTS.md."""
    with pytest.raises(ValueError, match="unistra.fr"):
        HarvardSimbadCatalogProvider(tap_url="https://simbad.cds.unistra.fr/simbad/sim-tap/sync")


def test_harvard_simbad_provider_resolves_benchmarks_and_coord_strings() -> None:
    """Verify offline resolution of curated benchmarks and raw RA/Dec coordinate strings."""
    provider = HarvardSimbadCatalogProvider()

    barnard = provider.resolve_target("Barnard's Star", cutout_size_arcsec=150.0)
    assert barnard.target_id == "barnards_star"
    assert barnard.cutout_size_arcsec == 150.0
    assert barnard.pm_dec_mas_yr > 10000.0

    custom = provider.resolve_target("133.7600, -7.2422", cutout_size_arcsec=120.0)
    assert custom.category == "custom"
    assert custom.ra_deg == pytest.approx(133.7600)
    assert custom.dec_deg == pytest.approx(-7.2422)
    assert custom.cutout_size_arcsec == 120.0

    with pytest.raises(ValueError, match="empty"):
        provider.resolve_target("   ")
