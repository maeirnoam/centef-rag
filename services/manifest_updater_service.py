"""
Cloud Run service for manifest updates.
Wraps tools/populate_manifest.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import sys
import os
import json

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

app = FastAPI(title="Manifest Updater Service")


class ManifestEntry(BaseModel):
    source_id: str
    title: str
    document_type: str  # pdf, video, audio, image, youtube, srt
    language: str
    source_uri: str
    chunks_uri: str
    summary_uri: Optional[str] = None
    num_chunks: int
    author: Optional[str] = None
    speaker: Optional[str] = None
    organization: Optional[str] = None
    date: Optional[str] = None
    tags: Optional[List[str]] = None


class UpdateManifestRequest(BaseModel):
    entry: ManifestEntry


class UpdateManifestResponse(BaseModel):
    success: bool
    source_id: str
    message: str


def load_manifest(manifest_path: str = "manifest.jsonl") -> List[Dict[str, Any]]:
    """Load existing manifest"""
    if not os.path.exists(manifest_path):
        return []
    
    entries = []
    with open(manifest_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def save_manifest(entries: List[Dict[str, Any]], manifest_path: str = "manifest.jsonl"):
    """Save manifest to JSONL"""
    with open(manifest_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.post("/update", response_model=UpdateManifestResponse)
async def update_manifest(request: UpdateManifestRequest):
    """
    Add or update an entry in manifest.jsonl
    
    Args:
        entry: Manifest entry with document metadata
    
    Returns:
        Success status and message
    """
    try:
        entry_dict = request.entry.dict(exclude_none=True)
        source_id = entry_dict["source_id"]
        
        print(f"[manifest_updater] Updating manifest for {source_id}")
        
        # Load existing manifest
        manifest_path = "manifest.jsonl"
        entries = load_manifest(manifest_path)
        
        # Find and update or append
        found = False
        for i, existing in enumerate(entries):
            if existing.get("source_id") == source_id:
                entries[i] = entry_dict
                found = True
                print(f"  Updated existing entry")
                break
        
        if not found:
            entries.append(entry_dict)
            print(f"  Added new entry")
        
        # Save manifest
        save_manifest(entries, manifest_path)
        
        return UpdateManifestResponse(
            success=True,
            source_id=source_id,
            message=f"Manifest updated for {source_id}"
        )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "manifest-updater"}


@app.get("/manifest")
async def get_manifest():
    """Get current manifest entries"""
    try:
        entries = load_manifest("manifest.jsonl")
        return {"entries": entries, "count": len(entries)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
