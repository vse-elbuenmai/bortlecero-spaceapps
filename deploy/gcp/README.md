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

- **Cloud Run API (`spherex-ingest-staging`)**: `https://spherex-ingest-staging-g7enhg3w4a-uc.a.run.app` (private IAM-invoked; scales `0..2` with `$0` idle cost and `SPHEREX_LEGACY_SYNC_ENABLED=false`).
- **GCS Bucket (`gs://bortle-cero-nasa-staging-26-spherex-bundles-staging`)**: Private, versioned, with a lifecycle rule deleting noncurrent versions after 7 days (keeping up to 3 newer versions) and `queries/` cache objects after 30 days.
- **Budget Alert**: Monthly budget alert set to `20 MXN` (~$1 USD) with thresholds at 50%, 90%, and 100%.
- **GitHub `staging` Environment**: Configured with all 8 `GCP_*` variables for keyless OIDC/WIF deployment via [`.github/workflows/cd-deploy.yml`](../../.github/workflows/cd-deploy.yml).
- **Static Web Viewer**: The public frontend (`mockup/`) is not yet deployed to Firebase Hosting. Run it locally with `uv run python -m http.server 8765 --directory mockup`, or stage and deploy to Firebase Hosting with `uv run python scripts/build_hosting.py` and `firebase deploy --only hosting`.
