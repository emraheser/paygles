#!/usr/bin/env bash
set -euo pipefail

# ─── Config ───────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${GCP_REGION:-europe-west1}"
BACKEND_SERVICE="paygles-api"
FRONTEND_SERVICE="paygles-web"
REPO="paygles"

# ─── Ensure Artifact Registry repo exists ─────────────────
gcloud artifacts repositories describe "$REPO" \
  --location="$REGION" --project="$PROJECT_ID" &>/dev/null || \
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --project="$PROJECT_ID"

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"

# ─── Ensure GCS bucket for SQLite persistence ─────────────
SQLITE_BUCKET="${PROJECT_ID}-paygles-data"
if ! gcloud storage buckets describe "gs://${SQLITE_BUCKET}" --project="$PROJECT_ID" &>/dev/null; then
  echo "🪣 Creating GCS bucket gs://${SQLITE_BUCKET}..."
  gcloud storage buckets create "gs://${SQLITE_BUCKET}" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --uniform-bucket-level-access
fi

# ─── Build & push backend (kaniko cached) ─────────────────
echo "🔨 Building backend..."
gcloud builds submit ./backend \
  --config=backend/cloudbuild.yaml \
  --substitutions="_REGISTRY=${REGISTRY}" \
  --project="$PROJECT_ID" \
  --quiet

# ─── Deploy backend ──────────────────────────────────────
# Note: SQLite + Cloud Run requires a single instance + persistent
# Cloud Storage volume mount. Do NOT raise max-instances above 1.
echo "🚀 Deploying backend..."
gcloud run deploy "$BACKEND_SERVICE" \
  --image "${REGISTRY}/${BACKEND_SERVICE}" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 1 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --execution-environment gen2 \
  --add-volume "name=sqlite-vol,type=cloud-storage,bucket=${SQLITE_BUCKET}" \
  --add-volume-mount "volume=sqlite-vol,mount-path=/data" \
  --update-env-vars "SQLITE_PATH=/data/paygles.db" \
  --remove-env-vars "SUPABASE_URL,DATABASE_URL" \
  --quiet

# Get backend URL
BACKEND_URL=$(gcloud run services describe "$BACKEND_SERVICE" \
  --region "$REGION" --project "$PROJECT_ID" \
  --format "value(status.url)")
echo "✅ Backend: $BACKEND_URL"

# ─── Build & push frontend (kaniko cached) ────────────────
echo "🔨 Building frontend..."
gcloud builds submit ./frontend \
  --config=frontend/cloudbuild.yaml \
  --substitutions="_REGISTRY=${REGISTRY},_VITE_API_URL=${BACKEND_URL}" \
  --project="$PROJECT_ID" \
  --quiet

# ─── Deploy frontend ─────────────────────────────────────
echo "🚀 Deploying frontend..."
gcloud run deploy "$FRONTEND_SERVICE" \
  --image "${REGISTRY}/${FRONTEND_SERVICE}" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3 \
  --memory 128Mi \
  --cpu 1 \
  --quiet

FRONTEND_URL=$(gcloud run services describe "$FRONTEND_SERVICE" \
  --region "$REGION" --project "$PROJECT_ID" \
  --format "value(status.url)")

# Cloud Run her servisi iki ayrı URL ile sunar:
#   1) https://<service>-<hash>.<region>.run.app  (status.url'de bu döner)
#   2) https://<service>-<project_number>.<region>.run.app  (numbered alias)
# Tarayıcı bu iki URL'den hangisinden gelirse gelsin CORS çalışsın diye
# her ikisini de izinli origin listesine ekliyoruz.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
ALT_FRONTEND_URL="https://${FRONTEND_SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

# ─── Update CORS with frontend URL ───────────────────────
echo "🔄 Updating CORS..."
ORIGINS_LIST="$FRONTEND_URL"
if [ -n "$ALT_FRONTEND_URL" ] && [ "$ALT_FRONTEND_URL" != "$FRONTEND_URL" ]; then
  ORIGINS_LIST="$ORIGINS_LIST,$ALT_FRONTEND_URL"
fi
EXTRA_ORIGINS="${EXTRA_ALLOWED_ORIGINS:-}"
if [ -n "$EXTRA_ORIGINS" ]; then
  ORIGINS_LIST="$ORIGINS_LIST,$EXTRA_ORIGINS"
fi
gcloud run services update "$BACKEND_SERVICE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --update-env-vars "^@^ALLOWED_ORIGINS=${ORIGINS_LIST}" \
  --quiet

echo ""
echo "═══════════════════════════════════════"
echo "✅ Deployment complete!"
echo "   Frontend: $FRONTEND_URL"
echo "   Backend:  $BACKEND_URL"
echo "═══════════════════════════════════════"
