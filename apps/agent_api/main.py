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

        # struct_data can be None, a google.protobuf.Struct, or a MapComposite
        struct = d.struct_data
        meta = {}

        if struct:
            # best-effort: treat it like a dict
            try:
                # MapComposite behaves like a dict
                for key, value in struct.items():
                    # value can be Value/Struct; try to get string_value / number_value
                    if hasattr(value, "string_value"):
                        meta[key] = value.string_value
                    elif hasattr(value, "number_value"):
                        meta[key] = value.number_value
                    else:
                        # fallback to plain Python
                        meta[key] = value
            except AttributeError:
                # older style: struct.fields
                if hasattr(struct, "fields"):
                    for key, value in struct.fields.items():
                        meta[key] = value.string_value

        results.append({
            "title": d.title,
            "uri": d.uri,
            "snippet": d.snippet,
            "metadata": meta,
        })

    return results

@app.post("/chat")
def chat(req: ChatReq):
    try:
        hits = vertex_search(req.question, k=req.k, filter_expr=req.filter)
        return {
            "answer": f"found {len(hits)} hits",
            "hits": hits,
        }
    except (PermissionDenied, NotFound, GoogleAPICallError, RuntimeError) as e:
        return {
            "error": str(e),
            "discovery_serving_config": DISCOVERY_SERVING_CONFIG,
        }
