param (
    [Parameter(Mandatory=$true)]
    [string]$ProjectId,
    [Parameter(Mandatory=$true)]
    [string]$SupabaseUrl,
    [Parameter(Mandatory=$true)]
    [string]$SupabaseServiceKey,
    [string]$ResendApiKey = "",
    [string]$GeminiApiKey = "",
    [string]$Region = "us-central1"
)

$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot/.."

function Set-GcpSecret {
    param ([string]$Name, [string]$Value)
    $exists = gcloud secrets list --filter="name:$Name" --format="value(name)" 2>$null
    if (-not $exists) {
        $Value | gcloud secrets create $Name --data-file=- --replication-policy=automatic
    } else {
        $Value | gcloud secrets versions add $Name --data-file=-
    }
}

gcloud config set project $ProjectId
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com
Set-GcpSecret -Name "supabase-url" -Value $SupabaseUrl
Set-GcpSecret -Name "supabase-service-key" -Value $SupabaseServiceKey
if ($ResendApiKey) { Set-GcpSecret -Name "resend-api-key" -Value $ResendApiKey }
if ($GeminiApiKey) { Set-GcpSecret -Name "gemini-api-key" -Value $GeminiApiKey }

$projectNumber = gcloud projects describe $ProjectId --format="value(projectNumber)"
$computeServiceAccount = "$projectNumber-compute@developer.gserviceaccount.com"
foreach ($secret in @("supabase-url", "supabase-service-key")) {
    gcloud secrets add-iam-policy-binding $secret --member="serviceAccount:$computeServiceAccount" --role=roles/secretmanager.secretAccessor
}

$image = "gcr.io/$ProjectId/autotrace:latest"
gcloud builds submit --tag $image .
gcloud run deploy autotrace-api --image=$image --platform=managed --region=$Region --allow-unauthenticated --set-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"
$apiUrl = gcloud run services describe autotrace-api --platform=managed --region=$Region --format="value(status.url)"

$jobSecrets = "SUPABASE_URL=supabase-url:latest,SUPABASE_SERVICE_KEY=supabase-service-key:latest"
if ($ResendApiKey) { $jobSecrets += ",RESEND_API_KEY=resend-api-key:latest" }
if ($GeminiApiKey) { $jobSecrets += ",GEMINI_API_KEY=gemini-api-key:latest" }

$jobExists = gcloud run jobs list --region=$Region --filter="metadata.name:autotrace-worker" --format="value(metadata.name)" 2>$null
if (-not $jobExists) {
    gcloud run jobs create autotrace-worker --image=$image --region=$Region --command=python --args="-m,autotrace.worker" --set-secrets=$jobSecrets
} else {
    gcloud run jobs update autotrace-worker --image=$image --region=$Region --command=python --args="-m,autotrace.worker" --set-secrets=$jobSecrets
}

$schedulerServiceAccount = "autotrace-scheduler@$ProjectId.iam.gserviceaccount.com"
$serviceAccountExists = gcloud iam service-accounts list --filter="email:$schedulerServiceAccount" --format="value(email)" 2>$null
if (-not $serviceAccountExists) {
    gcloud iam service-accounts create autotrace-scheduler --display-name="AutoTrace Scheduler"
}
gcloud run jobs add-iam-policy-binding autotrace-worker --region=$Region --member="serviceAccount:$schedulerServiceAccount" --role=roles/run.invoker

$scheduleExists = gcloud scheduler jobs list --location=$Region --filter="name:autotrace-every-five-minutes" --format="value(name)" 2>$null
if (-not $scheduleExists) {
    gcloud scheduler jobs create http autotrace-every-five-minutes --location=$Region --schedule="*/5 * * * *" --time-zone=UTC --uri="https://$Region-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$ProjectId/jobs/autotrace-worker:run" --http-method=POST --oauth-service-account-email=$schedulerServiceAccount
}

Write-Host "AutoTrace API: $apiUrl"
Write-Host "Set NEXT_PUBLIC_API_URL=$apiUrl before deploying the dashboard."