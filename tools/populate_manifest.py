#!/usr/bin/env python3
"""
Populate manifest.jsonl from summary files in gs://centef-rag-chunks/summaries/*.jsonl

This is the single authoritative script for creating the document manifest.
It extracts all metadata from the generated summaries and creates a complete
registry of all documents with their associated chunks, summaries, and metadata.

Output schema (manifest.jsonl):
{
  "source_id": str,
  "title": str,
  "document_type": str,  # pdf|srt|youtube|video|image
  "language": str,
  "source_uri": str,      # original file location
  "chunks_uri": str,      # chunked output location
  "summary_uri": str,     # summary location
  "num_chunks": int,
  
  # Optional fields (present based on document type):
  "author": str,          # for authored documents
  "speaker": str,         # for audio/video content
  "organization": str,    # publisher/creator
  "date": str,           # publication/recording date
  "tags": List[str]      # topical tags
}

Usage:
    python tools/populate_manifest.py
    python tools/populate_manifest.py --output custom_manifest.jsonl
"""

import json
import os
import argparse
from typing import List, Dict, Any
from google.cloud import storage


# ========= CONFIG =========
PROJECT_ID = os.environ.get("PROJECT_ID", "sylvan-faculty-476113-c9")
SUMMARIES_BUCKET = os.environ.get("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
SUMMARIES_PREFIX = "summaries/"
DEFAULT_OUTPUT = "manifest.jsonl"
# ==========================


def get_storage_client():
    """Get authenticated GCS client."""
    return storage.Client(project=PROJECT_ID)


def list_summary_files() -> List[str]:
    """
    List all .jsonl summary files in the summaries prefix.
    Returns: list of GCS URIs like gs://bucket/summaries/doc.jsonl
    """
    client = get_storage_client()
    bucket = client.bucket(SUMMARIES_BUCKET)
    blobs = bucket.list_blobs(prefix=SUMMARIES_PREFIX)
    
    files = []
    for blob in blobs:
        if blob.name.endswith(".jsonl") and blob.name != SUMMARIES_PREFIX:
            uri = f"gs://{SUMMARIES_BUCKET}/{blob.name}"
            files.append(uri)
    
    return sorted(files)


def read_summary_from_gcs(summary_uri: str) -> Dict[str, Any]:
    """
    Read a summary JSONL file from GCS and return the document dict.
    """
    # Parse gs://bucket/path
    parts = summary_uri.replace("gs://", "").split("/", 1)
    bucket_name = parts[0]
    blob_path = parts[1]
    
    client = get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    
    content = blob.download_as_text()
    doc = json.loads(content)
    return doc


def extract_manifest_entry(summary_uri: str, summary_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract manifest entry from a summary document.
    
    The summary's structData contains all the metadata we need:
    - source_id, title, document_type, language
    - source_uri, chunks_uri, num_chunks
    - author, speaker, organization, date, tags (optional)
    """
    struct = summary_doc.get("structData", {})
    
    # Required fields
    entry = {
        "source_id": struct["source_id"],
        "title": struct["title"],
        "document_type": struct["document_type"],
        "language": struct.get("language", "en"),
        "source_uri": struct["source_uri"],
        "chunks_uri": struct["chunks_uri"],
        "summary_uri": summary_uri,
        "num_chunks": struct["num_chunks"],
    }
    
    # Optional fields (include if present)
    optional_fields = ["author", "speaker", "organization", "date", "tags"]
    for field in optional_fields:
        if field in struct and struct[field]:
            entry[field] = struct[field]
    
    return entry


def generate_manifest() -> List[Dict[str, Any]]:
    """
    Scan all summary files and generate complete manifest.
    """
    summary_files = list_summary_files()
    
    if not summary_files:
        print("⚠️  No summary files found in gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}")
        print("    Run 'python tools/ingest_summaries.py --batch' first to generate summaries.")
        return []
    
    print(f"Found {len(summary_files)} summary files in gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}\n")
    
    manifest = []
    
    for i, summary_uri in enumerate(summary_files, 1):
        filename = summary_uri.split("/")[-1]
        print(f"[{i}/{len(summary_files)}] Processing {filename}")
        
        try:
            summary_doc = read_summary_from_gcs(summary_uri)
            entry = extract_manifest_entry(summary_uri, summary_doc)
            
            manifest.append(entry)
            
            # Preview
            print(f"  ✓ {entry['source_id']}")
            print(f"    Title: {entry['title']}")
            print(f"    Type: {entry['document_type']} | Chunks: {entry['num_chunks']} | Lang: {entry['language']}")
            
            # Show optional metadata
            metadata_preview = []
            if "author" in entry:
                metadata_preview.append(f"Author: {entry['author']}")
            if "speaker" in entry:
                metadata_preview.append(f"Speaker: {entry['speaker']}")
            if "organization" in entry:
                metadata_preview.append(f"Org: {entry['organization']}")
            if "date" in entry:
                metadata_preview.append(f"Date: {entry['date']}")
            
            if metadata_preview:
                print(f"    {' | '.join(metadata_preview)}")
            
            if "tags" in entry:
                print(f"    Tags: {', '.join(entry['tags'][:5])}{'...' if len(entry['tags']) > 5 else ''}")
            
            print()
            
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            print()
            continue
    
    return manifest


def write_manifest(manifest: List[Dict[str, Any]], output_path: str):
    """
    Write manifest to JSONL file.
    Each line is a complete JSON object (one document).
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for entry in manifest:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    print(f"✅ Wrote {len(manifest)} entries to {output_path}")


def print_summary(manifest: List[Dict[str, Any]]):
    """
    Print summary statistics about the manifest.
    """
    if not manifest:
        return
    
    print("\n" + "="*60)
    print("MANIFEST SUMMARY")
    print("="*60)
    
    # Group by document type
    by_type = {}
    total_chunks = 0
    
    for entry in manifest:
        doc_type = entry["document_type"]
        by_type[doc_type] = by_type.get(doc_type, 0) + 1
        total_chunks += entry["num_chunks"]
    
    print(f"\nTotal Documents: {len(manifest)}")
    print(f"Total Chunks: {total_chunks}")
    print(f"\nBy Document Type:")
    for doc_type, count in sorted(by_type.items()):
        print(f"  {doc_type:15s} {count:3d} documents")
    
    # Languages
    languages = set(entry["language"] for entry in manifest)
    print(f"\nLanguages: {', '.join(sorted(languages))}")
    
    print("="*60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generate manifest from summary files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate manifest.jsonl from summaries
  python tools/populate_manifest.py
  
  # Custom output path
  python tools/populate_manifest.py --output my_manifest.jsonl
        """
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output manifest file path (default: {DEFAULT_OUTPUT})"
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("POPULATING MANIFEST FROM SUMMARIES")
    print("="*60)
    print(f"Source: gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}*.jsonl")
    print(f"Output: {args.output}")
    print("="*60 + "\n")
    
    # Generate manifest from summaries
    manifest = generate_manifest()
    
    if not manifest:
        print("❌ No manifest entries generated. Exiting.")
        return 1
    
    # Write to file
    write_manifest(manifest, args.output)
    
    # Print summary
    print_summary(manifest)
    
    return 0


if __name__ == "__main__":
    exit(main())
