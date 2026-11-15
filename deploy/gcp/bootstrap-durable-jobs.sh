#!/usr/bin/env bash
# Provision shared job state and the authenticated HTTP task queue.
set -euo pipefail

: "${PROJECT_ID:?Set the target Google Cloud project}"
REGION="${REGION:-us-central1}"
ENVIRONMENT="${ENVIRONMENT:-staging}"
SERVICE_NAME="${SERVICE_NAME:-spherex-ingest-${ENVIRONMENT}}"
GCS_BUCKET="${GCS_BUCKET:-${PROJECT_ID}-spherex-bundles-${ENVIRONMENT}}"
RUNTIME_SA_EMAIL="${RUNTIME_SA_EMAIL:-spherex-runtime-${ENVIRONMENT}@${PROJECT_ID}.iam.gserviceaccount.com}"
DEPLOY_SA_EMAIL="${DEPLOY_SA_EMAIL:-spherex-deploy-${ENVIRONMENT}@${PROJECT_ID}.iam.gserviceaccount.com}"
WORKER_SA_NAME="spherex-worker-${ENVIRONMENT}"
TASKS_SA_NAME="spherex-tasks-${ENVIRONMENT}"
WORKER_SA_EMAIL="${WORKER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
TASKS_SA_EMAIL="${TASKS_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DRY_RUN=false
case "${1:-}" in
  --dry-run) DRY_RUN=true ;;
  "") ;;
  *) echo "Usage: bash $0 [--dry-run]" >&2; exit 1 ;;
esac

run() {
  if "${DRY_RUN}"; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

project=(--project="${PROJECT_ID}" --quiet)
run gcloud services enable cloudresourcemanager.googleapis.com firestore.googleapis.com \
  cloudtasks.googleapis.com "${project[@]}"
if "${DRY_RUN}"; then
  project_number=PROJECT_NUMBER
else
  project_number="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
fi
worker_label="${SERVICE_NAME}-worker-${project_number}"
if [[ -z "${project_number}" || ${#worker_label} -gt 63 ]]; then
  echo "The worker requires a deterministic Cloud Run URL." >&2
  exit 1
fi
worker_host="${worker_label}.${REGION}.run.app"

if "${DRY_RUN}" || ! gcloud firestore databases describe --database='(default)' "${project[@]}" >/dev/null 2>&1; then
  run gcloud firestore databases create --database='(default)' --location="${REGION}" \
    --type=firestore-native "${project[@]}"
fi
for collection in spherex_jobs spherex_job_keys; do
  run gcloud firestore fields ttls update expires_at --collection-group="${collection}" \
    --database='(default)' --enable-ttl --async "${project[@]}"
done

for name in "${WORKER_SA_NAME}" "${TASKS_SA_NAME}"; do
  if "${DRY_RUN}" || ! gcloud iam service-accounts describe \
    "${name}@${PROJECT_ID}.iam.gserviceaccount.com" "${project[@]}" >/dev/null 2>&1; then
    run gcloud iam service-accounts create "${name}" "${project[@]}"
  fi
done

for account in "${RUNTIME_SA_EMAIL}" "${WORKER_SA_EMAIL}"; do
  run gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${account}" \
    --role=roles/datastore.user --condition=None --quiet
done
run gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member="serviceAccount:${WORKER_SA_EMAIL}" --role=roles/storage.objectUser "${project[@]}"
run gcloud iam service-accounts add-iam-policy-binding "${WORKER_SA_EMAIL}" \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" --role=roles/iam.serviceAccountUser "${project[@]}"
run gcloud iam service-accounts add-iam-policy-binding "${TASKS_SA_EMAIL}" \
  --member="serviceAccount:${RUNTIME_SA_EMAIL}" --role=roles/iam.serviceAccountUser "${project[@]}"
# The deploy identity can verify the task identity on the worker without submitting a live job.
run gcloud iam service-accounts add-iam-policy-binding "${TASKS_SA_EMAIL}" \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role=roles/iam.serviceAccountOpenIdTokenCreator "${project[@]}"

# Scope invocation to the deterministic worker URL and the task endpoint.
run gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${TASKS_SA_EMAIL}" --role=roles/run.invoker --quiet \
  --condition="title=SpherexTask-${ENVIRONMENT},expression=request.host == '${worker_host}' && request.path == '/internal/worker/ingest'"

queue=( "${SERVICE_NAME}" --location="${REGION}" "${project[@]}" )
queue_limits=( --max-concurrent-dispatches=1 --max-dispatches-per-second=1
  --max-attempts=6 --min-backoff=15s --max-backoff=60s --log-sampling-ratio=1 )
if "${DRY_RUN}" || ! gcloud tasks queues describe "${queue[@]}" >/dev/null 2>&1; then
  run gcloud tasks queues create "${queue[@]}" "${queue_limits[@]}"
else
  run gcloud tasks queues update "${queue[@]}" "${queue_limits[@]}"
fi
run gcloud tasks queues add-iam-policy-binding "${queue[@]}" \
  --member="serviceAccount:${RUNTIME_SA_EMAIL}" --role=roles/cloudtasks.enqueuer

# Preserve existing lifecycle rules and add a rule limited to live-query objects when needed.
if "${DRY_RUN}"; then
  echo '[dry-run] Keep an existing Delete rule of at most 30 days for queries/ or queries/v1/.'
  echo '[dry-run] If absent, add an eight-day Delete rule for queries/v1/ only.'
else
  lifecycle="$(mktemp)"
  trap 'rm -f "${lifecycle}"' EXIT
  gcloud storage buckets describe "gs://${GCS_BUCKET}" "${project[@]}" --format='json(lifecycle_config)' \
    | python3 -c 'import json,sys
rules = (json.load(sys.stdin).get("lifecycle_config") or {}).get("rule", [])
for rule in rules:
    condition = rule.get("condition", {})
    if (rule["action"]["type"] == "Delete" and set(condition) == {"age", "matchesPrefix"}
        and condition["age"] <= 30 and {"queries/", "queries/v1/"}.intersection(condition["matchesPrefix"])):
        break
else:
    rules.append({"action": {"type": "Delete"}, "condition": {"age": 8, "matchesPrefix": ["queries/v1/"]}})
    print(json.dumps({"rule": rules}))' > "${lifecycle}"
  if [[ -s "${lifecycle}" ]]; then
    run gcloud storage buckets update "gs://${GCS_BUCKET}" --lifecycle-file="${lifecycle}" "${project[@]}"
  fi
fi
