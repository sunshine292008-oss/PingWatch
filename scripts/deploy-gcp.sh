#!/usr/bin/env bash
set -e

if [ -z "$PROJECT_ID" ] || [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_SERVICE_KEY" ] || [ -z "$RESEND_API_KEY" ]; then
  echo "Error: Missing required environment variables."
  echo "Usage: PROJECT_ID=my-project SUPABASE_URL=... SUPABASE_SERVICE_KEY=... RESEND_API_KEY=... ./scripts/deploy-gcp.sh"
  exit 1
fi

REGION="${REGION:-us-central1}"

echo "=========================================="
echo " PingWatch Cloud Run & Secret Manager Setup"
echo " Target Project: $PROJECT_ID"
echo " Region:         $REGION"
echo "=========================================="

# 1. Set Active Project & Enable APIs
echo "[1/6] Setting project & enabling required GCP APIs..."
gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com

# 2. Create or Update Secrets in Secret Manager
echo "[2/6] Storing credentials in Google Secret Manager..."

create_or_update_secret() {
  local NAME=$1
  local VALUE=$2
  if ! gcloud secrets describe "$NAME" &>/dev/null; then
    echo "Creating secret: $NAME"
    echo -n "$VALUE" | gcloud secrets create "$NAME" --data-file=- --replication-policy="automatic"
  else
    echo "Updating secret: $NAME"
    echo -n "$VALUE" | gcloud secrets versions add "$NAME" --data-file=-
  fi
}

create_or_update_secret "supabase-url" "$SUPABASE_URL"
create_or_update_secret "supabase-service-key" "$SUPABASE_SERVICE_KEY"
create_or_update_secret "resend-api-key" "$RESEND_API_KEY"

# 3. Grant Secret Access to Default Compute Service Account
echo "[3/6] Configuring Secret Access IAM..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
COMPUTE_SA="$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

for SECRET in "supabase-url" "supabase-service-key" "resend-api-key"; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:$COMPUTE_SA" \
    --role="roles/secretmanager.secretAccessor"
done

# 4. Build and Deploy Cloud Run API Service
echo "[4/6] Building and deploying pingwatch-api..."
gcloud builds submit --tag "gcr.io/$PROJECT_ID/pingwatch-api:latest" apps/api

gcloud run deploy pingwatch-api \
  --image="gcr.io/$PROJECT_ID/pingwatch-api:latest" \
  --platform=managed \
  --region="$REGION" \
  --allow-unauthenticated \
  --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"

API_URL=$(gcloud run services describe pingwatch-api --platform=managed --region="$REGION" --format="value(status.url)")
echo "PingWatch API deployed to: $API_URL"

# 5. Build and Deploy Cloud Run Worker Job
echo "[5/6] Building and deploying pingwatch-worker Job..."
gcloud builds submit --tag "gcr.io/$PROJECT_ID/pingwatch-worker:latest" apps/worker

if ! gcloud run jobs describe pingwatch-worker --region="$REGION" &>/dev/null; then
  gcloud run jobs create pingwatch-worker \
    --image="gcr.io/$PROJECT_ID/pingwatch-worker:latest" \
    --region="$REGION" \
    --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest,RESEND_API_KEY=resend-api-key:latest"
else
  gcloud run jobs update pingwatch-worker \
    --image="gcr.io/$PROJECT_ID/pingwatch-worker:latest" \
    --region="$REGION" \
    --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest,RESEND_API_KEY=resend-api-key:latest"
fi

# 6. Configure Cloud Scheduler (Every 1 Minute)
echo "[6/6] Configuring Cloud Scheduler 1-minute trigger..."
SCHEDULER_SA="pingwatch-scheduler@$PROJECT_ID.iam.gserviceaccount.com"

if ! gcloud iam service-accounts describe "$SCHEDULER_SA" &>/dev/null; then
  gcloud iam service-accounts create pingwatch-scheduler --display-name="PingWatch Scheduler Trigger"
fi

gcloud run jobs add-iam-policy-binding pingwatch-worker \
  --region="$REGION" \
  --member="serviceAccount:$SCHEDULER_SA" \
  --role="roles/run.invoker"

if ! gcloud scheduler jobs describe pingwatch-minutely --location="$REGION" &>/dev/null; then
  gcloud scheduler jobs create http pingwatch-minutely \
    --location="$REGION" \
    --schedule="* * * * *" \
    --time-zone="UTC" \
    --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/pingwatch-worker:run" \
    --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA"
fi

echo "=========================================="
echo " Deployment Complete!"
echo " API URL: $API_URL"
echo " Next step: Update NEXT_PUBLIC_API_URL in apps/web and deploy to Cloudflare Pages."
echo "=========================================="
