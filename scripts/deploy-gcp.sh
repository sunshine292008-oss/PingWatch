#!/usr/bin/env bash
set -euo pipefail

if [ -z "${PROJECT_ID:-}" ] || [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_KEY:-}" ]; then
  echo "Usage: PROJECT_ID=my-project SUPABASE_URL=... SUPABASE_SERVICE_KEY=... ./scripts/deploy-gcp.sh"
  exit 1
fi

REGION="${REGION:-us-central1}"
IMAGE="gcr.io/$PROJECT_ID/autotrace:latest"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com

create_or_update_secret() {
  local name="$1"
  local value="$2"
  if ! gcloud secrets describe "$name" >/dev/null 2>&1; then
    printf '%s' "$value" | gcloud secrets create "$name" --data-file=- --replication-policy=automatic
  else
    printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=-
  fi
}

create_or_update_secret "supabase-url" "$SUPABASE_URL"
create_or_update_secret "supabase-service-key" "$SUPABASE_SERVICE_KEY"
[ -n "${RESEND_API_KEY:-}" ] && create_or_update_secret "resend-api-key" "$RESEND_API_KEY"
[ -n "${GEMINI_API_KEY:-}" ] && create_or_update_secret "gemini-api-key" "$GEMINI_API_KEY"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
COMPUTE_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"
for secret in supabase-url supabase-service-key; do
  gcloud secrets add-iam-policy-binding "$secret" \
    --member="serviceAccount:$COMPUTE_SA" \
    --role=roles/secretmanager.secretAccessor
done

gcloud builds submit --tag "$IMAGE" .
gcloud run deploy autotrace-api \
  --image="$IMAGE" \
  --platform=managed \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"

API_URL="$(gcloud run services describe autotrace-api --platform=managed --region="$REGION" --format='value(status.url)')"

JOB_SECRETS="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"
[ -n "${RESEND_API_KEY:-}" ] && JOB_SECRETS="$JOB_SECRETS,RESEND_API_KEY=resend-api-key:latest"
[ -n "${GEMINI_API_KEY:-}" ] && JOB_SECRETS="$JOB_SECRETS,GEMINI_API_KEY=gemini-api-key:latest"

if gcloud run jobs describe autotrace-worker --region="$REGION" >/dev/null 2>&1; then
  gcloud run jobs update autotrace-worker \
    --image="$IMAGE" \
    --region="$REGION" \
    --command=python \
    --args=-m,autotrace.worker \
    --set-secrets="$JOB_SECRETS"
else
  gcloud run jobs create autotrace-worker \
    --image="$IMAGE" \
    --region="$REGION" \
    --command=python \
    --args=-m,autotrace.worker \
    --set-secrets="$JOB_SECRETS"
fi

SCHEDULER_SA="autotrace-scheduler@$PROJECT_ID.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$SCHEDULER_SA" >/dev/null 2>&1; then
  gcloud iam service-accounts create autotrace-scheduler --display-name="AutoTrace Scheduler"
fi
gcloud run jobs add-iam-policy-binding autotrace-worker \
  --region="$REGION" \
  --member="serviceAccount:$SCHEDULER_SA" \
  --role=roles/run.invoker

if ! gcloud scheduler jobs describe autotrace-every-five-minutes --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs create http autotrace-every-five-minutes \
    --location="$REGION" \
    --schedule='*/5 * * * *' \
    --time-zone=UTC \
    --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/autotrace-worker:run" \
    --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA"
fi

echo "AutoTrace API: $API_URL"
echo "Set NEXT_PUBLIC_API_URL=$API_URL before deploying the dashboard."