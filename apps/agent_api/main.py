from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .graph import build_graph
from .index_admin import reconcile_source_ids
from .retriever_vertex_search import search_vertex
from shared.io_gcs import list_prefix
from shared.config import get_config
import os

app = FastAPI(title="Agent API")
workflow = build_graph()


class ChatRequest(BaseModel):
    question: str
    k: int = 8
    filter: str | None = None


@app.post("/chat")
def chat(req: ChatRequest):
    state = {"question": req.question, "k": req.k, "filter": req.filter or ""}
    result = workflow.invoke(state)
    return {"answer": result.get("answer"), "contexts": result.get("contexts", [])}


@app.get("/healthz")
def health():
    return {"status": "ok"}


class ReconcileRequest(BaseModel):
    source_id: str
    new_chunk_ids: list[str]


@app.post("/admin/reconcile")
def reconcile(req: ReconcileRequest):
    if not req.source_id:
        raise HTTPException(status_code=400, detail="source_id required")
    summary = reconcile_source_ids(req.source_id, set(req.new_chunk_ids))
    return summary


@app.get("/admin/config")
def admin_config():
    # Return a safe subset of config for debugging
    return get_config().safe_dict()


@app.get("/admin/gcs/list")
def gcs_list(uri: str = Query(..., description="gs://bucket/prefix"), max: int = 20):
    if not uri.startswith("gs://"):
        raise HTTPException(status_code=400, detail="uri must start with gs://")
    objs = list_prefix(uri, max_results=max)
    return {"count": len(objs), "objects": objs}


@app.get("/admin/gcs/check")
def gcs_check():
    cfg = get_config()
    src = cfg.SOURCE_DATA_PREFIX
    chunks = cfg.CHUNKS_BUCKET
    out = {}
    if src and src.startswith("gs://"):
        out["source_sample"] = list_prefix(src, max_results=10)
    if chunks and chunks.startswith("gs://"):
        out["chunks_sample"] = list_prefix(chunks, max_results=10)
    return out


@app.get("/admin/search/ping")
def search_ping(query: str = "test", k: int = 3):
    try:
        hits = search_vertex(query, k=k)
        return {"query": query, "hits": len(hits), "results": hits}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/gcs/list_source")
def gcs_list_source(sub: str = Query("", description="Optional relative subpath under SOURCE_DATA_PREFIX"), max: int = 20):
    """List objects under SOURCE_DATA_PREFIX, optionally under a relative subpath.

    Example: if SOURCE_DATA_PREFIX=gs://bucket/data and sub="reports/",
    this lists gs://bucket/data/reports/...
    """
    cfg = get_config()
    base = cfg.SOURCE_DATA_PREFIX
    if not base or not base.startswith("gs://"):
        raise HTTPException(status_code=500, detail="SOURCE_DATA_PREFIX not configured or not a gs:// URI")
    # Normalize join
    base = base.rstrip("/")
    sub = sub.lstrip("/")
    uri = base if not sub else f"{base}/{sub}"
    objs = list_prefix(uri, max_results=max)
    return {"base": cfg.SOURCE_DATA_PREFIX, "listed_uri": uri, "count": len(objs), "objects": objs}
