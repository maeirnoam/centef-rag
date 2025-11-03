#!/bin/bash
# Deploy all Cloud Run services for the ingestion pipeline

set -e

PROJECT_ID=${PROJECT_ID:-"sylvan-faculty-476113-c9"}
REGION=${REGION:-"us-central1"}

echo "========================================="
echo "Deploying Ingestion Pipeline Services"
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "========================================="

# Array of services to deploy
declare -a SERVICES=(
    "ingest-docs"
    "ingest-av"
    "ingest-images"
    "summary-generator"
    "manifest-updater"
    "import-trigger"
)

# Deploy each service
for SERVICE in "${SERVICES[@]}"; do
    echo ""
    echo "========================================="
    echo "Deploying: $SERVICE"
    echo "========================================="
    
    # Build and submit to Container Registry
    echo "Building container image..."
    cd ..
    gcloud builds submit \
        --project=$PROJECT_ID \
        --tag=gcr.io/$PROJECT_ID/$SERVICE:latest \
        --config=- <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', 'gcr.io/$PROJECT_ID/$SERVICE:latest', '-f', 'services/Dockerfile.$SERVICE', '.']
images:
- 'gcr.io/$PROJECT_ID/$SERVICE:latest'
EOF
    cd services
    
    # Deploy to Cloud Run
    echo "Deploying to Cloud Run..."
    gcloud run deploy $SERVICE \
        --project=$PROJECT_ID \
        --image=gcr.io/$PROJECT_ID/$SERVICE:latest \
        --platform=managed \
        --region=$REGION \
        --allow-unauthenticated \
        --memory=2Gi \
        --cpu=2 \
        --timeout=3600 \
        --max-instances=10 \
        --set-env-vars="PROJECT_ID=$PROJECT_ID,\
SOURCE_BUCKET=centef-rag-bucket,\
TARGET_BUCKET=centef-rag-chunks,\
SUMMARIES_BUCKET=centef-rag-chunks,\
DATASTORE_ID=centef-chunk-data-store_1761831236752_gcs_store,\
SUMMARIES_DATASTORE_ID=centef-summaries-datastore_1762162632284_gcs_store,\
VERTEX_LOCATION=us-central1,\
SUMMARY_MODEL=gemini-2.5-flash"
    
    # Get service URL
    SERVICE_URL=$(gcloud run services describe $SERVICE \
        --project=$PROJECT_ID \
        --region=$REGION \
        --format="value(status.url)")
    
    echo "✓ Deployed: $SERVICE"
    echo "  URL: $SERVICE_URL"
done

echo ""
echo "========================================="
echo "✓ All services deployed successfully!"
echo "========================================="
echo ""
echo "Service URLs:"
for SERVICE in "${SERVICES[@]}"; do
    SERVICE_URL=$(gcloud run services describe $SERVICE \
        --project=$PROJECT_ID \
        --region=$REGION \
        --format="value(status.url)")
    echo "  $SERVICE: $SERVICE_URL"
done
