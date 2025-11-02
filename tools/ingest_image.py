"""
Ingest a single image (or a batch of images) from GCS, analyze it with Gemini Vision,
and write Discovery-Engine-style JSONL to the chunks bucket.

Output per line (structData format):
{
  "id": "...",
  "structData": {
    "text": "...",
    "source_uri": "...",
    "type": "image_analysis",
    "extractor": "gemini_vision",
    "model": "gemini-2.5-flash"
  }
}
"""

import json
import os
import re
from typing import Optional, List

from google.cloud import storage
import vertexai
from vertexai.preview.generative_models import GenerativeModel, Part


# ========= ENV =========
def env(name: str, default: Optional[str] = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = env("VERTEX_LOCATION", "us-central1")

SOURCE_BUCKET = env("SOURCE_BUCKET", "centef-rag-bucket").replace("gs://", "").strip("/")
TARGET_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")
SOURCE_DATA_PREFIX = os.environ.get("SOURCE_DATA_PREFIX", "data").strip("/")

# IMPORTANT: use a model that actually exists for your project/region
VISION_MODEL = os.environ.get("VISION_MODEL", "gemini-2.5-flash")
# =======================


def get_storage_client():
    return storage.Client()


def guess_mime(gcs_uri: str) -> str:
    ext = os.path.splitext(gcs_uri.lower())[1]
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".gif":
        return "image/gif"
    if ext == ".bmp":
        return "image/bmp"
    return "image/jpeg"


def analyze_image_with_gemini(image_gcs_uri: str) -> str:
    """
    Call Gemini multimodal model on GCS image URI and return extracted/structured text.
    """
    print(f"[gemini] analyzing: {image_gcs_uri}")

    # init Vertex
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel(VISION_MODEL)

    prompt = (
        "You will receive an image.\n"
        "Return plain text that is good for search.\n"
        "1) Extract ALL visible text (labels, captions, annotations) in reading order.\n"
        "2) Describe the visual/diagram/infographic structure.\n"
        "3) List the key entities/objects.\n"
        "4) Give a 2-3 sentence summary of the main message.\n"
    )

    mime = guess_mime(image_gcs_uri)
    image_part = Part.from_uri(image_gcs_uri, mime_type=mime)

    resp = model.generate_content([prompt, image_part])
    text = (resp.text or "").strip()
    print(f"[gemini] got {len(text)} chars using model={VISION_MODEL}")
    return text


def split_analysis_to_chunks(
    text: str,
    base_id: str,
    image_gcs_uri: str,
    model_name: str,
    max_len: int = 3000,
) -> List[dict]:
    if len(text) <= max_len:
        return [
            {
                "id": base_id,
                "structData": {
                    "text": text,
                    "source_uri": image_gcs_uri,
                    "type": "image_analysis",
                    "extractor": "gemini_vision",
                    "model": model_name,
                },
            }
        ]

    chunks = []
    start = 0
    idx = 1
    while start < len(text):
        part = text[start : start + max_len]
        chunks.append(
            {
                "id": f"{base_id}_{idx}",
                "structData": {
                    "text": part,
                    "source_uri": image_gcs_uri,
                    "type": "image_analysis",
                    "extractor": "gemini_vision",
                    "model": model_name,
                    "part": idx,
                },
            }
        )
        start += max_len
        idx += 1
    return chunks


def create_chunks(image_gcs_uri: str, analysis_text: str) -> List[dict]:
    filename = image_gcs_uri.split("/")[-1]
    base_name = filename.rsplit(".", 1)[0]
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", base_name)
    base_id = f"image_{safe_id}"
    return split_analysis_to_chunks(analysis_text, base_id, image_gcs_uri, VISION_MODEL)


def upload_jsonl(records: List[dict], target_blob: str):
    client = get_storage_client()
    bucket = client.bucket(TARGET_BUCKET)
    blob = bucket.blob(target_blob)
    ndjson = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    blob.upload_from_string(ndjson, content_type="application/x-ndjson")
    print(f"[ok] uploaded {len(records)} record(s) -> gs://{TARGET_BUCKET}/{target_blob}")


def list_images_in_bucket(prefix: Optional[str] = None) -> List[str]:
    client = get_storage_client()
    bucket = client.bucket(SOURCE_BUCKET)
    if prefix is None:
        prefix = SOURCE_DATA_PREFIX

    blobs = bucket.list_blobs(prefix=prefix)
    exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    images = []
    for b in blobs:
        ext = os.path.splitext(b.name.lower())[1]
        if ext in exts:
            images.append(f"gs://{SOURCE_BUCKET}/{b.name}")
    return images


def process_image(image_gcs_uri: str):
    print(f"\n== processing image: {image_gcs_uri}")
    analysis_text = analyze_image_with_gemini(image_gcs_uri)
    chunks = create_chunks(image_gcs_uri, analysis_text)

    # mirror source path
    rel_path = image_gcs_uri.replace(f"gs://{SOURCE_BUCKET}/", "")
    target_blob = f"{rel_path}.jsonl"

    upload_jsonl(chunks, target_blob)

    first = chunks[0]
    prev = first["structData"]["text"][:200].replace("\n", " ")
    print("preview:")
    print("  id:", first["id"])
    print("  len:", len(first["structData"]["text"]))
    print("  text:", prev + ("..." if len(first["structData"]["text"]) > 200 else ""))
    return chunks


def resolve_image_uri(arg: str) -> str:
    """
    Accept:
      - gs://bucket/path/img.png
      - data/img.png
      - img.png
    and normalize to gs://SOURCE_BUCKET/...
    """
    if arg.startswith("gs://"):
        return arg

    path = arg.lstrip("/")
    if SOURCE_DATA_PREFIX and not path.startswith(SOURCE_DATA_PREFIX):
        path = f"{SOURCE_DATA_PREFIX}/{path}"
    return f"gs://{SOURCE_BUCKET}/{path}"


def main():
    import argparse

    parser = argparse.ArgumentParser("Ingest images to Discovery via Gemini Vision")
    parser.add_argument("image_uri", nargs="?", help="filename OR relative path OR gs:// URI")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="process all images under SOURCE_DATA_PREFIX in SOURCE_BUCKET",
    )
    args = parser.parse_args()

    if args.batch or not args.image_uri:
        imgs = list_images_in_bucket()
        if not imgs:
            print("no images found.")
            return
        print(f"found {len(imgs)} images, processing...")
        for i, uri in enumerate(imgs, 1):
            print(f"[{i}/{len(imgs)}]")
            try:
                process_image(uri)
            except Exception as e:
                print(f"ERROR on {uri}: {e}")
        print("done.")
        return

    # single image
    image_gcs_uri = resolve_image_uri(args.image_uri)
    process_image(image_gcs_uri)
    print("done.")


if __name__ == "__main__":
    main()
