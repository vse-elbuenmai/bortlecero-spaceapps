"""Durable job state repositories for local SQLite and Google Cloud Firestore."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from spherex_ingest.domain.jobs import (
    AdmissionLimitExceeded,
    ClaimOutcome,
    JobRecord,
)
from spherex_ingest.limits import PublicLimits


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _expire_if_needed(record: JobRecord, now: datetime) -> JobRecord:
    if record.status in ("queued", "running") and now >= record.expires_at:
        return record.model_copy(
            update={
                "status": "expired",
                "updated_at": now,
                "lease_expires_at": None,
                "error_code": "job_expired",
                "error_message": "Job expired before completion.",
            }
        )
    return record


class LocalSQLiteJobStore:
    """Durable file-backed job store safe across threads and local processes."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                "job_id TEXT PRIMARY KEY,"
                "request_key TEXT NOT NULL,"
                "status TEXT NOT NULL,"
                "created_at REAL NOT NULL,"
                "expires_at REAL NOT NULL,"
                "record_json TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_request_key "
                "ON jobs (request_key, status, created_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=30.0)

    @staticmethod
    def _save_row(conn: sqlite3.Connection, record: JobRecord) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO jobs "
            "(job_id, request_key, status, created_at, expires_at, record_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.job_id,
                record.request_key,
                record.status,
                record.created_at.timestamp(),
                record.expires_at.timestamp(),
                record.model_dump_json(),
            ),
        )

    @staticmethod
    def _load_row(row: tuple[str] | None) -> JobRecord | None:
        if row is None:
            return None
        return JobRecord.model_validate_json(row[0])

    def get_job(self, job_id: str) -> JobRecord | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT record_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._load_row(row)

    def get_active_or_succeeded_by_key(self, request_key: str) -> JobRecord | None:
        now = _now_utc()
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT record_json FROM jobs "
                "WHERE request_key = ? AND status IN ('queued', 'running', 'succeeded') "
                "AND expires_at > ? "
                "ORDER BY created_at DESC LIMIT 1",
                (request_key, now.timestamp()),
            ).fetchone()
        return self._load_row(row)

    def create_or_deduplicate_job(
        self, job: JobRecord, limits: PublicLimits
    ) -> tuple[JobRecord, bool]:
        now = _now_utc()
        now_ts = now.timestamp()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")

            # Expire stale non-terminal jobs first so they do not block capacity.
            stale_rows = conn.execute(
                "SELECT record_json FROM jobs "
                "WHERE status IN ('queued', 'running') AND expires_at <= ?",
                (now_ts,),
            ).fetchall()
            for (raw_json,) in stale_rows:
                stale = _expire_if_needed(JobRecord.model_validate_json(raw_json), now)
                self._save_row(conn, stale)

            existing_row = conn.execute(
                "SELECT record_json FROM jobs "
                "WHERE request_key = ? AND status IN ('queued', 'running', 'succeeded') "
                "AND expires_at > ? "
                "ORDER BY created_at DESC LIMIT 1",
                (job.request_key, now_ts),
            ).fetchone()
            if existing_row is not None:
                return JobRecord.model_validate_json(existing_row[0]), False

            outstanding = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchone()[0]
            if outstanding >= limits.max_outstanding_jobs:
                raise AdmissionLimitExceeded("queue_full", retry_after_seconds=30)

            window_start = now_ts - 60.0
            recent_rows = conn.execute(
                "SELECT created_at FROM jobs "
                "WHERE created_at >= ? AND (status != 'succeeded' OR "
                "json_extract(record_json, '$.attempts') > 0) "
                "ORDER BY created_at ASC",
                (window_start,),
            ).fetchall()
            if len(recent_rows) >= limits.max_new_jobs_per_minute:
                oldest_ts = float(recent_rows[0][0])
                retry_after = max(1, int(60.0 - (now_ts - oldest_ts)) + 1)
                raise AdmissionLimitExceeded("rate_limited", retry_after_seconds=retry_after)

            self._save_row(conn, job)
            return job, True

    def save_cached_job(self, job: JobRecord) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._save_row(conn, job)

    def claim_for_execution(
        self,
        job_id: str,
        worker_id: str,
        max_attempts: int,
        lease_seconds: int,
    ) -> ClaimOutcome:
        now = _now_utc()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT record_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            record = self._load_row(row)
            if record is None:
                return ClaimOutcome(status="not_found")

            expired = _expire_if_needed(record, now)
            if expired.status == "expired" and record.status != "expired":
                self._save_row(conn, expired)
                return ClaimOutcome(status="expired", record=expired)

            if record.status == "succeeded":
                return ClaimOutcome(status="already_succeeded", record=record)
            if record.status in ("failed", "expired"):
                return ClaimOutcome(status="already_terminal", record=record)
            if (
                record.status == "running"
                and record.lease_expires_at is not None
                and now < record.lease_expires_at
            ):
                return ClaimOutcome(status="already_running", record=record)

            effective_max = min(max_attempts, record.max_attempts)
            if record.attempts >= effective_max:
                failed = record.model_copy(
                    update={
                        "status": "failed",
                        "updated_at": now,
                        "lease_expires_at": None,
                        "error_code": record.error_code or "retry_exhausted",
                        "error_message": record.error_message
                        or "Job exceeded maximum retry attempts.",
                    }
                )
                self._save_row(conn, failed)
                return ClaimOutcome(status="exhausted", record=failed)

            claimed = record.model_copy(
                update={
                    "status": "running",
                    "attempts": record.attempts + 1,
                    "worker_id": worker_id,
                    "updated_at": now,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                }
            )
            self._save_row(conn, claimed)
            return ClaimOutcome(status="claimed", record=claimed)

    def _update_job(self, job_id: str, updater: Any) -> JobRecord:
        now = _now_utc()
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT record_json FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            record = self._load_row(row)
            if record is None:
                raise KeyError(f"Unknown job_id '{job_id}'")
            updated = updater(record, now)
            self._save_row(conn, updated)
            return updated

    def mark_succeeded(self, job_id: str, result_digest: str) -> JobRecord:
        def _apply(record: JobRecord, now: datetime) -> JobRecord:
            return record.model_copy(
                update={
                    "status": "succeeded",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "result_digest": result_digest,
                    "error_code": None,
                    "error_message": None,
                }
            )

        return self._update_job(job_id, _apply)

    def mark_retryable_failure(
        self, job_id: str, error_code: str, error_message: str
    ) -> JobRecord:
        def _apply(record: JobRecord, now: datetime) -> JobRecord:
            exhausted = record.attempts >= record.max_attempts
            return record.model_copy(
                update={
                    "status": "failed" if exhausted else "queued",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "error_code": error_code,
                    "error_message": error_message,
                }
            )

        return self._update_job(job_id, _apply)

    def mark_permanent_failure(
        self, job_id: str, error_code: str, error_message: str
    ) -> JobRecord:
        def _apply(record: JobRecord, now: datetime) -> JobRecord:
            return record.model_copy(
                update={
                    "status": "failed",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "error_code": error_code,
                    "error_message": error_message,
                }
            )

        return self._update_job(job_id, _apply)

    def mark_expired(self, job_id: str) -> JobRecord:
        def _apply(record: JobRecord, now: datetime) -> JobRecord:
            if record.status == "succeeded":
                return record
            return record.model_copy(
                update={
                    "status": "expired",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "error_code": "job_expired",
                    "error_message": "Job expired before completion.",
                }
            )

        return self._update_job(job_id, _apply)


class FirestoreJobStore:
    """Cloud-ready Firestore-backed durable job store with transactional guarantees.

    Uses three logical structures in Firestore:
    - ``{collection}/{job_id}``: canonical ``JobRecord`` document.
    - ``{key_collection}/{request_key}``: pointer ``{"job_id": ...}`` for O(1) dedup.
    - ``{meta_collection}/admission``: sliding window timestamps & active job IDs
      for atomic global rate/concurrency admission checks inside a single transaction.
    """

    def __init__(
        self,
        client: Any,
        *,
        collection_name: str = "spherex_jobs",
        key_collection_name: str = "spherex_job_keys",
        meta_collection_name: str = "spherex_job_meta",
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.key_collection_name = key_collection_name
        self.meta_collection_name = meta_collection_name

    @classmethod
    def from_project(
        cls,
        project_id: str | None = None,
        *,
        collection_name: str = "spherex_jobs",
    ) -> FirestoreJobStore:
        """Instantiate using google-cloud-firestore Client."""
        from google.cloud import firestore

        client = firestore.Client(project=project_id) if project_id else firestore.Client()
        return cls(client=client, collection_name=collection_name)

    def _job_ref(self, job_id: str) -> Any:
        return self.client.collection(self.collection_name).document(job_id)

    def _key_ref(self, request_key: str) -> Any:
        return self.client.collection(self.key_collection_name).document(request_key)

    def _admission_ref(self) -> Any:
        return self.client.collection(self.meta_collection_name).document("admission")

    @staticmethod
    def _from_snapshot(snapshot: Any) -> JobRecord | None:
        if not snapshot or not snapshot.exists:
            return None
        data = snapshot.to_dict()
        if not data:
            return None
        return JobRecord.model_validate(data)

    @staticmethod
    def _job_data(job: JobRecord) -> dict[str, Any]:
        # Firestore's TTL policy requires a native timestamp.
        return {**job.model_dump(mode="json"), "expires_at": job.expires_at}

    @staticmethod
    def _key_data(job: JobRecord) -> dict[str, Any]:
        return {"job_id": job.job_id, "expires_at": job.expires_at}

    def get_job(self, job_id: str) -> JobRecord | None:
        return self._from_snapshot(self._job_ref(job_id).get())

    def get_active_or_succeeded_by_key(self, request_key: str) -> JobRecord | None:
        key_snap = self._key_ref(request_key).get()
        if not key_snap or not key_snap.exists:
            return None
        job_id = (key_snap.to_dict() or {}).get("job_id")
        if not job_id:
            return None
        record = self.get_job(job_id)
        if record is None:
            return None
        now = _now_utc()
        if record.status in ("queued", "running", "succeeded") and record.expires_at > now:
            return record
        return None

    def create_or_deduplicate_job(
        self, job: JobRecord, limits: PublicLimits
    ) -> tuple[JobRecord, bool]:
        now = _now_utc()
        now_ts = now.timestamp()
        transaction = self.client.transaction()
        key_ref = self._key_ref(job.request_key)
        admission_ref = self._admission_ref()
        job_ref = self._job_ref(job.job_id)

        def _tx(tx: Any) -> tuple[JobRecord, bool]:
            key_snap = key_ref.get(transaction=tx)
            if key_snap and key_snap.exists:
                existing_id = (key_snap.to_dict() or {}).get("job_id")
                if existing_id:
                    existing_snap = self._job_ref(existing_id).get(transaction=tx)
                    existing = self._from_snapshot(existing_snap)
                    if (
                        existing is not None
                        and existing.status in ("queued", "running", "succeeded")
                        and existing.expires_at > now
                    ):
                        return existing, False

            adm_snap = admission_ref.get(transaction=tx)
            adm_data = (adm_snap.to_dict() if adm_snap and adm_snap.exists else None) or {}
            active_ids: list[str] = list(adm_data.get("active_job_ids", []))
            recent_ts: list[float] = [
                float(ts) for ts in adm_data.get("recent_timestamps", []) if ts >= now_ts - 60.0
            ]

            still_active: list[str] = []
            for active_id in active_ids:
                snap = self._job_ref(active_id).get(transaction=tx)
                rec = self._from_snapshot(snap)
                if rec is not None and rec.status in ("queued", "running") and rec.expires_at > now:
                    still_active.append(active_id)

            if len(still_active) >= limits.max_outstanding_jobs:
                raise AdmissionLimitExceeded("queue_full", retry_after_seconds=30)

            if len(recent_ts) >= limits.max_new_jobs_per_minute:
                oldest_ts = min(recent_ts)
                retry_after = max(1, int(60.0 - (now_ts - oldest_ts)) + 1)
                raise AdmissionLimitExceeded("rate_limited", retry_after_seconds=retry_after)

            still_active.append(job.job_id)
            recent_ts.append(now_ts)

            tx.set(job_ref, self._job_data(job))
            tx.set(key_ref, self._key_data(job))
            tx.set(
                admission_ref,
                {"active_job_ids": still_active, "recent_timestamps": recent_ts},
            )
            return job, True

        return self._run_transaction(transaction, _tx)

    def save_cached_job(self, job: JobRecord) -> None:
        batch = self.client.batch()
        batch.set(self._job_ref(job.job_id), self._job_data(job))
        batch.set(self._key_ref(job.request_key), self._key_data(job))
        batch.commit()

    def claim_for_execution(
        self,
        job_id: str,
        worker_id: str,
        max_attempts: int,
        lease_seconds: int,
    ) -> ClaimOutcome:
        now = _now_utc()
        transaction = self.client.transaction()
        job_ref = self._job_ref(job_id)

        def _tx(tx: Any) -> ClaimOutcome:
            snap = job_ref.get(transaction=tx)
            record = self._from_snapshot(snap)
            if record is None:
                return ClaimOutcome(status="not_found")

            expired = _expire_if_needed(record, now)
            if expired.status == "expired" and record.status != "expired":
                tx.set(job_ref, self._job_data(expired))
                return ClaimOutcome(status="expired", record=expired)

            if record.status == "succeeded":
                return ClaimOutcome(status="already_succeeded", record=record)
            if record.status in ("failed", "expired"):
                return ClaimOutcome(status="already_terminal", record=record)
            if (
                record.status == "running"
                and record.lease_expires_at is not None
                and now < record.lease_expires_at
            ):
                return ClaimOutcome(status="already_running", record=record)

            effective_max = min(max_attempts, record.max_attempts)
            if record.attempts >= effective_max:
                failed = record.model_copy(
                    update={
                        "status": "failed",
                        "updated_at": now,
                        "lease_expires_at": None,
                        "error_code": record.error_code or "retry_exhausted",
                        "error_message": record.error_message
                        or "Job exceeded maximum retry attempts.",
                    }
                )
                tx.set(job_ref, self._job_data(failed))
                return ClaimOutcome(status="exhausted", record=failed)

            claimed = record.model_copy(
                update={
                    "status": "running",
                    "attempts": record.attempts + 1,
                    "worker_id": worker_id,
                    "updated_at": now,
                    "lease_expires_at": now + timedelta(seconds=lease_seconds),
                }
            )
            tx.set(job_ref, self._job_data(claimed))
            return ClaimOutcome(status="claimed", record=claimed)

        return self._run_transaction(transaction, _tx)

    def _update_job_tx(self, job_id: str, updater: Any) -> JobRecord:
        now = _now_utc()
        transaction = self.client.transaction()
        job_ref = self._job_ref(job_id)

        def _tx(tx: Any) -> JobRecord:
            snap = job_ref.get(transaction=tx)
            record = self._from_snapshot(snap)
            if record is None:
                raise KeyError(f"Unknown job_id '{job_id}'")
            updated = updater(record, now)
            tx.set(job_ref, self._job_data(updated))
            return updated

        return self._run_transaction(transaction, _tx)

    def mark_succeeded(self, job_id: str, result_digest: str) -> JobRecord:
        return self._update_job_tx(
            job_id,
            lambda record, now: record.model_copy(
                update={
                    "status": "succeeded",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "result_digest": result_digest,
                    "error_code": None,
                    "error_message": None,
                }
            ),
        )

    def mark_retryable_failure(
        self, job_id: str, error_code: str, error_message: str
    ) -> JobRecord:
        return self._update_job_tx(
            job_id,
            lambda record, now: record.model_copy(
                update={
                    "status": "failed" if record.attempts >= record.max_attempts else "queued",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "error_code": error_code,
                    "error_message": error_message,
                }
            ),
        )

    def mark_permanent_failure(
        self, job_id: str, error_code: str, error_message: str
    ) -> JobRecord:
        return self._update_job_tx(
            job_id,
            lambda record, now: record.model_copy(
                update={
                    "status": "failed",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "error_code": error_code,
                    "error_message": error_message,
                }
            ),
        )

    def mark_expired(self, job_id: str) -> JobRecord:
        return self._update_job_tx(
            job_id,
            lambda record, now: record
            if record.status == "succeeded"
            else record.model_copy(
                update={
                    "status": "expired",
                    "updated_at": now,
                    "lease_expires_at": None,
                    "error_code": "job_expired",
                    "error_message": "Job expired before completion.",
                }
            ),
        )

    @staticmethod
    def _run_transaction(transaction: Any, fn: Any) -> Any:
        from google.cloud import firestore

        return firestore.transactional(fn)(transaction)
