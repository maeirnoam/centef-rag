from __future__ import annotations
from typing import Iterable, Set
import os
from google.cloud import discoveryengine_v1 as des

# Expect env var: DISCOVERY_DATASTORE = projects/.../locations/.../dataStores/...
DATASTORE = os.environ.get("DISCOVERY_DATASTORE", "")


def _doc_parent() -> str:
    if not DATASTORE:
        raise RuntimeError("DISCOVERY_DATASTORE env var not set")
    return DATASTORE


def list_document_ids_by_source(source_id: str) -> Set[str]:
    client = des.DocumentServiceClient()
    parent = _doc_parent()
    ids: Set[str] = set()
    for doc in client.list_documents(parent=parent):
        # Beware: listing all can be expensive; use only in admin flows.
        if doc.struct_data and "source_id" in doc.struct_data.fields:
            if doc.struct_data.fields["source_id"].string_value == source_id:
                ids.add(doc.id)
    return ids


def delete_documents(doc_ids: Iterable[str]) -> int:
    client = des.DocumentServiceClient()
    parent = _doc_parent()
    count = 0
    for did in doc_ids:
        name = f"{parent}/documents/{did}"
        client.delete_document(name=name)
        count += 1
    return count


def reconcile_source_ids(source_id: str, new_ids: Set[str]) -> dict:
    existing = list_document_ids_by_source(source_id)
    to_delete = existing - set(new_ids)
    deleted = delete_documents(to_delete) if to_delete else 0
    return {"existing": len(existing), "kept": len(existing) - deleted, "deleted": deleted}
