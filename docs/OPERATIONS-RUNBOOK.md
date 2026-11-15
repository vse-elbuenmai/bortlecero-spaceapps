# Operations Runbook — Bortle Cero SPHEREx Ingestion & Viewer

This runbook defines observability, alerting, ownership, and rollback procedures for the **Bortle Cero** SPHEREx Blink Comparator across staging (`bortle-cero-nasa-staging-26`) and production environments.

---

## 1. Architecture & Operator Ownership

| Component | Runtime / Hosting | Identity / Access | Primary Owner |
|---|---|---|---|
| **Ingestion API** (`spherex-ingest`) | Google Cloud Run (`gen2`, `us-central1`) | `spherex-runtime-<env>` (private invoker IAM in staging) | Backend / Cloud Delivery Lead |
| **Container Registry** | Google Artifact Registry (`spherex-ingest`) | `spherex-deploy-<env>` via GitHub OIDC/WIF | Cloud Delivery Lead |
| **Data Bundles** | GCS (`<project>-spherex-bundles-<env>`, versioned) + `mockup/data/` | Uniform bucket-level access, public access prevented | Data Pipeline Lead |
| **Static Viewer** (`mockup/`) | Static web hosting (GitHub Pages / Vercel / GCS) | Public read-only static assets | Frontend Lead |

- **Keyless CI/CD:** GitHub Actions (`.github/workflows/cd-deploy.yml`) authenticates via `google-github-actions/auth@v2` and OIDC Workload Identity Federation. Long-lived JSON keys are prohibited.
- **Untrusted PR Isolation:** Pull requests run only CI (`ci-pr-*.yml`, `ci-cloud-run-container.yml`) with `contents: read` and never receive deployment credentials.

---

## 2. Structured Logging & Cloud Logging Queries

Cloud Run automatically captures stdout/stderr from `uvicorn` and enriches each log entry with `resource.labels.service_name`, `resource.labels.revision_name` (`K_REVISION`), and HTTP request metadata.

### Useful Cloud Logging Filters

- **All errors in staging (`severity >= ERROR`):**
  ```text
  resource.type="cloud_run_revision"
  resource.labels.service_name="spherex-ingest-staging"
  severity>=ERROR
  ```

- **Filter by specific Cloud Run revision:**
  ```text
  resource.type="cloud_run_revision"
  resource.labels.revision_name="spherex-ingest-staging-00004-xyz"
  ```

- **Slow requests (`latency > 10s`) or HTTP 5xx responses:**
  ```text
  resource.type="cloud_run_revision"
  resource.labels.service_name="spherex-ingest-staging"
  (httpRequest.status>=500 OR httpRequest.latency>"10s")
  ```

### Log Retention

- Cloud Logging `_Default` bucket retains logs for **30 days** by default.
- For longer audit retention during hackathon judging, configure a custom retention period (e.g., 90 days) on the `_Default` bucket:
  ```bash
  gcloud logging buckets update _Default \
    --location=global \
    --retention-days=90 \
    --project=bortle-cero-nasa-staging-26
  ```

---

## 3. Metrics & SLO Targets

| Metric (Cloud Monitoring) | Target / SLO | Alert Threshold |
|---|---|---|
| `run.googleapis.com/request_count` (`response_code_class="5xx"`) | `< 1%` 5xx rate | `> 5%` over 5 minutes |
| `run.googleapis.com/request_latencies` (p95 on `/api/v1/health`) | `< 500 ms` | `> 2000 ms` over 5 minutes |
| `run.googleapis.com/request_latencies` (p95 on `/api/v1/blink`) | `< 215 s` (cold IRSA) | `> 270 s` (near 300 s timeout) |
| `run.googleapis.com/container/memory/utilizations` (p95) | `< 75%` of 1 GiB | `> 85%` over 5 minutes |
| `run.googleapis.com/container/billable_instance_time` | Scale to zero (`minScale=0`) | Unexpected sustained `maxScale=2` |

---

## 4. Uptime Checks & Alerting

### Health Endpoint Uptime Check

The `/api/v1/health` endpoint returns HTTP 200 with package version, `K_REVISION`, and `legacy_sync_enabled` without contacting IRSA.

For public production endpoints, create a Cloud Monitoring HTTPS uptime check:

```bash
gcloud monitoring uptime create spherex-api-health \
  --display-name="SPHEREx Ingestion API Health" \
  --resource-type="uptime-url" \
  --resource-labels="host=<CLOUD_RUN_HOST>,project_id=<PROJECT_ID>" \
  --path="/api/v1/health" \
  --protocol="https" \
  --period="60" \
  --timeout="10" \
  --project="<PROJECT_ID>"
```

> **Note:** Private staging (`invoker-iam-disabled: "false"`) rejects unauthenticated requests with HTTP 401/403 by design; verify staging health via `cd-deploy.yml` OIDC smoke checks or `gcloud run services proxy`.

### Notification Channel & Alert Policy

Create an email or Slack notification channel in Cloud Monitoring, then attach an alert policy for 5xx error bursts:

```bash
gcloud monitoring channels list --project="<PROJECT_ID>"
```

Recommended alert policies to keep enabled in Cloud Monitoring:
1. **High 5xx Error Rate:** `run.googleapis.com/request_count` filtered by `response_code_class="5xx"` > 5% over 5 minutes.
2. **Memory Saturation:** `run.googleapis.com/container/memory/utilizations` > 0.85 over 5 minutes (prevents OOM kills from `/scratch` tmpfs + NumPy/Astropy buffers).
3. **Uptime Check Failure:** At least 2 consecutive failures across regions on `/api/v1/health`.

---

## 5. Step-by-Step Rollback Procedures

### A. Backend Rollback (Cloud Run)

**Option 1 — Instant Revision Traffic Shift (fastest, < 15 seconds):**
1. List recent healthy revisions:
   ```bash
   gcloud run revisions list \
     --service="spherex-ingest-staging" \
     --region="us-central1" \
     --project="bortle-cero-nasa-staging-26"
   ```
2. Shift 100% of traffic to the last known-good revision (via GitHub Actions **CD / Cloud Run Keyless Delivery** -> `workflow_dispatch` -> `action: rollback`, `revision: <REVISION_NAME>`, or via CLI):
   ```bash
   gcloud run services update-traffic "spherex-ingest-staging" \
     --to-revisions="<LAST_GOOD_REVISION>=100" \
     --region="us-central1" \
     --project="bortle-cero-nasa-staging-26"
   ```
3. Verify `/api/v1/health` returns the expected `revision` and HTTP 200.

**Option 2 — Redeploy Previous Immutable Image Digest:**
1. Find the previous digest in Artifact Registry:
   ```bash
   gcloud artifacts docker images list \
     "us-central1-docker.pkg.dev/bortle-cero-nasa-staging-26/spherex-ingest/spherex-ingest" \
     --include-tags --sort-by="~UPDATE_TIME"
   ```
2. Trigger **CD / Cloud Run Keyless Delivery** with `action: rollback` and `image_digest: <REGION>-docker.pkg.dev/<PROJECT>/<REPO>/spherex-ingest@sha256:<DIGEST>`.

### B. Frontend Rollback (Static Viewer)

1. Identify the last known-good commit on `main` (`git log --oneline -n 10`).
2. Revert the offending frontend commit cleanly (`git revert <BAD_SHA>`) and open a PR to `main`, **or** redeploy the previous static build artifact from CI/hosting dashboard (Vercel/GitHub Pages deployment history -> **Promote to Production**).
3. Verify the viewer loads `mockup/data/<target>.json` and renders blink frames without console errors.

### C. Data Rollback (Benchmark Bundles & GCS)

**In-Repo Static Bundles (`mockup/data/`):**
1. Restore the previous bundle version from git:
   ```bash
   git checkout <LAST_GOOD_SHA> -- mockup/data/
   ```
2. Validate bundle integrity with `uv run pytest tests/test_mockup_integration.py` before pushing.

**GCS Bucket Bundles (`gs://<project>-spherex-bundles-<env>`):**
1. Object versioning is enabled by `deploy/gcp/bootstrap.sh`. List object generations:
   ```bash
   gcloud storage ls -a "gs://<BUCKET>/<OBJECT_PATH>"
   ```
2. Restore the prior generation (`#<GENERATION>`):
   ```bash
   gcloud storage cp "gs://<BUCKET>/<OBJECT_PATH>#<GENERATION>" "gs://<BUCKET>/<OBJECT_PATH>"
   ```
3. Confirm the API or static viewer serves the restored bundle checksum.
