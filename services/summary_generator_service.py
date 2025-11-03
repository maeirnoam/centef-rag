"""
Cloud Run service for summary generation.
Wraps tools/ingest_summaries.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import os

# Add tools and shared directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from ingest_summaries import (
    read_chunks_from_gcs,
    generate_summary_with_metadata,
    create_summary_document,
    upload_summary_jsonl
)

app = FastAPI(title="Summary Generation Service")


class GenerateSummaryRequest(BaseModel):
    source_id: str  # Unique document identifier
    chunks_uri: str  # gs://bucket/path/chunks.jsonl
    metadata: Dict[str, Any]  # title, author, speaker, date, etc.


class GenerateSummaryResponse(BaseModel):
    success: bool
    source_id: str
    summary_uri: str
    summary_length: int
    num_chunks: int
    message: str


@app.post("/generate", response_model=GenerateSummaryResponse)
async def generate_summary(request: GenerateSummaryRequest):
    """
    Generate a comprehensive AI summary from document chunks.
    
    Args:
        source_id: Unique identifier (e.g., "pdf_fraud_report_2024")
        chunks_uri: GCS URI to chunks JSONL
        metadata: Dict with title, author, speaker, organization, date, language, tags, etc.
    
    Returns:
        summary_uri: Location of summary document
        summary_length: Character length of generated summary
        num_chunks: Number of source chunks processed
    """
    try:
        source_id = request.source_id
        chunks_uri = request.chunks_uri
        metadata = request.metadata
        
        # Validate inputs
        if not chunks_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="chunks_uri must be a GCS URI")
        
        print(f"[summary_generator] Processing {source_id}")
        print(f"  Chunks: {chunks_uri}")
        print(f"  Metadata: {metadata}")
        
        # Read chunks
        chunks = read_chunks_from_gcs(chunks_uri)
        if not chunks:
            raise HTTPException(status_code=422, detail="No chunks found in chunks_uri")
        
        print(f"  Loaded {len(chunks)} chunks")
        
        # Generate summary
        summary_text = generate_summary_with_metadata(chunks, metadata)
        print(f"  Generated summary: {len(summary_text)} chars")
        
        # Create summary document
        summary_doc = create_summary_document(
            source_id=source_id,
            summary_text=summary_text,
            metadata=metadata,
            chunks_uri=chunks_uri,
            num_chunks=len(chunks)
        )
        
        # Upload to summaries bucket
        target_blob = f"summaries/{source_id}.jsonl"
        upload_summary_jsonl(summary_doc, target_blob)
        
        SUMMARIES_BUCKET = os.environ.get("SUMMARIES_BUCKET", "centef-rag-chunks")
        summary_uri = f"gs://{SUMMARIES_BUCKET}/{target_blob}"
        
        return GenerateSummaryResponse(
            success=True,
            source_id=source_id,
            summary_uri=summary_uri,
            summary_length=len(summary_text),
            num_chunks=len(chunks),
            message=f"Successfully generated summary from {len(chunks)} chunks"
        )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "summary-generator"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
