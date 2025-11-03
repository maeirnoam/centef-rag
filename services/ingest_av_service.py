"""
Cloud Run service for audio/video ingestion.
Wraps tools/ingest_video.py and tools/ingest_srt.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import sys
import os

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

app = FastAPI(title="Audio/Video Ingestion Service")


class IngestAVRequest(BaseModel):
    source_uri: str  # gs://bucket/path/file.mp4 or .srt
    language: Optional[str] = "ar-SA"  # Default Arabic
    translate_to: Optional[str] = "en"  # Target language for translation


class IngestAVResponse(BaseModel):
    success: bool
    source_uri: str
    chunks_uri: str
    num_chunks: int
    source_type: str  # "video", "audio", "srt"
    message: str


@app.post("/ingest", response_model=IngestAVResponse)
async def ingest_av(request: IngestAVRequest):
    """
    Ingest audio/video file or SRT subtitle file.
    
    For video/audio:
    - Extracts audio using ffmpeg
    - Transcribes using Speech-to-Text API
    - Translates to target language
    - Creates time-windowed chunks
    
    For SRT:
    - Parses subtitle segments
    - Creates time-windowed chunks (30-second windows)
    
    Args:
        source_uri: GCS URI like gs://centef-rag-bucket/data/video.mp4
        language: Source language code (default: ar-SA for Arabic)
        translate_to: Target language for translation (default: en)
    
    Returns:
        chunks_uri: Location of generated chunks
        num_chunks: Number of chunks created
        source_type: Type of source processed
    """
    try:
        source_uri = request.source_uri
        
        # Validate input
        if not source_uri.startswith("gs://"):
            raise HTTPException(status_code=400, detail="source_uri must be a GCS URI (gs://...)")
        
        # Determine file type
        file_ext = source_uri.lower().split(".")[-1]
        
        if file_ext == "srt":
            # Process SRT file
            from ingest_srt import process_srt_file
            
            print(f"[ingest_av] Processing SRT: {source_uri}")
            chunks_uri = process_srt_file(source_uri)
            
            # Count chunks by reading the file
            from google.cloud import storage
            client = storage.Client()
            parts = chunks_uri.replace("gs://", "").split("/", 1)
            bucket = client.bucket(parts[0])
            blob = bucket.blob(parts[1])
            content = blob.download_as_text()
            num_chunks = len([line for line in content.split("\n") if line.strip()])
            
            return IngestAVResponse(
                success=True,
                source_uri=source_uri,
                chunks_uri=chunks_uri,
                num_chunks=num_chunks,
                source_type="srt",
                message=f"Successfully ingested {num_chunks} subtitle chunks"
            )
            
        elif file_ext in ["mp4", "mp3", "wav", "m4a", "avi", "mov"]:
            # Process video/audio file
            from ingest_video import process_video_file
            
            print(f"[ingest_av] Processing video/audio: {source_uri}")
            chunks_uri = process_video_file(
                source_uri,
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
            
            return IngestAVResponse(
                success=True,
                source_uri=source_uri,
                chunks_uri=chunks_uri,
                num_chunks=num_chunks,
                source_type="video" if file_ext == "mp4" else "audio",
                message=f"Successfully ingested {num_chunks} transcript chunks"
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_ext}. Supported: mp4, mp3, wav, m4a, avi, mov, srt"
            )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ingest-av"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
