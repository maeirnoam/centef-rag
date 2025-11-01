from fastapi import FastAPI
from pydantic import BaseModel
import os

from google.cloud import discoveryengine_v1 as des
from google.api_core.exceptions import GoogleAPICallError, PermissionDenied, NotFound
from google.protobuf.json_format import MessageToDict

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
        # turn the whole document into a plain dict
        doc_dict = MessageToDict(r.document._pb, preserving_proto_field_name=True)

        # typical shape:
        # {
        #   "id": "...",
        #   "struct_data": { ... },
        #   "content": { ... },
        #   "title": "...",
        #   "uri": "...",
        #   ...
        # }
        struct_data = doc_dict.get("struct_data", {})
        results.append(
            {
                "title": doc_dict.get("title", ""),
                "uri": doc_dict.get("uri", ""),
                "snippet": doc_dict.get("snippet", ""),
                "metadata": struct_data,
                "raw": doc_dict,  # keep for debugging; remove later
            }
        )

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
