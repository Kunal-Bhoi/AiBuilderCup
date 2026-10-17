#!/usr/bin/env bash
# Deploy worker-service and api-service from source (Cloud Build + Google Cloud buildpacks;
# no Dockerfile, no local Docker), then run migrations as a Cloud Run Job.
#
#   PROJECT=tradeit-511910 ./infra/deploy.sh
#   AI_MODE=http AI_SERVICE_URL=https://ai-service-xxxx.a.run.app AUTH_MODE=firebase PROJECT=... ./infra/deploy.sh
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-southeast1}"
BUCKET="${BUCKET:-${PROJECT}-tradecheck-docs}"
SQL_INSTANCE="${SQL_INSTANCE:-tradecheck-pg}"
QUEUE="${QUEUE:-pipeline}"
KEYRING="${KEYRING:-tradecheck}"
KEY="${KEY:-report-signing}"
AI_MODE="${AI_MODE:-stub}"
AI_SERVICE_URL="${AI_SERVICE_URL:-}"
AUTH_MODE="${AUTH_MODE:-dev}"
ORIGINS="${ALLOWED_ORIGINS:-*}"
API_MIN_INSTANCES="${API_MIN_INSTANCES:-0}"   # set to 1 on judging day

SRC="$(cd "$(dirname "$0")/../backend" && pwd)"
API_SA="api-sa@$PROJECT.iam.gserviceaccount.com"
WORKER_SA="worker-sa@$PROJECT.iam.gserviceaccount.com"
CONN="$PROJECT:$REGION:$SQL_INSTANCE"
KMS_VERSION="projects/$PROJECT/locations/$REGION/keyRings/$KEYRING/cryptoKeys/$KEY/cryptoKeyVersions/1"
gc() { gcloud --project "$PROJECT" "$@"; }

common_env() {
  echo "^;^ENVIRONMENT=prod;GCP_PROJECT=$PROJECT;GCP_REGION=$REGION;GCS_BUCKET=$BUCKET;STORAGE_MODE=gcs;\
CLOUD_SQL_INSTANCE=$CONN;DB_USER=tradecheck;DB_NAME=tradecheck;TASKS_MODE=cloudtasks;TASKS_QUEUE=$QUEUE;\
TASKS_SERVICE_ACCOUNT=$WORKER_SA;AI_MODE=$AI_MODE;AI_SERVICE_URL=$AI_SERVICE_URL;AUTH_MODE=$AUTH_MODE;\
FIREBASE_PROJECT=$PROJECT;SIGNING_MODE=kms;KMS_KEY_VERSION=$KMS_VERSION;ALLOWED_ORIGINS=$ORIGINS;$1"
}

echo "== worker-service (internal ingress, invoked only by Cloud Tasks as worker-sa)"
gc run deploy worker-service --source "$SRC" --region "$REGION" --service-account "$WORKER_SA" \
  --no-allow-unauthenticated --ingress internal --cpu 2 --memory 2Gi --concurrency 1 --timeout 1800 \
  --no-cpu-throttling --min-instances 0 --max-instances 20 \
  --set-secrets DB_PASSWORD=tradecheck-db-password:latest \
  --set-env-vars "$(common_env "SERVICE_ROLE=worker")" -q
WORKER_URL="$(gc run services describe worker-service --region "$REGION" --format 'value(status.url)')"
gc run services add-iam-policy-binding worker-service --region "$REGION" \
  --member "serviceAccount:$WORKER_SA" --role roles/run.invoker -q >/dev/null
gc run services update worker-service --region "$REGION" \
  --update-env-vars "WORKER_URL=$WORKER_URL" -q >/dev/null

IMAGE="$(gc run services describe worker-service --region "$REGION" \
  --format 'value(spec.template.spec.containers[0].image)')"

echo "== migrations (Cloud Run Job, before traffic shifts)"
gc run jobs deploy tradecheck-migrate --image "$IMAGE" --region "$REGION" --service-account "$WORKER_SA" \
  --set-secrets DB_PASSWORD=tradecheck-db-password:latest \
  --set-env-vars "$(common_env "SERVICE_ROLE=worker")" \
  --command python --args=-m,alembic,upgrade,head --max-retries 0 -q
gc run jobs execute tradecheck-migrate --region "$REGION" --wait -q

echo "== api-service (public; the app enforces Firebase auth)"
gc run deploy api-service --image "$IMAGE" --region "$REGION" --service-account "$API_SA" \
  --allow-unauthenticated --cpu 1 --memory 512Mi --concurrency 80 --timeout 900 \
  --min-instances "$API_MIN_INSTANCES" --max-instances 10 \
  --set-secrets DB_PASSWORD=tradecheck-db-password:latest \
  --set-env-vars "$(common_env "SERVICE_ROLE=api;WORKER_URL=$WORKER_URL")" -q
API_URL="$(gc run services describe api-service --region "$REGION" --format 'value(status.url)')"
gc run services update api-service --region "$REGION" --update-env-vars "PUBLIC_BASE_URL=$API_URL" -q >/dev/null

echo
echo "api-service:    $API_URL   (docs: $API_URL/docs, health: $API_URL/health)"
echo "worker-service: $WORKER_URL (internal)"
