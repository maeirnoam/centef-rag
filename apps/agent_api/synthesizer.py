"""
Advanced answer synthesis for two-tier RAG system.

This module handles:
1. Categorizing results into summaries (Tier 1) and chunks (Tier 2)
2. Building rich context with document-level and granular information
3. Generating well-cited answers using Gemini
4. Formatting citations with proper anchors (timestamps, pages)
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
import os

try:
    import vertexai
    from vertexai.preview.generative_models import GenerativeModel
except ImportError:
    vertexai = None

# Configuration
PROJECT_ID = os.environ.get("PROJECT_ID", os.environ.get("GCP_PROJECT"))
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
# Use gemini-2.5-flash via preview API (available and fast)
GENERATION_MODEL = os.environ.get("GENERATION_MODEL", "gemini-2.5-flash")


def _ensure_vertex():
    """Initialize Vertex AI once."""
    if vertexai is None:
        raise RuntimeError("vertexai library not installed. Run: pip install google-cloud-aiplatform")
    if PROJECT_ID is None:
        raise RuntimeError("PROJECT_ID or GCP_PROJECT environment variable not set")
    vertexai.init(project=PROJECT_ID, location=VERTEX_LOCATION)


def categorize_results(results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Split results into summaries (Tier 1) and chunks (Tier 2).
    
    Args:
        results: List of search result dicts with 'id', 'metadata', etc.
    
    Returns:
        Dict with 'summaries' and 'chunks' lists
    """
    summaries = []
    chunks = []
    
    for result in results:
        doc_id = result.get("id", "")
        metadata = result.get("metadata", {})
        doc_type = metadata.get("type", "")
        
        # Categorize by ID prefix or type
        if doc_id.startswith("summary_") or doc_type == "document_summary":
            summaries.append(result)
        else:
            chunks.append(result)
    
    return {
        "summaries": summaries,
        "chunks": chunks,
        "total": len(results)
    }


def get_source_id(result: Dict[str, Any]) -> str:
    """
    Extract source_id from result, trying multiple locations.
    
    Returns:
        Source ID string or result ID as fallback
    """
    metadata = result.get("metadata", {})
    
    # Try metadata first
    if "source_id" in metadata:
        return metadata["source_id"]
    
    # Try extracting from source_uri
    source_uri = metadata.get("source_uri", "")
    if source_uri:
        # For youtube: youtube://_7ri5lgCCTM -> _7ri5lgCCTM
        if "youtube://" in source_uri:
            return source_uri.split("youtube://")[-1].split("/")[0]
        # For GCS: gs://bucket/file.srt -> file
        if "gs://" in source_uri:
            return source_uri.split("/")[-1].split(".")[0]
    
    # Fallback to result id
    return result.get("id", "unknown")


def format_anchor(metadata: Dict[str, Any]) -> str:
    """
    Extract and format citation anchor from metadata.
    
    Returns:
        Formatted anchor string like "[Page 5]" or "[12:30-13:45]" or ""
    """
    # Video/audio timestamp
    if "start_sec" in metadata and "end_sec" in metadata:
        try:
            start_sec = float(metadata["start_sec"])
            end_sec = float(metadata["end_sec"])
            
            # Format as MM:SS
            start_min = int(start_sec // 60)
            start_s = int(start_sec % 60)
            end_min = int(end_sec // 60)
            end_s = int(end_sec % 60)
            
            return f"[{start_min:02d}:{start_s:02d}-{end_min:02d}:{end_s:02d}]"
        except (ValueError, TypeError):
            pass
    
    # PDF page
    if "page" in metadata:
        try:
            page = int(float(metadata["page"]))
            return f"[Page {page}]"
        except (ValueError, TypeError):
            pass
    
    # Slide number
    if "slide" in metadata:
        try:
            slide = int(float(metadata["slide"]))
            return f"[Slide {slide}]"
        except (ValueError, TypeError):
            pass
    
    return ""


def build_synthesis_prompt(
    question: str,
    summaries: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en"
) -> str:
    """
    Build a comprehensive prompt for answer synthesis.
    
    The prompt structure:
    1. System instruction
    2. Document-level context (summaries)
    3. Granular context (chunks with anchors)
    4. The question
    5. Answer instructions
    """
    
    lines = [
        "You are an expert research assistant analyzing documents from CENTEF (Center for Terrorism & Economic Fraud).",
        "Your task is to provide a direct, comprehensive answer based on two tiers of information:",
        "- Tier 1: Document summaries (high-level context with speaker/author metadata)",
        "- Tier 2: Specific chunks with precise anchors (detailed evidence)",
        "",
        "IMPORTANT INSTRUCTIONS:",
        "- If the question asks about a specific person's views (e.g., 'what does Matthew Levitt think'),",
        "  and you see that person listed as speaker/author in the summaries, USE THEIR CONTENT.",
        "- Be direct and confident in attributing statements when the metadata clearly identifies the speaker.",
        "- Don't say 'the documents don't attribute' if the speaker metadata shows who is speaking.",
        "",
        "CITATION RULES:",
        "- Always cite sources using [S1], [S2] for summaries and [C1], [C2] for chunks",
        "- Include anchors like [Page 5] or [12:30-13:45] when citing chunks",
        "- Prefer citing specific chunks over summaries when available",
        "- Multiple citations are encouraged: [C1][C2]",
        "",
    ]
    
    # Tier 1: Document Summaries
    if summaries:
        lines.append("=== TIER 1: DOCUMENT SUMMARIES ===")
        for i, summary in enumerate(summaries, 1):
            metadata = summary.get("metadata", {})
            
            # Handle nested structData from Discovery Engine
            if "structData" in metadata and isinstance(metadata["structData"], dict):
                metadata = metadata["structData"]
            
            title = summary.get("title") or metadata.get("title", "Unknown Document")
            
            # Extract document metadata
            doc_meta = []
            if "speaker" in metadata:
                doc_meta.append(f"Speaker: {metadata['speaker']}")
            elif "author" in metadata:
                doc_meta.append(f"Author: {metadata['author']}")
            if "organization" in metadata:
                doc_meta.append(f"Organization: {metadata['organization']}")
            if "date" in metadata:
                doc_meta.append(f"Date: {metadata['date']}")
            if "document_type" in metadata:
                doc_meta.append(f"Type: {metadata['document_type']}")
            
            meta_str = " | ".join(doc_meta)
            
            # Get text from multiple possible locations
            text = summary.get("text") or metadata.get("text", "")
            
            # Skip if no meaningful content
            if not text and not meta_str:
                continue
            
            lines.append(f"\n[S{i}] {title}")
            if meta_str:
                lines.append(f"   {meta_str}")
            if text:
                lines.append(f"   Summary: {text[:500]}..." if len(text) > 500 else f"   Summary: {text}")
        lines.append("")
    
    # Tier 2: Granular Chunks
    if chunks:
        lines.append("=== TIER 2: SPECIFIC CHUNKS (WITH ANCHORS) ===")
        for i, chunk in enumerate(chunks, 1):
            metadata = chunk.get("metadata", {})
            text = chunk.get("text") or metadata.get("text") or metadata.get("text_original", "")
            
            # Get source info using helper function
            source_id = get_source_id(chunk)
            
            # Get anchor
            anchor = format_anchor(metadata)
            
            # Format chunk entry
            source_line = f"{source_id} {anchor}" if anchor else source_id
            lines.append(f"\n[C{i}] {source_line}")
            
            # Add text (truncate if very long)
            chunk_text = text[:300] + "..." if len(text) > 300 else text
            lines.append(f"   {chunk_text}")
        lines.append("")
    
    # No results case
    if not summaries and not chunks:
        lines.append("=== NO RELEVANT DOCUMENTS FOUND ===")
        lines.append("")
    
    # Question and instructions
    lines.extend([
        f"=== QUESTION ===",
        question,
        "",
        "=== INSTRUCTIONS ===",
        f"Answer in {language if language != 'en' else 'English'}.",
        "Structure your answer as follows:",
        "1. Direct answer to the question (2-3 sentences)",
        "2. Supporting evidence with citations",
        "3. Additional context if relevant",
        "",
        "IMPORTANT:",
        "- Cite every factual claim",
        "- Use [S1], [S2] for summaries and [C1], [C2] for chunks",
        "- When citing chunks, mention the anchor: 'According to the analysis [C1][Page 5]...'",
        "- For video/audio: 'As stated in the interview [C2][12:30-13:45]...'",
        "- Be specific and precise",
        "- If the sources don't fully answer the question, acknowledge the gaps",
        "",
        "Now provide your synthesized answer:"
    ])
    
    return "\n".join(lines)


def synthesize_answer(
    question: str,
    results: List[Dict[str, Any]],
    language: str = "en"
) -> Dict[str, Any]:
    """
    Synthesize a comprehensive answer from two-tier search results.
    
    Args:
        question: User's question
        results: List of search results from Vertex AI Search
        language: Target language for the answer
    
    Returns:
        Dict with:
        - answer: Generated text with citations
        - summaries: List of Tier 1 documents
        - chunks: List of Tier 2 chunks with anchors
        - prompt: The prompt used (for debugging)
        - model: Model used for generation
    """
    _ensure_vertex()
    
    # Categorize results
    categorized = categorize_results(results)
    summaries = categorized["summaries"]
    chunks = categorized["chunks"]
    
    # Build prompt
    prompt = build_synthesis_prompt(question, summaries, chunks, language)
    
    # Generate answer
    model = GenerativeModel(GENERATION_MODEL)
    
    generation_config = {
        "temperature": 0.1,  # Very low for most factual, direct responses
        "top_p": 0.9,
        "top_k": 20,
        "max_output_tokens": 2048,
    }
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )
        answer_text = response.text
    except Exception as e:
        answer_text = f"Error generating answer: {str(e)}"
    
    return {
        "answer": answer_text,
        "summaries": summaries,
        "chunks": chunks,
        "total_results": categorized["total"],
        "prompt": prompt,  # Include for debugging
        "model": GENERATION_MODEL,
        "language": language
    }


def format_final_response(synthesis: Dict[str, Any]) -> str:
    """
    Format the synthesis result into a nice human-readable response.
    
    Args:
        synthesis: Output from synthesize_answer()
    
    Returns:
        Formatted string with answer and references
    """
    lines = [
        "=" * 80,
        "ANSWER",
        "=" * 80,
        "",
        synthesis["answer"],
        "",
        "=" * 80,
        "SOURCES",
        "=" * 80,
    ]
    
    # Document summaries
    summaries = synthesis.get("summaries", [])
    if summaries:
        lines.append("\n📚 DOCUMENT SUMMARIES:")
        for i, summary in enumerate(summaries, 1):
            metadata = summary.get("metadata", {})
            title = summary.get("title") or metadata.get("title", "Unknown")
            
            doc_info = []
            if "speaker" in metadata:
                doc_info.append(f"Speaker: {metadata['speaker']}")
            elif "author" in metadata:
                doc_info.append(f"Author: {metadata['author']}")
            if "document_type" in metadata:
                doc_info.append(f"Type: {metadata['document_type']}")
            
            lines.append(f"\n[S{i}] {title}")
            if doc_info:
                lines.append(f"     {' | '.join(doc_info)}")
            if "source_uri" in metadata:
                lines.append(f"     URL: {metadata['source_uri']}")
    
    # Specific chunks
    chunks = synthesis.get("chunks", [])
    if chunks:
        lines.append("\n🔍 SPECIFIC REFERENCES:")
        for i, chunk in enumerate(chunks, 1):
            metadata = chunk.get("metadata", {})
            source_id = get_source_id(chunk)
            anchor = format_anchor(metadata)
            
            lines.append(f"\n[C{i}] {source_id} {anchor}")
            
            # Show snippet
            text = chunk.get("text") or metadata.get("text") or metadata.get("text_original", "")
            snippet = text[:200] + "..." if len(text) > 200 else text
            lines.append(f"     {snippet}")
    
    lines.extend([
        "",
        "=" * 80,
        f"Model: {synthesis.get('model', 'unknown')}",
        f"Results: {synthesis.get('total_results', 0)} ({len(summaries)} summaries, {len(chunks)} chunks)",
        "=" * 80
    ])
    
    return "\n".join(lines)


if __name__ == "__main__":
    """Test the synthesizer with sample data."""
    
    # Sample results (mimicking real search output)
    sample_results = [
        {
            "id": "summary_youtube_iran_resistance",
            "title": "Iran's Axis of Resistance under Pressure",
            "text": "Matthew Levitt discusses Iran's proxy networks...",
            "metadata": {
                "type": "document_summary",
                "speaker": "Matthew Levitt",
                "organization": "CIDItv",
                "document_type": "youtube",
                "source_uri": "https://youtube.com/watch?v=_7ri5lgCCTM"
            }
        },
        {
            "id": "chunk_123",
            "text": "Regional instability that Iran has created...",
            "metadata": {
                "source_id": "youtube_iran_resistance",
                "start_sec": 1493.2,
                "end_sec": 1528.5,
                "type": "video_transcript"
            }
        }
    ]
    
    result = synthesize_answer(
        "What does Matthew Levitt think of Iran's current state?",
        sample_results
    )
    
    print(format_final_response(result))
