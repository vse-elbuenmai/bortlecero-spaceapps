# Google Cloud Keyless Delivery Infrastructure

This directory contains the reproducible provisioning script for deploying the Bortle Cero SPHEREx ingestion API (`spherex-ingest`) to Google Cloud Run without long-lived service account JSON keys.

## Architecture & Least-Privilege Separation

1. **Artifact Registry (`spherex-ingest`)**: Stores immutable container images tagged by commit SHA and deployed by `@sha256:...` digest.
2. **GCS Bucket (`<project>-spherex-bundles-<env>`)**: Private, uniform-bucket-level-access, object-versioned storage for pre-generated benchmark bundles and durable cache artifacts.
3. **Runtime Service Account (`spherex-runtime-<env>`)**: Identity attached to the Cloud Run service. Granted only:
   - `roles/logging.logWriter` (project)
   - `roles/monitoring.metricWriter` (project)
   - `roles/storage.objectUser` (scoped strictly to the bundles bucket)
4. **Deploy Service Account (`spherex-deploy-<env>`)**: Identity impersonated by GitHub Actions via OIDC Workload Identity Federation. Granted only:
   - `roles/artifactregistry.writer` (scoped to the Artifact Registry repository)
   - `roles/run.developer` (project)
   - `roles/run.invoker` (project, for post-deploy OIDC smoke checks against private services)
   - `roles/iam.serviceAccountUser` (scoped strictly to `spherex-runtime-<env>`)
   - `roles/storage.objectAdmin` (scoped strictly to the bundles bucket)
5. **Workload Identity Federation (WIF)**: Maps GitHub OIDC tokens (`https://token.actions.githubusercontent.com`) with an attribute condition restricting impersonation to `assertion.repository == '<GITHUB_REPO>'`.

## Provisioning

> **Windows users:** `deploy/gcp/bootstrap.sh` is a `bash` script. Run it from **Git Bash** or **WSL** with the Google Cloud CLI (`gcloud`) installed and authenticated (`gcloud auth login`).

Preview all commands first with `--dry-run`:

```bash
PROJECT_ID=bortle-cero-nasa-staging-26 \
GITHUB_REPO=vse-elbuenmai/bortlecero-spaceapps \
ENVIRONMENT=staging \
REGION=us-central1 \
bash deploy/gcp/bootstrap.sh --dry-run
```

Run for real once verified by a project owner/admin:

```bash
PROJECT_ID=bortle-cero-nasa-staging-26 \
GITHUB_REPO=vse-elbuenmai/bortlecero-spaceapps \
ENVIRONMENT=staging \
REGION=us-central1 \
bash deploy/gcp/bootstrap.sh
```

After running, copy the printed `GCP_*` variables into the corresponding GitHub Environment (`staging` or `production`) under **Settings -> Environments**. For `production`, enable **Required reviewers** on the GitHub Environment so promotions require manual approval.

## Live Staging Environment (`bortle-cero-nasa-staging-26`)

The staging environment is provisioned in `us-central1` (Google Cloud Free Tier eligible) with cost controls:

- **Cloud Run API (`spherex-ingest-staging`)**: `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` (publicly invokable via `allUsers` `roles/run.invoker` for the NASA Space Apps demo, `GCP_REQUIRE_INVOKER_IAM=false` default in `cd-deploy.yml`; scales `0..2` with `$0` idle cost, `run.googleapis.com/cpu-throttling: "false"`, `SPHEREX_LEGACY_SYNC_ENABLED=false`, and arbitrary coordinate queries served via the bounded async job queue `POST /api/v1/jobs`, capped at 6 new jobs/min and 8 outstanding).
- **GCS Bucket (`gs://bortle-cero-nasa-staging-26-spherex-bundles-staging`)**: Stores the five durable benchmark snapshots under `benchmarks/v1/`. Other live results use per-instance SQLite. Private, versioned, with a lifecycle rule deleting noncurrent versions after 7 days (keeping up to 3 newer versions) and `queries/` cache objects after 30 days.
- **Budget Alert**: Monthly budget alert set to `20 MXN` (~$1 USD) with thresholds at 50%, 90%, and 100%.
- **GitHub `staging` Environment**: Configured with all 8 `GCP_*` variables for keyless OIDC/WIF deployment via [`.github/workflows/cd-deploy.yml`](../../.github/workflows/cd-deploy.yml).
- **Static Web Viewer**: Hosted on the public GCS bucket `gs://bortle-cero-nasa-staging-26-viewer` (`https://bortle-cero-nasa-staging-26-viewer.storage.googleapis.com/index.html`) and deployed automatically on every push to `main` by `.github/workflows/cd-deploy.yml` with `Cache-Control: no-cache` on entrypoints/manifest and `public, max-age=31536000, immutable` on `releases/**` (with Firebase Hosting via `firebase.json` as an optional alternative). Run locally with `uv run python -m http.server 8765 --directory mockup`.
