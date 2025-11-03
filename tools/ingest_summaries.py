"""
Generate document-level summaries with metadata and ingest to a separate Vertex AI Search datastore.

This creates a "summaries index" for coarse-grained retrieval, where each document gets:
- A single comprehensive summary
- Rich metadata (title, author, speaker, organization, date, language, etc.)
- Links to the original document and its chunks

Usage:
    python tools/ingest_summaries.py --source-id "pdf_doc123" --title "AI Fraud Report" --author "CENTEF" --date "2024-10"
    python tools/ingest_summaries.py --batch  # Process all documents from a manifest
"""

import json
import os
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from google.cloud import storage
import vertexai
from vertexai.preview.generative_models import GenerativeModel


# ========= ENV =========
def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


def normalize_date(date_str: str) -> str:
    """
    Normalize date string to YYYY-MM-DD format.
    Handles various input formats:
    - "2024-10" -> "2024-10-01"
    - "2024" -> "2024-01-01"
    - "2024-10-15" -> "2024-10-15"
    - Empty/None -> ""
    """
    if not date_str:
        return ""
    
    date_str = date_str.strip()
    parts = date_str.split("-")
    
    if len(parts) == 1:  # Just year: "2024"
        return f"{parts[0]}-01-01"
    elif len(parts) == 2:  # Year-month: "2024-10"
        return f"{parts[0]}-{parts[1]}-01"
    elif len(parts) == 3:  # Full date: "2024-10-15"
        return date_str
    else:
        print(f"Warning: Invalid date format '{date_str}', using empty string")
        return ""


PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = env("VERTEX_LOCATION", "us-central1")

SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
CHUNKS_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
# New bucket for summaries (or can use same bucket with different prefix)
SUMMARIES_BUCKET = env("SUMMARIES_BUCKET", CHUNKS_BUCKET).replace("gs://", "").strip("/")

SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "gemini-2.5-flash")
# =======================


def get_storage_client():
    return storage.Client()


def read_chunks_from_gcs(chunks_uri: str) -> List[Dict[str, Any]]:
    """
    Read chunks JSONL file from GCS and return list of chunk dicts.
    Each chunk has structData with text, source_uri, page/timestamp, etc.
    """
    client = get_storage_client()
    
    # Parse gs://bucket/path
    if not chunks_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got: {chunks_uri}")
    
    parts = chunks_uri.replace("gs://", "").split("/", 1)
    bucket_name = parts[0]
    blob_path = parts[1] if len(parts) > 1 else ""
    
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    
    if not blob.exists():
        print(f"Warning: chunks file not found: {chunks_uri}")
        return []
    
    content = blob.download_as_text()
    chunks = []
    for line in content.strip().split("\n"):
        if line.strip():
            chunks.append(json.loads(line))
    
    return chunks


def generate_summary_with_metadata(
    chunks: List[Dict[str, Any]],
    metadata: Dict[str, Any]
) -> str:
    """
    Use Gemini to generate a comprehensive summary of all chunks,
    incorporating the provided metadata (title, author, etc.).
    """
    print(f"[gemini] generating summary with {SUMMARY_MODEL}")
    
    # Extract text from all chunks
    chunk_texts = []
    for chunk in chunks:
        if "structData" in chunk:
            text = chunk["structData"].get("text", "")
            # Include chunk context if available
            chunk_type = chunk["structData"].get("type", "")
            if chunk_type == "page_text":
                page = chunk["structData"].get("page", "")
                chunk_texts.append(f"[Page {page}] {text}")
            elif chunk_type in ("subtitle_chunk", "video_transcript"):
                start = chunk["structData"].get("start_sec", 0)
                end = chunk["structData"].get("end_sec", 0)
                chunk_texts.append(f"[{int(start//60)}:{int(start%60):02d}-{int(end//60)}:{int(end%60):02d}] {text}")
            else:
                chunk_texts.append(text)
    
    full_text = "\n\n".join(chunk_texts)
    
    # Build metadata context
    metadata_context = []
    if metadata.get("title"):
        metadata_context.append(f"Title: {metadata['title']}")
    if metadata.get("author"):
        metadata_context.append(f"Author: {metadata['author']}")
    if metadata.get("speaker"):
        metadata_context.append(f"Speaker: {metadata['speaker']}")
    if metadata.get("organization"):
        metadata_context.append(f"Organization: {metadata['organization']}")
    if metadata.get("date"):
        metadata_context.append(f"Date: {metadata['date']}")
    if metadata.get("language"):
        metadata_context.append(f"Language: {metadata['language']}")
    if metadata.get("document_type"):
        metadata_context.append(f"Type: {metadata['document_type']}")
    
    metadata_str = "\n".join(metadata_context)
    
    prompt = f"""You are summarizing a document for a search index. Generate a comprehensive, searchable summary.

DOCUMENT METADATA:
{metadata_str}

DOCUMENT CONTENT:
{full_text[:50000]}  # Limit to ~50k chars to stay within context window

Generate a summary that:
1. Incorporates key metadata (title, author, date, etc.) naturally in the first sentence
2. Captures main topics, themes, and key points
3. Includes important entities (people, organizations, locations, dates, numbers)
4. Uses terminology and keywords that users might search for
5. Is 300-500 words long
6. Is written in a neutral, informative style suitable for search retrieval

SUMMARY:"""

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel(SUMMARY_MODEL)
    
    response = model.generate_content(prompt)
    summary = (response.text or "").strip()
    
    print(f"[gemini] generated summary: {len(summary)} chars")
    return summary


def create_summary_document(
    source_id: str,
    summary_text: str,
    metadata: Dict[str, Any],
    chunks_uri: str,
    num_chunks: int
) -> Dict[str, Any]:
    """
    Create a Discovery Engine document for the summaries datastore.
    Uses structData format with enriched metadata.
    """
    # Sanitize source_id for use as document ID
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', source_id)
    doc_id = f"summary_{safe_id}"
    
    # Normalize date to YYYY-MM-DD format
    date_str = normalize_date(metadata.get("date", ""))
    
    struct_data = {
        "text": summary_text,
        "source_id": source_id,
        "source_uri": metadata.get("source_uri", ""),
        "chunks_uri": chunks_uri,
        "num_chunks": num_chunks,
        "type": "document_summary",
        "document_type": metadata.get("document_type", ""),
        "title": metadata.get("title", ""),
        "author": metadata.get("author", ""),
        "speaker": metadata.get("speaker", ""),
        "organization": metadata.get("organization", ""),
        "date": date_str,
        "language": metadata.get("language", "en"),
        "tags": metadata.get("tags", []),
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    
    # Remove empty fields to keep JSONL clean
    struct_data = {k: v for k, v in struct_data.items() if v}
    
    return {
        "id": doc_id,
        "structData": struct_data
    }


def upload_summary_jsonl(document: Dict[str, Any], target_blob: str):
    """Upload summary document to summaries bucket"""
    client = get_storage_client()
    bucket = client.bucket(SUMMARIES_BUCKET)
    blob = bucket.blob(target_blob)
    
    jsonl = json.dumps(document, ensure_ascii=False)
    blob.upload_from_string(jsonl + "\n", content_type="application/x-ndjson")
    
    print(f"[ok] uploaded summary -> gs://{SUMMARIES_BUCKET}/{target_blob}")


def process_document(
    source_id: str,
    chunks_uri: str,
    metadata: Dict[str, Any]
):
    """
    Generate and ingest a summary for a single document.
    
    Args:
        source_id: Unique identifier for the document (e.g., "pdf_fraud_report_2024")
        chunks_uri: GCS URI to the chunks JSONL (e.g., gs://centef-rag-chunks/data/doc.pdf.jsonl)
        metadata: Dict with title, author, speaker, organization, date, language, tags, etc.
    """
    print(f"\n=== Processing document: {source_id}")
    print(f"Chunks: {chunks_uri}")
    print(f"Metadata: {metadata}")
    
    # Read all chunks for this document
    chunks = read_chunks_from_gcs(chunks_uri)
    if not chunks:
        print("No chunks found, skipping")
        return
    
    print(f"Loaded {len(chunks)} chunks")
    
    # Generate summary with Gemini
    summary_text = generate_summary_with_metadata(chunks, metadata)
    
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
    
    # Print preview
    print("\nPreview:")
    print(f"  ID: {summary_doc['id']}")
    print(f"  Title: {metadata.get('title', 'N/A')}")
    print(f"  Chunks: {len(chunks)}")
    print(f"  Summary length: {len(summary_text)} chars")
    print(f"  Summary preview: {summary_text[:200]}...")


def load_manifest(manifest_path: str) -> List[Dict[str, Any]]:
    """
    Load a manifest file that lists all documents to summarize.
    
    Expected format (JSONL):
    {"source_id": "...", "chunks_uri": "gs://...", "metadata": {"title": "...", "author": "...", ...}}
    {"source_id": "...", "chunks_uri": "gs://...", "metadata": {...}}
    """
    documents = []
    with open(manifest_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                documents.append(json.loads(line))
    return documents


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate document summaries for Vertex AI Search")
    parser.add_argument("--source-id", help="Unique document identifier")
    parser.add_argument("--chunks-uri", help="GCS URI to chunks JSONL (gs://bucket/path.jsonl)")
    parser.add_argument("--title", help="Document title")
    parser.add_argument("--author", help="Document author")
    parser.add_argument("--speaker", help="Speaker (for videos/audio)")
    parser.add_argument("--organization", help="Organization")
    parser.add_argument("--date", help="Publication/creation date (YYYY-MM-DD, YYYY-MM, or YYYY - will be normalized)")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--document-type", help="Type: pdf, video, audio, image, etc.")
    parser.add_argument("--tags", help="Comma-separated tags")
    parser.add_argument("--source-uri", help="Original source URI (gs://...)")
    parser.add_argument("--batch", action="store_true", help="Process all documents from manifest.jsonl")
    parser.add_argument("--manifest", default="manifest.jsonl", help="Path to manifest file (default: manifest.jsonl)")
    
    args = parser.parse_args()
    
    if args.batch:
        # Batch mode: process from manifest
        if not os.path.exists(args.manifest):
            print(f"Error: manifest file not found: {args.manifest}")
            print("\nCreate a manifest.jsonl with entries like:")
            print('{"source_id": "doc1", "chunks_uri": "gs://bucket/doc1.jsonl", "metadata": {"title": "...", "author": "..."}}')
            return
        
        documents = load_manifest(args.manifest)
        print(f"Loaded {len(documents)} documents from manifest")
        
        for i, doc in enumerate(documents, 1):
            print(f"\n[{i}/{len(documents)}]")
            try:
                process_document(
                    source_id=doc["source_id"],
                    chunks_uri=doc["chunks_uri"],
                    metadata=doc.get("metadata", {})
                )
            except Exception as e:
                print(f"Error processing {doc['source_id']}: {e}")
        
        print("\n=== Batch complete ===")
        return
    
    # Single document mode
    if not args.source_id or not args.chunks_uri:
        print("Error: --source-id and --chunks-uri are required (or use --batch)")
        parser.print_help()
        return
    
    # Build metadata from args
    metadata = {
        "title": args.title or "",
        "author": args.author or "",
        "speaker": args.speaker or "",
        "organization": args.organization or "",
        "date": args.date or "",
        "language": args.language or "en",
        "document_type": args.document_type or "",
        "source_uri": args.source_uri or "",
        "tags": [t.strip() for t in args.tags.split(",")] if args.tags else [],
    }
    
    process_document(args.source_id, args.chunks_uri, metadata)
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
