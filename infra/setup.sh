#!/usr/bin/env bash
# One-time GCP setup for the backend. Idempotent: safe to re-run.
# Requires: gcloud logged in, billing linked to the project.
#
#   PROJECT=tradeit-511910 ./infra/setup.sh
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-southeast1}"
BUCKET="${BUCKET:-${PROJECT}-tradecheck-docs}"
SQL_INSTANCE="${SQL_INSTANCE:-tradecheck-pg}"
DB_NAME="${DB_NAME:-tradecheck}"
DB_USER="${DB_USER:-tradecheck}"
QUEUE="${QUEUE:-pipeline}"
KEYRING="${KEYRING:-tradecheck}"
KEY="${KEY:-report-signing}"
ORIGINS="${ALLOWED_ORIGINS:-*}"

gc() { gcloud --project "$PROJECT" "$@"; }
exists() { "$@" >/dev/null 2>&1; }

echo "== APIs"
gc services enable run.googleapis.com sqladmin.googleapis.com cloudtasks.googleapis.com cloudkms.googleapis.com \
  storage.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com iamcredentials.googleapis.com \
  secretmanager.googleapis.com identitytoolkit.googleapis.com firebase.googleapis.com logging.googleapis.com

echo "== Service accounts"
for sa in api-sa worker-sa; do
  exists gc iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com" ||
    gc iam service-accounts create "$sa" --display-name "tradecheck $sa"
done
API_SA="api-sa@$PROJECT.iam.gserviceaccount.com"
WORKER_SA="worker-sa@$PROJECT.iam.gserviceaccount.com"

for sa in "$API_SA" "$WORKER_SA"; do
  for role in roles/cloudsql.client roles/cloudtasks.enqueuer roles/logging.logWriter; do
    gc projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" --role "$role" --condition=None -q >/dev/null
  done
  # Sign GCS URLs through the IAM signBlob API (no private keys on Cloud Run).
  gc iam service-accounts add-iam-policy-binding "$sa" --member "serviceAccount:$sa" \
    --role roles/iam.serviceAccountTokenCreator -q >/dev/null
done
# Cloud Tasks mints OIDC tokens as worker-sa; both services enqueue tasks, so both may act as it.
for sa in "$API_SA" "$WORKER_SA"; do
  gc iam service-accounts add-iam-policy-binding "$WORKER_SA" --member "serviceAccount:$sa" \
    --role roles/iam.serviceAccountUser -q >/dev/null
done

echo "== Cloud Storage"
exists gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" ||
  gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
cat > /tmp/tradecheck-cors.json <<EOF
[{"origin": ["${ORIGINS//,/\",\"}"], "method": ["PUT", "GET", "HEAD"],
  "responseHeader": ["Content-Type"], "maxAgeSeconds": 3600}]
EOF
gcloud storage buckets update "gs://$BUCKET" --project "$PROJECT" --cors-file /tmp/tradecheck-cors.json
for sa in "$API_SA" "$WORKER_SA"; do
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$PROJECT" \
    --member "serviceAccount:$sa" --role roles/storage.objectAdmin -q >/dev/null
done

echo "== Cloud SQL (PostgreSQL 16, smallest tier; takes ~10 minutes the first time)"
exists gc sql instances describe "$SQL_INSTANCE" ||
  gc sql instances create "$SQL_INSTANCE" --database-version POSTGRES_16 --edition enterprise \
    --tier db-f1-micro --region "$REGION" --storage-size 10 --storage-auto-increase
exists gc sql databases describe "$DB_NAME" --instance "$SQL_INSTANCE" ||
  gc sql databases create "$DB_NAME" --instance "$SQL_INSTANCE"
if ! exists gc secrets describe tradecheck-db-password; then
  PW="$(openssl rand -base64 24 | tr -d '/+=')"
  printf '%s' "$PW" | gc secrets create tradecheck-db-password --data-file=- --replication-policy automatic
  gc sql users create "$DB_USER" --instance "$SQL_INSTANCE" --password "$PW"
fi
for sa in "$API_SA" "$WORKER_SA"; do
  gc secrets add-iam-policy-binding tradecheck-db-password --member "serviceAccount:$sa" \
    --role roles/secretmanager.secretAccessor -q >/dev/null
done

echo "== Cloud Tasks"
exists gc tasks queues describe "$QUEUE" --location "$REGION" ||
  gc tasks queues create "$QUEUE" --location "$REGION" --max-attempts 5 --min-backoff 10s \
    --max-backoff 300s --max-doublings 4

echo "== Cloud KMS report-signing key"
exists gc kms keyrings describe "$KEYRING" --location "$REGION" || gc kms keyrings create "$KEYRING" --location "$REGION"
exists gc kms keys describe "$KEY" --keyring "$KEYRING" --location "$REGION" ||
  gc kms keys create "$KEY" --keyring "$KEYRING" --location "$REGION" --purpose asymmetric-signing \
    --default-algorithm ec-sign-p256-sha256
gc kms keys add-iam-policy-binding "$KEY" --keyring "$KEYRING" --location "$REGION" \
  --member "serviceAccount:$API_SA" --role roles/cloudkms.signerVerifier -q >/dev/null

echo
echo "Setup complete. Next: PROJECT=$PROJECT ./infra/deploy.sh"
