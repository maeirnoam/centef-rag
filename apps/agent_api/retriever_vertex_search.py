from __future__ import annotations
from typing import List, Dict, Any
import os
from google.cloud import discoveryengine_v1 as des
from shared.config import get_config

SERVING_CONFIG = get_config().DISCOVERY_SERVING_CONFIG or ""


def search_vertex(query: str, k: int = 8, filter_expr: str = "") -> List[Dict[str, Any]]:
    if not SERVING_CONFIG:
        raise RuntimeError("DISCOVERY_SERVING_CONFIG env var not set")
    client = des.SearchServiceClient()
    req = des.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=k,
        filter=filter_expr,
    )
    hits: List[Dict[str, Any]] = []
    resp = client.search(request=req)
    for r in resp.results:
        d = r.document
        f = d.struct_data.fields if d.struct_data else {}
        def getf(name, default=None):
            return f[name].string_value if name in f else default
        # snippet holds extractive passage if configured
        hits.append({
            "title": d.title or getf("title"),
            "uri": d.uri,
            "text": d.snippet or getf("text", ""),
            "metadata": {
                "source_id": getf("source_id"),
                "source_type": getf("source_type"),
                "page": getf("page"),
                "slide": getf("slide"),
                "start_sec": getf("start_sec"),
                "end_sec": getf("end_sec"),
            },
        })
    return hits
