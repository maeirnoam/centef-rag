"""
Ingest images with Gemini Vision for text extraction and visual understanding.
Supports diagrams, flowcharts, infographics, and text-heavy images.
"""
import json
import os
import sys
import tempfile
import re
from typing import Optional

from google.cloud import storage
import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part, Image


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# ====== ENV ======
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = env("VERTEX_LOCATION", "us-central1")
SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
TARGET_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
SOURCE_DATA_PREFIX = os.environ.get("SOURCE_DATA_PREFIX", "data").strip("/")
# =================================


def get_storage_client():
    return storage.Client()


def analyze_image_with_gemini(image_gcs_uri: str) -> dict:
    """
    Use Gemini Vision to analyze image and extract text, relationships, and structure.
    """
    print(f"Analyzing image with Gemini Vision: {image_gcs_uri}")
    
    # Initialize Vertex AI
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    
    # Use Gemini Pro Vision for image analysis
    # Gemini 1.5 models support multimodal inputs including images
    model = GenerativeModel("gemini-pro-vision")
    
    # Create prompt for comprehensive image understanding
    prompt = """Analyze this image in detail and provide:

1. **Text Content**: Extract all visible text, labels, and annotations exactly as they appear.

2. **Visual Structure**: Describe the type of visual (flowchart, diagram, infographic, table, etc.) and its overall organization.

3. **Relationships**: If this is a flowchart or diagram, describe:
   - Key entities/nodes and what they represent
   - Connections and flows between elements
   - Directional relationships (what leads to what)
   - Any hierarchies or groupings

4. **Key Insights**: Summarize the main message or purpose of this visual.

Format your response as structured text that would be useful for semantic search. Be comprehensive but concise."""
    
    # Load image from GCS
    image_part = Part.from_uri(image_gcs_uri, mime_type="image/jpeg")
    
    # Generate response
    response = model.generate_content([prompt, image_part])
    
    analysis = response.text
    
    print(f"✓ Analysis complete ({len(analysis)} characters)")
    
    return {
        "full_analysis": analysis,
        "model": "gemini-pro-vision"
    }


def create_chunk(image_gcs_uri: str, analysis: dict) -> dict:
    """
    Create Discovery Engine chunk from image analysis.
    """
    # Extract filename for ID
    filename = image_gcs_uri.split("/")[-1]
    base_name = filename.rsplit(".", 1)[0]
    # Sanitize for chunk ID
    chunk_id = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
    
    # Use the full analysis as searchable text
    text = analysis["full_analysis"]
    
    chunk = {
        "id": f"image_{chunk_id}",
        "structData": {
            "text": text,
            "source_uri": image_gcs_uri,
            "type": "image_analysis",
            "extractor": "gemini_vision",
            "model": analysis["model"],
            "filename": filename
        }
    }
    
    return chunk


def upload_jsonl(records: list, target_blob: str):
    """Upload chunks as JSONL to GCS"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(TARGET_BUCKET)
    blob = bucket.blob(target_blob)
    ndjson = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    print(f"[OK] Uploaded {len(records)} chunk(s) → gs://{TARGET_BUCKET}/{target_blob}")


def process_image(image_gcs_uri: str):
    """
    Process an image: analyze with Gemini Vision and create searchable chunk.
    """
    print(f"\n== Processing image: {image_gcs_uri}")
    
    # Analyze with Gemini
    analysis = analyze_image_with_gemini(image_gcs_uri)
    
    # Create chunk
    chunk = create_chunk(image_gcs_uri, analysis)
    
    # Show preview
    print(f"\nChunk preview:")
    print(f"  ID: {chunk['id']}")
    print(f"  Text length: {len(chunk['structData']['text'])} characters")
    print(f"  First 200 chars: {chunk['structData']['text'][:200]}...")
    
    # Upload
    rel_path = image_gcs_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
    target_blob = f"{rel_path}.jsonl"
    upload_jsonl([chunk], target_blob)
    
    return chunk


def list_images_in_bucket(prefix: str = None) -> list:
    """List all image files in the source bucket"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(SOURCE_BUCKET)
    
    if prefix is None:
        prefix = SOURCE_DATA_PREFIX
    
    blobs = bucket.list_blobs(prefix=prefix)
    
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    images = []
    
    for blob in blobs:
        ext = os.path.splitext(blob.name.lower())[1]
        if ext in image_extensions:
            images.append(f"gs://{SOURCE_BUCKET}/{blob.name}")
    
    return images


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest images with Gemini Vision analysis")
    parser.add_argument("image_uri", nargs='?', help="GCS URI of image file (gs://bucket/path/image.jpg)")
    parser.add_argument("--batch", action="store_true", help="Process all images in source bucket")
    
    args = parser.parse_args()
    
    if args.batch or not args.image_uri:
        # Process all images
        print("Scanning for images in bucket...")
        images = list_images_in_bucket()
        
        if not images:
            print("No images found in bucket.")
            return
        
        print(f"Found {len(images)} image(s):")
        for img in images:
            print(f"  - {img}")
        
        print("\nProcessing images...")
        for i, img_uri in enumerate(images, 1):
            print(f"\n[{i}/{len(images)}]")
            try:
                process_image(img_uri)
            except Exception as e:
                print(f"ERROR processing {img_uri}: {e}")
                import traceback
                traceback.print_exc()
        
        print(f"\n✓ Batch processing complete! Processed {len(images)} image(s)")
    else:
        # Process single image
        process_image(args.image_uri)
        print("\n✓ Image ingestion complete!")


if __name__ == "__main__":
    main()
