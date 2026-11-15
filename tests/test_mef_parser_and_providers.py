"""Tests for SPHERExMEFParser, IRSASiaCutoutProvider, and HarvardSimbadCatalogProvider."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from spherex_ingest.domain.models import SPHERExFlagBits, TargetSpec
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


def test_harvard_simbad_provider_resolves_sexagesimal_coordinates() -> None:
    """Verify Finding 11: sexagesimal string resolution using SkyCoord."""
    provider = HarvardSimbadCatalogProvider()

    formats = [
        "17h57m48.5s +04d41m36s",
        "17:57:48.5 +04:41:36",
        "17 57 48.5 +04 41 36",
        "17:57:48.5, +04:41:36",
        "17h57m48.5s, +04d41m36s",
    ]
    for coord_str in formats:
        spec = provider.resolve_target(coord_str, cutout_size_arcsec=180.0)
        assert spec.category == "custom"
        assert spec.ra_deg == pytest.approx(269.45208, abs=0.001)
        assert spec.dec_deg == pytest.approx(4.69333, abs=0.001)
        assert spec.cutout_size_arcsec == 180.0

    # Negative declination
    spec_neg = provider.resolve_target("22:04:18.3 -56:47:38")
    assert spec_neg.category == "custom"
    assert spec_neg.ra_deg == pytest.approx(331.07625, abs=0.005)
    assert spec_neg.dec_deg == pytest.approx(-56.79389, abs=0.005)


def test_irsa_sia_provider_priority_bands_subset_selection() -> None:
    """Verify Finding 11: priority bands (bands 5 & 6) are selected when capped."""
    rows = [
        {"filename": "f_d1_1.fits", "t_min": 60700.0, "band": 1},
        {"filename": "f_d2_1.fits", "t_min": 60700.0, "band": 2},
        {"filename": "f_d3_1.fits", "t_min": 60700.0, "band": 3},
        {"filename": "f_d4_1.fits", "t_min": 60700.0, "band": 4},
        {"filename": "f_d5_1.fits", "t_min": 60700.0, "band": 5},
        {"filename": "f_d6_1.fits", "t_min": 60700.0, "band": 6},
        {"filename": "f_d5_2.fits", "t_min": 60900.0, "band": 5},
        {"filename": "f_d6_2.fits", "t_min": 60900.0, "band": 6},
    ]

    # Select 4 frames prioritizing bands 5 and 6
    selected = IRSASiaCutoutProvider._select_balanced_subset(
        rows, max_frames=4, priority_bands=(5, 6)
    )
    assert len(selected) == 4
    # All 4 selected should be from bands 5 and 6
    assert all(r["band"] in (5, 6) for r in selected)

    # Select 6 frames prioritizing bands 5 and 6 (there are 4 in 5/6, so 2 come from other bands)
    selected_6 = IRSASiaCutoutProvider._select_balanced_subset(
        rows, max_frames=6, priority_bands=(5, 6)
    )
    assert len(selected_6) == 6
    p_count = sum(1 for r in selected_6 if r["band"] in (5, 6))
    assert p_count == 4


def test_irsa_sia_provider_tracks_dropped_cutouts_on_download_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify Finding 9: failed cutouts are logged in provider.dropped_frames."""
    provider = IRSASiaCutoutProvider(cache_dir=tmp_path / "cache")
    target = TargetSpec(
        target_id="test_target",
        name="Test Target",
        ra_deg=269.452,
        dec_deg=4.693,
        collections=("spherex_dr1",),
    )

    # Mock SIA query returning 2 candidates
    fake_candidates = [
        {
            "filename": "cand1.fits",
            "access_url": "https://example.com/cand1.fits",
            "t_min": 60800.0,
            "band": 2,
        },
        {
            "filename": "cand2.fits",
            "access_url": "https://example.com/cand2.fits",
            "t_min": 60801.0,
            "band": 3,
        },
    ]
    monkeypatch.setattr(
        provider,
        "_query_collection",
        lambda *args, **kwargs: fake_candidates,
    )

    # Make _download_and_parse raise a 503 error on cand1, and return a fake frame on cand2
    from unittest.mock import MagicMock
    fake_frame = MagicMock()
    fake_frame.mjd_avg = 60801.0
    fake_frame.detector_band = 3

    def mock_download(client, cutout_url, base_filename, collection, target_ra_deg, target_dec_deg):
        if "cand1" in base_filename:
            raise RuntimeError("503 Service Unavailable")
        return fake_frame

    monkeypatch.setattr(provider, "_download_and_parse", mock_download)

    frames = provider.fetch_cutouts(target)
    assert len(frames) == 1
    assert len(provider.dropped_frames) == 1
    dropped = provider.dropped_frames[0]
    assert dropped.frame_id == "cand1.fits"
    assert dropped.reason == "cutout_download_error"
    assert dropped.attempted_band == 2
    assert "503" in (dropped.error_detail or "")

