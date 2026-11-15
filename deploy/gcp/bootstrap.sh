#!/usr/bin/env bash
# Idempotent GCP infrastructure bootstrap for Bortle Cero SPHEREx Ingestion API.
# Provisions Artifact Registry, GCS bucket, least-privilege IAM service accounts,
# and GitHub Actions OIDC Workload Identity Federation (keyless delivery).
#
# Usage:
#   PROJECT_ID=bortle-cero-nasa-staging-26 \
#   GITHUB_REPO=vse-elbuenmai/bortlecero-spaceapps \
#   ./deploy/gcp/bootstrap.sh
#
#   Add --dry-run (or DRY_RUN=true) to print commands without executing them.

set -euo pipefail

DRY_RUN="${DRY_RUN:-false}"
for arg in "$@"; do
  case "${arg}" in
    --dry-run)
      DRY_RUN="true"
      ;;
    --help|-h)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: ${arg}" >&2
      exit 1
      ;;
  esac
done

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID (e.g. bortle-cero-nasa-staging-26)}"
GITHUB_REPO="${GITHUB_REPO:?Set GITHUB_REPO (e.g. vse-elbuenmai/bortlecero-spaceapps)}"
REGION="${REGION:-us-central1}"
ENVIRONMENT="${ENVIRONMENT:-staging}"
SERVICE_NAME="${SERVICE_NAME:-spherex-ingest-${ENVIRONMENT}}"
AR_REPO="${AR_REPO:-spherex-ingest}"
GCS_BUCKET="${GCS_BUCKET:-${PROJECT_ID}-spherex-bundles-${ENVIRONMENT}}"
WIF_POOL_ID="${WIF_POOL_ID:-github-actions-pool}"
WIF_PROVIDER_ID="${WIF_PROVIDER_ID:-github-oidc-provider}"
DEPLOY_SA_NAME="${DEPLOY_SA_NAME:-spherex-deploy-${ENVIRONMENT}}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-spherex-runtime-${ENVIRONMENT}}"

DEPLOY_SA_EMAIL="${DEPLOY_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA_EMAIL="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

echo "==> Bootstrapping GCP project '${PROJECT_ID}' (env=${ENVIRONMENT}, region=${REGION}, dry_run=${DRY_RUN})"

echo "==> 1. Enabling required Google Cloud APIs"
run gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  storage.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  --project="${PROJECT_ID}"

echo "==> 2. Ensuring Artifact Registry Docker repository '${AR_REPO}'"
if [[ "${DRY_RUN}" == "true" ]] || ! gcloud artifacts repositories describe "${AR_REPO}" \
  --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  run gcloud artifacts repositories create "${AR_REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Bortle Cero SPHEREx ingestion API container images" \
    --project="${PROJECT_ID}"
fi

echo "==> 3. Ensuring private versioned GCS bucket 'gs://${GCS_BUCKET}'"
if [[ "${DRY_RUN}" == "true" ]] || ! gcloud storage buckets describe "gs://${GCS_BUCKET}" \
  --project="${PROJECT_ID}" >/dev/null 2>&1; then
  run gcloud storage buckets create "gs://${GCS_BUCKET}" \
    --project="${PROJECT_ID}" \
    --location="${REGION}" \
    --uniform-bucket-level-access \
    --public-access-prevention
fi
run gcloud storage buckets update "gs://${GCS_BUCKET}" --versioning

echo "==> 4. Ensuring least-privilege Service Accounts (deploy vs runtime)"
for sa_spec in \
  "${RUNTIME_SA_NAME}:Bortle Cero Cloud Run runtime identity (${ENVIRONMENT})" \
  "${DEPLOY_SA_NAME}:Bortle Cero GitHub Actions OIDC deploy identity (${ENVIRONMENT})"; do
  sa_name="${sa_spec%%:*}"
  sa_desc="${sa_spec#*:}"
  sa_email="${sa_name}@${PROJECT_ID}.iam.gserviceaccount.com"
  if [[ "${DRY_RUN}" == "true" ]] || ! gcloud iam service-accounts describe "${sa_email}" \
    --project="${PROJECT_ID}" >/dev/null 2>&1; then
    run gcloud iam service-accounts create "${sa_name}" \
      --display-name="${sa_desc}" \
      --project="${PROJECT_ID}"
  fi
done

echo "==> 5. Binding least-privilege IAM roles to Runtime SA (${RUNTIME_SA_EMAIL})"
for role in roles/logging.logWriter roles/monitoring.metricWriter; do
  run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet
done
run gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
  --role="roles/storage.objectUser" \
  --quiet

echo "==> 6. Binding least-privilege IAM roles to Deploy SA (${DEPLOY_SA_EMAIL})"
run gcloud artifacts repositories add-iam-policy-binding "${AR_REPO}" \
  --location="${REGION}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role="roles/artifactregistry.writer" \
  --quiet
for role in roles/run.developer roles/run.invoker; do
  run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet
done
run gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" \
  --quiet
run gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role="roles/storage.objectAdmin" \
  --quiet

echo "==> 7. Configuring GitHub OIDC Workload Identity Federation"
if [[ "${DRY_RUN}" == "true" ]] || ! gcloud iam workload-identity-pools describe "${WIF_POOL_ID}" \
  --location="global" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  run gcloud iam workload-identity-pools create "${WIF_POOL_ID}" \
    --location="global" \
    --display-name="GitHub Actions OIDC Pool" \
    --project="${PROJECT_ID}"
fi

if [[ "${DRY_RUN}" == "true" ]] || ! gcloud iam workload-identity-pools providers describe "${WIF_PROVIDER_ID}" \
  --workload-identity-pool="${WIF_POOL_ID}" --location="global" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  run gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER_ID}" \
    --location="global" \
    --workload-identity-pool="${WIF_POOL_ID}" \
    --display-name="GitHub OIDC Provider" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
    --attribute-condition="assertion.repository == '${GITHUB_REPO}'" \
    --project="${PROJECT_ID}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
  PROJECT_NUMBER="<PROJECT_NUMBER>"
else
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
fi

WIF_PRINCIPAL="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/attribute.repository/${GITHUB_REPO}"
WIF_PROVIDER_FULL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL_ID}/providers/${WIF_PROVIDER_ID}"

run gcloud iam service-accounts add-iam-policy-binding "${DEPLOY_SA_EMAIL}" \
  --project="${PROJECT_ID}" \
  --member="${WIF_PRINCIPAL}" \
  --role="roles/iam.workloadIdentityUser" \
  --quiet

cat <<EOF

==> Bootstrap complete. Configure these GitHub Environment ('${ENVIRONMENT}') variables:
  GCP_PROJECT_ID=${PROJECT_ID}
  GCP_REGION=${REGION}
  GCP_AR_REPOSITORY=${AR_REPO}
  GCP_CLOUD_RUN_SERVICE=${SERVICE_NAME}
  GCP_GCS_BUCKET=${GCS_BUCKET}
  GCP_RUNTIME_SERVICE_ACCOUNT=${RUNTIME_SA_EMAIL}
  GCP_DEPLOY_SERVICE_ACCOUNT=${DEPLOY_SA_EMAIL}
  GCP_WIF_PROVIDER=${WIF_PROVIDER_FULL}
EOF
