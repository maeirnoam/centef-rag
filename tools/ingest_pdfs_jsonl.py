import json
import os
import sys
import time
from typing import List, Dict, Optional

from google.cloud import documentai_v1 as documentai
from google.cloud import storage
from google.api_core.operation import Operation


def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# ====== ENV ======
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
DOCAI_LOCATION = env("DOCAI_LOCATION", "us")
DOCAI_PROCESSOR_ID = env("DOCAI_PROCESSOR_ID", "666f583067e8ebff")

SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
TARGET_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")

# where your PDFs live inside SOURCE_BUCKET (e.g. "data")
SOURCE_DATA_PREFIX = os.environ.get("SOURCE_DATA_PREFIX", "data").strip("/")

# discovery / datastore id (for reference)
DISCOVERY_GCS_STORE = os.environ.get(
    "DISCOVERY_GCS_STORE",
    "centef-chunk-data-store_1761831236752_gcs_store"
)
# =================================


def get_docai_client():
    return documentai.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{DOCAI_LOCATION}-documentai.googleapis.com"}
    )


def get_storage_client():
    return storage.Client()


def process_pdf_batch(gcs_input_uri: str) -> documentai.Document:
    """
    Process a single PDF using batch processing (required for Layout Parser).
    Returns the processed Document.
    """
    client = get_docai_client()
    name = client.processor_path(PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID)

    # Create temp output location
    base_name = gcs_input_uri.split("/")[-1].replace(".pdf", "")
    output_prefix = f"gs://{TARGET_BUCKET}/_docai_temp/{base_name}/"
    
    if not output_prefix.endswith("/"):
        output_prefix = output_prefix + "/"

    gcs_document = documentai.GcsDocument(
        gcs_uri=gcs_input_uri,
        mime_type="application/pdf",
    )
    input_config = documentai.BatchDocumentsInputConfig(
        gcs_documents=documentai.GcsDocuments(documents=[gcs_document])
    )
    
    output_config = documentai.DocumentOutputConfig(
        gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=output_prefix
        )
    )

    request = documentai.BatchProcessRequest(
        name=name,
        input_documents=input_config,
        document_output_config=output_config,
        skip_human_review=True
    )

    print(f"Starting batch processing for {gcs_input_uri}...")
    operation = client.batch_process_documents(request)
    
    # Wait for completion
    print("Waiting for Document AI to complete...")
    operation.result(timeout=300)  # 5 minute timeout
    
    print("Document AI finished. Reading output...")
    
    # Read the output JSON from GCS
    storage_client = get_storage_client()
    bucket_name = output_prefix.replace("gs://", "").split("/")[0]
    prefix_path = "/".join(output_prefix.replace("gs://", "").split("/")[1:])
    
    bucket = storage_client.bucket(bucket_name)
    blobs = list(bucket.list_blobs(prefix=prefix_path))
    
    # Find the JSON output file
    json_blobs = [b for b in blobs if b.name.endswith(".json")]
    if not json_blobs:
        raise RuntimeError(f"No JSON output found in {output_prefix}")
    
    # Read and parse the JSON
    json_content = json_blobs[0].download_as_text()
    doc_dict = json.loads(json_content)
    
    # Clean up temp files
    for blob in blobs:
        blob.delete()
    
    return doc_dict


def extract_chunks_from_doc(doc: dict, source_uri: str) -> List[Dict]:
    """
    doc is the dict version of Document AI Document (JSON).
    Build Discovery-compatible JSONL entries.
    """
    chunks = []
    fulltext = doc.get("text", "")
    pages = doc.get("pages", [])

    # helper to read text from anchor
    def get_text(text_anchor):
        if not text_anchor:
            return ""
        parts = []
        for seg in text_anchor.get("textSegments", []):
            start = int(seg.get("startIndex", 0))
            end = int(seg.get("endIndex", 0))
            parts.append(fulltext[start:end])
        return "".join(parts)

    base_name = os.path.basename(source_uri)

    for idx, page in enumerate(pages, start=1):
        # 1) main page text = all blocks
        blocks = page.get("blocks", [])
        page_text_parts = []
        for b in blocks:
            page_text_parts.append(get_text(b.get("layout", {}).get("textAnchor")))
        page_text = "\n".join(t.strip() for t in page_text_parts if t and t.strip())
        if page_text:
            chunks.append({
                "id": f"{base_name}_p{idx}_main",
                "content": page_text,
                "metadata": {
                    "source_uri": source_uri,
                    "page": idx,
                    "type": "page_text",
                    "processor_id": DOCAI_PROCESSOR_ID,
                }
            })

        # 2) tables
        for t_i, table in enumerate(page.get("tables", []), start=1):
            rows_text = []
            # header + body
            for row in table.get("headerRows", []) + table.get("bodyRows", []):
                cells_text = []
                for cell in row.get("cells", []):
                    cells_text.append(get_text(cell.get("layout", {}).get("textAnchor")).strip())
                rows_text.append("\t".join(cells_text))
            table_text = "\n".join(rows_text)
            chunks.append({
                "id": f"{base_name}_p{idx}_table_{t_i}",
                "content": table_text,
                "metadata": {
                    "source_uri": source_uri,
                    "page": idx,
                    "type": "table",
                    "rows": len(table.get("headerRows", [])) + len(table.get("bodyRows", [])),
                    "processor_id": DOCAI_PROCESSOR_ID,
                }
            })

        # 3) visual elements
        for v_i, ve in enumerate(page.get("visualElements", []), start=1):
            ve_type = ve.get("type", "image")
            ve_text = get_text(ve.get("layout", {}).get("textAnchor"))
            chunks.append({
                "id": f"{base_name}_p{idx}_visual_{v_i}",
                "content": ve_text.strip(),
                "metadata": {
                    "source_uri": source_uri,
                    "page": idx,
                    "type": ve_type,
                    "processor_id": DOCAI_PROCESSOR_ID,
                }
            })

    return chunks


def upload_jsonl(records: List[Dict], target_blob: str):
    storage_client = get_storage_client()
    bucket = storage_client.bucket(TARGET_BUCKET)
    blob = bucket.blob(target_blob)
    ndjson = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    print(f"[OK] uploaded {len(records)} chunks → gs://{TARGET_BUCKET}/{target_blob}")


def process_one_pdf(source_uri: str):
    print(f"== Processing single PDF: {source_uri}")

    # Process PDF with batch processing (required for Layout Parser)
    doc_json = process_pdf_batch(source_uri)
    
    chunks = extract_chunks_from_doc(doc_json, source_uri)
    print(f"Extracted {len(chunks)} chunks")

    # final Discovery jsonl, mirroring source path:
    rel_path = source_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
    target_blob = f"{rel_path}.jsonl"
    upload_jsonl(chunks, target_blob)


def list_pdfs_in_bucket(prefix: str) -> List[str]:
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
        # single file mode
        arg = args[0]
        if arg.startswith("gs://"):
            gcs_uri = arg
        else:
            # treat as path inside source bucket
            path = arg.lstrip("/")
            if SOURCE_DATA_PREFIX and not path.startswith(SOURCE_DATA_PREFIX):
                path = f"{SOURCE_DATA_PREFIX}/{path}"
            gcs_uri = f"gs://{SOURCE_BUCKET}/{path}"
        process_one_pdf(gcs_uri)
    else:
        # batch mode
        pdfs = list_pdfs_in_bucket(SOURCE_DATA_PREFIX)
        if not pdfs:
            print("No PDFs found.")
            return
        for uri in pdfs:
            process_one_pdf(uri)


if __name__ == "__main__":
    main()
