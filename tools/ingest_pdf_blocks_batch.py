import os
import json
import time
from typing import List, Dict

from google.cloud import storage
from google.cloud import documentai_v1 as documentai

# -------------------------------------------------------------------
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = os.getenv("DOCAI_LOCATION", "us")
PROCESSOR_ID = os.getenv("DOCAI_PROCESSOR_ID", "666f583067e8ebff")

# your source PDF is here:
SOURCE_BUCKET = os.getenv("SOURCE_BUCKET", "centef-rag-bucket")

# Discovery Engine watches this bucket:
TARGET_BUCKET = os.getenv("TARGET_BUCKET", "centef-rag-chunks")
TARGET_PREFIX = os.getenv("TARGET_PREFIX", "docs")

# DocAI will PUT its JSON output here (can be same as target, or another)
DOCAI_OUTPUT_BUCKET = os.getenv("DOCAI_OUTPUT_BUCKET", TARGET_BUCKET)
DOCAI_OUTPUT_PREFIX = os.getenv("DOCAI_OUTPUT_PREFIX", "docai-out")
# -------------------------------------------------------------------


def batch_process_pdf(gcs_input_uri: str) -> str:
    """Submit a batch process and return the output GCS prefix."""
    client = documentai.DocumentProcessorServiceClient()
    name = client.processor_path(PROJECT_ID, LOCATION, PROCESSOR_ID)

    # input
    gcs_doc = documentai.GcsDocument(
        gcs_uri=gcs_input_uri,
        mime_type="application/pdf",
    )
    gcs_docs = documentai.GcsDocuments(documents=[gcs_doc])
    input_config = documentai.BatchDocumentsInputConfig(gcs_documents=gcs_docs)

    # output
    output_gcs_uri = f"gs://{DOCAI_OUTPUT_BUCKET}/{DOCAI_OUTPUT_PREFIX}/"
    output_config = documentai.DocumentOutputConfig(
        gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(
            gcs_uri=output_gcs_uri
        )
    )

    request = documentai.BatchProcessRequest(
        name=name,
        input_documents=input_config,
        document_output_config=output_config,
    )

    print(f"[docai] submitting batch for {gcs_input_uri} -> {output_gcs_uri}")
    operation = client.batch_process_documents(request=request)
    operation.result()  # wait
    print("[docai] batch finished")
    return output_gcs_uri


def read_docai_output(output_prefix: str) -> List[documentai.Document]:
    """
    DocAI batch writes N JSON files to GCS (one per page or shard).
    We read them all and return a list of Document objects.
    """
    assert output_prefix.startswith("gs://")
    without = output_prefix[5:]
    bucket_name, prefix = without.split("/", 1)

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    docs = []
    for blob in bucket.list_blobs(prefix=prefix):
        if not blob.name.endswith(".json"):
            continue
        json_bytes = blob.download_as_bytes()
        doc = documentai.Document.from_json(json_bytes, ignore_unknown_fields=True)
        docs.append(doc)
        print(f"[docai] loaded {blob.name}")
    return docs


def collect_blocks_from_docs(docs: List[documentai.Document]) -> List[Dict]:
    """Flatten all layout blocks from all returned documents."""
    all_blocks: List[Dict] = []
    for doc in docs:
        layout = doc.document_layout
        if not layout or not layout.blocks:
            # fallback to whole text
            all_blocks.append(
                {
                    "block_id": "0",
                    "page_start": 1,
                    "page_end": 1,
                    "text": doc.text or "",
                    "type": "paragraph",
                }
            )
            continue

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

            all_blocks.append(
                {
                    "block_id": b.block_id or "",
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": text.strip(),
                    "type": btype,
                }
            )

    print(f"[merge] collected {len(all_blocks)} raw blocks")
    return all_blocks


def merge_small_blocks(blocks: List[Dict], min_chars: int = 40) -> List[Dict]:
    """
    Combine adjacent blocks on the SAME PAGE if their text is too short.
    This keeps your "one-block = one-chunk" idea, but avoids 2-word chunks.
    """
    if not blocks:
        return blocks

    # sort by page, then by block_id (not perfect but okay)
    blocks = sorted(blocks, key=lambda b: (b.get("page_start", 1), b.get("block_id", "")))

    merged: List[Dict] = []
    carry = None

    for b in blocks:
        page = b.get("page_start", 1)
        text = b.get("text", "")

        if carry is None:
            carry = b
            continue

        same_page = carry.get("page_start", 1) == page
        if same_page and (len(carry.get("text", "")) < min_chars or len(text) < min_chars):
            # merge
            carry["text"] = (carry.get("text", "") + " " + text).strip()
        else:
            merged.append(carry)
            carry = b

    if carry is not None:
        merged.append(carry)

    print(f"[merge] reduced to {len(merged)} blocks after merging")
    return merged


def upload_as_jsonl(blocks: List[Dict], source_gcs_uri: str):
    storage_client = storage.Client()
    bucket = storage_client.bucket(TARGET_BUCKET)

    without = source_gcs_uri[5:]
    source_bucket, source_object = without.split("/", 1)
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

        blob_name = f"{TARGET_PREFIX}/{out_doc['id']}.jsonl"
        blob = bucket.blob(blob_name)
        blob.upload_from_string(json.dumps(out_doc, ensure_ascii=False) + "\n",
                                content_type="application/json")
        print(f"[upload] gs://{TARGET_BUCKET}/{blob_name}")


def main(gcs_uri: str):
    out_prefix = batch_process_pdf(gcs_uri)
    docs = read_docai_output(out_prefix)
    raw_blocks = collect_blocks_from_docs(docs)
    merged_blocks = merge_small_blocks(raw_blocks, min_chars=40)
    upload_as_jsonl(merged_blocks, gcs_uri)
    print("[done] now run Discovery Engine import on gs://centef-rag-chunks/docs/*.jsonl")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gcs-uri", required=True)
    args = parser.parse_args()
    main(args.gcs_uri)
