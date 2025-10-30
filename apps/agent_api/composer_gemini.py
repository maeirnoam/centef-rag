from __future__ import annotations
from typing import List, Dict, Any
import os

try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
except Exception:  # pragma: no cover
    vertexai = None


MODEL_NAME = os.environ.get("GENERATION_MODEL", "gemini-1.5-pro")
LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
PROJECT = os.environ.get("GCP_PROJECT")


def _ensure_vertex():
    if vertexai is None:
        raise RuntimeError("vertexai library not installed")
    vertexai.init(project=PROJECT, location=LOCATION)


def build_prompt(question: str, contexts: List[Dict[str, Any]]) -> str:
    lines = [
        "You are a helpful assistant. Answer the question using the provided context only.",
        "Cite each statement with anchors (page x) or [start-end sec] for AV when possible.",
        "\nContext:",
    ]
    for i, c in enumerate(contexts, 1):
        meta = c.get("metadata", {})
        anchor = None
        if meta.get("page"):
            anchor = f"page {meta['page']}"
        elif meta.get("start_sec") and meta.get("end_sec"):
            anchor = f"{float(meta['start_sec']):.1f}-{float(meta['end_sec']):.1f}s"
        title = c.get("title") or meta.get("source_id")
        lines.append(f"[{i}] {title} ({anchor}): {c.get('text','')}")
    lines.append("\nQuestion: " + question)
    lines.append("Answer in the same language as the question. Keep it concise and include citations like [1], [2].")
    return "\n".join(lines)


def generate_answer(question: str, contexts: List[Dict[str, Any]]) -> Dict[str, Any]:
    _ensure_vertex()
    prompt = build_prompt(question, contexts)
    model = GenerativeModel(MODEL_NAME)
    resp = model.generate_content(prompt)
    text = resp.text
    return {"answer": text, "citations": contexts}
