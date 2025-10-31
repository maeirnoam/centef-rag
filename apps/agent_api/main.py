from fastapi import FastAPI
from pydantic import BaseModel
import os
from google.cloud import discoveryengine_v1 as des
from google.api_core.exceptions import GoogleAPICallError, PermissionDenied, NotFound

app = FastAPI(title="CENTEF RAG Agent API")

DISCOVERY_SERVING_CONFIG = os.getenv("DISCOVERY_SERVING_CONFIG")

class ChatReq(BaseModel):
    question: str
    k: int = 8
    filter: str = ""

@app.get("/debug/env")
def debug_env():
    return {
        "DISCOVERY_SERVING_CONFIG": DISCOVERY_SERVING_CONFIG,
    }

def vertex_search(query: str, k: int = 8, filter_expr: str = ""):
    if not DISCOVERY_SERVING_CONFIG:
        raise RuntimeError("DISCOVERY_SERVING_CONFIG env var is not set on the service")

    client = des.SearchServiceClient()
    req = des.SearchRequest(
        serving_config=DISCOVERY_SERVING_CONFIG,
        query=query,
        page_size=k,
        filter=filter_expr,
    )
    results = []
    for r in client.search(request=req).results:
        d = r.document
        struct = d.struct_data
        fields = struct.fields if struct else {}
        def sf(name, default=None):
            return fields[name].string_value if name in fields else default
        results.append({
            "title": d.title,
            "uri": d.uri,
            "snippet": d.snippet,
            "metadata": {
                "source_id": sf("source_id"),
                "source_type": sf("source_type"),
                "page": sf("page"),
                "slide": sf("slide"),
                "start_sec": sf("start_sec"),
                "end_sec": sf("end_sec"),
            }
        })
    return results

@app.post("/chat")
def chat(req: ChatReq):
    try:
        hits = vertex_search(req.question, k=req.k, filter_expr=req.filter)
        # later we can call Gemini on top, for now return raw hits
        return {
            "answer": f"found {len(hits)} hits",
            "hits": hits,
        }
    except (PermissionDenied, NotFound, GoogleAPICallError, RuntimeError) as e:
        return {
            "error": str(e),
            "discovery_serving_config": DISCOVERY_SERVING_CONFIG,
        }
