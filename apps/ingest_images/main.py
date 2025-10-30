from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared.schemas import make_chunk, to_discoveryengine_jsonl
from shared.io_gcs import write_text
from shared.chunk_utils import deterministic_chunk_id
from shared.config import get_config

app = FastAPI(title="Ingest Images Service")

CHUNKS_BUCKET = get_config().CHUNKS_BUCKET or "gs://centef-rag-chunks"


class IngestImageRequest(BaseModel):
    source_id: str
    uri: str        # gs:// to an image (png/jpg)
    title: str
    ocr_text: str | None = None
    caption: str | None = None
    lang: str = "en"


@app.post("/ingest")
def ingest(req: IngestImageRequest):
    if not req.uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Only gs:// URIs supported in this version")

    text = (req.caption or "").strip() or (req.ocr_text or "").strip() or "image"
    chunk_id = deterministic_chunk_id(
        source_id=req.source_id,
        source_type="image",
        extra="image"
    )
    chunk = make_chunk(
        chunk_id=chunk_id,
        source_id=req.source_id,
        source_type="image",
        title=req.title,
        uri=req.uri,
        text=text,
        modality_payload={"bbox": None},
        lang=req.lang,
    )

    jsonl = to_discoveryengine_jsonl([chunk])
    out_path = f"{CHUNKS_BUCKET}/images/{req.source_id}.jsonl"
    write_text(out_path, jsonl)
    return {"written": 1, "output": out_path, "chunk_ids": [chunk.chunk_id]}
