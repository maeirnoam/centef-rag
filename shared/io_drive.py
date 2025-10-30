from __future__ import annotations
"""
Minimal Google Drive helper utilities. Optional: used if ingesting directly from Drive.
To use, ensure the service account has Drive API access and domain delegation if needed.
"""
from typing import Optional
import io
import os

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    from google.oauth2 import service_account
except Exception:  # pragma: no cover
    build = None


def _drive_service() -> Optional[any]:
    if build is None:
        return None
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    if creds_json and os.path.exists(creds_json):
        creds = service_account.Credentials.from_service_account_file(creds_json, scopes=scopes)
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    # On Cloud Run with default SA, use ADC (needs proper scopes/permissions configured)
    return build("drive", "v3")


def download_file_bytes(file_id: str) -> bytes:
    svc = _drive_service()
    if svc is None:
        raise RuntimeError("google-api-python-client not installed. Install to use Drive helpers.")
    request = svc.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    fh.seek(0)
    return fh.read()
