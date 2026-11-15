from types import SimpleNamespace

import httpx
import pytest

from spherex_ingest.admission import AdmissionDenied, InMemoryAdmissionController
from spherex_ingest.domain.models import TargetSpec
from spherex_ingest.infrastructure.bounded_http import fetch_bytes, retry_limit
from spherex_ingest.infrastructure.irsa_sia_provider import IRSASiaCutoutProvider
from spherex_ingest.limits import PublicLimits, WorkLimitExceeded, active_budget, bounded_ingestion


class ResponseChunks(httpx.SyncByteStream):
    def __iter__(self):
        yield b"abcd"
        yield b"efgh"


def test_public_request_limits_match_grid_boundary():
    limits = PublicLimits(max_grid_pixels=961, max_exposures=12)
    limits.validate_request(190.65, 12)
    for size, frames in [(190.66, 12), (180, 13), (float("nan"), 1)]:
        with pytest.raises(WorkLimitExceeded, match="request_limit"):
            limits.validate_request(size, frames)


@pytest.mark.parametrize("declared_size", [None, "8"])
def test_stream_stops_at_download_budget(declared_size):
    headers = {"content-length": declared_size} if declared_size else {}
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers=headers, stream=ResponseChunks())
    )
    with httpx.Client(transport=transport) as client:
        with (
            pytest.raises(WorkLimitExceeded, match="download_limit"),
            bounded_ingestion(PublicLimits(max_download_bytes=6), 1),
        ):
            assert PublicLimits().max_upstream_attempts == 3
            assert retry_limit(4) == 3
            fetch_bytes(client, "https://example.test", 2)
    assert active_budget.get() is None
    assert retry_limit(4) == 4


def test_deadline_is_checked_during_the_work(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("spherex_ingest.limits.time.monotonic", lambda: now[0])
    with (
        pytest.raises(WorkLimitExceeded, match="timeout"),
        bounded_ingestion(PublicLimits(max_elapsed_seconds=1), 1),
    ):
        budget = active_budget.get()
        assert budget.timeout(45) == 1
        now[0] = 2
    assert active_budget.get() is None


def test_provider_balances_total_exposure_limit_across_collections(tmp_path, monkeypatch):
    provider = IRSASiaCutoutProvider(cache_dir=tmp_path)
    limits = []

    def candidates(collection, max_frames, **_):
        limits.append((collection, max_frames))
        return [
            {"access_url": "https://example.test/cutout", "filename": str(i)}
            for i in range(max_frames)
        ]

    monkeypatch.setattr(provider, "_query_collection", candidates)
    monkeypatch.setattr(
        provider,
        "_download_and_parse",
        lambda **_: SimpleNamespace(mjd_avg=61000, detector_band=1),
    )
    target = TargetSpec(target_id="test", name="test", ra_deg=120, dec_deg=1)
    with bounded_ingestion(PublicLimits(), 5):
        provider.fetch_cutouts(target, max_frames_per_collection=5)
    assert limits == [("spherex_dr1", 3), ("spherex_qr3", 2)]


def test_admission_controller_enforces_rate_and_concurrency_limits():
    now = [100.0]
    limits = PublicLimits(max_new_jobs_per_minute=2, max_outstanding_jobs=1)
    controller = InMemoryAdmissionController(limits=limits, clock=lambda: now[0])

    with controller.admit():
        with pytest.raises(AdmissionDenied) as exc_info:
            with controller.admit():
                pass
        assert exc_info.value.reason == "queue_full"
        assert exc_info.value.retry_after_seconds >= 1

    now[0] = 110.0
    with controller.admit():
        pass

    with pytest.raises(AdmissionDenied) as rate_exc:
        with controller.admit():
            pass
    assert rate_exc.value.reason == "rate_limit"
    assert rate_exc.value.retry_after_seconds == 50

    now[0] = 160.1
    with controller.admit():
        pass


def test_public_limits_from_environment(monkeypatch):
    monkeypatch.setenv("SPHEREX_MAX_EXPOSURES", "6")
    monkeypatch.setenv("SPHEREX_MAX_NEW_JOBS_PER_MINUTE", "3")
    limits = PublicLimits.from_environment()
    assert limits.max_exposures == 6
    assert limits.max_new_jobs_per_minute == 3
