"""Admission control and rate limiting for public live SPHEREx ingestion requests."""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol

from spherex_ingest.limits import PublicLimits


class AdmissionDenied(RuntimeError):
    """Raised when public admission capacity or rate limits are exceeded."""

    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = max(1, retry_after_seconds)


class AdmissionControllerProtocol(Protocol):
    """Protocol for admission controllers (in-memory or distributed)."""

    @contextmanager
    def admit(self) -> Iterator[None]:
        """Acquire an admission slot or raise `AdmissionDenied`."""
        ...


class InMemoryAdmissionController:
    """Thread-safe in-process admission controller enforcing concurrency and rate limits."""

    def __init__(
        self,
        limits: PublicLimits,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        self._in_flight = 0
        self._admitted_timestamps: deque[float] = deque()

    @contextmanager
    def admit(self) -> Iterator[None]:
        """Reserve an outstanding job slot and per-minute admission token."""
        with self._lock:
            if self._in_flight >= self._limits.max_outstanding_jobs:
                raise AdmissionDenied(reason="queue_full", retry_after_seconds=5)

            now = self._clock()
            cutoff = now - 60.0
            while self._admitted_timestamps and self._admitted_timestamps[0] <= cutoff:
                self._admitted_timestamps.popleft()

            if len(self._admitted_timestamps) >= self._limits.max_new_jobs_per_minute:
                oldest = self._admitted_timestamps[0]
                wait_seconds = math.ceil(60.0 - (now - oldest))
                raise AdmissionDenied(
                    reason="rate_limit",
                    retry_after_seconds=max(1, wait_seconds),
                )

            self._admitted_timestamps.append(now)
            self._in_flight += 1

        try:
            yield
        finally:
            with self._lock:
                self._in_flight = max(0, self._in_flight - 1)
