import json
import os
import sys
from typing import List, Dict, Optional

from google.cloud import documentai_v1 as documentai
from google.cloud import storage


def env(name: str, default: Optional[str] = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


# ====== READ FROM ENV ======
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
DOCAI_LOCATION = env("DOCAI_LOCATION", "us")
DOCAI_PROCESSOR_ID = env("DOCAI_PROCESSOR_ID", "666f583067e8ebff")

# user sometimes puts gs:// in the bucket vars — normalize
def normalize_bucket(b: str) -> str:
    return b.replace("gs://", "").strip("/")

SOURCE_BUCKET = normalize_bucket(env("SOURCE_BUCKET", "centef-rag-bucket"))
TARGET_BUCKET = normalize_bucket(env("TARGET_BUCKET", "centef-rag-chunks"))

# optional: prefix where PDFs live
SOURCE_DATA_PREFIX = os.environ.get("SOURCE_DATA_PREFIX", "")  # can be gs://.../data
if SOURCE_DATA_PREFIX.startswith("gs://"):
    # turn "gs://centef-rag-bucket/data" into prefix "data"
    _tmp = SOURCE_DATA_PREFIX.replace(f"gs://{SOURCE_BUCKET}/", "")
    SOURCE_DATA_PREFIX = _tmp.strip("/")
# =================================


def get_docai_client():
    return documentai.DocumentProcessorServiceClient()


def process_gcs_pdf(gcs_uri: str) -> documentai.types.Document:
    client = get_docai_client()
    name = client.processor_path(PROJECT_ID, DOCAI_LOCATION, DOCAI_PROCESSOR_ID)

    gcs_document = documentai.GcsDocument(
        gcs_uri=gcs_uri,
        mime_type="application/pdf",
    )
    gcs_documents = documentai.GcsDocuments(documents=[gcs_document])
    input_config = documentai.BatchDocumentsInputConfig(gcs_documents=gcs_documents)

    request = documentai.ProcessRequest(
        name=name,
        input_documents=input_config,
    )
    result = client.process_document(request=request)
    return result.document


def extract_page_chunks(doc: documentai.Document) -> List[Dict]:
    chunks = []
    for page_index, page in enumerate(doc.pages, start=1):
        # combine all blocks
        page_text_parts = []
        for block in page.blocks:
            if block.layout and block.layout.text_anchor.text_segments:
                seg = block.layout.text_anchor.text_segments[0]
                page_text_parts.append(doc.text[seg.start_index:seg.end_index])
        main_text = "\n".join(t.strip() for t in page_text_parts if t.strip())

        chunks.append({
            "id": f"p{page_index}-main",
            "page": page_index,
            "type": "page_text",
            "text": main_text,
            "metadata": {
                "page_width": page.dimension.width,
                "page_height": page.dimension.height,
            },
        })

        # tables
        for t_idx, table in enumerate(page.tables, start=1):
            rows_text = []
            for row in table.header_rows + table.body_rows:
                cells_text = []
                for cell in row.cells:
                    text_parts = []
                    for seg in cell.layout.text_anchor.text_segments:
                        text_parts.append(doc.text[seg.start_index:seg.end_index])
                    cells_text.append(" ".join(text_parts).strip())
                rows_text.append("\t".join(cells_text))
            table_text = "\n".join(rows_text)
            chunks.append({
                "id": f"p{page_index}-table-{t_idx}",
                "page": page_index,
                "type": "table",
                "text": table_text,
                "metadata": {
                    "rows": len(table.header_rows) + len(table.body_rows),
                    "cols": len(table.header_rows[0].cells) if table.header_rows else (
                        len(table.body_rows[0].cells) if table.body_rows else 0
                    ),
                }
            })

        # visual elements (images/charts/figures)
        if hasattr(page, "visual_elements"):
            for v_idx, ve in enumerate(page.visual_elements, start=1):
                ve_type = ve.type_ or "image"
                ve_text = ""
                if ve.layout and ve.layout.text_anchor.text_segments:
                    for seg in ve.layout.text_anchor.text_segments:
                        ve_text += doc.text[seg.start_index:seg.end_index]
                chunks.append({
                    "id": f"p{page_index}-visual-{v_idx}",
                    "page": page_index,
                    "type": ve_type,
                    "text": ve_text.strip(),
                    "metadata": {}
                })
    return chunks


def upload_json_to_gcs(bucket_name: str, blob_name: str, data: dict):
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json"
    )
    print(f"[OK] gs://{bucket_name}/{blob_name}")


def list_pdfs_in_bucket(bucket_name: str, prefix: str = "") -> List[str]:
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=prefix)
    pdfs = []
    for b in blobs:
        if b.name.lower().endswith(".pdf"):
            pdfs.append(f"gs://{bucket_name}/{b.name}")
    return pdfs


def target_name_from_source_uri(source_uri: str) -> str:
    # source: gs://centef-rag-bucket/data/folder/file.pdf
    # target: data/folder/file.pdf.json
    src_bucket = f"gs://{SOURCE_BUCKET}/"
    rel_path = source_uri.replace(src_bucket, "")
    return f"{rel_path}.json"


def process_one_pdf(gcs_uri: str):
    print(f"== Processing single PDF: {gcs_uri}")
    doc = process_gcs_pdf(gcs_uri)
    chunks = extract_page_chunks(doc)
    out_obj = {
        "source_uri": gcs_uri,
        "processor_id": DOCAI_PROCESSOR_ID,
        "chunks": chunks,
    }
    target_blob_name = target_name_from_source_uri(gcs_uri)
    upload_json_to_gcs(TARGET_BUCKET, target_blob_name, out_obj)


def main():
    # CLI:
    #   python ingest_pdfs.py                -> process all under SOURCE_DATA_PREFIX (if set) or whole bucket
    #   python ingest_pdfs.py file.pdf       -> process exactly that file under SOURCE_BUCKET (root or prefix)
    #   python ingest_pdfs.py gs://.../x.pdf -> process that exact URI
    args = sys.argv[1:]

    if args:
        # single-file mode
        arg = args[0]
        if arg.startswith("gs://"):
            gcs_uri = arg
        else:
            # treat as "path inside source bucket"
            # if user gave "data/my.pdf" and we have SOURCE_DATA_PREFIX="data", fine
            # if user just gave "my.pdf", we put it at root
            path = arg.lstrip("/")
            if SOURCE_DATA_PREFIX:
                # if prefix exists, and user gave only filename, prepend prefix
                if not path.startswith(SOURCE_DATA_PREFIX):
                    path = f"{SOURCE_DATA_PREFIX.rstrip('/')}/{path}"
            gcs_uri = f"gs://{SOURCE_BUCKET}/{path}"
        process_one_pdf(gcs_uri)
        return

    # batch mode
    prefix = SOURCE_DATA_PREFIX
    print(f"== Batch mode. Listing PDFs in gs://{SOURCE_BUCKET}/{prefix}")
    pdf_uris = list_pdfs_in_bucket(SOURCE_BUCKET, prefix=prefix)
    if not pdf_uris:
        print("No PDFs found.")
        return

    for uri in pdf_uris:
        process_one_pdf(uri)


if __name__ == "__main__":
    main()
