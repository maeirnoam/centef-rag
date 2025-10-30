from __future__ import annotations
import os
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared.schemas import make_chunk, to_discoveryengine_jsonl
from shared.io_gcs import write_text
from shared.chunk_utils import deterministic_chunk_id
from shared.asr_google import GoogleASRClient
from shared.asr_11labs import ElevenLabsASRClient
from shared.config import get_config

app = FastAPI(title="Ingest AV Service")

cfg = get_config()
ASR_PROVIDER = cfg.ASR_PROVIDER or "google"  # "google" | "11labs"
CHUNKS_BUCKET = cfg.CHUNKS_BUCKET or "gs://centef-rag-chunks"
DEFAULT_LANG = os.environ.get("ASR_LANG", "en")


def get_asr():
    if ASR_PROVIDER.lower() == "11labs":
        return ElevenLabsASRClient()
    project_id = cfg.PROJECT_ID
    location = cfg.SPEECH_LOCATION or "global"
    recognizer_id = cfg.SPEECH_RECOGNIZER_ID
    return GoogleASRClient(project_id=project_id, location=location, recognizer_id=recognizer_id)


class IngestAVRequest(BaseModel):
    source_id: str
    uri: str        # gs:// path to audio/video (audio track preferred)
    title: str
    source_type: str = "audio"  # or "video"
    lang: str = DEFAULT_LANG


@app.post("/ingest")
def ingest(req: IngestAVRequest):
    if not req.uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Only gs:// URIs supported in this version")

    asr = get_asr()
    segments = asr.transcribe(req.uri, lang=req.lang)
    if not segments:
        raise HTTPException(status_code=400, detail="No segments transcribed")

    chunks = []
    chunk_ids = []
    for seg in segments:
        start, end = float(seg.get("start", 0.0)), float(seg.get("end", 0.0))
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        chunk_id = deterministic_chunk_id(
            source_id=req.source_id,
            source_type=req.source_type,
            start_sec=round(start, 2),
            end_sec=round(end, 2),
        )
        chunks.append(
            make_chunk(
                chunk_id=chunk_id,
                source_id=req.source_id,
                source_type=req.source_type,
                title=f"{req.title} [{start:.1f}-{end:.1f}s]",
                uri=req.uri,
                text=text,
                modality_payload={"start_sec": start, "end_sec": end},
                lang=req.lang,
            )
        )
        chunk_ids.append(chunk_id)

    if not chunks:
        raise HTTPException(status_code=400, detail="No text content from ASR")

    jsonl = to_discoveryengine_jsonl(chunks)
    out_path = f"{CHUNKS_BUCKET}/av/{req.source_id}.jsonl"
    write_text(out_path, jsonl)
    return {"written": len(chunks), "output": out_path, "chunk_ids": chunk_ids}
