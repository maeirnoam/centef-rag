"""
Cloud Run service for YouTube video ingestion.
Wraps tools/ingest_youtube.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
import os

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from ingest_youtube import process_youtube_video

app = FastAPI(title="YouTube Ingestion Service")


class IngestYouTubeRequest(BaseModel):
    video_id: str  # YouTube video ID (e.g., "_7ri5lgCCTM")
    language: Optional[str] = "en-US"  # Language code for transcription
    translate_to: Optional[str] = "en"  # Target language for translation


class IngestYouTubeResponse(BaseModel):
    success: bool
    video_id: str
    youtube_url: str
    chunks_uri: str
    num_chunks: int
    message: str


@app.post("/ingest", response_model=IngestYouTubeResponse)
async def ingest_youtube(request: IngestYouTubeRequest):
    """
    Ingest a YouTube video by downloading, transcribing, and chunking.
    
    Args:
        video_id: YouTube video ID from URL (e.g., "_7ri5lgCCTM")
        language: Language code for transcription (default: en-US)
        translate_to: Target language for translation (default: en)
    
    Returns:
        chunks_uri: Location of generated chunks
        num_chunks: Number of chunks created
        youtube_url: Full YouTube URL
    """
    try:
        video_id = request.video_id
        
        # Validate input
        if not video_id or len(video_id) < 10:
            raise HTTPException(status_code=400, detail="Invalid YouTube video ID")
        
        print(f"[ingest_youtube] Processing video: {video_id}")
        chunks_uri = process_youtube_video(
            video_id=video_id,
            language_code=request.language,
            translate_to=request.translate_to
        )
        
        # Count chunks
        from google.cloud import storage
        client = storage.Client()
        parts = chunks_uri.replace("gs://", "").split("/", 1)
        bucket = client.bucket(parts[0])
        blob = bucket.blob(parts[1])
        content = blob.download_as_text()
        num_chunks = len([line for line in content.split("\n") if line.strip()])
        
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        
        return IngestYouTubeResponse(
            success=True,
            video_id=video_id,
            youtube_url=youtube_url,
            chunks_uri=chunks_uri,
            num_chunks=num_chunks,
            message=f"Successfully ingested {num_chunks} YouTube transcript chunks"
        )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ingest-youtube"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
