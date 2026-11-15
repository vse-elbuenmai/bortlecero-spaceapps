"""Result object storage with generation-conditional publication."""

from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from google.api_core.exceptions import NotFound, PreconditionFailed

if TYPE_CHECKING:
    from google.cloud.storage import Bucket

LOCAL_MAX_BYTES = 128 * 1024 * 1024
LOCAL_RETENTION_SECONDS = 8 * 86_400


@dataclass(frozen=True)
class ResultObject:
    data: bytes
    generation: int


class ResultObjects(Protocol):
    """Read an object snapshot and conditionally publish an object generation."""

    def read(self, name: str) -> ResultObject | None: ...

    def write_if_generation(self, name: str, data: bytes, expected_generation: int) -> bool: ...


class LocalResultObjects:
    """Transactional object generations for independent local processes."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS objects ("
                "generation INTEGER PRIMARY KEY AUTOINCREMENT,"
                "name TEXT NOT NULL UNIQUE,"
                "data BLOB NOT NULL,"
                "created_at INTEGER NOT NULL)"
            )

    def read(self, name: str) -> ResultObject | None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT data, generation FROM objects WHERE name = ?", (name,)
            ).fetchone()
        return ResultObject(*row) if row is not None else None

    def write_if_generation(self, name: str, data: bytes, expected_generation: int) -> bool:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            connection.execute(f"PRAGMA max_page_count = {LOCAL_MAX_BYTES // page_size}")
            connection.execute("BEGIN IMMEDIATE")
            now = int(time.time())
            connection.execute(
                "DELETE FROM objects WHERE created_at < ?", (now - LOCAL_RETENTION_SECONDS,)
            )
            row = connection.execute(
                "SELECT generation FROM objects WHERE name = ?", (name,)
            ).fetchone()
            generation = row[0] if row is not None else 0
            if generation != expected_generation:
                return False
            connection.execute(
                "INSERT OR REPLACE INTO objects (name, data, created_at) VALUES (?, ?, ?)",
                (name, data, now),
            )
        return True


class CloudResultObjects:
    """Private Google Cloud Storage objects with generation preconditions."""

    def __init__(self, bucket: Bucket) -> None:
        self.bucket = bucket

    @classmethod
    def from_bucket_name(cls, bucket_name: str) -> CloudResultObjects:
        from google.cloud.storage import Client

        return cls(Client().bucket(bucket_name))

    def read(self, name: str) -> ResultObject | None:
        for _ in range(3):
            blob = self.bucket.get_blob(name, timeout=15)
            if blob is None:
                return None
            generation = blob.generation
            if generation is None:
                raise RuntimeError("Cloud Storage omitted the object generation.")
            try:
                data = blob.download_as_bytes(if_generation_match=generation, timeout=15)
            except (NotFound, PreconditionFailed):
                continue
            return ResultObject(data, generation)
        raise RuntimeError("The Cloud Storage object changed repeatedly during a read.")

    def write_if_generation(self, name: str, data: bytes, expected_generation: int) -> bool:
        blob = self.bucket.blob(name)
        try:
            blob.upload_from_string(
                data,
                content_type="application/octet-stream",
                if_generation_match=expected_generation,
                timeout=15,
            )
        except PreconditionFailed:
            return False
        return True
