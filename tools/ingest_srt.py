"""
Ingest SRT (subtitle) files into Discovery Engine with timestamp anchors.
Each subtitle segment becomes a separate chunk with start_sec and end_sec metadata.
"""
import json
import os
import sys
from typing import List, Dict, Optional
import re

from google.cloud import storage


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# ====== ENV ======
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
TARGET_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
SOURCE_DATA_PREFIX = os.environ.get("SOURCE_DATA_PREFIX", "data").strip("/")
# =================================


def get_storage_client():
    return storage.Client()


def download_srt(gcs_uri: str) -> str:
    """Download SRT file from GCS as text"""
    storage_client = get_storage_client()
    bucket_name, blob_path = gcs_uri.replace("gs://", "").split("/", 1)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    return blob.download_as_text(encoding="utf-8")


def parse_timestamp(timestamp: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds"""
    # Format: 00:00:20,000
    timestamp = timestamp.replace(',', '.')
    parts = timestamp.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_srt(srt_content: str) -> List[Dict]:
    """
    Parse SRT content into subtitle segments.
    
    SRT format:
    1
    00:00:20,000 --> 00:00:24,400
    Subtitle text line 1
    Subtitle text line 2
    
    2
    00:00:24,600 --> 00:00:27,800
    Next subtitle
    """
    segments = []
    
    # Split by double newline (segments are separated by blank lines)
    blocks = re.split(r'\n\s*\n', srt_content.strip())
    
    for block in blocks:
        if not block.strip():
            continue
        
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue  # Invalid segment
        
        # Line 0: sequence number
        try:
            seq_num = int(lines[0].strip())
        except ValueError:
            continue  # Skip invalid segments
        
        # Line 1: timestamp range
        timestamp_line = lines[1].strip()
        match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})', timestamp_line)
        if not match:
            continue  # Skip invalid timestamp
        
        start_time = parse_timestamp(match.group(1))
        end_time = parse_timestamp(match.group(2))
        
        # Lines 2+: subtitle text
        text = '\n'.join(lines[2:]).strip()
        
        segments.append({
            'sequence': seq_num,
            'start_sec': start_time,
            'end_sec': end_time,
            'text': text
        })
    
    return segments


def segments_to_chunks(segments: List[Dict], source_uri: str, window_seconds: float = 30.0) -> List[Dict]:
    """
    Convert SRT segments to Discovery Engine chunks by combining consecutive segments.
    Groups segments into time windows (default 30 seconds) to create meaningful chunks.
    """
    chunks = []
    base_name = source_uri.split("/")[-1].replace(".srt", "")
    # Sanitize base_name: replace spaces and special chars with underscores
    base_name = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name)
    
    if not segments:
        return chunks
    
    current_chunk_segments = []
    chunk_start_sec = segments[0]['start_sec']
    chunk_id = 1
    
    for seg in segments:
        # If this segment would extend the chunk beyond the window, finalize current chunk
        if current_chunk_segments and (seg['end_sec'] - chunk_start_sec) > window_seconds:
            # Finalize current chunk
            combined_text = ' '.join(s['text'] for s in current_chunk_segments)
            chunk_end_sec = current_chunk_segments[-1]['end_sec']
            
            chunk = {
                "id": f"{base_name}_chunk_{chunk_id}",
                "structData": {
                    "text": combined_text,
                    "source_uri": source_uri,
                    "start_sec": chunk_start_sec,
                    "end_sec": chunk_end_sec,
                    "duration_sec": chunk_end_sec - chunk_start_sec,
                    "segment_count": len(current_chunk_segments),
                    "type": "subtitle_chunk",
                    "extractor": "srt_parser"
                }
            }
            chunks.append(chunk)
            
            # Start new chunk
            current_chunk_segments = [seg]
            chunk_start_sec = seg['start_sec']
            chunk_id += 1
        else:
            # Add to current chunk
            current_chunk_segments.append(seg)
    
    # Finalize last chunk
    if current_chunk_segments:
        combined_text = ' '.join(s['text'] for s in current_chunk_segments)
        chunk_end_sec = current_chunk_segments[-1]['end_sec']
        
        chunk = {
            "id": f"{base_name}_chunk_{chunk_id}",
            "structData": {
                "text": combined_text,
                "source_uri": source_uri,
                "start_sec": chunk_start_sec,
                "end_sec": chunk_end_sec,
                "duration_sec": chunk_end_sec - chunk_start_sec,
                "segment_count": len(current_chunk_segments),
                "type": "subtitle_chunk",
                "extractor": "srt_parser"
            }
        }
        chunks.append(chunk)
    
    return chunks


def upload_jsonl(records: List[Dict], target_blob: str):
    """Upload chunks as JSONL to GCS"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(TARGET_BUCKET)
    blob = bucket.blob(target_blob)
    ndjson = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    print(f"[OK] Uploaded {len(records)} chunks → gs://{TARGET_BUCKET}/{target_blob}")


def process_one_srt(source_uri: str, window_seconds: float = 30.0):
    """Process a single SRT file"""
    print(f"\n== Processing: {source_uri}")
    print(f"Using {window_seconds}s time window for chunking")
    
    # Download SRT
    srt_content = download_srt(source_uri)
    print(f"Downloaded {len(srt_content)} characters")
    
    # Parse segments
    segments = parse_srt(srt_content)
    print(f"Parsed {len(segments)} subtitle segments")
    
    if not segments:
        print("WARNING: No subtitle segments found")
        return
    
    # Show sample
    if segments:
        first = segments[0]
        print(f"First segment: [{first['start_sec']:.1f}s - {first['end_sec']:.1f}s] {first['text'][:50]}...")
    
    # Convert to chunks with time windowing
    chunks = segments_to_chunks(segments, source_uri, window_seconds=window_seconds)
    print(f"Created {len(chunks)} chunks (combined from {len(segments)} segments)")
    
    # Show first chunk example
    if chunks:
        first_chunk = chunks[0]
        duration = first_chunk['structData']['duration_sec']
        seg_count = first_chunk['structData']['segment_count']
        text_preview = first_chunk['structData']['text'][:100]
        print(f"First chunk: {duration:.1f}s duration, {seg_count} segments")
        print(f"  Text: {text_preview}...")
    
    # Upload to GCS
    rel_path = source_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
    target_blob = f"{rel_path}.jsonl"
    upload_jsonl(chunks, target_blob)


def list_srts_in_bucket(prefix: str) -> List[str]:
    """List all SRT files in bucket under prefix"""
    sc = get_storage_client()
    bucket = sc.bucket(SOURCE_BUCKET)
    srts = []
    for blob in bucket.list_blobs(prefix=prefix):
        if blob.name.lower().endswith(".srt"):
            srts.append(f"gs://{SOURCE_BUCKET}/{blob.name}")
    return srts


def main():
    args = sys.argv[1:]
    if args:
        # Single file mode
        arg = args[0]
        if arg.startswith("gs://"):
            gcs_uri = arg
        else:
            # Treat as path inside source bucket
            path = arg.lstrip("/")
            if SOURCE_DATA_PREFIX and not path.startswith(SOURCE_DATA_PREFIX):
                path = f"{SOURCE_DATA_PREFIX}/{path}"
            gcs_uri = f"gs://{SOURCE_BUCKET}/{path}"
        process_one_srt(gcs_uri)
    else:
        # Batch mode
        srts = list_srts_in_bucket(SOURCE_DATA_PREFIX)
        if not srts:
            print("No SRT files found.")
            return
        print(f"Found {len(srts)} SRT files to process")
        for uri in srts:
            process_one_srt(uri)


if __name__ == "__main__":
    main()
