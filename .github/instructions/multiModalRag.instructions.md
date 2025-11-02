---
applyTo: '**'
---
Perfect, that makes it simpler 👍

We’ll **drop**:

* future-proof dual emitters,
* BYO embeddings,
* Matching Engine.

We’ll **keep**:

* multimodal → **text-as-pivot**
* one retriever → **Vertex AI Search (Discovery Engine)**
* fine-grained anchors (page / slide / start_sec)
* modular ingestion services
* and we’ll add **pluggable ASR** so you can swap Google STT ↔ 11labs (or any other ME-focused ASR).

Here’s the **cleaned** design.

---

## 1. What we’re building now

**Goal:** “Give me an answer and show me where it came from (page/timestamp).”
**Index:** **Vertex AI Search** only.
**Ingestion:** 3 services → Docs, AV, Images.
**Audio/Video:** can call **Google STT v2** *or* **11labs (custom ASR)** based on config.

---

## 2. Repo structure (simplified)

```text
centef-rag/
  README.md
  infra/
    cloudrun/
      agent-api.Dockerfile
      ingest-docs.Dockerfile
      ingest-av.Dockerfile
      ingest-images.Dockerfile
  shared/
    schemas.py
    io_gcs.py
    io_drive.py
    chunk_utils.py
    asr_base.py          # <-- interface
    asr_google.py        # <-- impl 1
    asr_11labs.py        # <-- impl 2 (your ME/languages)
  apps/
    agent_api/
      main.py
      retriever_vertex_search.py
      composer_gemini.py
      graph.py
      requirements.txt
    ingest_docs/
      main.py
      docai_layout.py
      requirements.txt
    ingest_av/
      main.py
      requirements.txt
    ingest_images/
      main.py
      requirements.txt
  lovable/
    openapi.yaml
```

---

## 3. Canonical chunk schema (no BYO)

```python
# shared/schemas.py
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import uuid, hashlib, time, json

@dataclass
class Chunk:
    chunk_id: str
    source_id: str          # drive file id or gcs path
    source_type: str        # "pdf" | "pptx" | "audio" | "video" | "image" | "srt"
    title: str
    uri: str                # gs://... or drive://...
    text: str
    modality_payload: Dict[str, Any]
    entities: List[str]
    labels: List[str]
    lang: str
    created_at: str
    hash: str

def make_chunk(**kw) -> Chunk:
    txt = kw.get("text", "")
    return Chunk(
        chunk_id=str(uuid.uuid4()),
        hash=hashlib.sha256(txt.encode("utf-8")).hexdigest(),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        entities=[],
        labels=[],
        lang="en",
        **kw
    )

def to_jsonl(chunks: List[Chunk]) -> str:
    return "\n".join(json.dumps(asdict(c), ensure_ascii=False) for c in chunks)
```

**Note:** we removed `embeddings` from the schema. Discovery Engine will just **auto-embed** for us.

---

## 4. Ingestion services

### 4.1 Docs (`apps/ingest_docs/`)

**Flow**:

1. Get file (Drive/GCS).
2. If PPTX → convert to PDF (in container).
3. Call **Document AI Layout** → get per-page text.
4. For each page → `Chunk(source_type="pdf", modality_payload={"page": i})`.
5. Write JSONL to GCS in a prefix Discovery Engine watches, e.g.:

   * `gs://centef-rag-chunks/docs/<file_id>.jsonl`

**Discovery Engine** is then configured to pull from `gs://centef-rag-chunks/**`.

---

### 4.2 AV (`apps/ingest_av/`)

This is where your 11labs-like service comes in.

**Video Ingestion Tools:**
- `tools/extract_audio.py`: Extract audio from video files using ffmpeg, converts to mono 16kHz WAV for Speech-to-Text API
- `tools/ingest_video.py`: Complete video ingestion pipeline:
  - Transcribes audio using Google Speech-to-Text API with word-level timestamps
  - Supports 125+ languages (e.g., ar-SA for Arabic, en-US for English)
  - Translates transcription to target language using Cloud Translation API
  - Stores both original and translated text in chunks
  - Creates time-windowed chunks (default 30 seconds) from transcription segments
  - Generates structData format with start_sec, end_sec, text_original, language metadata

We define an **ASR interface**:

```python
# shared/asr_base.py
from abc import ABC, abstractmethod
from typing import List, Dict, Any

class ASRClient(ABC):
    @abstractmethod
    def transcribe(self, uri: str, lang: str = "ar") -> List[Dict[str, Any]]:
        """
        Returns a list of segments:
        [
          {"text": "....", "start": 1.2, "end": 3.5},
          ...
        ]
        """
        ...
```

**Google STT impl:**

```python
# shared/asr_google.py
from .asr_base import ASRClient

class GoogleASRClient(ASRClient):
    def transcribe(self, uri: str, lang: str = "ar") -> list[dict]:
        # pseudo: call STT v2 on GCS URI
        # return [{"text": "...", "start": 0.0, "end": 4.2}, ...]
        ...
```

**11labs / custom impl:**

```python
# shared/asr_11labs.py
import os, requests
from .asr_base import ASRClient

ELEVENLABS_ASR_URL = os.getenv("ELEVENLABS_ASR_URL")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

class ElevenLabsASRClient(ASRClient):
    def transcribe(self, uri: str, lang: str = "ar") -> list[dict]:
        # 1) download or stream audio from uri
        # 2) send to 11labs/custom endpoint
        # 3) normalize to [{"text":..., "start":..., "end":...}]
        resp = requests.post(
            ELEVENLABS_ASR_URL,
            headers={"Authorization": f"Bearer {ELEVENLABS_API_KEY}"},
            json={"audio_url": uri, "language": lang}
        )
        data = resp.json()
        # you normalize here depending on their real response
        segments = []
        for seg in data["segments"]:
            segments.append({
                "text": seg["text"],
                "start": seg["start"],
                "end": seg["end"]
            })
        return segments
```

**The ingestion worker chooses the ASR via env var:**

```python
# apps/ingest_av/main.py
import os
from shared.schemas import make_chunk, to_jsonl
from shared.io_gcs import write_text
from shared.asr_google import GoogleASRClient
from shared.asr_11labs import ElevenLabsASRClient

ASR_PROVIDER = os.getenv("ASR_PROVIDER", "google")  # "google" | "11labs"

def get_asr():
    if ASR_PROVIDER == "11labs":
        return ElevenLabsASRClient()
    return GoogleASRClient()

def ingest_av(source_id: str, uri: str, title: str, lang: str = "ar"):
    asr = get_asr()
    segments = asr.transcribe(uri, lang=lang)
    chunks = []
    for seg in segments:
        chunks.append(
            make_chunk(
                source_id=source_id,
                source_type="audio",
                title=title,
                uri=uri,
                text=seg["text"],
                modality_payload={
                    "start_sec": seg["start"],
                    "end_sec": seg["end"],
                }
            )
        )
    jsonl = to_jsonl(chunks)
    out_path = f"gs://centef-rag-chunks/av/{source_id}.jsonl"
    write_text(out_path, jsonl)
```

So: **the only thing you change to switch to 11labs is the env var**.

---

### 4.3 Images (`apps/ingest_images/`)

Same idea: OCR + caption → chunk → GCS.

```python
# apps/ingest_images/main.py
from shared.schemas import make_chunk, to_jsonl
from shared.io_gcs import write_text

def ingest_image(source_id: str, uri: str, title: str, ocr_text: str, caption: str):
    text = caption or ocr_text or "image with no text"
    chunk = make_chunk(
        source_id=source_id,
        source_type="image",
        title=title,
        uri=uri,
        text=text,
        modality_payload={"bbox": None}
    )
    jsonl = to_jsonl([chunk])
    out_path = f"gs://centef-rag-chunks/images/{source_id}.jsonl"
    write_text(out_path, jsonl)
```

(You can later plug Gemini Vision here to improve captions.)

---

## 5. Agent API (unchanged, just simpler)

```python
# apps/agent_api/retriever_vertex_search.py
from google.cloud import discoveryengine_v1 as des
import os

SERVING_CONFIG = os.environ["DISCOVERY_SERVING_CONFIG"]

def search_vertex(query: str, k: int = 8, filter_expr: str = ""):
    client = des.SearchServiceClient()
    req = des.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=k,
        filter=filter_expr,
    )
    hits = []
    for r in client.search(request=req).results:
        d = r.document
        f = d.struct_data.fields if d.struct_data else {}
        def getf(name, default=None):
            return f[name].string_value if name in f else default
        hits.append({
            "title": d.title,
            "uri": d.uri,
            "text": d.snippet or getf("text",""),
            "metadata": {
                "source_id": getf("source_id"),
                "source_type": getf("source_type"),
                "page": getf("page"),
                "slide": getf("slide"),
                "start_sec": getf("start_sec"),
                "end_sec": getf("end_sec"),
            }
        })
    return hits
```

Composer stays the same: it just prints citations based on what metadata is present.

---

## 6. Discovery Engine setup (what you need to do in GCP)

1. Create a **datastore** in Vertex AI Search (Content search type, unstructured).
2. Set **source = Cloud Storage**.
3. Point it to `gs://centef-rag-chunks/**/*.jsonl`.
4. Use **structData-only** format (no content field) for JSONL documents:
   ```json
   {
     "id": "unique_chunk_id",
     "structData": {
       "text": "chunk text content",
       "source_uri": "gs://bucket/path",
       "page": 10,
       "start_sec": 42.5,
       "end_sec": 72.5,
       "type": "page_text|subtitle_chunk|video_transcript",
       "extractor": "pymupdf|subtitle_parser|speech_to_text"
     }
   }
   ```
5. Deploy serving config → put the full path in `DISCOVERY_SERVING_CONFIG` for the agent.
6. Use incremental reconciliation mode for imports to allow updates/additions.

**Supported chunk types:**
- `page_text`: PDF pages with `page` field
- `subtitle_chunk`: SRT time windows with `start_sec`, `end_sec`, `duration_sec`, `segment_count`
- `video_transcript`: Transcribed video with `start_sec`, `end_sec`, `text_original`, `language`, timestamps

**Search features:**
- AI-generated summaries with `ContentSearchSpec.SummarySpec`
- Citation references with anchors: `[Page N]` for PDFs, `[MM:SS - MM:SS]` for video/audio
- Semantic search across all content types with unified text-as-pivot approach

Now every time one of the ingestion jobs writes a JSONL into that bucket, Search will pick it up and index it.

---

## 7. What we'll commit to the repo

Into `centef-rag/`:

1. `shared/schemas.py` (above)
2. `shared/io_gcs.py` (simple GCS writer)
3. `shared/asr_base.py`, `shared/asr_google.py`, `shared/asr_11labs.py`
4. `apps/ingest_av/main.py` using ASR_PROVIDER
5. `apps/ingest_docs/*` stub for DocAI layout
6. `apps/ingest_images/*` stub
7. `apps/agent_api/*` (FastAPI + retriever + composer)
8. `infra/cloudrun/*` Dockerfiles
9. **Local ingestion tools** (`tools/`):
   - `ingest_pdf_pages.py`: PyMuPDF-based PDF extraction with page anchors
   - `ingest_srt.py`: SRT subtitle parser with time-windowing (30-second chunks)
   - `extract_audio.py`: Audio extraction from video using ffmpeg
   - `ingest_video.py`: Video transcription + translation pipeline
   - `search_datastore.py`: Simple Discovery Engine search
   - `search_with_summary.py`: AI-powered search with summary and anchored citations
   - `trigger_datastore_import.py`: Trigger Discovery Engine JSONL import

