"""Tests for SPHERExMEFParser, IRSASiaCutoutProvider, and HarvardSimbadCatalogProvider."""

from __future__ import annotations

import hashlib
import io
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import httpx
import numpy as np
import pytest
import pyvo
from astropy.io import fits
from astropy.table import Table

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


def test_irsa_sia_provider_select_balanced_subset_balances_bands_and_epochs() -> None:
    """Verify band-balanced multi-epoch subset selection distributes frames across bands 1..6."""
    epochs = [60700.0, 60750.0, 60800.0, 60900.0]
    rows = [
        {"filename": f"f_d{band}_{idx}.fits", "t_min": t, "band": band}
        for band in range(1, 7)
        for idx, t in enumerate(epochs)
    ]

    selected = IRSASiaCutoutProvider._select_balanced_subset(rows, max_frames=12)
    assert len(selected) == 12
    for band in range(1, 7):
        band_rows = [r for r in selected if r["band"] == band]
        assert len(band_rows) == 2
        assert [r["t_min"] for r in band_rows] == [60700.0, 60900.0]
    assert selected == sorted(selected, key=lambda r: (r["t_min"], r["band"], r["filename"]))

    uneven_rows = [
        {"filename": "f_d1_0.fits", "t_min": 60700.0, "band": 1},
        *[
            {"filename": f"f_d2_{idx}.fits", "t_min": t, "band": 2}
            for idx, t in enumerate([60700.0, 60740.0, 60780.0, 60820.0, 60900.0])
        ],
        *[
            {"filename": f"f_d3_{idx}.fits", "t_min": t, "band": 3}
            for idx, t in enumerate([60700.0, 60740.0, 60780.0, 60820.0, 60900.0])
        ],
    ]
    selected_uneven = IRSASiaCutoutProvider._select_balanced_subset(uneven_rows, max_frames=6)
    assert len(selected_uneven) == 6
    d1_rows = [r for r in selected_uneven if r["band"] == 1]
    d2_rows = [r for r in selected_uneven if r["band"] == 2]
    d3_rows = [r for r in selected_uneven if r["band"] == 3]
    assert len(d1_rows) == 1
    assert len(d2_rows) == 3
    assert len(d3_rows) == 2
    assert d2_rows[0]["t_min"] == 60700.0 and d2_rows[-1]["t_min"] == 60900.0
    assert d3_rows[0]["t_min"] == 60700.0 and d3_rows[-1]["t_min"] == 60900.0


@pytest.mark.parametrize(
    ("cutout_size_arcsec", "expected_fetch_size"),
    [
        (180.0, 261.0),
        (100.0, 160.0),
        (1500.0, 1800.0),
    ],
)
def test_irsa_sia_provider_fetch_cutouts_requests_overscanned_size(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    cutout_size_arcsec: float,
    expected_fetch_size: float,
) -> None:
    """Verify fetch_cutouts overscans IRSA cutout size so rotated frames cover the target grid."""
    provider = IRSASiaCutoutProvider(cache_dir=tmp_path / "cache")
    target = TargetSpec(
        target_id="test_overscan",
        name="Test Overscan",
        ra_deg=269.452,
        dec_deg=4.693,
        cutout_size_arcsec=cutout_size_arcsec,
        collections=("spherex_dr1",),
    )

    monkeypatch.setattr(
        provider,
        "_query_collection",
        lambda *args, **kwargs: [
            {
                "filename": "cand1.fits",
                "access_url": "https://example.com/cand1.fits",
                "t_min": 60800.0,
                "band": 2,
            }
        ],
    )

    seen_urls: list[str] = []
    from unittest.mock import MagicMock

    fake_frame = MagicMock()
    fake_frame.mjd_avg = 60800.0
    fake_frame.detector_band = 2

    def mock_download(client, cutout_url, base_filename, collection, target_ra_deg, target_dec_deg):
        seen_urls.append(cutout_url)
        return fake_frame

    monkeypatch.setattr(provider, "_download_and_parse", mock_download)

    result = provider.fetch_cutouts(target)
    assert len(result.frames) == 1
    assert len(seen_urls) == 1
    assert f"size={expected_fetch_size:.1f}arcsec" in seen_urls[0]


def test_irsa_sia_provider_tracks_dropped_cutouts_on_download_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The retrieval result includes failed cutouts and their source diagnostics."""
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

    result = provider.fetch_cutouts(target)
    assert len(result.frames) == 1
    assert len(result.dropped_frames) == 1
    dropped = result.dropped_frames[0]
    assert dropped.frame_id == "cand1.fits"
    assert dropped.reason == "cutout_download_error"
    assert dropped.attempted_band == 2
    assert "503" in (dropped.error_detail or "")


def test_corrupt_discovery_cache_refetches_and_only_publishes_valid_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    votable = io.BytesIO()
    Table({"access_url": ["https://example.invalid/cutout.fits"]}).write(votable, format="votable")
    valid_response = votable.getvalue()
    partial_response = valid_response[: len(valid_response) // 2]
    error_response = valid_response.replace(
        b"</RESOURCE>", b'<INFO name="QUERY_STATUS" value="ERROR"/></RESOURCE>'
    )
    cache_path = tmp_path / "sia_spherex_dr1_42.0000_m10.0000.vot"
    cache_path.write_bytes(partial_response)
    updated_response = valid_response.replace(b"cutout.fits", b"newcut.fits")
    payloads = iter([error_response, valid_response, updated_response])
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200, content=next(payloads), request=httpx.Request("GET", url)
        ),
    )
    provider = IRSASiaCutoutProvider(cache_dir=tmp_path, max_retries=1)
    sia_service = pyvo.dal.SIA2Service(provider.sia_url, check_baseurl=False)

    def query():
        return provider._execute_sia_table_with_retry(sia_service, "spherex_dr1", 42.0, -10.0)

    with pytest.raises(ValueError, match="failed SIAv2 query"):
        query()
    assert cache_path.read_bytes() == partial_response

    assert list(query()["access_url"]) == ["https://example.invalid/cutout.fits"]
    assert cache_path.read_bytes() == valid_response
    assert list(query()["access_url"]) == ["https://example.invalid/cutout.fits"]
    stale_time = time.time() - provider.sia_cache_ttl_sec - 1
    os.utime(cache_path, (stale_time, stale_time))
    assert list(query()["access_url"]) == ["https://example.invalid/newcut.fits"]
    assert cache_path.read_bytes() == updated_response


def test_concurrent_identical_cutouts_recover_a_truncated_fits_cache(
    tmp_path: Path, mef_factory
) -> None:
    buffer = io.BytesIO()
    mef_factory().writeto(buffer)
    valid_cutout = buffer.getvalue()
    url = "https://example.invalid/cutout.fits"
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    cache_path = tmp_path / f"cutout_{url_hash}.fits"
    cache_path.write_bytes(valid_cutout[:-1])
    overlap = Barrier(2, timeout=10)
    provider = IRSASiaCutoutProvider(cache_dir=tmp_path, max_retries=1)

    def download(request):
        overlap.wait()
        return httpx.Response(200, content=valid_cutout)

    def fetch(client):
        return provider._download_and_parse(client, url, "cutout.fits", "spherex_dr1", 331, -56)

    with (
        httpx.Client(transport=httpx.MockTransport(download)) as client,
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        requests = [executor.submit(fetch, client) for _ in range(2)]
        frames = [request.result(timeout=10) for request in requests]

    assert [frame.frame_id for frame in frames] == ["cutout", "cutout"]
    assert cache_path.read_bytes() == valid_cutout
    assert list(tmp_path.iterdir()) == [cache_path]


def test_disabled_irsa_disk_cache_does_not_write_discovery_or_fits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mef_factory
) -> None:
    url = "https://example.invalid/cutout.fits"
    votable = io.BytesIO()
    Table({"access_url": [url]}).write(votable, format="votable")
    fits_buffer = io.BytesIO()
    mef_factory().writeto(fits_buffer)
    monkeypatch.setattr(
        httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200, content=votable.getvalue(), request=httpx.Request("GET", url)
        ),
    )
    monkeypatch.chdir(tmp_path)
    provider = IRSASiaCutoutProvider(cache_dir=None, max_retries=1)
    sia_service = pyvo.dal.SIA2Service(provider.sia_url, check_baseurl=False)

    table = provider._execute_sia_table_with_retry(sia_service, "spherex_dr1", 331, -56)
    assert list(table["access_url"]) == [url]
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, content=fits_buffer.getvalue()
        ))
    ) as client:
        frame = provider._download_and_parse(client, url, "cutout.fits", "spherex_dr1", 331, -56)
    assert frame.frame_id == "cutout"
    assert not list(tmp_path.iterdir())
