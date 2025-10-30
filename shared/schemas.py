from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
import uuid
import hashlib
import time
import json


@dataclass
class Chunk:
    """Canonical chunk schema for Discovery Engine ingestion.

    Note: We do NOT store vectors. Vertex AI Search will handle embeddings internally.
    """
    chunk_id: str  # used as Discovery Engine document id
    source_id: str  # drive file id or gcs path
    source_type: str  # "pdf" | "pptx" | "audio" | "video" | "image" | "srt"
    title: str
    uri: str  # gs://... or drive://...
    text: str
    modality_payload: Dict[str, Any]
    entities: List[str]
    labels: List[str]
    lang: str
    created_at: str
    hash: str


def make_chunk(**kw) -> Chunk:
    """Create a Chunk. You can override chunk_id for deterministic IDs."""
    txt = kw.get("text", "")
    return Chunk(
        chunk_id=kw.get("chunk_id", str(uuid.uuid4())),
        hash=hashlib.sha256(txt.encode("utf-8")).hexdigest(),
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        entities=kw.get("entities", []),
        labels=kw.get("labels", []),
        lang=kw.get("lang", "en"),
        **{k: v for k, v in kw.items() if k not in {"entities", "labels", "lang", "chunk_id"}}
    )


def to_jsonl(chunks: List[Chunk]) -> str:
    return "\n".join(json.dumps(asdict(c), ensure_ascii=False) for c in chunks)


def to_discoveryengine_jsonl(chunks: List[Chunk]) -> str:
    """Convert chunks to Discovery Engine Import JSONL records.

    Each record is a Document with id, title, uri and structData fields.
    """
    records = []
    for c in chunks:
        payload = c.modality_payload or {}
        struct_data = {
            "text": c.text,
            "source_id": c.source_id,
            "source_type": c.source_type,
            "modality_payload": payload,
            "entities": c.entities,
            "labels": c.labels,
            "lang": c.lang,
            "created_at": c.created_at,
            "hash": c.hash,
        }
        # Flatten common anchor fields for easy filtering/retrieval in Vertex AI Search
        if "page" in payload:
            struct_data["page"] = payload["page"]
        if "slide" in payload:
            struct_data["slide"] = payload["slide"]
        if "start_sec" in payload:
            struct_data["start_sec"] = payload["start_sec"]
        if "end_sec" in payload:
            struct_data["end_sec"] = payload["end_sec"]

        record = {
            "id": c.chunk_id,
            "title": c.title,
            "uri": c.uri,
            "structData": struct_data,
        }
        records.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(records)
