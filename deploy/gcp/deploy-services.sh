#!/usr/bin/env bash
# Deploy and verify the private worker before deploying the public API.
set -euo pipefail

: "${PROJECT_ID:?}" "${REGION:?}" "${SERVICE_NAME:?}"
: "${RUNTIME_SA:?}" "${DEPLOY_SA:?}" "${TASKS_SA:?}" "${WORKER_SA:?}"
: "${BUNDLE_BUCKET:?}" "${IMAGE_DIGEST:?}" "${CODE_SHA:?}"
[[ "${CODE_SHA}" =~ ^[0-9a-f]{40}$ ]] || { echo "CODE_SHA must be the image's Git SHA." >&2; exit 1; }
[[ "${IMAGE_DIGEST}" =~ @sha256:[0-9a-f]{64}$ ]] || { echo "An immutable image digest is required." >&2; exit 1; }

WORKER_NAME="${SERVICE_NAME}-worker"
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
HOST_LABEL="${WORKER_NAME}-${PROJECT_NUMBER}"
if [[ -z "${PROJECT_NUMBER}" || ${#HOST_LABEL} -gt 63 ]]; then
  echo "The worker requires a deterministic Cloud Run URL." >&2
  exit 1
fi
WORKER_URL="https://${HOST_LABEL}.${REGION}.run.app"
template="$(dirname "$0")/../cloud-run/service.yaml"
rendered="$(mktemp)"
trap 'rm -f "${rendered}"' EXIT

deploy_service() {
  local name="$1" account="$2" max_instances="$3" concurrency="$4" timeout="$5"
  local submissions="$6" worker="$7"
  sed \
    -e "s|__SERVICE_NAME__|${name}|g" \
    -e "s|__RUNTIME_SERVICE_ACCOUNT__|${account}|g" \
    -e "s|__MAX_INSTANCES__|${max_instances}|g" \
    -e "s|__CONCURRENCY__|${concurrency}|g" \
    -e "s|__TIMEOUT_SECONDS__|${timeout}|g" \
    -e "s|__SUBMISSIONS_ENABLED__|${submissions}|g" \
    -e "s|__WORKER_ENABLED__|${worker}|g" \
    -e "s|__IMAGE_DIGEST__|${IMAGE_DIGEST}|g" \
    -e "s|__CODE_SHA__|${CODE_SHA}|g" \
    -e "s|__BUNDLE_BUCKET__|${BUNDLE_BUCKET}|g" \
    -e "s|__PROJECT_ID__|${PROJECT_ID}|g" \
    -e "s|__REGION__|${REGION}|g" \
    -e "s|__TASKS_QUEUE__|${SERVICE_NAME}|g" \
    -e "s|__TASKS_SERVICE_ACCOUNT__|${TASKS_SA}|g" \
    -e "s|__WORKER_URL__|${WORKER_URL}|g" \
    "${template}" > "${rendered}"
  gcloud run services replace "${rendered}" --project="${PROJECT_ID}" --region="${REGION}"
}

# The one-task queue and one-request worker put a ceiling on simultaneous IRSA ingestion.
deploy_service "${WORKER_NAME}" "${WORKER_SA}" 1 1 210 false true
worker_token="$(gcloud auth print-identity-token \
  --impersonate-service-account="${DEPLOY_SA}" --audiences="${WORKER_URL}")"
unauthenticated="$(curl -sS --max-time 45 -o /dev/null -w '%{http_code}' "${WORKER_URL}/api/v1/health")"
[[ "${unauthenticated}" == 401 || "${unauthenticated}" == 403 ]]
curl -fsS --max-time 45 -H "Authorization: Bearer ${worker_token}" "${WORKER_URL}/api/v1/health" \
  | python3 -c 'import json,sys; h=json.load(sys.stdin); assert h["status"]=="ok" and h["revision"] and not h["async_jobs_enabled"], h; print("Worker ready:", h["revision"])'

# An authenticated delivery to a nonexistent ID verifies IAM, OIDC and the Firestore connection.
# It submits no ingestion and contacts no upstream archive.
deploy_access_token="$(gcloud auth print-access-token)"
task_token="$(curl -fsS --max-time 20 \
  -H "Authorization: Bearer ${deploy_access_token}" -H "Content-Type: application/json" \
  --data "{\"audience\":\"${WORKER_URL}\",\"includeEmail\":true}" \
  "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${TASKS_SA}:generateIdToken" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
unset deploy_access_token
probe_status="$(curl -sS --max-time 45 -o "${rendered}" -w '%{http_code}' \
  -H "Authorization: Bearer ${task_token}" \
  -H "X-CloudTasks-TaskName: deployment-probe" -H "Content-Type: application/json" \
  --data '{"job_id":"deployment-probe","request_key":"deployment-probe","correlation_id":"deployment-probe"}' \
  "${WORKER_URL}/internal/worker/ingest")"
[[ "${probe_status}" == 404 ]] || { echo "Worker delivery probe returned HTTP ${probe_status}." >&2; exit 1; }
python3 -c 'import json,sys; h=json.load(open(sys.argv[1])); assert h["status"]=="not_found", h' "${rendered}"

deploy_service "${SERVICE_NAME}" "${RUNTIME_SA}" 2 8 60 true false
