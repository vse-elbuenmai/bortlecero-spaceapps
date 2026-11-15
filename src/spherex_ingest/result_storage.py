"""Versioned storage for derived blink results from live queries."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from functools import cache, lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from spherex_ingest.domain.models import BUNDLE_SCHEMA_VERSION, BlinkBundleDTO, TargetSpec
from spherex_ingest.infrastructure.result_objects import (
    CloudResultObjects,
    LocalResultObjects,
    ResultObject,
    ResultObjects,
)

logger = logging.getLogger(__name__)

ALGORITHM_VERSION = "1"
CATALOG_VERSION = "gaia-dr3-targets-v1"
RESULT_PREFIX = "queries/v1"
_DIGEST = re.compile(r"[0-9a-f]{64}")
_UPSTREAM_DROP_REASONS = {"collection_query_error", "cutout_download_error"}


class ResultKey(BaseModel):
    """Reproducible processing parameters for one resolved sky target."""

    model_config = ConfigDict(frozen=True)

    target: TargetSpec
    max_frames_per_collection: int | None = Field(default=None, ge=1)
    algorithm_version: str = ALGORITHM_VERSION
    catalog_version: str = CATALOG_VERSION
    bundle_schema_version: str = BUNDLE_SCHEMA_VERSION

    @classmethod
    def from_target(cls, target: TargetSpec, max_frames_per_collection: int | None) -> ResultKey:
        return cls(target=target, max_frames_per_collection=max_frames_per_collection)

    @property
    def digest(self) -> str:
        """Use round-trip binary64 coordinates and preserve collection processing order."""
        parameters = self.model_dump(mode="json")
        target_values = parameters["target"]
        for field, value in target_values.items():
            if isinstance(value, float) and value == 0.0:
                target_values[field] = 0.0
        data = json.dumps(
            parameters, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        return hashlib.sha256(data).hexdigest()


class StoredBlinkResult(BaseModel):
    """A self-contained immutable bundle with its processing and cache metadata."""

    cache_schema_version: Literal[1]
    key: ResultKey
    code_sha: str
    generated_at: AwareDatetime
    refresh_after: AwareDatetime
    expires_at: AwareDatetime
    bundle: BlinkBundleDTO


class ResultStore:
    """Publish complete immutable bundles before changing their manifest pointers."""

    def __init__(
        self,
        objects: ResultObjects,
        code_sha: str,
        ttl_seconds: int = 86_400,
    ) -> None:
        if not 0 < ttl_seconds <= 7 * 86_400:
            raise ValueError("Result retention must be between one second and seven days.")
        self.objects = objects
        self.code_sha = code_sha
        self.ttl = timedelta(seconds=ttl_seconds)

    @staticmethod
    def _manifest_path(key: ResultKey) -> str:
        return f"{RESULT_PREFIX}/manifests/{key.digest}"

    @staticmethod
    def _asset_path(digest: str) -> str:
        return f"{RESULT_PREFIX}/bundles/{digest}.json"

    def lookup(self, key: ResultKey, *, allow_stale_partial: bool = False) -> BlinkBundleDTO | None:
        """Return the current verified result. Existing jobs may reuse a partial result longer."""
        pointer = self.objects.read(self._manifest_path(key))
        return self._read_bundle(key, pointer, allow_stale_partial=allow_stale_partial)

    def _read_bundle(
        self,
        key: ResultKey,
        pointer: ResultObject | None,
        *,
        allow_stale_partial: bool = False,
    ) -> BlinkBundleDTO | None:
        if pointer is None:
            return None
        try:
            asset_digest = pointer.data.decode("ascii")
            if not _DIGEST.fullmatch(asset_digest):
                raise ValueError("Invalid result manifest.")
            asset = self.objects.read(self._asset_path(asset_digest))
            if asset is None or hashlib.sha256(asset.data).hexdigest() != asset_digest:
                raise ValueError("Missing or corrupt result asset.")
            result = StoredBlinkResult.model_validate_json(asset.data)
            if (
                result.key != key
                or result.bundle.target != key.target
                or result.bundle.schema_version != key.bundle_schema_version
                or not result.generated_at <= result.refresh_after <= result.expires_at
            ):
                raise ValueError("The result asset does not match its processing parameters.")
        except ValueError as exc:
            logger.warning("Ignoring invalid query result %s: %s", key.digest, exc)
            return None

        now = datetime.now(UTC)
        expires = result.expires_at if allow_stale_partial else result.refresh_after
        return result.bundle if now < expires else None

    def publish(self, key: ResultKey, bundle: BlinkBundleDTO) -> BlinkBundleDTO:
        """Store a complete result or return the existing result when publishers overlap."""
        if bundle.target != key.target or bundle.schema_version != key.bundle_schema_version:
            raise ValueError("The bundle does not match its processing parameters.")
        if not bundle.total_frames:
            return bundle

        now = datetime.now(UTC)
        expires = now + self.ttl
        partial = any(frame.reason in _UPSTREAM_DROP_REASONS for frame in bundle.dropped_frames)
        result = StoredBlinkResult(
            cache_schema_version=1,
            key=key,
            code_sha=self.code_sha,
            generated_at=now,
            expires_at=expires,
            refresh_after=min(expires, now + timedelta(minutes=5)) if partial else expires,
            bundle=bundle,
        )
        payload = result.model_dump_json().encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        manifest_path = self._manifest_path(key)
        asset_path = self._asset_path(digest)

        for _ in range(3):
            pointer = self.objects.read(manifest_path)
            existing = self._read_bundle(key, pointer)
            if existing is not None:
                return existing
            if not self.objects.write_if_generation(asset_path, payload, expected_generation=0):
                created_asset = self.objects.read(asset_path)
                if created_asset is None or created_asset.data != payload:
                    raise RuntimeError("The immutable result asset has unexpected contents.")
            generation = pointer.generation if pointer is not None else 0
            if self.objects.write_if_generation(
                manifest_path, digest.encode("ascii"), expected_generation=generation
            ):
                return bundle

        existing = self.lookup(key)
        if existing is not None:
            return existing
        raise RuntimeError("Could not publish a query result after concurrent updates.")


@cache
def _local_code_sha() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


@lru_cache(maxsize=4)
def _configure_store(
    bucket: str | None, root: Path, code_sha: str | None, ttl_seconds: int
) -> ResultStore:
    if bucket:
        if not code_sha or not re.fullmatch(r"[0-9a-f]{40}", code_sha):
            raise ValueError("Cloud result storage requires SPHEREX_CODE_SHA with a full Git SHA.")
        objects: ResultObjects = CloudResultObjects.from_bucket_name(bucket)
    else:
        objects = LocalResultObjects(root / "results.sqlite3")
    return ResultStore(objects, code_sha or _local_code_sha(), ttl_seconds)


def get_result_store() -> ResultStore:
    """Configure private Cloud Storage or an on-disk local result database."""
    scratch = Path(os.getenv("SPHEREX_CACHE_DIR", ".cache/fits")).parent
    root = Path(os.environ.get("SPHEREX_RESULTS_DIR", scratch / "results")).resolve()
    return _configure_store(
        os.getenv("SPHEREX_RESULTS_BUCKET"),
        root,
        os.getenv("SPHEREX_CODE_SHA"),
        int(os.getenv("SPHEREX_RESULT_TTL_SECONDS", "86400")),
    )
