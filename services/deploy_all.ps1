# PowerShell deployment script for Windows
# Deploy all Cloud Run services for the ingestion pipeline

$ErrorActionPreference = "Stop"

$PROJECT_ID = if ($env:PROJECT_ID) { $env:PROJECT_ID } else { "sylvan-faculty-476113-c9" }
$REGION = if ($env:REGION) { $env:REGION } else { "us-central1" }

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Deploying Ingestion Pipeline Services" -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID" -ForegroundColor Yellow
Write-Host "Region: $REGION" -ForegroundColor Yellow
Write-Host "=========================================" -ForegroundColor Cyan

# Array of services to deploy
$SERVICES = @(
    "ingest-docs",
    "ingest-av",
    "ingest-images",
    "summary-generator",
    "manifest-updater",
    "import-trigger"
)

# Deploy each service
foreach ($SERVICE in $SERVICES) {
    Write-Host ""
    Write-Host "=========================================" -ForegroundColor Cyan
    Write-Host "Deploying: $SERVICE" -ForegroundColor Green
    Write-Host "=========================================" -ForegroundColor Cyan
    
    # Build and submit to Container Registry
    Write-Host "Building container image..." -ForegroundColor Yellow
    gcloud builds submit `
        --project=$PROJECT_ID `
        --tag=gcr.io/$PROJECT_ID/$SERVICE`:latest `
        --dockerfile=services/Dockerfile.$SERVICE `
        .
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error building $SERVICE" -ForegroundColor Red
        continue
    }
    
    # Deploy to Cloud Run
    Write-Host "Deploying to Cloud Run..." -ForegroundColor Yellow
    gcloud run deploy $SERVICE `
        --project=$PROJECT_ID `
        --image=gcr.io/$PROJECT_ID/$SERVICE`:latest `
        --platform=managed `
        --region=$REGION `
        --allow-unauthenticated `
        --memory=2Gi `
        --cpu=2 `
        --timeout=3600 `
        --max-instances=10 `
        --set-env-vars="PROJECT_ID=$PROJECT_ID,SOURCE_BUCKET=centef-rag-bucket,TARGET_BUCKET=centef-rag-chunks,SUMMARIES_BUCKET=centef-rag-chunks,DATASTORE_ID=centef-chunk-data-store_1761831236752_gcs_store,SUMMARIES_DATASTORE_ID=centef-summaries-datastore_1762162632284_gcs_store,VERTEX_LOCATION=us-central1,SUMMARY_MODEL=gemini-2.5-flash"
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error deploying $SERVICE" -ForegroundColor Red
        continue
    }
    
    # Get service URL
    $SERVICE_URL = gcloud run services describe $SERVICE `
        --project=$PROJECT_ID `
        --region=$REGION `
        --format="value(status.url)"
    
    Write-Host "✓ Deployed: $SERVICE" -ForegroundColor Green
    Write-Host "  URL: $SERVICE_URL" -ForegroundColor White
}

Write-Host ""
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "✓ All services deployed successfully!" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Service URLs:" -ForegroundColor Yellow
foreach ($SERVICE in $SERVICES) {
    $SERVICE_URL = gcloud run services describe $SERVICE `
        --project=$PROJECT_ID `
        --region=$REGION `
        --format="value(status.url)"
    Write-Host "  $SERVICE`: $SERVICE_URL" -ForegroundColor White
}
