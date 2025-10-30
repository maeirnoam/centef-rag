# CENTEF RAG – Multimodal RAG on Google Cloud

End-to-end, modular multimodal RAG built with Python, LangChain, LangGraph, and Vertex AI (Gemini + Vertex AI Search). Ingests PDFs/PPTX, audio/video, and images from Google Cloud Storage (optionally Google Drive → GCS), chunks at page/slide/timestamp granularity, indexes in Vertex AI Search, and serves a chat API with grounded citations.

This repo follows the design in `.github/instructions/multiModalRag.instructions.md`.

## Architecture

- Index: Vertex AI Search (Discovery Engine) with Cloud Storage source at `gs://<CHUNKS_BUCKET>/**`.
- Ingestion services (Cloud Run):
	- apps/ingest_docs: per-page chunks (PDF/PPTX→PDF), PyMuPDF fallback; DocAI optional.
	- apps/ingest_av: pluggable ASR (Google STT v2 or 11labs) → timestamped chunks.
	- apps/ingest_images: OCR/caption (simple text pivot) → single chunk.
- Agent API (Cloud Run): retrieves with Vertex AI Search and composes answers via Gemini, orchestrated with LangGraph.
- Update strategy: deterministic chunk IDs so updates overwrite; optional admin reconcile endpoint deletes obsolete chunks.

## Prereqs

- Google Cloud project: sylvan-faculty-476113-c9 (or your project)
- Enable APIs:
	- Vertex AI API
	- Discovery Engine API (Vertex AI Search)
	- Cloud Run Admin API
	- Cloud Build API
	- Artifact Registry API
	- Cloud Storage
	- Speech-to-Text v2 (if using Google ASR)
	- Document AI (optional)
- Service account with roles: Storage Admin (or Object Admin), Discovery Engine Admin, Vertex AI User, Cloud Run Admin (for deploy), Speech-to-Text Admin (if STT), Document AI Editor (if DocAI).

## Buckets and Data Store

- Create a GCS bucket for chunks (or reuse): `gs://centef-rag-chunks`
- In Vertex AI Search:
	1. Create a Data Store (Content search) in your project and location.
	2. Configure source = Cloud Storage, path = `gs://centef-rag-chunks/**`.
	3. In schema, add custom fields: `source_id`, `source_type`, `page`, `slide`, `start_sec`, `end_sec`, `lang`, `hash`.
	4. Deploy a Serving Config and note its full resource name.

Set env vars (example) – a `.env` is included with sane defaults:

- PROJECT_ID = sylvan-faculty-476113-c9
- VERTEX_SEARCH_LOCATION = global
- DISCOVERY_DATASTORE = projects/sylvan-faculty-476113-c9/locations/global/collections/default_collection/dataStores/centef-chunk-data-store
- DISCOVERY_SERVING_CONFIG = projects/sylvan-faculty-476113-c9/locations/global/collections/default_collection/dataStores/centef-chunk-data-store/servingConfigs/default_serving_config
- GENERATION_LOCATION = us-central1
- SOURCE_DATA_PREFIX = gs://centef-rag-bucket/data
- CHUNKS_BUCKET = gs://centef-rag-chunks
- ASR_PROVIDER = google (or 11labs)
- ELEVENLABS_ASR_URL, ELEVENLABS_API_KEY if using 11labs

Optional:
- DOC_AI_PROJECT, DOC_AI_LOCATION, DOC_AI_PROCESSOR_ID if using Document AI
- SPEECH_RECOGNIZER_ID if you pre-created a v2 recognizer

## Deploy to Cloud Run

Build and deploy each service. Replace <REGION> and <PROJECT> as needed.

```powershell
# Agent API
gcloud builds submit --tag "{REGION}-docker.pkg.dev/{PROJECT}/centef/agent-api:latest" . ; \
gcloud run deploy agent-api --image "{REGION}-docker.pkg.dev/{PROJECT}/centef/agent-api:latest" --region {REGION} --platform managed --allow-unauthenticated \
		# Vertex AI Search is in 'global' for this app
		--set-env-vars "DISCOVERY_SERVING_CONFIG=projects/{PROJECT}/locations/global/collections/default_collection/dataStores/centef-chunk-data-store/servingConfigs/default_serving_config" \
		--set-env-vars "DISCOVERY_DATASTORE=projects/{PROJECT}/locations/global/collections/default_collection/dataStores/centef-chunk-data-store" \
	--set-env-vars "CHUNKS_BUCKET=gs://centef-rag-chunks" \
	--set-env-vars "GCP_PROJECT={PROJECT}" \
		--set-env-vars "VERTEX_LOCATION=us-central1"

# Ingest Docs
gcloud builds submit --tag "{REGION}-docker.pkg.dev/{PROJECT}/centef/ingest-docs:latest" . ; \
gcloud run deploy ingest-docs --image "{REGION}-docker.pkg.dev/{PROJECT}/centef/ingest-docs:latest" --region {REGION} --platform managed --allow-unauthenticated \
	--set-env-vars "CHUNKS_BUCKET=gs://centef-rag-chunks"

# Ingest AV
gcloud builds submit --tag "{REGION}-docker.pkg.dev/{PROJECT}/centef/ingest-av:latest" . ; \
gcloud run deploy ingest-av --image "{REGION}-docker.pkg.dev/{PROJECT}/centef/ingest-av:latest" --region {REGION} --platform managed --allow-unauthenticated \
	--set-env-vars "CHUNKS_BUCKET=gs://centef-rag-chunks" \
	--set-env-vars "ASR_PROVIDER=google" \
	--set-env-vars "GCP_PROJECT={PROJECT}" \
	--set-env-vars "SPEECH_LOCATION={REGION}"

# Ingest Images
gcloud builds submit --tag "{REGION}-docker.pkg.dev/{PROJECT}/centef/ingest-images:latest" . ; \
gcloud run deploy ingest-images --image "{REGION}-docker.pkg.dev/{PROJECT}/centef/ingest-images:latest" --region {REGION} --platform managed --allow-unauthenticated \
	--set-env-vars "CHUNKS_BUCKET=gs://centef-rag-chunks"
```

Tip: For faster builds, create an Artifact Registry repo `centef` beforehand and use `--source` pointing at each app with a simple Dockerfile context. The above submits the whole repo for brevity.

## Try it

1) Ingest a PDF (replace values):

```powershell
$body = @{ source_id = "doc-123"; uri = "gs://your-bucket/path/to/file.pdf"; title = "My PDF"; source_type = "pdf" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://<INGEST_DOCS_URL>/ingest" -ContentType 'application/json' -Body $body
```

2) Ingest an audio file:

```powershell
$body = @{ source_id = "aud-001"; uri = "gs://your-bucket/audio.mp3"; title = "Interview"; source_type = "audio" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://<INGEST_AV_URL>/ingest" -ContentType 'application/json' -Body $body
```

3) Ask a question:

```powershell
$body = @{ question = "Summarize page 2 of My PDF"; k = 6 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://<AGENT_API_URL>/chat" -ContentType 'application/json' -Body $body
```

## Anchors and citations
- Docs: page number included in `modality_payload.page`; retriever returns it in metadata.
- AV: segments include `start_sec` and `end_sec`; answer prompt formats [start-end s].
- Images: one chunk per image for now; you can extend with object/region-level anchors.

## Updates and deletes

- Deterministic chunk IDs ensure re-ingests overwrite existing documents in Discovery Engine.
- If a source’s chunk layout changed (e.g., slides added/removed), call the admin endpoint to delete obsolete chunks:

```powershell
$reconcile = @{ source_id = "doc-123"; new_chunk_ids = @("<id1>", "<id2>") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://<AGENT_API_URL>/admin/reconcile" -ContentType 'application/json' -Body $reconcile
```

Note: Listing all documents can be costly; for large indices, maintain a per-source manifest of chunk IDs in GCS and only reconcile when necessary.

## Local dev

- Set GOOGLE_APPLICATION_CREDENTIALS to a service account JSON with required roles.
- Launch any service with uvicorn locally, e.g.:

```powershell
$env:DISCOVERY_SERVING_CONFIG = "projects/<PROJECT>/locations/<LOC>/collections/default_collection/dataStores/<DATASTORE>/servingConfigs/default_serving_config"
uvicorn apps.agent_api.main:app --reload --port 8080
```

## Notes

- PPTX → PDF conversion can be added in `ingest_docs` Dockerfile with LibreOffice (soffice) and a small wrapper; current version expects PDF already.
- For high-fidelity images/diagrams, plug Gemini 1.5 Vision or Document AI Form Parser to enrich `text` and `modality_payload`.
- If you prefer Vertex AI Agent Builder for conversation, you can still reuse this indexing path and call Retrieval via its Search grounding from the agent.
