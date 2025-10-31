# tools/ingest_dummy.py
import os, time
from google.cloud import storage

# bucket that your datastore is watching
BUCKET = os.getenv("CHUNKS_BUCKET", "centef-rag-chunks")   # name, not gs://...
FOLDER = "docs"

def main():
    client = storage.Client()
    bucket = client.bucket(BUCKET)

    # this is the content we want to index
    doc = {
        "id": "demo-pdf-1",
        "content": "This is a demo document about sanctions, Hezbollah, and financial networks in Lebanon.",
        "structData": {
            "source_id": "demo-pdf-1",
            "source_type": "pdf",
            "page": 1
        }
    }

    jsonl = f"{doc}\n".replace("'", '"')  # quick+dirty: turn dict into json string

    blob_name = f"{FOLDER}/demo-pdf-1.jsonl"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(jsonl, content_type="application/jsonl")

    print(f"wrote gs://{BUCKET}/{blob_name}")

if __name__ == "__main__":
    main()
