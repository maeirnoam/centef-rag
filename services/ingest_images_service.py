"""
Cloud Run service for image ingestion.
Wraps tools/ingest_image.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import sys
import os

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from ingest_image import process_image

app = FastAPI(title="Image Ingestion Service")


class IngestImageRequest(BaseModel):
    source_uri: str  # gs://bucket/path/image.jpg


class IngestImageResponse(BaseModel):
    success: bool
    source_uri: str
    chunks_uri: str
    num_chunks: int
    message: str


@app.post("/ingest", response_model=IngestImageResponse)
async def ingest_image(request: IngestImageRequest):
    """
    Ingest an image file with OCR and captioning.
    
    Args:
        source_uri: GCS URI like gs://centef-rag-bucket/data/image.jpg
    
    Returns:
        chunks_uri: Location of generated chunks
        num_chunks: Number of chunks (typically 1 per image)
    """
    try:
        source_uri = request.source_uri
        
        # Validate input
        if not source_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="source_uri must be a GCS URI (gs://...)")
        
        file_ext = source_uri.lower().split(".")[-1]
        if file_ext not in ["jpg", "jpeg", "png", "gif", "bmp", "webp"]:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported image format: {file_ext}"
            )
        
        print(f"[ingest_images] Processing: {source_uri}")
        chunks_uri = process_image(source_uri)
        
        # Images typically produce 1 chunk
        num_chunks = 1
        
        return IngestImageResponse(
            success=True,
            source_uri=source_uri,
            chunks_uri=chunks_uri,
            num_chunks=num_chunks,
            message="Successfully ingested image"
        )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ingest-images"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
