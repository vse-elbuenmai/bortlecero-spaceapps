"""Read upstream responses within the active ingestion attempt's transfer budget."""

from __future__ import annotations

import time
from collections.abc import Mapping

import httpx

from spherex_ingest.limits import active_budget


def fetch_bytes(
    client: httpx.Client,
    url: str,
    timeout: float,
    params: Mapping[str, str] | None = None,
) -> bytes:
    """Read the response incrementally for budgeted ingestion."""
    budget = active_budget.get()
    if budget is None:
        response = client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        return response.content

    # Ask for identity encoding so the transfer and parser limits track the same bytes.
    with client.stream(
        "GET",
        url,
        params=params,
        timeout=budget.timeout(timeout),
        headers={"Accept-Encoding": "identity"},
    ) as response:
        response.raise_for_status()
        if response.headers.get("content-encoding", "identity").lower() != "identity":
            raise ValueError("Unexpected upstream content encoding")
        length = response.headers.get("content-length")
        if length and length.isdecimal():
            budget.require_download_capacity(int(length))
        body = bytearray()
        for chunk in response.iter_raw():
            budget.consume_download(len(chunk))
            body.extend(chunk)
        budget.remaining_time()
        return bytes(body)


def retry_limit(configured: int) -> int:
    budget = active_budget.get()
    return min(configured, budget.limits.max_upstream_attempts) if budget else configured


def retry_sleep(seconds: float) -> None:
    budget = active_budget.get()
    time.sleep(budget.timeout(seconds) if budget else seconds)
