from __future__ import annotations
from typing import Dict, Any
from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver

from .retriever_vertex_search import search_vertex
from .composer_gemini import generate_answer


class ChatState(dict):
    pass


def node_retrieve(state: ChatState) -> ChatState:
    query = state["question"]
    k = state.get("k", 8)
    filter_expr = state.get("filter", "")
    results = search_vertex(query, k=k, filter_expr=filter_expr)
    state["contexts"] = results
    return state


def node_generate(state: ChatState) -> ChatState:
    answer = generate_answer(state["question"], state.get("contexts", []))
    state.update(answer)
    return state


def build_graph():
    g = StateGraph(ChatState)
    g.add_node("retrieve", node_retrieve)
    g.add_node("generate", node_generate)
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "generate")
    memory = MemorySaver()
    return g.compile(checkpointer=memory)
