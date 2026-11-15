"""Atomic file publication for instance-local storage."""

from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Publish bytes by replacing the destination from a temporary sibling file."""
    temporary_path = None
    try:
        with NamedTemporaryFile(
            dir=path.parent, prefix=".spherex-", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
