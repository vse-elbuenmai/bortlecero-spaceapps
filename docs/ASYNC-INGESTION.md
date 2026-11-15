# Durable Asynchronous Ingestion (Issue #20)

This document describes the durable asynchronous ingestion architecture for arbitrary sky
coordinates in `spherex-ingest`. Cloud Run API revisions share Firestore job state
and Cloud Storage results. Cloud Tasks invokes a private worker that performs the
ingestion during the authenticated HTTP request.

## Overview

Long-running SPHEREx SIAv2 discovery, FITS cutout downloads, WCS reprojection, and bundle
export are decoupled from public HTTP request lifetimes:

1. **Submit (`POST /api/v1/jobs`)**:
   - Validates parameters against `PublicLimits` (`SPHEREX_MAX_EXPOSURES`,
     `SPHEREX_MAX_GRID_PIXELS`). Rejects `force_refresh=true` and invalid inputs with HTTP `422`.
   - Resolves the canonical `TargetSpec` and computes `ResultKey.digest` (SHA-256 over target,
     frame cap, algorithm version, catalog version, and bundle schema version).
   - **Cache hit (`200 OK`)**: If `ResultStore` already holds a fresh verified `BlinkBundleDTO`,
     returns `JobStatusDTO` with `status="succeeded"`, `cached=true`, and `result` populated
     without consuming queue admission quota.
   - **Deduplication (`202 Accepted` / `200 OK`)**: If an unexpired `queued`, `running`, or
     `succeeded` job already exists for `request_key`, returns that existing job instead of
     enqueuing duplicate work.
   - **Admission control (`429 Too Many Requests`)**: Enforces `SPHEREX_MAX_OUTSTANDING_JOBS` and
     `SPHEREX_MAX_NEW_JOBS_PER_MINUTE` atomically in the job store, returning `Retry-After`.
     CORS exposes that header so the public viewer can show when to try again.
   - **Enqueue (`202 Accepted`)**: Persists the `queued` `JobRecord` durably before dispatching,
     returning `job_id`, `status`, `status_url`, `result_url`, and `correlation_id`.

2. **Poll Status (`GET /api/v1/jobs/{job_id}`)**:
   - Returns `JobStatusDTO` with state in `{"queued", "running", "succeeded", "failed", "expired"}`.
   - Transitions overdue `queued`/`running` jobs to `expired` when `expires_at` has passed.
   - Failed jobs expose only sanitized `error_code`, `error_message`, and `correlation_id` (no
     stack traces or internal exception details).
   - The viewer retries transient status and result reads at most twice with backoff
     and stops automatic polling after five minutes. A new submission requires a
     user action.

3. **Fetch Result (`GET /api/v1/jobs/{job_id}/result`)**:
   - `200 OK`: Returns `BlinkBundleDTO` from `ResultStore` when `status="succeeded"`.
   - `409 Conflict`: Job is still `queued` or `running`.
   - `410 Gone`: Job or its stored result has `expired`.
   - `422 Unprocessable Entity`: Job reached `failed` with sanitized error metadata.
   - `404 Not Found`: Unknown `job_id`.

4. **Private Worker (`POST /internal/worker/ingest`)**:
   - Protected by `WorkerAuthVerifierProtocol` (`OIDCWorkerAuthVerifier` in cloud deployments,
     verifying `Authorization: Bearer <OIDC JWT>`, expected audience, expected service account
     email, and optionally `X-CloudTasks-TaskName`).
   - Atomically claims an exclusive lease (`claim_for_execution`) before running
     `SPHERExBlinkIngestionService.ingest_target` inside `bounded_ingestion(limits, max_frames)`.
   - Publishes the `BlinkBundleDTO` atomically to `ResultStore` **before** marking the job
     `succeeded`.

## Job State Machine & Retry Semantics

| State | Meaning | Worker HTTP Response |
| --- | --- | --- |
| `queued` | Persisted and waiting for worker claim (or scheduled for retry) | `503` on transient failure while `attempts < max_attempts` |
| `running` | Claimed by a worker with a bounded `lease_expires_at` | `409` on duplicate concurrent delivery |
| `succeeded` | Bundle published atomically to `ResultStore` | `200` (idempotent no-op on redelivery) |
| `failed` | Permanent validation/no-observations error or `attempts >= max_attempts` | `200` (stops Cloud Tasks redelivery) |
| `expired` | Exceeded `expires_at` or result evicted from `ResultStore` | `200` (stops Cloud Tasks redelivery) |

Permanent errors (`NoObservations`, `ValueError`, `WorkLimitExceeded` for `request_limit` /
`download_limit` / `exposure_limit`) are never retried. Transient errors (`UpstreamUnavailable`,
`WorkLimitExceeded("timeout")`, unexpected runtime failures) retry up to
`SPHEREX_JOB_MAX_ATTEMPTS` (two in Cloud Run staging, three by default in local
development). Cloud Tasks can deliver a task up to six times to accommodate HTTP
delivery failures or a worker restart before a lease expires. The job record enforces
the two-attempt ingestion limit. Each creation uses the job ID as the task name so
retrying the enqueue operation cannot create a second task for that job.

## Storage & Queue Implementations

- **Local Development / Testing**:
  - `LocalSQLiteJobStore` (`SPHEREX_JOBS_BACKEND=sqlite`, `SPHEREX_JOBS_DIR`): transactional
    `BEGIN IMMEDIATE` SQLite store safe across threads and local processes.
  - `LocalThreadPoolJobDispatcher` (`SPHEREX_JOBS_DISPATCHER=local`): bounded thread-pool
    executor running `AsyncIngestionWorker.execute`.
- **Cloud Run + Firestore + Cloud Tasks**:
  - `FirestoreJobStore` (`SPHEREX_JOBS_BACKEND=firestore`, `SPHEREX_FIRESTORE_PROJECT`,
    `SPHEREX_JOBS_COLLECTION`): transactional Firestore job documents, `request_key` dedup
    pointers, and global admission counters. Job and dedup documents use Firestore
    TTL on the native `expires_at` timestamp.
  - `CloudTasksJobDispatcher` (`SPHEREX_JOBS_DISPATCHER=cloud_tasks`): enqueues `POST` tasks
    with OIDC tokens targeting `POST /internal/worker/ingest`.

## Deployment Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `SPHEREX_ASYNC_JOBS_ENABLED` | `true` | Capability flag for `/api/v1/jobs` |
| `SPHEREX_JOBS_BACKEND` | `sqlite` | `sqlite` or `firestore` |
| `SPHEREX_JOBS_DIR` | `<cache_parent>/jobs` | Local SQLite directory |
| `SPHEREX_FIRESTORE_PROJECT` | unset | GCP project ID for Firestore |
| `SPHEREX_JOBS_COLLECTION` | `spherex_jobs` | Firestore collection name |
| `SPHEREX_JOBS_DISPATCHER` | `local` | `local` or `cloud_tasks` |
| `SPHEREX_TASKS_PROJECT` | unset | GCP project ID for Cloud Tasks |
| `SPHEREX_TASKS_LOCATION` | unset | Cloud Tasks region |
| `SPHEREX_TASKS_QUEUE` | unset | Cloud Tasks queue ID |
| `SPHEREX_WORKER_BASE_URL` | unset | Base URL of private worker service |
| `SPHEREX_TASKS_SERVICE_ACCOUNT` | unset | Invoker service account email for OIDC |
| `SPHEREX_WORKER_OIDC_AUDIENCE` | unset | Expected OIDC audience on `/internal/worker/ingest` |
| `SPHEREX_REQUIRE_CLOUD_TASKS_HEADER` | `false` | Require `X-CloudTasks-TaskName` header |
| `SPHEREX_WORKER_ENABLED` | `true` | The Cloud Run API sets this to `false`; the private worker exposes the ingestion endpoint. |
| `SPHEREX_WORKER_AUTH_REQUIRED` | `false` (auto `true` on `K_SERVICE`) | Fail-closed worker auth guard |
| `SPHEREX_JOB_MAX_ATTEMPTS` | `3` | Maximum execution attempts per job |
| `SPHEREX_JOB_TTL_SECONDS` | `86400` | Job retention/expiration window in seconds |
