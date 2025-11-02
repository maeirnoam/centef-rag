"""
Simple PDF page-level ingestion without DocAI.
Extracts text per page using PyMuPDF and uploads to Discovery Engine.
"""
import json
import os
import sys
from typing import List, Dict, Optional
import tempfile

import fitz  # PyMuPDF
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


def download_pdf(gcs_uri: str) -> bytes:
    """Download PDF from GCS"""
    storage_client = get_storage_client()
    bucket_name, blob_path = gcs_uri.replace("gs://", "").split("/", 1)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    return blob.download_as_bytes()


def extract_pages_pymupdf(pdf_bytes: bytes, source_uri: str) -> List[Dict]:
    """Extract text from each page using PyMuPDF"""
    chunks = []
    base_name = source_uri.split("/")[-1].replace(".pdf", "")
    
    # Open PDF from bytes
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    
    try:
        doc = fitz.open(tmp_path)
        print(f"Processing {len(doc)} pages...")
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            
            # Skip empty pages
            if not text.strip():
                print(f"  Page {page_num + 1}: empty, skipping")
                continue
            
            # Discovery Engine document format - structData only for unstructured stores
            chunk = {
                "id": f"{base_name}_page_{page_num + 1}",
                "structData": {
                    "text": text.strip(),
                    "source_uri": source_uri,
                    "page": page_num + 1,
                    "type": "page_text",
                    "extractor": "pymupdf"
                }
            }
            chunks.append(chunk)
            print(f"  Page {page_num + 1}: {len(text)} chars")
        
        doc.close()
    finally:
        os.unlink(tmp_path)
    
    return chunks


def upload_jsonl(records: List[Dict], target_blob: str):
    """Upload chunks as JSONL to GCS"""
    storage_client = get_storage_client()
    bucket = storage_client.bucket(TARGET_BUCKET)
    blob = bucket.blob(target_blob)
    ndjson = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    print(f"[OK] Uploaded {len(records)} chunks → gs://{TARGET_BUCKET}/{target_blob}")


def process_one_pdf(source_uri: str):
    """Process a single PDF"""
    print(f"\n== Processing: {source_uri}")
    
    # Download PDF
    pdf_bytes = download_pdf(source_uri)
    print(f"Downloaded {len(pdf_bytes)} bytes")
    
    # Extract page-level chunks
    chunks = extract_pages_pymupdf(pdf_bytes, source_uri)
    print(f"Extracted {len(chunks)} page chunks")
    
    if not chunks:
        print("WARNING: No content extracted from PDF")
        return
    
    # Upload to GCS
    rel_path = source_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
    target_blob = f"{rel_path}.jsonl"
    upload_jsonl(chunks, target_blob)


def list_pdfs_in_bucket(prefix: str) -> List[str]:
    """List all PDFs in bucket under prefix"""
    sc = get_storage_client()
    bucket = sc.bucket(SOURCE_BUCKET)
    pdfs = []
    for blob in bucket.list_blobs(prefix=prefix):
        if blob.name.lower().endswith(".pdf"):
            pdfs.append(f"gs://{SOURCE_BUCKET}/{blob.name}")
    return pdfs


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
        process_one_pdf(gcs_uri)
    else:
        # Batch mode
        pdfs = list_pdfs_in_bucket(SOURCE_DATA_PREFIX)
        if not pdfs:
            print("No PDFs found.")
            return
        print(f"Found {len(pdfs)} PDFs to process")
        for uri in pdfs:
            process_one_pdf(uri)


if __name__ == "__main__":
    main()
