"""
Cloud Run service for document ingestion (PDF, PPTX).
Wraps tools/ingest_pdf_pages.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sys
import os

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from ingest_pdf_pages import process_one_pdf, download_pdf, extract_pages_pymupdf, upload_jsonl

app = FastAPI(title="Document Ingestion Service")


class IngestRequest(BaseModel):
    source_uri: str  # gs://bucket/path/file.pdf
    

class IngestResponse(BaseModel):
    success: bool
    source_uri: str
    chunks_uri: str
    num_chunks: int
    message: str


@app.post("/ingest", response_model=IngestResponse)
async def ingest_document(request: IngestRequest):
    """
    Ingest a PDF document and generate chunks.
    
    Args:
        source_uri: GCS URI like gs://centef-rag-bucket/data/document.pdf
    
    Returns:
        chunks_uri: Location of generated chunks (gs://centef-rag-chunks/data/document.pdf.jsonl)
        num_chunks: Number of chunks created
    """
    try:
        source_uri = request.source_uri
        
        # Validate input
        if not source_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="source_uri must be a GCS URI (gs://...)")
        
        if not source_uri.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        
        # Download and extract
        print(f"[ingest_docs] Processing: {source_uri}")
        pdf_bytes = download_pdf(source_uri)
        chunks = extract_pages_pymupdf(pdf_bytes, source_uri)
        
        if not chunks:
            raise HTTPException(status_code=422, detail="No content extracted from PDF")
        
        # Upload to chunks bucket
        SOURCE_BUCKET = os.environ.get("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
        TARGET_BUCKET = os.environ.get("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
        
        rel_path = source_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
        target_blob = f"{rel_path}.jsonl"
        upload_jsonl(chunks, target_blob)
        
        chunks_uri = f"gs://{TARGET_BUCKET}/{target_blob}"
        
        return IngestResponse(
            success=True,
            source_uri=source_uri,
            chunks_uri=chunks_uri,
            num_chunks=len(chunks),
            message=f"Successfully ingested {len(chunks)} page chunks"
        )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ingest-docs"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
