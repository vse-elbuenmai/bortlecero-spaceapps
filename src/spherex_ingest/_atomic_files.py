"""Atomic file publication for instance-local storage."""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import NamedTemporaryFile

_REPLACE_MAX_ATTEMPTS = 10


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Publish bytes by replacing the destination from a temporary sibling file."""
    temporary_path = None
    try:
        with NamedTemporaryFile(
            dir=path.parent, prefix=".spherex-", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
        for attempt in range(1, _REPLACE_MAX_ATTEMPTS + 1):
            try:
                temporary_path.replace(path)
                break
            except PermissionError:
                if attempt == _REPLACE_MAX_ATTEMPTS:
                    raise
                time.sleep(0.005 * attempt)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
