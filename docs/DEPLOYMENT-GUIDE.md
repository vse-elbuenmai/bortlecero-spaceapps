# Developer Deployment & Integration Guide (Google Cloud)

This guide explains how the Bortle Cero SPHEREx web viewer (`mockup/`) and ingestion API (`src/spherex_ingest/`) are deployed to Google Cloud (`bortle-cero-nasa-staging-26`, `us-central1`), and how to ship updates safely when either the frontend or backend changes.

## 1. Current Staging Architecture

| Component | Source | Live Staging URL / Resource | Hosting Mechanism |
| :--- | :--- | :--- | :--- |
| **Static Web Viewer** | `mockup/` + `scripts/build_hosting.py` | `https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html` | Public GCS bucket (`gs://bortle-cero-nasa-staging-26-viewer`, automated on push to `main` by `.github/workflows/cd-deploy.yml`; Firebase Hosting via `firebase.json` optional) |
| **Ingestion API** | `src/spherex_ingest/` + `Dockerfile` | `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` | Cloud Run (`spherex-ingest-staging`, publicly invokable via `allUsers` `roles/run.invoker` for demo; async queue `POST /api/v1/jobs`) |
| **Private ingestion worker** | `src/spherex_ingest/` + `Dockerfile` | `spherex-ingest-staging-worker` | Cloud Run with authenticated Cloud Tasks delivery |
| **Job state** | `src/spherex_ingest/infrastructure/job_store.py` | Default Firestore database | Shared status, deduplication, admission, and leases |
| **Processed result store** | `src/spherex_ingest/result_storage.py` | Private staging bundle bucket | Five seeded benchmarks and a 24-hour live result cache |
| **Container Registry** | `.github/workflows/cd-deploy.yml` | `us-central1-docker.pkg.dev/bortle-cero-nasa-staging-26/spherex-ingest` | Artifact Registry (SHA-tagged) |

### Cost-Control Guardrails (Free-Tier Friendly)

- **Region**: `us-central1` (eligible for Google Cloud Free Tier on Cloud Run and Cloud Storage).
- **Compute** uses request-based Cloud Run billing, zero minimum instances, and maximums of two API instances and one worker. The previous instance-based configuration billed the full lifetime of an instance, including idle time before shutdown.
- **Public demo IAM & async ingestion**: `spherex-ingest-staging` is publicly invokable (`allUsers` `roles/run.invoker`, `GCP_REQUIRE_INVOKER_IAM=false` default in `cd-deploy.yml`) with synchronous ingestion disabled (`SPHEREX_LEGACY_SYNC_ENABLED=false`) and arbitrary coordinate queries served via the bounded async job queue (`POST /api/v1/jobs`, capped at 6 new jobs/min and 8 outstanding).
- **Bucket lifecycle**: `gs://bortle-cero-nasa-staging-26-spherex-bundles-staging` deletes noncurrent versions after 7 days (keeping up to 3 newer versions) and `queries/` objects after 30 days.
- **Budget alert**: A `20 MXN` monthly budget alert (`50% / 90% / 100%`) is configured on `bortle-cero-nasa-staging-26` and was verified on November 15, 2026. It sends notifications as spend reaches the thresholds. Usage can continue after an alert.

---

## 2. Updating & Deploying the Frontend (`mockup/`)

The static viewer in `mockup/` is packaged by `scripts/build_hosting.py` into `dist/hosting/` (gitignored).

### When `mockup/` Changes

1. **Added new static files?** Update `PUBLIC_FILES` in `scripts/build_hosting.py` so the new HTML/CSS/JS/image assets are included in `dist/hosting/`.
2. **Updated benchmark bundles?** Follow [benchmark result storage](RESULT-STORAGE.md#durable-nasa-benchmark-cache) to seed the private bucket. The viewer validates its static release using `benchmark-manifest.json`.
3. **Connecting to the Cloud Run backend:**
   - `mockup/viewer-config.json` controls `apiBaseUrl` and `liveQueries`.
   - Keep `liveQueries: false` until you intend to expose live coordinate queries publicly.
   - When ready to point the viewer at the Cloud Run backend, set `apiBaseUrl` to `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` and `liveQueries: true` (verify CORS and admission limits first).

### Build & Verify Locally

```bash
# Stage dist/hosting/ and validate tests
uv run python scripts/build_hosting.py
uv run pytest tests/test_mockup_integration.py

# Preview locally
uv run python -m http.server 8765 --directory dist/hosting
```

### Publish to Google Cloud Storage

Merging to `main` deploys the static viewer automatically via `.github/workflows/cd-deploy.yml` (`deploy-viewer`), setting `Cache-Control: public, max-age=31536000, immutable` on `releases/**` and `Cache-Control: no-cache` on mutable entrypoints and manifest (`index.html`, `*.js`, `*.css`, `*.json`, `sky/sky.json`). To publish manually:

```bash
uv run python scripts/build_hosting.py
gcloud storage rsync --recursive --delete-unmatched-destination-objects dist/hosting gs://bortle-cero-nasa-staging-26-viewer
gcloud storage objects update "gs://bortle-cero-nasa-staging-26-viewer/releases/**" --cache-control="public, max-age=31536000, immutable"
gcloud storage objects update \
  "gs://bortle-cero-nasa-staging-26-viewer/index.html" \
  "gs://bortle-cero-nasa-staging-26-viewer/*.js" \
  "gs://bortle-cero-nasa-staging-26-viewer/*.css" \
  "gs://bortle-cero-nasa-staging-26-viewer/*.json" \
  "gs://bortle-cero-nasa-staging-26-viewer/sky/sky.json" \
  --cache-control="no-cache"
```

Verify the live deployment:

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html
curl -fsS https://storage.googleapis.com/bortle-cero-nasa-staging-26-viewer/benchmark-manifest.json
```

*(Optional alternative: If Firebase Hosting is enabled for `bortle-cero-nasa-staging-26`, you can deploy `dist/hosting/` with `firebase deploy --only hosting --project bortle-cero-nasa-staging-26` using `firebase.json`.)*

---

## 3. Updating & Deploying the Backend (`src/spherex_ingest/`)

Backend deployments to Cloud Run are automated via **keyless OIDC Workload Identity Federation** in `.github/workflows/cd-deploy.yml`.

### Automatic Deployment on `main`

Before the first durable deployment in an environment, run
[the durable bootstrap](CLOUD-RUN.md#durable-staging-setup).
The keyless workflow deploys and verifies the worker, deploys the API,
checks all five cached benchmark requests, then publishes the viewer.

Every merge to `main` triggers `.github/workflows/cd-deploy.yml`:
1. **Verify**: Runs `uv sync --frozen --extra dev`, `pytest`, and `ruff check`.
2. **Deploy Static Viewer (`deploy-viewer`)**: Runs `scripts/build_hosting.py`, syncs `dist/hosting/` to `gs://bortle-cero-nasa-staging-26-viewer` (`GCP_VIEWER_BUCKET`, defaulting to `<GCP_PROJECT_ID>-viewer`), sets `Cache-Control: public, max-age=31536000, immutable` on `releases/**` and `Cache-Control: no-cache` on entrypoints/manifest, and verifies `index.html` (`200`) and `benchmark-manifest.json`.
3. **Build & Push**: Builds the `Dockerfile` and pushes a commit-SHA-tagged image to Artifact Registry.
4. **Deploy (`deploy-or-promote`)**: Renders `deploy/cloud-run/service.yaml` with the exact `@sha256:...` digest, deploys `spherex-ingest-staging`, and verifies `/api/v1/health`, `/api/v1/benchmarks`, and the `/api/v1/blink` `503` gate (using `GCP_REQUIRE_INVOKER_IAM`, default `false` for public demo environments).

### When the Backend Changes

- **New Python dependencies?** Update `pyproject.toml`, run `uv lock`, and export `requirements.txt` (`uv pip compile pyproject.toml -o requirements.txt` or `uv sync --frozen`). The Docker image installs strictly from `uv.lock`.
- **New environment variables?** Add them to `deploy/cloud-run/service.yaml` (never commit secrets; use Secret Manager or Cloud Run env vars).
- **Local container smoke test (Linux/macOS with Docker):**

  ```bash
  docker build --platform linux/amd64 --tag spherex-ingest:smoke .
  uv run python scripts/smoke_cloud_run.py spherex-ingest:smoke
  ```

### Manual Rollback or Promotion

Use **GitHub Actions -> `CD / Cloud Run Keyless Delivery` -> Run workflow** (`workflow_dispatch`):
- `action: promote` with a specific `image_digest` (`...@sha256:...`)
- `action: rollback` with a known-good API `revision` and, when needed, the compatible `worker_revision`.
- For `promote` or an image-based `rollback`, supply `image_digest` and the image's original full Git `code_sha`.

See [OPERATIONS-RUNBOOK.md](OPERATIONS-RUNBOOK.md) for full incident and rollback procedures.

---

## 4. Standard Pull Request Workflow

1. Create a feature branch from `main` (never commit directly to `main`):
   ```bash
   git checkout -b <your-name>/<topic>
   ```
2. Run all local checks before committing:
   ```bash
   uv run pytest
   uv run ruff check src/ tests/ scripts/
   uv run python scripts/check_docs.py
   ```
3. Log AI-assisted changes in [docs/AI-USAGE.md](AI-USAGE.md) and cite any new data/code sources in [docs/SOURCES.md](SOURCES.md) in the same commit.
4. Push your branch, open a PR targeting `main`, and wait for all GitHub Actions CI checks to pass before merging.
