from __future__ import annotations
import os
from typing import List, Tuple


def page_texts_with_docai(gs_pdf_uri: str) -> List[Tuple[int, str]]:
    """Use Document AI Layout to extract per-page text from a PDF in GCS.

    Requires env vars: DOC_AI_PROJECT, DOC_AI_LOCATION, DOC_AI_PROCESSOR_ID
    """
    try:
        from google.cloud import documentai
    except Exception as e:  # pragma: no cover
        raise RuntimeError("google-cloud-documentai not installed") from e

    project_id = os.environ.get("DOC_AI_PROJECT")
    location = os.environ.get("DOC_AI_LOCATION", "us")
    processor_id = os.environ.get("DOC_AI_PROCESSOR_ID")
    if not (project_id and processor_id):
        raise RuntimeError("Document AI not configured (DOC_AI_PROJECT/DOC_AI_PROCESSOR_ID)")

    client = documentai.DocumentProcessorServiceClient()
    name = client.processor_path(project_id, location, processor_id)

    raw_document = documentai.RawDocument(
        content=b"",  # empty because we are using GCS input config
        mime_type="application/pdf",
    )

    gcs_document = documentai.GcsDocument(
        gcs_uri=gs_pdf_uri, mime_type="application/pdf"
    )
    input_config = documentai.BatchDocumentsInputConfig(gcs_documents=documentai.GcsDocuments(documents=[gcs_document]))

    request = documentai.ProcessRequest(name=name, raw_document=None, inline_document=None, skip_human_review=True, )
    # Document AI online processing doesn't take GCS input; for large files use BatchProcessRequest.
    # So we pivot to Batch for robustness.
    batch_request = documentai.BatchProcessRequest(
        name=name,
        input_documents=input_config,
        document_output_config=documentai.DocumentOutputConfig(
            gcs_output_config=documentai.DocumentOutputConfig.GcsOutputConfig(gcs_uri=os.environ.get("DOC_AI_OUTPUT_GCS", "gs://centef-rag-chunks/docai-outputs/"))
        ),
    )
    op = client.batch_process_documents(request=batch_request)
    op.result(timeout=600)
    # Reading outputs from GCS is more involved; for simplicity, we recommend the PyMuPDF fallback unless DocAI is critical.
    # In production, parse the JSON outputs and assemble per-page text here.
    raise NotImplementedError("DocAI batch output parsing not implemented in this stub; use PyMuPDF fallback.")


def page_texts_with_pymupdf(gs_pdf_uri: str) -> List[Tuple[int, str]]:
    import tempfile
    import fitz  # PyMuPDF
    from google.cloud import storage

    # download PDF locally first
    client = storage.Client()
    assert gs_pdf_uri.startswith("gs://")
    _, path = gs_pdf_uri[5:].split("/", 1)
    bucket_name = gs_pdf_uri[5:].split("/", 1)[0]
    blob_name = path
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        blob.download_to_filename(tmp.name)
        doc = fitz.open(tmp.name)
        pages: List[Tuple[int, str]] = []
        for i, page in enumerate(doc):
            text = page.get_text("text")
            pages.append((i + 1, text))
        return pages
