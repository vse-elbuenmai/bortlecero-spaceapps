# Developer Deployment & Integration Guide (Google Cloud)

This guide explains how the Bortle Cero SPHEREx web viewer (`mockup/`) and ingestion API (`src/spherex_ingest/`) are deployed to Google Cloud (`bortle-cero-nasa-staging-26`, `us-central1`), and how to ship updates safely when either the frontend or backend changes.

## 1. Current Staging Architecture

| Component | Source | Live Staging URL / Resource | Hosting Mechanism |
| :--- | :--- | :--- | :--- |
| **Static Web Viewer** | `mockup/` + `scripts/build_hosting.py` | `https://storage.googleapis.com/bortle-cero-nasa-staging-26-viewer/index.html` | Public GCS bucket (`gs://bortle-cero-nasa-staging-26-viewer`) |
| **Ingestion API** | `src/spherex_ingest/` + `Dockerfile` | `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` | Cloud Run (`spherex-ingest-staging`) |
| **Bundle / Cache Store** | `src/spherex_ingest/result_storage.py` | `gs://bortle-cero-nasa-staging-26-spherex-bundles-staging` | Private versioned GCS bucket |
| **Container Registry** | `.github/workflows/cd-deploy.yml` | `us-central1-docker.pkg.dev/bortle-cero-nasa-staging-26/spherex-ingest` | Artifact Registry (SHA-tagged) |

### Cost-Control Guardrails (Free-Tier Friendly)

- **Region**: `us-central1` (eligible for Google Cloud Free Tier on Cloud Run and Cloud Storage).
- **Zero idle compute**: Cloud Run uses `minScale: 0` and `maxScale: 2` (`deploy/cloud-run/service.yaml`), so idle instances cost `$0`.
- **Live IRSA gate**: `SPHEREX_LEGACY_SYNC_ENABLED=false` by default in Cloud Run so public requests do not trigger unbounded IRSA downloads.
- **Bucket lifecycle**: `gs://bortle-cero-nasa-staging-26-spherex-bundles-staging` deletes noncurrent versions after 7 days (keeping up to 3 newer versions) and `queries/` objects after 30 days.
- **Budget alert**: A `20 MXN` monthly budget alert (`50% / 90% / 100%`) is configured on `bortle-cero-nasa-staging-26`.

---

## 2. Updating & Deploying the Frontend (`mockup/`)

The static viewer in `mockup/` is packaged by `scripts/build_hosting.py` into `dist/hosting/` (gitignored).

### When `mockup/` Changes

1. **Added new static files?** Update `PUBLIC_FILES` in `scripts/build_hosting.py` so the new HTML/CSS/JS/image assets are included in `dist/hosting/`.
2. **Updated benchmark bundles?** Regenerate bundles into `mockup/data/<target_id>/bundle.json` and run `scripts/build_hosting.py` to compute a new content-addressed `releases/<sha256>/` directory and `benchmark-manifest.json`.
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

```bash
uv run python scripts/build_hosting.py
gcloud storage cp -r dist/hosting/* gs://bortle-cero-nasa-staging-26-viewer/
```

Verify the live deployment:

```bash
curl -fsS -o /dev/null -w "%{http_code}\n" https://storage.googleapis.com/bortle-cero-nasa-staging-26-viewer/index.html
curl -fsS https://storage.googleapis.com/bortle-cero-nasa-staging-26-viewer/benchmark-manifest.json
```

*(Optional: If Firebase Hosting is later enabled in the Firebase Console for `bortle-cero-nasa-staging-26`, you can deploy `dist/hosting/` with `firebase deploy --only hosting --project bortle-cero-nasa-staging-26` using `firebase.json`.)*

---

## 3. Updating & Deploying the Backend (`src/spherex_ingest/`)

Backend deployments to Cloud Run are automated via **keyless OIDC Workload Identity Federation** in `.github/workflows/cd-deploy.yml`.

### Automatic Deployment on `main`

Every merge to `main` triggers `.github/workflows/cd-deploy.yml`:
1. **Verify**: Runs `uv sync --frozen --extra dev`, `pytest`, and `ruff check`.
2. **Deploy Static Viewer (`deploy-viewer`)**: Runs `scripts/build_hosting.py` and syncs `dist/hosting/` to `gs://bortle-cero-nasa-staging-26-viewer` (`GCP_VIEWER_BUCKET`, defaulting to `<GCP_PROJECT_ID>-viewer`), then verifies `index.html` (`200`) and `benchmark-manifest.json`.
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

Use **GitHub Actions -> `CD / Build & Deploy Cloud Run` -> Run workflow** (`workflow_dispatch`):
- `action: promote` with a specific `image_digest` (`...@sha256:...`)
- `action: rollback` with a known-good Cloud Run `revision` or `image_digest`

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
