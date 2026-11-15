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

## Private staging

Use an Artifact Registry repository and a dedicated runtime service account in the approved
staging project. Use a new staging service name and keep the Cloud Run invoker IAM check
enabled. The operator running the smoke commands needs permission to invoke the staging service.
Use the CI-published image digest when available.

1. Copy [the service template](../deploy/cloud-run/service.yaml) to `service.staging.yaml` outside
   the repository or an ignored directory. Replace `__SERVICE_NAME__` with the staging service
   name, `__RUNTIME_SERVICE_ACCOUNT__` with the runtime account email, and `__IMAGE_DIGEST__` with
   the full Artifact Registry image reference ending in `@sha256:<digest>`. Replace
   `__BENCHMARK_BUCKET__` with the private bucket name or leave its value empty to
   disable [benchmark caching](RESULT-STORAGE.md).
2. Replace `PROJECT_ID`, `REGION`, and `SERVICE_NAME` in the following commands with staging values.
   These commands work in Bash and PowerShell.

   ```shell
   gcloud run services replace service.staging.yaml --project PROJECT_ID --region REGION --dry-run
   gcloud run services replace service.staging.yaml --project PROJECT_ID --region REGION
   gcloud run services get-iam-policy SERVICE_NAME --project PROJECT_ID --region REGION
   gcloud run services proxy SERVICE_NAME --port 8189 --project PROJECT_ID --region REGION
   ```

3. In a second terminal, use `curl` in Bash or `curl.exe` in PowerShell to request
   `http://127.0.0.1:8189/api/v1/health`. Expect HTTP 200, a non-null `revision`, and
   `legacy_sync_enabled: false`. Request `http://127.0.0.1:8189/api/v1/benchmarks` and verify
   that it lists five targets. Request `http://127.0.0.1:8189/api/v1/blink?ra=331&dec=-56` and
   expect HTTP 503. Check the staged service IAM policy for public principals such as `allUsers`
   or `allAuthenticatedUsers` and verify that unauthenticated requests to its service URL receive
   HTTP 401 or 403.

## Runtime settings

The service starts with 1 vCPU, 1 GiB memory, concurrency 1, a 300-second request timeout, `run.googleapis.com/cpu-throttling: "false"` (so background async job worker threads are not CPU-throttled between poll requests), and zero to two replicas. The offline container smoke measured 157 MiB after serving the fixture. The memory limit leaves room for the 256 MiB scratch volume and the Python process. These are staging settings. Measure peak memory, scratch use, and latency with representative ingestion inputs before raising concurrency. The request timeout allows for the previously reported cold benchmark latency of up to 212 seconds ([issue #13](https://github.com/vse-elbuenmai/bortlecero-spaceapps/issues/13)).

The container sets `SPHEREX_IRSA_DISK_CACHE_ENABLED=false` so raw FITS cutouts and IRSA discovery
tables do not accumulate on the memory-backed scratch volume. IRSA responses are still downloaded
and processed in memory. Staging uses a per-instance SQLite database at
`/scratch/results/results.sqlite3` for processed bundles, capped at 128 MiB plus journal overhead.
The private results bucket is provisioned but staging uses it only if `SPHEREX_RESULTS_BUCKET`
and `SPHEREX_CODE_SHA` are configured. The scratch volume is erased with the instance. Synchronous live
requests (`/api/v1/blink`) return HTTP 503 while `SPHEREX_LEGACY_SYNC_ENABLED=false`; arbitrary
coordinate queries are served instead via the bounded async job queue (`POST /api/v1/jobs`, capped
at 6 new jobs/min and 8 outstanding). The local Python command retains its development defaults.

The HTTP startup and liveness probes use `/api/v1/health`. It reports package version, Cloud
Run revision, and the live-query setting without resolving targets or contacting IRSA.

## Live Staging Verification (`bortle-cero-nasa-staging-26`)

- **Ingestion API (`spherex-ingest-staging`):** Deployed in `us-central1` at
  `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` and publicly invokable (`allUsers`
  `roles/run.invoker`) for the NASA Space Apps demo (`GCP_REQUIRE_INVOKER_IAM=false` default in
  `.github/workflows/cd-deploy.yml`; set `GCP_REQUIRE_INVOKER_IAM=true` in a GitHub Environment to
  enforce `401/403` unauthenticated checks). Synchronous ingestion is disabled
  (`SPHEREX_LEGACY_SYNC_ENABLED=false`), and arbitrary coordinate queries are served via the bounded
  async job queue (`POST /api/v1/jobs`, capped at 6 new jobs/min and 8 outstanding).
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
