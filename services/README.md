# Cloud Run Services Deployment Guide

This directory contains Cloud Run services for the centef-rag ingestion pipeline.

## Services Overview

| Service | Purpose | Port |
|---------|---------|------|
| **ingest-docs** | PDF/PPTX document ingestion | 8080 |
| **ingest-av** | Audio/Video/SRT ingestion | 8080 |
| **ingest-images** | Image ingestion with OCR | 8080 |
| **summary-generator** | AI summary generation | 8080 |
| **manifest-updater** | Manifest.jsonl management | 8080 |
| **import-trigger** | Discovery Engine import trigger | 8080 |

## Prerequisites

1. **GCP Project Setup**
   ```bash
   export PROJECT_ID=sylvan-faculty-476113-c9
   export REGION=us-central1
   gcloud config set project $PROJECT_ID
   ```

2. **Enable Required APIs**
   ```bash
   gcloud services enable \
     run.googleapis.com \
     cloudbuild.googleapis.com \
     containerregistry.googleapis.com \
     speech.googleapis.com \
     translate.googleapis.com \
     vision.googleapis.com \
     aiplatform.googleapis.com \
     discoveryengine.googleapis.com
   ```

3. **Service Account Permissions**
   - Cloud Run Admin
   - Storage Object Admin
   - Vertex AI User
   - Discovery Engine Editor

## Quick Deploy (All Services)

### Windows (PowerShell)
```powershell
cd services
.\deploy_all.ps1
```

### Linux/Mac
```bash
cd services
chmod +x deploy_all.sh
./deploy_all.sh
```

## Individual Service Deployment

### 1. Build Container Image
```bash
SERVICE_NAME=ingest-docs  # or ingest-av, ingest-images, etc.

gcloud builds submit \
  --project=$PROJECT_ID \
  --tag=gcr.io/$PROJECT_ID/$SERVICE_NAME:latest \
  --dockerfile=services/Dockerfile.$SERVICE_NAME \
  .
```

### 2. Deploy to Cloud Run
```bash
gcloud run deploy $SERVICE_NAME \
  --project=$PROJECT_ID \
  --image=gcr.io/$PROJECT_ID/$SERVICE_NAME:latest \
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
```

### 3. Get Service URL
```bash
gcloud run services describe $SERVICE_NAME \
  --project=$PROJECT_ID \
  --region=$REGION \
  --format="value(status.url)"
```

## Testing Services

### Test Document Ingestion
```bash
SERVICE_URL=https://ingest-docs-XXX.run.app

curl -X POST $SERVICE_URL/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "gs://centef-rag-bucket/data/test.pdf"
  }'
```

### Test Audio/Video Ingestion
```bash
SERVICE_URL=https://ingest-av-XXX.run.app

curl -X POST $SERVICE_URL/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "gs://centef-rag-bucket/data/video.mp4",
    "language": "ar-SA",
    "translate_to": "en"
  }'
```

### Test Summary Generation
```bash
SERVICE_URL=https://summary-generator-XXX.run.app

curl -X POST $SERVICE_URL/generate \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "test_doc_123",
    "chunks_uri": "gs://centef-rag-chunks/data/test.pdf.jsonl",
    "metadata": {
      "title": "Test Document",
      "author": "CENTEF",
      "date": "2024-11-03",
      "language": "en"
    }
  }'
```

### Test Import Trigger
```bash
SERVICE_URL=https://import-trigger-XXX.run.app

curl -X POST $SERVICE_URL/trigger \
  -H "Content-Type: application/json" \
  -d '{"datastore": "both"}'
```

## Environment Variables

All services use these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PROJECT_ID` | sylvan-faculty-476113-c9 | GCP project ID |
| `SOURCE_BUCKET` | centef-rag-bucket | Source documents bucket |
| `TARGET_BUCKET` | centef-rag-chunks | Processed chunks bucket |
| `SUMMARIES_BUCKET` | centef-rag-chunks | Summaries storage |
| `DATASTORE_ID` | centef-chunk-data-store_... | Chunks datastore ID |
| `SUMMARIES_DATASTORE_ID` | centef-summaries-datastore_... | Summaries datastore ID |
| `VERTEX_LOCATION` | us-central1 | Vertex AI region |
| `SUMMARY_MODEL` | gemini-2.5-flash | Model for summaries |

## Monitoring & Logs

### View Logs
```bash
gcloud run services logs read $SERVICE_NAME \
  --project=$PROJECT_ID \
  --region=$REGION \
  --limit=50
```

### Monitor Metrics
```bash
# In GCP Console
Navigation > Cloud Run > [Service] > Metrics
```

## Cost Optimization

1. **Memory**: Services use 2Gi - adjust based on needs
2. **CPU**: 2 CPUs allocated - scale down for lighter workloads
3. **Max Instances**: Set to 10 - adjust based on traffic
4. **Timeout**: 3600s (1 hour) - reduce for faster operations

## Troubleshooting

### Common Issues

**Build Fails**
```bash
# Check Cloud Build logs
gcloud builds list --project=$PROJECT_ID --limit=5

# View specific build
gcloud builds log <BUILD_ID> --project=$PROJECT_ID
```

**Service Not Responding**
```bash
# Check service status
gcloud run services describe $SERVICE_NAME \
  --project=$PROJECT_ID \
  --region=$REGION

# View recent logs
gcloud run services logs read $SERVICE_NAME \
  --project=$PROJECT_ID \
  --region=$REGION \
  --limit=100
```

**Permission Errors**
- Ensure service account has required IAM roles
- Check bucket permissions
- Verify API enablement

## Next Steps

1. **Deploy Services**: Run `deploy_all.ps1` or `deploy_all.sh`
2. **Test Endpoints**: Use curl commands above
3. **Set Up Orchestrator**: Configure Cloud Workflows to chain services
4. **Monitor**: Set up alerts for errors and latency

## Service URLs (After Deployment)

After deployment, save your service URLs:

```bash
export INGEST_DOCS_URL=https://ingest-docs-XXX.run.app
export INGEST_AV_URL=https://ingest-av-XXX.run.app
export INGEST_IMAGES_URL=https://ingest-images-XXX.run.app
export SUMMARY_GENERATOR_URL=https://summary-generator-XXX.run.app
export MANIFEST_UPDATER_URL=https://manifest-updater-XXX.run.app
export IMPORT_TRIGGER_URL=https://import-trigger-XXX.run.app
```

These will be used in the orchestration workflow.
