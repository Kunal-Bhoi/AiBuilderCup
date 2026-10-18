#!/usr/bin/env bash
# One-time GCP setup. Idempotent: every step checks first and skips what already exists,
# so it is safe to re-run after a partial failure.
# Requires: gcloud logged in as a project owner, billing linked to the project.
#
#   PROJECT=aibuildercup-512008 ./infra/setup.sh
#
# Org policies this project relies on (set at project level, outside this script):
#   sql.restrictPublicIp = not enforced   (Cloud SQL public IP; the app connects only via the
#                                          Cloud SQL connector, authorised networks stay blocked)
#   iam.automaticIamGrantsForDefaultServiceAccounts is enforced, so the build service account
#   is granted roles/run.builder explicitly below.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-southeast1}"
BUCKET="${BUCKET:-${PROJECT}-tradecheck-docs}"
SQL_INSTANCE="${SQL_INSTANCE:-tradecheck-pg}"
DB_NAME="${DB_NAME:-tradecheck}"
DB_USER="${DB_USER:-tradecheck}"
DB_SECRET="${DB_SECRET:-tradecheck-db-password}"
QUEUE="${QUEUE:-pipeline}"
KEYRING="${KEYRING:-tradecheck}"
KEY="${KEY:-report-signing}"
AR_REPO="${AR_REPO:-cloud-run-source-deploy}"   # the repository name Cloud Run source deploys use
ORIGINS="${ALLOWED_ORIGINS:-*}"

gc() { gcloud --project "$PROJECT" "$@"; }
exists() { "$@" >/dev/null 2>&1; }
skip() { echo "   exists, skipping: $*"; }
creating() { echo "   creating: $*"; }

echo "== APIs"
APIS=(
  serviceusage.googleapis.com cloudresourcemanager.googleapis.com iam.googleapis.com iamcredentials.googleapis.com
  compute.googleapis.com run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
  sqladmin.googleapis.com cloudtasks.googleapis.com cloudkms.googleapis.com storage.googleapis.com
  secretmanager.googleapis.com logging.googleapis.com aiplatform.googleapis.com
)
ENABLED="$(gc services list --enabled --format 'value(config.name)')"
MISSING=()
for api in "${APIS[@]}"; do
  if grep -qx "$api" <<<"$ENABLED"; then skip "$api"; else MISSING+=("$api"); fi
done
if ((${#MISSING[@]})); then
  creating "${MISSING[*]}"
  gc services enable "${MISSING[@]}"
fi

echo "== Service accounts"
API_SA="api-sa@$PROJECT.iam.gserviceaccount.com"
WORKER_SA="worker-sa@$PROJECT.iam.gserviceaccount.com"
for sa in api-sa worker-sa; do
  if exists gc iam service-accounts describe "$sa@$PROJECT.iam.gserviceaccount.com"; then skip "$sa"
  else creating "$sa"; gc iam service-accounts create "$sa" --display-name "tradecheck $sa"; fi
done

echo "== IAM bindings (adding an existing binding is a no-op)"
for sa in "$API_SA" "$WORKER_SA"; do
  for role in roles/cloudsql.client roles/cloudtasks.enqueuer roles/logging.logWriter; do
    gc projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$sa" --role "$role" --condition=None -q >/dev/null
  done
  # Sign GCS URLs through the IAM signBlob API (no private keys on Cloud Run).
  gc iam service-accounts add-iam-policy-binding "$sa" --member "serviceAccount:$sa" \
    --role roles/iam.serviceAccountTokenCreator -q >/dev/null
done
# Gemini runs inside the worker (AI_MODE=vertex); only the worker calls Vertex AI.
gc projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$WORKER_SA" --role roles/aiplatform.user \
  --condition=None -q >/dev/null
# Cloud Tasks mints OIDC tokens as worker-sa; both services enqueue tasks, so both may act as it.
for sa in "$API_SA" "$WORKER_SA"; do
  gc iam service-accounts add-iam-policy-binding "$WORKER_SA" --member "serviceAccount:$sa" \
    --role roles/iam.serviceAccountUser -q >/dev/null
done

echo "== Build service account for Cloud Run source deploys"
# Source deploys build as the Compute Engine default service account. With
# iam.automaticIamGrantsForDefaultServiceAccounts enforced it has no roles, so grant Cloud Run Builder.
PROJECT_NUMBER="$(gc projects describe "$PROJECT" --format 'value(projectNumber)')"
BUILD_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
for _ in $(seq 1 24); do   # the account appears shortly after compute.googleapis.com is enabled
  exists gc iam service-accounts describe "$BUILD_SA" && break
  echo "   waiting for $BUILD_SA ..."; sleep 5
done
gc iam service-accounts describe "$BUILD_SA" >/dev/null
gc projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$BUILD_SA" --role roles/run.builder \
  --condition=None -q >/dev/null
echo "   roles/run.builder -> $BUILD_SA"

echo "== Artifact Registry ($AR_REPO)"
if exists gc artifacts repositories describe "$AR_REPO" --location "$REGION"; then skip "$AR_REPO"
else creating "$AR_REPO"; gc artifacts repositories create "$AR_REPO" --repository-format docker --location "$REGION" \
  --description "Cloud Run source deploy images"; fi

echo "== Cloud Storage"
if exists gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT"; then skip "gs://$BUCKET"
else creating "gs://$BUCKET"; gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "$REGION" \
  --uniform-bucket-level-access --public-access-prevention; fi
CORS_FILE="$(mktemp)"
cat > "$CORS_FILE" <<EOF
[{"origin": ["${ORIGINS//,/\",\"}"], "method": ["PUT", "GET", "HEAD"],
  "responseHeader": ["Content-Type"], "maxAgeSeconds": 3600}]
EOF
gcloud storage buckets update "gs://$BUCKET" --project "$PROJECT" --cors-file "$CORS_FILE" >/dev/null
rm -f "$CORS_FILE"
echo "   CORS origins: $ORIGINS"
for sa in "$API_SA" "$WORKER_SA"; do
  gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$PROJECT" \
    --member "serviceAccount:$sa" --role roles/storage.objectAdmin -q >/dev/null
done

echo "== Cloud SQL (PostgreSQL 16, smallest tier; takes ~10 minutes the first time)"
if exists gc sql instances describe "$SQL_INSTANCE"; then skip "$SQL_INSTANCE"
else creating "$SQL_INSTANCE"; gc sql instances create "$SQL_INSTANCE" --database-version POSTGRES_16 --edition enterprise \
  --tier db-f1-micro --region "$REGION" --storage-size 10 --storage-auto-increase; fi
if exists gc sql databases describe "$DB_NAME" --instance "$SQL_INSTANCE"; then skip "database $DB_NAME"
else creating "database $DB_NAME"; gc sql databases create "$DB_NAME" --instance "$SQL_INSTANCE"; fi
if exists gc secrets describe "$DB_SECRET"; then skip "secret $DB_SECRET"
else
  creating "secret $DB_SECRET"
  openssl rand -base64 24 | tr -d '/+=\n' | gc secrets create "$DB_SECRET" --data-file=- --replication-policy automatic
fi
if gc sql users list --instance "$SQL_INSTANCE" --format 'value(name)' | grep -qx "$DB_USER"; then skip "db user $DB_USER"
else
  creating "db user $DB_USER (password from $DB_SECRET)"
  gc sql users create "$DB_USER" --instance "$SQL_INSTANCE" \
    --password "$(gc secrets versions access latest --secret "$DB_SECRET")"
fi
for sa in "$API_SA" "$WORKER_SA"; do
  gc secrets add-iam-policy-binding "$DB_SECRET" --member "serviceAccount:$sa" \
    --role roles/secretmanager.secretAccessor -q >/dev/null
done

echo "== Cloud Tasks"
if exists gc tasks queues describe "$QUEUE" --location "$REGION"; then skip "queue $QUEUE"
else creating "queue $QUEUE"; gc tasks queues create "$QUEUE" --location "$REGION" --max-attempts 5 --min-backoff 10s \
  --max-backoff 300s --max-doublings 4; fi

echo "== Cloud KMS report-signing key"
if exists gc kms keyrings describe "$KEYRING" --location "$REGION"; then skip "keyring $KEYRING"
else creating "keyring $KEYRING"; gc kms keyrings create "$KEYRING" --location "$REGION"; fi
if exists gc kms keys describe "$KEY" --keyring "$KEYRING" --location "$REGION"; then skip "key $KEY"
else creating "key $KEY"; gc kms keys create "$KEY" --keyring "$KEYRING" --location "$REGION" --purpose asymmetric-signing \
  --default-algorithm ec-sign-p256-sha256; fi
gc kms keys add-iam-policy-binding "$KEY" --keyring "$KEYRING" --location "$REGION" \
  --member "serviceAccount:$API_SA" --role roles/cloudkms.signerVerifier -q >/dev/null

echo
echo "Setup complete. Next: PROJECT=$PROJECT ./infra/deploy.sh"
