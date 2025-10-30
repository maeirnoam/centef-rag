from __future__ import annotations
import os
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared.schemas import make_chunk, to_discoveryengine_jsonl
from shared.io_gcs import write_text
from shared.chunk_utils import deterministic_chunk_id
from .docai_layout import page_texts_with_pymupdf

app = FastAPI(title="Ingest Docs Service")

from shared.config import get_config
CHUNKS_BUCKET = get_config().CHUNKS_BUCKET or "gs://centef-rag-chunks"


class IngestDocRequest(BaseModel):
    source_id: str  # drive file id or path stem
    uri: str        # gs:// path to a PDF (or PPTX converted prior)
    title: str
    source_type: str = "pdf"  # or "pptx" once conversion supported
    lang: str = "en"


@app.post("/ingest")
def ingest(req: IngestDocRequest):
    if not req.uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Only gs:// URIs supported in this version")

    # TODO: if source_type == pptx, convert to PDF (LibreOffice) and set pdf_uri
    pdf_uri = req.uri

    # Extract per-page text (PyMuPDF fallback)
    pages = page_texts_with_pymupdf(pdf_uri)
    chunks = []
    chunk_ids = []
    for page_num, text in pages:
        if not text.strip():
            continue
        chunk_id = deterministic_chunk_id(
            source_id=req.source_id,
            source_type=req.source_type,
            page=page_num,
        )
        chunks.append(
            make_chunk(
                chunk_id=chunk_id,
                source_id=req.source_id,
                source_type=req.source_type,
                title=f"{req.title} - p.{page_num}",
                uri=req.uri,
                text=text,
                modality_payload={"page": page_num},
                lang=req.lang,
            )
        )
        chunk_ids.append(chunk_id)

    if not chunks:
        raise HTTPException(status_code=400, detail="No text extracted from document")

    jsonl = to_discoveryengine_jsonl(chunks)
    out_path = f"{CHUNKS_BUCKET}/docs/{req.source_id}.jsonl"
    write_text(out_path, jsonl)
    return {"written": len(chunks), "output": out_path, "chunk_ids": chunk_ids}
