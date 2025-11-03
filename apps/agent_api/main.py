from fastapi import FastAPI
from pydantic import BaseModel
import os

from google.cloud import discoveryengine_v1 as des
from google.api_core.exceptions import GoogleAPICallError, PermissionDenied, NotFound
from google.protobuf.json_format import MessageToDict

from .synthesizer import synthesize_answer, format_final_response

app = FastAPI(title="CENTEF RAG Agent API")

DISCOVERY_SERVING_CONFIG = os.getenv("DISCOVERY_SERVING_CONFIG")


class ChatReq(BaseModel):
    question: str
    k: int = 10  # Increased default for two-tier
    filter: str = ""
    language: str = "en"  # Target language for answer
    include_prompt: bool = False  # Include synthesis prompt in response


@app.get("/debug/env")
def debug_env():
    return {
        "DISCOVERY_SERVING_CONFIG": DISCOVERY_SERVING_CONFIG,
    }


def vertex_search(query: str, k: int = 10, filter_expr: str = ""):
    """
    Search the two-tier Vertex AI Search system.
    Returns normalized results with id, title, text, and metadata.
    """
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
        # Convert to dict
        doc_dict = MessageToDict(r.document._pb, preserving_proto_field_name=True)
        struct_data = doc_dict.get("struct_data", {})
        
        # Normalize structure for synthesizer
        results.append({
            "id": doc_dict.get("id", ""),
            "title": doc_dict.get("title", ""),
            "uri": doc_dict.get("uri", ""),
            "text": doc_dict.get("snippet", "") or struct_data.get("text", ""),
            "metadata": struct_data,
        })

    return results


@app.post("/chat")
def chat(req: ChatReq):
    """
    Main chat endpoint with two-tier retrieval and answer synthesis.
    
    Returns:
        - answer: Synthesized response with citations
        - summaries: Document-level results (Tier 1)
        - chunks: Granular results with anchors (Tier 2)
        - model: Generation model used
        - total_results: Total number of search results
    """
    try:
        # Retrieve from two-tier search
        hits = vertex_search(req.question, k=req.k, filter_expr=req.filter)
        
        if not hits:
            return {
                "answer": "No relevant documents found for your query.",
                "summaries": [],
                "chunks": [],
                "total_results": 0,
            }
        
        # Synthesize answer
        synthesis = synthesize_answer(
            question=req.question,
            results=hits,
            language=req.language
        )
        
        # Prepare response
        response = {
            "answer": synthesis["answer"],
            "summaries": synthesis["summaries"],
            "chunks": synthesis["chunks"],
            "total_results": synthesis["total_results"],
            "model": synthesis["model"],
            "language": synthesis["language"],
        }
        
        # Optionally include the prompt (for debugging)
        if req.include_prompt:
            response["prompt"] = synthesis["prompt"]
        
        return response
        
    except (PermissionDenied, NotFound, GoogleAPICallError, RuntimeError) as e:
        return {
            "error": str(e),
            "discovery_serving_config": DISCOVERY_SERVING_CONFIG,
        }


@app.post("/chat/formatted")
def chat_formatted(req: ChatReq):
    """
    Chat endpoint that returns a nicely formatted text response.
    Useful for CLI tools or simple integrations.
    """
    try:
        # Retrieve from two-tier search
        hits = vertex_search(req.question, k=req.k, filter_expr=req.filter)
        
        if not hits:
            return {
                "formatted_response": "No relevant documents found for your query."
            }
        
        # Synthesize answer
        synthesis = synthesize_answer(
            question=req.question,
            results=hits,
            language=req.language
        )
        
        # Format for display
        formatted = format_final_response(synthesis)
        
        return {
            "formatted_response": formatted,
            "json_response": {
                "answer": synthesis["answer"],
                "total_results": synthesis["total_results"],
                "model": synthesis["model"],
            }
        }
        
    except (PermissionDenied, NotFound, GoogleAPICallError, RuntimeError) as e:
        return {
            "error": str(e),
            "discovery_serving_config": DISCOVERY_SERVING_CONFIG,
        }
