import os
import json
from google.cloud import storage

# name of the bucket (NO gs://)
BUCKET = os.getenv("CHUNKS_BUCKET", "centef-rag-chunks")
FOLDER = "docs"

def main():
    client = storage.Client()
    bucket = client.bucket(BUCKET)

    # this is the document as Discovery Engine wants it
    doc = {
        "id": "demo-pdf-1",
        "structData": {
            "text": "This is a demo document about sanctions, Hezbollah, and financial networks in Lebanon.",
            "source_id": "demo-pdf-1",
            "source_type": "pdf",
            "page": 1
        }
    }

    jsonl_line = json.dumps(doc, ensure_ascii=False)

    blob_name = f"{FOLDER}/demo-pdf-1.jsonl"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(
        jsonl_line + "\n",
        content_type="application/json"
    )

    print(f"wrote gs://{BUCKET}/{blob_name}")

if __name__ == "__main__":
    main()
