from __future__ import annotations
import os
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Any, Dict


@dataclass(frozen=True)
class AppConfig:
    # Project / locations
    PROJECT_ID: str | None
    VERTEX_SEARCH_LOCATION: str | None  # Discovery Engine location (e.g., "global")
    GENERATION_LOCATION: str | None     # Vertex AI region for Gemini (e.g., "us-central1")

    # Discovery Engine (Vertex AI Search)
    DISCOVERY_DATASTORE: str | None
    DISCOVERY_SERVING_CONFIG: str | None

    # Storage
    SOURCE_DATA_PREFIX: str | None  # gs://... where your source files live
    CHUNKS_BUCKET: str | None       # gs://... where JSONL chunks are written

    # ASR
    ASR_PROVIDER: str | None        # "google" | "11labs"

    # Optional: DocAI
    DOC_AI_PROJECT: str | None
    DOC_AI_LOCATION: str | None
    DOC_AI_PROCESSOR_ID: str | None

    # Optional: Speech v2 recognizer
    SPEECH_LOCATION: str | None
    SPEECH_RECOGNIZER_ID: str | None

    def safe_dict(self) -> Dict[str, Any]:
        # Do not include secrets; only presence booleans if needed
        d = asdict(self)
        # Add secret presence flags
        d["ELEVENLABS_ASR_URL_SET"] = bool(os.environ.get("ELEVENLABS_ASR_URL"))
        d["ELEVENLABS_API_KEY_SET"] = bool(os.environ.get("ELEVENLABS_API_KEY"))
        return d


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    # Support both PROJECT_ID and GCP_PROJECT
    project_id = os.environ.get("PROJECT_ID") or os.environ.get("GCP_PROJECT")

    return AppConfig(
        PROJECT_ID=project_id,
        VERTEX_SEARCH_LOCATION=os.environ.get("VERTEX_SEARCH_LOCATION"),
        GENERATION_LOCATION=os.environ.get("GENERATION_LOCATION") or os.environ.get("VERTEX_LOCATION"),
        DISCOVERY_DATASTORE=os.environ.get("DISCOVERY_DATASTORE"),
        DISCOVERY_SERVING_CONFIG=os.environ.get("DISCOVERY_SERVING_CONFIG"),
        SOURCE_DATA_PREFIX=os.environ.get("SOURCE_DATA_PREFIX"),
        CHUNKS_BUCKET=os.environ.get("CHUNKS_BUCKET"),
        ASR_PROVIDER=os.environ.get("ASR_PROVIDER", "google"),
        DOC_AI_PROJECT=os.environ.get("DOC_AI_PROJECT"),
        DOC_AI_LOCATION=os.environ.get("DOC_AI_LOCATION"),
        DOC_AI_PROCESSOR_ID=os.environ.get("DOC_AI_PROCESSOR_ID"),
        SPEECH_LOCATION=os.environ.get("SPEECH_LOCATION"),
        SPEECH_RECOGNIZER_ID=os.environ.get("SPEECH_RECOGNIZER_ID"),
    )
