"""Resource limits for the public queue and each admitted ingestion attempt."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, fields
from threading import Lock

# The default SPHEREx output pixel scale, in arcseconds.
PIXEL_SCALE_ARCSEC = 6.15


def grid_side(cutout_size_arcsec: float, pixel_scale: float = PIXEL_SCALE_ARCSEC) -> int:
    """Return the odd pixel width of the North-up reprojection grid."""
    return max(9, math.ceil(cutout_size_arcsec / pixel_scale)) | 1


@dataclass(frozen=True)
class PublicLimits:
    """Conservative launch settings, loaded from the worker's environment."""

    max_exposures: int = 12
    max_grid_pixels: int = 961
    max_download_bytes: int = 96 * 1024 * 1024
    max_elapsed_seconds: int = 120
    max_upstream_attempts: int = 3
    max_new_jobs_per_minute: int = 6
    max_outstanding_jobs: int = 8

    def __post_init__(self) -> None:
        if any(getattr(self, field.name) < 1 for field in fields(self)):
            raise ValueError("Ingestion limits must be positive")

    @classmethod
    def from_environment(cls) -> PublicLimits:
        return cls(**{
            field.name: int(os.environ[f"SPHEREX_{field.name.upper()}"])
            for field in fields(cls)
            if f"SPHEREX_{field.name.upper()}" in os.environ
        })

    def validate_request(self, size_arcsec: float, max_frames: int) -> None:
        if (
            not math.isfinite(size_arcsec)
            or not 12 < size_arcsec <= 1800
            or grid_side(size_arcsec) ** 2 > self.max_grid_pixels
            or not 1 <= max_frames <= self.max_exposures
        ):
            raise WorkLimitExceeded("request_limit")


class WorkLimitExceeded(RuntimeError):
    """Carry a stable error code across pipeline boundaries."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkBudget:
    """Track work for one queue attempt and interrupt it at work boundaries."""

    def __init__(self, limits: PublicLimits, max_frames: int) -> None:
        self.limits = limits
        self.exposures_left = min(max_frames, limits.max_exposures)
        self.bytes_left = limits.max_download_bytes
        self._download_lock = Lock()
        self.deadline = time.monotonic() + limits.max_elapsed_seconds

    def remaining_time(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise WorkLimitExceeded("timeout")
        return remaining

    def timeout(self, configured_seconds: float) -> float:
        return min(configured_seconds, self.remaining_time())

    def consume_exposure(self) -> None:
        self.remaining_time()
        if self.exposures_left <= 0:
            raise WorkLimitExceeded("exposure_limit")
        self.exposures_left -= 1

    def require_download_capacity(self, size: int) -> None:
        with self._download_lock:
            self._require_download_capacity(size)

    def _require_download_capacity(self, size: int) -> None:
        self.remaining_time()
        if size > self.bytes_left:
            raise WorkLimitExceeded("download_limit")

    def consume_download(self, size: int) -> None:
        with self._download_lock:
            self._require_download_capacity(size)
            self.bytes_left -= size


active_budget: ContextVar[WorkBudget | None] = ContextVar("active_budget", default=None)


@contextmanager
def bounded_ingestion(limits: PublicLimits, max_frames: int) -> Iterator[None]:
    """Apply worker limits to one pipeline execution and restore the caller's scope."""
    budget = WorkBudget(limits, max_frames)
    token = active_budget.set(budget)
    try:
        yield
        budget.remaining_time()
    finally:
        active_budget.reset(token)
