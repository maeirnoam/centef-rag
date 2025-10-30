from __future__ import annotations
from google.cloud import storage
from typing import Optional, List
import io
import os
import re
import itertools
import google.auth
from google.auth import impersonated_credentials as _imp

_GS_RE = re.compile(r"^gs://([^/]+)/(.+)$")


def _parse_gs_uri(gs_uri: str):
    m = _GS_RE.match(gs_uri)
    if not m:
        raise ValueError(f"Invalid GCS URI: {gs_uri}")
    return m.group(1), m.group(2)


def get_client() -> storage.Client:
    """Return a Storage client.

    Supports two modes:
    - Default ADC (user login or workload identity)
    - Service Account Impersonation if IMPERSONATE_SERVICE_ACCOUNT is set.
    """
    target_sa = os.getenv("IMPERSONATE_SERVICE_ACCOUNT")
    if target_sa:
        # Use Application Default Credentials to impersonate the target service account.
        # Requires roles/iam.serviceAccountTokenCreator on the target SA for the caller.
        source_creds, project_id = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        imp_creds = _imp.Credentials(
            source_credentials=source_creds,
            target_principal=target_sa,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            lifetime=3600,
        )
        # Prefer explicit project from env, fallback to detected project_id.
        project = os.getenv("GCP_PROJECT") or project_id
        return storage.Client(project=project, credentials=imp_creds)
    # Fallback to default ADC (may use user login or VM/Cloud Run identity)
    return storage.Client()


def write_text(gs_uri: str, text: str, content_type: str = "application/jsonl") -> None:
    bucket_name, blob_name = _parse_gs_uri(gs_uri)
    client = get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(text, content_type=content_type)


def read_text(gs_uri: str) -> str:
    bucket_name, blob_name = _parse_gs_uri(gs_uri)
    client = get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.download_as_text()


def exists(gs_uri: str) -> bool:
    bucket_name, blob_name = _parse_gs_uri(gs_uri)
    client = get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    return blob.exists()


def delete(gs_uri: str) -> None:
    bucket_name, blob_name = _parse_gs_uri(gs_uri)
    client = get_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.delete()


def list_prefix(gs_uri: str, max_results: int = 50) -> List[str]:
    """List objects under a gs://bucket/prefix. Returns full gs:// URIs limited by max_results."""
    bucket_name, prefix = _parse_gs_uri(gs_uri)
    client = get_client()
    bucket = client.bucket(bucket_name)
    it = bucket.list_blobs(prefix=prefix)
    out = []
    for b in itertools.islice(it, max_results):
        out.append(f"gs://{bucket_name}/{b.name}")
    return out
