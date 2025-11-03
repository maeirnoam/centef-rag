# Cloud Run Deployment Summary

## ✅ What We Created

### 1. **Six Microservices** (FastAPI + Docker)

| Service | Wraps | Purpose |
|---------|-------|---------|
| `ingest-docs` | `tools/ingest_pdf_pages.py` | PDF document processing with PyMuPDF |
| `ingest-av` | `tools/ingest_video.py` + `tools/ingest_srt.py` | Video/audio transcription + SRT parsing |
| `ingest-images` | `tools/ingest_image.py` | Image OCR and captioning |
| `summary-generator` | `tools/ingest_summaries.py` | AI-powered document summaries |
| `manifest-updater` | `tools/populate_manifest.py` | Manifest.jsonl management |
| `import-trigger` | `tools/trigger_datastore_import.py` | Discovery Engine imports (chunks + summaries) |

### 2. **Infrastructure Files**

- ✅ **6 Dockerfiles**: One per service with optimized dependencies
- ✅ **2 Deployment Scripts**: PowerShell (Windows) and Bash (Linux/Mac)
- ✅ **requirements.txt**: Shared dependencies for all services
- ✅ **README.md**: Complete deployment and testing guide

### 3. **Key Features**

- **RESTful APIs**: All services expose `/ingest`, `/generate`, or `/trigger` endpoints
- **Health Checks**: Every service has `/health` endpoint
- **Error Handling**: Proper HTTP status codes and error messages
- **Environment Variables**: Configurable via Cloud Run env vars
- **Scalability**: Auto-scaling from 0 to 10 instances
- **Timeouts**: 1-hour timeout for long-running operations

## 📋 Deployment Steps

### Option 1: Deploy All Services (Recommended)

```powershell
# Windows
cd services
.\deploy_all.ps1
```

```bash
# Linux/Mac
cd services
chmod +x deploy_all.sh
./deploy_all.sh
```

### Option 2: Deploy Individual Service

```bash
SERVICE_NAME=ingest-docs  # Choose: ingest-docs, ingest-av, ingest-images, etc.

# Build
gcloud builds submit \
  --tag=gcr.io/sylvan-faculty-476113-c9/$SERVICE_NAME:latest \
  --dockerfile=services/Dockerfile.$SERVICE_NAME \
  .

# Deploy
gcloud run deploy $SERVICE_NAME \
  --image=gcr.io/sylvan-faculty-476113-c9/$SERVICE_NAME:latest \
  --platform=managed \
  --region=us-central1 \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=3600 \
  --set-env-vars="PROJECT_ID=sylvan-faculty-476113-c9,SOURCE_BUCKET=centef-rag-bucket,TARGET_BUCKET=centef-rag-chunks"
```

## 🧪 Testing After Deployment

### 1. Test Document Ingestion

```bash
curl -X POST https://ingest-docs-XXXX.run.app/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "gs://centef-rag-bucket/data/Algorithmic_Scams_How_AI_and_Social_Media_Enable_Financial_Fraud.pdf"
  }'
```

**Expected Response:**
```json
{
  "success": true,
  "source_uri": "gs://...",
  "chunks_uri": "gs://centef-rag-chunks/data/...pdf.jsonl",
  "num_chunks": 27,
  "message": "Successfully ingested 27 page chunks"
}
```

### 2. Test Video Ingestion

```bash
curl -X POST https://ingest-av-XXXX.run.app/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "source_uri": "gs://centef-rag-bucket/data/Syria Finances Round Table Recording Jan 8 2025.srt",
    "language": "en-US"
  }'
```

### 3. Test Summary Generation

```bash
curl -X POST https://summary-generator-XXXX.run.app/generate \
  -H "Content-Type: application/json" \
  -d '{
    "source_id": "pdf_algorithmic_scams",
    "chunks_uri": "gs://centef-rag-chunks/data/Algorithmic_Scams_How_AI_and_Social_Media_Enable_Financial_Fraud.pdf.jsonl",
    "metadata": {
      "title": "Algorithmic Scams Report",
      "author": "CENTEF Research Team",
      "date": "2024-10-01",
      "language": "en",
      "document_type": "pdf"
    }
  }'
```

### 4. Test Import Trigger

```bash
curl -X POST https://import-trigger-XXXX.run.app/trigger \
  -H "Content-Type: application/json" \
  -d '{"datastore": "both"}'
```

## 📊 Architecture Flow

```
User uploads file to gs://centef-rag-bucket/data/
       ↓
Cloud Storage Event Trigger
       ↓
┌──────────────────────────────────────┐
│ Orchestrator (Future: Cloud Workflow)│
└──────────────────────────────────────┘
       ↓
Route by file type:
       ├─→ .pdf/.pptx  → ingest-docs service
       ├─→ .mp4/.srt   → ingest-av service
       └─→ .jpg/.png   → ingest-images service
       ↓
Chunks written to gs://centef-rag-chunks/data/
       ↓
summary-generator service
       ↓
Summaries written to gs://centef-rag-chunks/summaries/
       ↓
manifest-updater service
       ↓
manifest.jsonl updated
       ↓
import-trigger service (datastore: "both")
       ↓
Discovery Engine datastores refreshed
```

## 🔧 Configuration

All services share these environment variables (set during deployment):

```bash
PROJECT_ID=sylvan-faculty-476113-c9
SOURCE_BUCKET=centef-rag-bucket
TARGET_BUCKET=centef-rag-chunks
SUMMARIES_BUCKET=centef-rag-chunks
DATASTORE_ID=centef-chunk-data-store_1761831236752_gcs_store
SUMMARIES_DATASTORE_ID=centef-summaries-datastore_1762162632284_gcs_store
VERTEX_LOCATION=us-central1
SUMMARY_MODEL=gemini-2.5-flash
```

## 💰 Cost Estimate

**Per Service:**
- Memory: 2 GiB
- CPU: 2
- Typical request: 30-300 seconds
- Cost: ~$0.05-0.50 per request (depending on duration)

**Monthly (100 documents):**
- Estimated: $20-50 for all services combined
- Free tier: First 2 million requests/month free

## 📝 Next Steps

### Immediate (Manual Testing)
1. ✅ Deploy services using `deploy_all.ps1`
2. ✅ Test each endpoint with curl commands
3. ✅ Verify chunks appear in GCS buckets
4. ✅ Check Discovery Engine imports complete

### Short-term (Orchestration)
1. Create Cloud Workflow YAML to chain services
2. Set up Cloud Storage trigger on upload
3. Add error handling and retries
4. Implement notification on completion (Pub/Sub)

### Long-term (Production)
1. Add authentication (IAM-based service-to-service)
2. Implement rate limiting
3. Add monitoring dashboards (Cloud Monitoring)
4. Set up alerting for failures
5. Add Cloud Logging for audit trail
6. Implement batch processing for large uploads

## 🐛 Troubleshooting

### Build Fails
```bash
# View build logs
gcloud builds list --limit=5
gcloud builds log <BUILD_ID>
```

### Service Errors
```bash
# Check logs
gcloud run services logs read ingest-docs --region=us-central1 --limit=100
```

### Permission Issues
- Verify service account has Storage Admin role
- Check Discovery Engine permissions
- Ensure Vertex AI API is enabled

## 🎯 Success Criteria

- [ ] All 6 services deploy successfully
- [ ] Health check endpoints return 200 OK
- [ ] Document ingestion produces chunks in GCS
- [ ] Summary generation creates summaries
- [ ] Import trigger successfully updates datastores
- [ ] End-to-end: PDF → chunks → summary → datastore

## 📚 Resources

- **Service Code**: `services/` directory
- **Testing Guide**: `services/README.md`
- **Deployment Scripts**: `services/deploy_all.{ps1,sh}`
- **Original Tools**: `tools/` directory (tested and working)

---

**Status**: ✅ Ready for deployment
**Last Updated**: 2025-11-03
**Git Commit**: `8565604`
