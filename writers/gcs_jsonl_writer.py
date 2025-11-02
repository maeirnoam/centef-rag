# writers/gcs_jsonl_writer.py

import json
from google.cloud import storage

def write_chunks_to_gcs_jsonl(chunks, bucket_name: str, prefix: str = "docs"):
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    for ch in chunks:
        blob_name = f"{prefix}/{ch['id']}.jsonl"
        blob = bucket.blob(blob_name)
        line = json.dumps(ch, ensure_ascii=False) + "\n"
        blob.upload_from_string(line, content_type="application/json")
        print("uploaded", f"gs://{bucket_name}/{blob_name}")
