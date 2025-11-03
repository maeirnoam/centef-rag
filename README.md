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
	- Speech-to-Text API (for video/audio transcription)
	- Cloud Translation API (for multilingual video transcription)
	- Document AI (optional)
- Service account with roles: Storage Admin (or Object Admin), Discovery Engine Admin, Vertex AI User, Cloud Run Admin (for deploy), Speech-to-Text Admin, Cloud Translation User, Document AI Editor (if DocAI).

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

## Local tools for ingestion

Several standalone tools are provided in the `tools/` directory for local batch ingestion:

### PDF Ingestion
```powershell
# Ingest a single PDF with page-level chunking
python tools/ingest_pdf_pages.py "gs://centef-rag-bucket/data/document.pdf"

# Process all PDFs in the source bucket
python tools/ingest_pdf_pages.py
```

### SRT Subtitle Ingestion
```powershell
# Ingest SRT with 30-second time windows
python tools/ingest_srt.py "gs://centef-rag-bucket/data/video.srt"

# Process all SRT files
python tools/ingest_srt.py
```

### Video Ingestion (Transcription + Translation)
```powershell
# Step 1: Extract audio from video (requires ffmpeg)
python tools/extract_audio.py "gs://centef-rag-bucket/data/video.mp4"

# Step 2: Transcribe (Arabic) and translate (English) with 30-second windows
python tools/ingest_video.py "gs://centef-rag-bucket/data/video.mp4" \
  --audio-uri "gs://centef-rag-bucket/data/video.wav" \
  --language ar-SA \
  --translate en \
  --window 30
```

The video ingestion tool:
- Uses Google Speech-to-Text API for transcription with word-level timestamps
- Supports multiple languages (e.g., ar-SA for Arabic, en-US for English)
- Uses Google Cloud Translation API to translate to target language
- Stores both original and translated text in chunks
- Creates time-windowed chunks (default 30 seconds) from transcription segments

### YouTube Ingestion
```powershell
# Ingest English YouTube video (no translation needed)
python tools/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID" \
  --language en-US \
  --translate none \
  --window 30

# Ingest Arabic YouTube video with English translation
python tools/ingest_youtube.py "https://www.youtube.com/watch?v=VIDEO_ID" \
  --language ar-SA \
  --translate en \
  --window 30
```

The YouTube ingestion tool:
- Downloads audio using yt-dlp and converts to 16kHz mono WAV with ffmpeg
- Uploads audio to GCS automatically
- Calls the video transcription pipeline (Speech-to-Text + optional Translation)
- Creates time-windowed chunks with timestamps for precise navigation
- Requires: `yt-dlp` package and `ffmpeg` installed locally

### Trigger Discovery Engine Import
```powershell
# Import all JSONL files from the chunks bucket
python tools/trigger_datastore_import.py
```

### Search with AI Summary
```powershell
# Search with AI-generated summary and citations
python tools/search_with_summary.py "your search query"

# Simple search
python tools/search_datastore.py "your search query"
```

## Try it (Cloud Run)

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

## Two-Tier Retrieval Architecture (Optional)

For improved search relevance, you can implement a **two-tier retrieval** system using multiple Vertex AI Search datastores:

### Architecture
1. **Summaries Index** (`summaries_datastore`): One enriched summary per document with metadata
2. **Chunks Index** (`chunks_datastore`): Granular chunks with page/timestamp anchors (current implementation)

### Benefits
- **Better Document Discovery**: Summaries capture document-level context, themes, and metadata
- **Metadata-Rich Search**: Search by author, speaker, organization, date, tags, etc.
- **Coarse-to-Fine Retrieval**: Find relevant documents first, then drill down to specific chunks
- **Improved Ranking**: Multi-datastore search combines signals from both levels

### Setup
```powershell
# 1. Generate summaries with metadata for all documents
python tools/ingest_summaries.py --batch --manifest manifest.jsonl

# 2. Create a new Vertex AI Search datastore for summaries
#    Point it to gs://centef-rag-chunks/summaries/**/*.jsonl

# 3. Create a Search App that combines both datastores
#    Update SERVING_CONFIG to point to the App's serving config

# 4. Searches now automatically query both summaries and chunks
python tools/search_with_summary.py "What are the terrorist financing methods?"
```

### Manifest Format
Create `manifest.jsonl` with document metadata:
```json
{"source_id": "doc1", "chunks_uri": "gs://bucket/doc1.jsonl", "metadata": {"title": "...", "author": "...", "speaker": "...", "organization": "...", "date": "2024-10", "tags": ["tag1", "tag2"]}}
```

See `manifest.jsonl` for examples with all current documents.

## Anchors and citations
- **PDFs**: Page numbers displayed as `[Page N]` in search results, stored in `structData.page`
- **Videos/Audio**: Timestamps displayed as `[MM:SS - MM:SS]` in search results, stored in `structData.start_sec` and `structData.end_sec`
- **SRT subtitles**: Time-windowed chunks with timestamp ranges for precise navigation
- **Images**: Single chunk per image (can be extended with region-level anchors)

Search results automatically detect content type and format anchors accordingly, enabling direct navigation to relevant content.

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

## Supported Content Types

### Current Implementation
- ✅ **PDFs**: Page-level text extraction using PyMuPDF, with page anchors
- ✅ **SRT Subtitles**: Time-windowed chunking (30-second windows) from subtitle files
- ✅ **Videos**: Audio extraction with ffmpeg, transcription via Speech-to-Text API, translation support for multilingual content
- ✅ **YouTube**: Direct ingestion from YouTube URLs using yt-dlp, automatic audio download and transcription
- ✅ **Search**: AI-generated summaries with citations and precise anchors (page numbers, timestamps)

### Roadmap
- 🔄 **PPTX**: Slide-level extraction (can add LibreOffice soffice conversion in Dockerfile)
- 🔄 **Audio files**: Direct audio ingestion without video extraction
- 🔄 **Images**: OCR and captioning with Vision API or Document AI
- 🔄 **Cloud Run deployment**: Containerized services ready for production deployment

## Notes

- **Video transcription** supports 125+ languages via Speech-to-Text API (e.g., ar-SA for Arabic, en-US for English)
- **Translation** available for all videos via Cloud Translation API, storing both original and translated text
- **Audio extraction** requires ffmpeg installed locally or in container
- PPTX → PDF conversion can be added in `ingest_docs` Dockerfile with LibreOffice (soffice) and a small wrapper; current version expects PDF already.
- For high-fidelity images/diagrams, plug Gemini 1.5 Vision or Document AI Form Parser to enrich `text` and `modality_payload`.
- If you prefer Vertex AI Agent Builder for conversation, you can still reuse this indexing path and call Retrieval via its Search grounding from the agent.
