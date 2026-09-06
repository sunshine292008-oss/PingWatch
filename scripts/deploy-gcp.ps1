# Google Cloud & Secret Manager Deployment Script for PingWatch
param (
    [Parameter(Mandatory=$true)]
    [string]$ProjectId,
    [Parameter(Mandatory=$true)]
    [string]$SupabaseUrl,
    [Parameter(Mandatory=$true)]
    [string]$SupabaseServiceKey,
    [Parameter(Mandatory=$true)]
    [string]$ResendApiKey,
    [string]$Region = "us-central1"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " PingWatch Cloud Run & Secret Manager Setup" -ForegroundColor Cyan
Write-Host " Target Project: $ProjectId" -ForegroundColor Cyan
Write-Host " Region:         $Region" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. Set Active Project & Enable APIs
Write-Host "`n[1/6] Setting project & enabling required GCP APIs..." -ForegroundColor Yellow
gcloud config set project $ProjectId
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com

# 2. Create or Update Secrets in Secret Manager
Write-Host "`n[2/6] Storing credentials in Google Secret Manager..." -ForegroundColor Yellow

function Set-GcpSecret {
    param ([string]$Name, [string]$Value)
    $exists = gcloud secrets list --filter="name:$Name" --format="value(name)" 2>$null
    if (-not $exists) {
        Write-Host "Creating secret: $Name"
        $Value | gcloud secrets create $Name --data-file=- --replication-policy="automatic"
    } else {
        Write-Host "Updating secret version: $Name"
        $Value | gcloud secrets versions add $Name --data-file=-
    }
}

Set-GcpSecret -Name "supabase-url" -Value $SupabaseUrl
Set-GcpSecret -Name "supabase-service-key" -Value $SupabaseServiceKey
Set-GcpSecret -Name "resend-api-key" -Value $ResendApiKey

# 3. Grant Secret Access to Default Compute Service Account
Write-Host "`n[3/6] Configuring Secret Access IAM..." -ForegroundColor Yellow
$PROJECT_NUMBER = (gcloud projects describe $ProjectId --format="value(projectNumber)")
$COMPUTE_SA = "$PROJECT_NUMBER-compute@developer.gserviceaccount.com"

foreach ($secret in @("supabase-url", "supabase-service-key", "resend-api-key")) {
    gcloud secrets add-iam-policy-binding $secret `
        --member="serviceAccount:$COMPUTE_SA" `
        --role="roles/secretmanager.secretAccessor"
}

# 4. Build and Deploy Cloud Run API Service
Write-Host "`n[4/6] Building and deploying pingwatch-api..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/pingwatch-api:latest" apps/api

gcloud run deploy pingwatch-api `
    --image="gcr.io/$ProjectId/pingwatch-api:latest" `
    --platform=managed `
    --region=$Region `
    --allow-unauthenticated `
    --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"

$API_URL = (gcloud run services describe pingwatch-api --platform=managed --region=$Region --format="value(status.url)")
Write-Host "PingWatch API deployed to: $API_URL" -ForegroundColor Green

# 5. Build and Deploy Cloud Run Worker Job
Write-Host "`n[5/6] Building and deploying pingwatch-worker Job..." -ForegroundColor Yellow
gcloud builds submit --tag "gcr.io/$ProjectId/pingwatch-worker:latest" apps/worker

$jobExists = gcloud run jobs list --region=$Region --filter="metadata.name:pingwatch-worker" --format="value(metadata.name)" 2>$null
if (-not $jobExists) {
    gcloud run jobs create pingwatch-worker `
        --image="gcr.io/$ProjectId/pingwatch-worker:latest" `
        --region=$Region `
        --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest,RESEND_API_KEY=resend-api-key:latest"
} else {
    gcloud run jobs update pingwatch-worker `
        --image="gcr.io/$ProjectId/pingwatch-worker:latest" `
        --region=$Region `
        --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest,RESEND_API_KEY=resend-api-key:latest"
}

# 6. Configure Cloud Scheduler (Every 1 Minute)
Write-Host "`n[6/6] Configuring Cloud Scheduler 1-minute trigger..." -ForegroundColor Yellow
$SCHEDULER_SA = "pingwatch-scheduler@$ProjectId.iam.gserviceaccount.com"
$saExists = gcloud iam service-accounts list --filter="email:$SCHEDULER_SA" --format="value(email)" 2>$null

if (-not $saExists) {
    gcloud iam service-accounts create pingwatch-scheduler --display-name="PingWatch Scheduler Trigger"
}

gcloud run jobs add-iam-policy-binding pingwatch-worker `
    --region=$Region `
    --member="serviceAccount:$SCHEDULER_SA" `
    --role="roles/run.invoker"

$schedExists = gcloud scheduler jobs list --location=$Region --filter="name:pingwatch-minutely" --format="value(name)" 2>$null
if (-not $schedExists) {
    gcloud scheduler jobs create http pingwatch-minutely `
        --location=$Region `
        --schedule="* * * * *" `
        --time-zone="UTC" `
        --uri="https://$Region-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$ProjectId/jobs/pingwatch-worker:run" `
        --http-method=POST `
        --oauth-service-account-email=$SCHEDULER_SA
}

Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host " Deployment Complete!" -ForegroundColor Green
Write-Host " API URL: $API_URL" -ForegroundColor Green
Write-Host " Next step: Update NEXT_PUBLIC_API_URL in apps/web and deploy to Cloudflare Pages." -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan
