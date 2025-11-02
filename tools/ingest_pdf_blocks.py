import os
import json
from typing import List, Dict

from google.cloud import storage
from google.cloud import documentai_v1 as documentai


PROJECT_ID = os.getenv("GCP_PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = os.getenv("DOCAI_LOCATION", "us")
PROCESSOR_ID = os.getenv("DOCAI_PROCESSOR_ID", "666f583067e8ebff")

SOURCE_BUCKET = os.getenv("SOURCE_BUCKET", "centef-rag-bucket")
TARGET_BUCKET = os.getenv("TARGET_BUCKET", "centef-rag-chunks")
TARGET_PREFIX = os.getenv("TARGET_PREFIX", "docs")


def download_from_gcs(gcs_uri: str) -> str:
    """download gs://... to /tmp/... and return local path"""
    assert gcs_uri.startswith("gs://")
    without = gcs_uri[5:]
    bucket_name, blob_name = without.split("/", 1)

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    local_path = f"/tmp/{os.path.basename(blob_name)}"
    print(f"[download] {gcs_uri} -> {local_path}")
    blob.download_to_filename(local_path)
    return local_path


def call_docai_layout(local_pdf_path: str) -> documentai.Document:
    """call online DocAI with bytes"""
    client = documentai.DocumentProcessorServiceClient()
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    with open(local_pdf_path, "rb") as f:
        pdf_bytes = f.read()

    raw_doc = documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf")
    request = documentai.ProcessRequest(name=name, raw_document=raw_doc)
    print(f"[docai] calling processor {name} on {local_pdf_path}")
    result = client.process_document(request=request)
    return result.document


def docai_document_to_blocks(doc: documentai.Document) -> List[Dict]:
    """Convert layout-style doc to our block list"""
    layout = doc.document_layout
    if not layout or not layout.blocks:
        print("[docai] no document_layout.blocks found, falling back to whole doc")
        return [
            {
                "block_id": "0",
                "page_start": 1,
                "page_end": 1,
                "text": doc.text or "",
                "type": "paragraph",
            }
        ]

    blocks_out = []
    for b in layout.blocks:
        page_span = b.page_span
        page_start = page_span.page_start
        page_end = page_span.page_end

        text = ""
        btype = "other"

        if b.text_block:
            text = b.text_block.text or ""
            btype = b.text_block.type or "paragraph"
        elif b.table_block:
            btype = "table"
        elif b.image_block:
            btype = "image"

        blocks_out.append(
            {
                "block_id": b.block_id or "",
                "page_start": page_start,
                "page_end": page_end,
                "text": text.strip(),
                "type": btype,
            }
        )

    print(f"[docai] extracted {len(blocks_out)} blocks")
    return blocks_out


def blocks_to_jsonl_and_upload(
    blocks: List[Dict], source_gcs_uri: str, source_bucket: str, source_object: str
):
    client = storage.Client()
    bucket = client.bucket(TARGET_BUCKET)

    base_id = os.path.basename(source_object)

    for idx, b in enumerate(blocks, start=1):
        block_id = b.get("block_id") or f"blk-{idx}"
        page_start = b.get("page_start", 1)

        out_doc = {
            "id": f"{base_id}-p{page_start}-b{block_id}",
            "structData": {
                "text": b.get("text", ""),
                "source_bucket": source_bucket,
                "source_object": source_object,
                "source_id": base_id,
                "source_type": "pdf",
                "page": page_start,
                "block_id": block_id,
                "block_type": b.get("type", ""),
                "page_anchor": {
                    "page": page_start,
                    "uri": source_gcs_uri,
                },
            },
        }

        line = json.dumps(out_doc, ensure_ascii=False) + "\n"
        blob_name = f"{TARGET_PREFIX}/{out_doc['id']}.jsonl"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(line, content_type="application/json")
        print(f"[upload] gs://{TARGET_BUCKET}/{blob_name}")


def main(gcs_uri: str):
    # 1) download
    local_path = download_from_gcs(gcs_uri)

    # 2) docai
    doc = call_docai_layout(local_path)

    # 3) to blocks
    blocks = docai_document_to_blocks(doc)

    # 4) upload each block as jsonl
    without = gcs_uri[5:]
    source_bucket, source_object = without.split("/", 1)
    blocks_to_jsonl_and_upload(blocks, gcs_uri, source_bucket, source_object)

    print("[done] ingest done. go sync the datastore in Vertex AI Search.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--gcs-uri", required=True)
    args = parser.parse_args()

    main(args.gcs_uri)
