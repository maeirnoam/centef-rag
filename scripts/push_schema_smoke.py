from __future__ import annotations
import os
import sys

# Ensure project root is on sys.path when running as a script (python scripts/...).
# This allows importing the local 'shared' package reliably.
_CURRENT_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_CURRENT_DIR, os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from shared.schemas import make_chunk, to_discoveryengine_jsonl
from shared.io_gcs import write_text


def main():
    # Target bucket to which Discovery Engine (Vertex AI Search) listens
    chunks_bucket = os.environ.get("CHUNKS_BUCKET", "gs://centef-rag-chunks")

    # URIs to point back to your source data (purely informational for smoke)
    # These don't need to exist for the schema/ingest test to work.
    src_prefix = os.environ.get("SOURCE_DATA_PREFIX", "gs://centef-rag-bucket/data")
    pdf_uri = f"{src_prefix.rstrip('/')}/pdfs/sample.pdf"
    av_uri = f"{src_prefix.rstrip('/')}/av/interview.mp3"

    chunks = []

    # PDF page example
    chunks.append(
        make_chunk(
            chunk_id="schema_pdf_p1",
            source_id="schema-pdf",
            source_type="pdf",
            title="Schema Smoke PDF – p.1",
            uri=pdf_uri,
            text=(
                "Schema smoke: sample PDF page one. This line helps Discovery Engine "
                "see 'text' as the primary searchable field and 'page' as an anchor."
            ),
            modality_payload={"page": 1},
            lang="en",
        )
    )

    # AV segment example
    chunks.append(
        make_chunk(
            chunk_id="schema_av_0_4_2",
            source_id="schema-av",
            source_type="audio",
            title="Schema Smoke AV [0.0-4.2s]",
            uri=av_uri,
            text=(
                "Schema smoke: audio snippet zero to four point two seconds. "
                "This demonstrates timestamp anchoring."
            ),
            modality_payload={"start_sec": 0.0, "end_sec": 4.2},
            lang="en",
        )
    )

    jsonl = to_discoveryengine_jsonl(chunks)
    out_path = f"{chunks_bucket.rstrip('/')}/schema-smoke.jsonl"
    write_text(out_path, jsonl)
    print({"written": len(chunks), "output": out_path})


if __name__ == "__main__":
    main()
