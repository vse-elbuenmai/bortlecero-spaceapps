# Run the ingestion API on Cloud Run

See also:
- [GCP bootstrap and Workload Identity Federation setup](../deploy/gcp/README.md) for automated keyless CI/CD provisioning via `deploy/gcp/bootstrap.sh` and `.github/workflows/cd-deploy.yml`.
- [Operations runbook](OPERATIONS-RUNBOOK.md) for Cloud Logging queries, Cloud Monitoring alerts, and backend/frontend/data rollback procedures.

## Local development

The Python API works outside the container in Bash and PowerShell.

```shell
uv sync --locked --extra dev
uv run spherex-ingest serve --host 127.0.0.1 --port 8000
```

To reproduce the Linux production image locally, use Docker with Linux containers enabled.

```shell
docker build --platform linux/amd64 --tag spherex-ingest:local .
uv run --no-sync python scripts/smoke_cloud_run.py spherex-ingest:local
docker run --rm --read-only --tmpfs /scratch:size=256m,mode=1777 -p 127.0.0.1:8080:8080 spherex-ingest:local
```

The smoke test exercises the injected port, health response, a synthetic bundle, the live-query
gate, SIGTERM handling, and restart. It runs in an isolated container without upstream network
access. The interactive server exposes `http://127.0.0.1:8080/api/v1/health` and
`http://127.0.0.1:8080/docs`.

## Durable staging setup

Run the durable job bootstrap in Bash, Git Bash, or WSL after the base
[Google Cloud bootstrap](../deploy/gcp/README.md). Use `--dry-run` to review the
commands without provisioning resources.

```bash
PROJECT_ID=bortle-cero-nasa-staging-26 bash deploy/gcp/bootstrap-durable-jobs.sh --dry-run
PROJECT_ID=bortle-cero-nasa-staging-26 bash deploy/gcp/bootstrap-durable-jobs.sh
```

The bootstrap enables Firestore and Cloud Tasks, creates the default Firestore
database when missing, adds TTL for jobs and deduplication pointers, and configures
the regional queue and scoped service account permissions. The API runtime account
enqueues tasks and reads results. The worker runtime account claims jobs and writes
results. The task identity can invoke only the worker delivery endpoint. The
GitHub deployment identity uses Workload Identity Federation and can mint a token
for the task identity to verify delivery during deployment.

The [deployment script](../deploy/gcp/deploy-services.sh) renders the Cloud Run
service template for both services from the same immutable image digest. It deploys
the worker first, confirms that unauthenticated requests are rejected, and checks
authenticated delivery against an unknown job ID to exercise Firestore without
contacting IRSA. It then deploys the API. The workflow checks the health endpoint,
synchronous-ingestion gate, and all five cached benchmarks before publishing
the viewer.

## Runtime settings

| Setting | Public API | Private worker |
| --- | --- | --- |
| CPU and memory | 1 vCPU, 1 GiB | 1 vCPU, 1 GiB |
| Service-level minimum and maximum | 0 and 2 | 0 and 1 |
| Concurrent HTTP requests | 8 | 1 |
| Request timeout | 60 seconds | 210 seconds |
| Billing and startup check | Request-based, default TCP | Request-based, default TCP |

The queue starts at one concurrent delivery and one delivery per second. It
allows up to six deliveries to cover infrastructure retries, while each job is
limited to two ingestion attempts. Each processing attempt retains the
120-second work budget, 12-exposure limit, and 96 MiB upstream download limit.
The task request has a 180-second deadline. Job state lives in Firestore, and
processed bundles live in private Cloud Storage. The 256 MiB memory-backed
scratch volume is temporary, and the container disables its raw FITS cache.

## Live Staging Verification (`bortle-cero-nasa-staging-26`)

- **Ingestion API (`spherex-ingest-staging`):** Deployed in `us-central1` at
  `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` and publicly invokable (`allUsers`
  `roles/run.invoker`) for the NASA Space Apps demo (`GCP_REQUIRE_INVOKER_IAM=false` default in
  `.github/workflows/cd-deploy.yml`; set `GCP_REQUIRE_INVOKER_IAM=true` in a GitHub Environment to
  enforce `401/403` unauthenticated checks). Synchronous ingestion is disabled
  (`SPHEREX_LEGACY_SYNC_ENABLED=false`), and arbitrary coordinate queries are served via the bounded
  async job queue (`POST /api/v1/jobs`, capped at 6 new jobs/min and 8 outstanding).
  The worker is `spherex-ingest-staging-worker` and keeps the invoker IAM check enabled.
- **Static Viewer (GCS):** Hosted on the public GCS bucket `gs://bortle-cero-nasa-staging-26-viewer`
  (`https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html`) and deployed
  automatically on every push to `main` by `.github/workflows/cd-deploy.yml`, with
  `Cache-Control: no-cache` on entrypoints/manifest (`index.html`, `*.js`, `*.css`, `*.json`,
  `sky/sky.json`) and `public, max-age=31536000, immutable` on `releases/**` (with Firebase Hosting
  via `firebase.json` as an optional alternative).

Authorized team members can also proxy the Cloud Run service locally via:

```bash
gcloud run services proxy spherex-ingest-staging --port 8189 --project bortle-cero-nasa-staging-26 --region us-central1
```

See [deploy/gcp/README.md](../deploy/gcp/README.md) for the provisioned GCS lifecycle, budget alert,
and GitHub `staging` Environment configuration, and [DEPLOYMENT-GUIDE.md](DEPLOYMENT-GUIDE.md) for
the end-to-end frontend + backend deployment workflow.
