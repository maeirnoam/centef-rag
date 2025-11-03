# Answer Synthesis System

Advanced two-tier answer generation for the CENTEF RAG system.

## Overview

The synthesis system generates comprehensive, well-cited answers by leveraging two tiers of information:

1. **Tier 1 (Summaries)**: Document-level context with metadata (speaker, author, organization, date, tags)
2. **Tier 2 (Chunks)**: Granular content with precise anchors (timestamps, page numbers, slide numbers)

## Architecture

```
User Query
    ↓
Two-Tier Vertex AI Search
    ↓
Results Categorization
    ├── Summaries (Tier 1) → Document context
    └── Chunks (Tier 2) → Specific evidence
    ↓
Synthesis Prompt Construction
    ├── System instructions
    ├── Citation rules
    ├── Tier 1 context (summaries)
    ├── Tier 2 context (chunks with anchors)
    └── Question + answer instructions
    ↓
Gemini Generation (gemini-2.0-flash-exp)
    ↓
Formatted Response with Citations
```

## Key Features

### 1. Intelligent Result Categorization

Automatically separates results into two tiers:

```python
{
  "summaries": [
    {
      "id": "summary_youtube_iran_resistance",
      "title": "Iran's Axis of Resistance under Pressure",
      "metadata": {
        "speaker": "Matthew Levitt",
        "organization": "CIDItv",
        "date": "2025-05-27",
        "tags": ["Iran", "terrorism", "Middle East"]
      }
    }
  ],
  "chunks": [
    {
      "id": "_7ri5lgCCTM_chunk_41",
      "metadata": {
        "start_sec": 1493.2,
        "end_sec": 1528.5,
        "source_id": "youtube_iran_resistance"
      }
    }
  ]
}
```

### 2. Rich Citation Anchors

Supports multiple anchor types:

- **Video/Audio**: `[12:30-13:45]` - Minute:second timestamps
- **PDF Pages**: `[Page 5]` - Page numbers
- **Slides**: `[Slide 12]` - Presentation slides

### 3. Structured Synthesis Prompt

The prompt is carefully structured to guide Gemini:

```
=== TIER 1: DOCUMENT SUMMARIES ===
[S1] Title: Iran's Axis of Resistance under Pressure
     Speaker: Matthew Levitt | Organization: CIDItv
     Summary: Matthew Levitt discusses...

=== TIER 2: SPECIFIC CHUNKS (WITH ANCHORS) ===
[C1] youtube_iran_resistance [24:53-25:28]
     Regional instability that Iran has created...

[C2] syria_finances [Page 5]
     The new Syrian regime compared to Iran...

=== QUESTION ===
What does Matthew Levitt think of Iran's current state?

=== INSTRUCTIONS ===
- Cite every factual claim using [S1], [C1] etc.
- Prefer specific chunks over summaries
- Include anchors when citing chunks
```

### 4. Multi-Language Support

Generates answers in the target language:

```python
synthesis = synthesize_answer(
    question="ما رأي ماثيو ليفيت في الوضع الحالي لإيران؟",
    results=results,
    language="ar"  # Arabic
)
```

## Usage

### Option 1: As a Module

```python
from apps.agent_api.synthesizer import synthesize_answer, format_final_response

# Your search results from Vertex AI Search
results = vertex_search("what does matthew levitt think of iran?", k=10)

# Synthesize answer
synthesis = synthesize_answer(
    question="what does matthew levitt think of iran?",
    results=results,
    language="en"
)

# Get formatted output
print(format_final_response(synthesis))
```

### Option 2: FastAPI Endpoint

```bash
# Start the API
uvicorn apps.agent_api.main:app --reload

# Query via HTTP
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "question": "what does matthew levitt think of iran?",
    "k": 10,
    "language": "en"
  }'
```

Response structure:
```json
{
  "answer": "Matthew Levitt believes that Iran is under significant pressure...[C1][S1]",
  "summaries": [...],
  "chunks": [...],
  "total_results": 10,
  "model": "gemini-2.0-flash-exp",
  "language": "en"
}
```

### Option 3: Test Script

```bash
# Basic query
python tools/test_synthesis.py "what does matthew levitt think of iran?"

# With options
python tools/test_synthesis.py "terrorist financing" \
  --k 15 \
  --lang en \
  --save results.json \
  --show-prompt
```

Output:
```
🔍 QUERY: what does matthew levitt think of iran?
📊 Retrieving up to 10 results from two-tier search...
✅ Retrieved 10 results
🤖 Synthesizing answer with Gemini...

================================================================================
ANSWER
================================================================================

Matthew Levitt believes that Iran is currently under significant pressure 
from multiple fronts[S1]. He emphasizes that the regional instability Iran 
has fostered is at risk of boomeranging back across its borders[C1][24:53-25:28]. 
According to his analysis, the Iranian regime feels the military threat very 
strongly, which is why they seek framework agreements[C1][24:53-25:28].

However, Levitt cautions against banking on near-term political change or 
revolution in Iran, calling such hopes unrealistic[C2][41:20-42:18]. He argues 
that effective multinational coordination is needed to constrict Iran's ability 
to finance and arm its proxy networks[C3][28:55-29:11].

================================================================================
SOURCES
================================================================================

📚 DOCUMENT SUMMARIES:

[S1] Iran's Axis of Resistance under Pressure
     Speaker: Matthew Levitt | Type: youtube
     URL: https://www.youtube.com/watch?v=_7ri5lgCCTM

🔍 SPECIFIC REFERENCES:

[C1] youtube_iran_resistance [24:53-25:28]
     Regional instability that Iran has created and fostered...

[C2] youtube_iran_resistance [41:20-42:18]
     Anyone who banks on near-term political change in Iran...

[C3] youtube_iran_resistance [28:55-29:11]
     Need to put together a multinational effort to constrict Iran's...

================================================================================
Model: gemini-2.0-flash-exp
Results: 10 (1 summaries, 9 chunks)
================================================================================
```

## Configuration

Environment variables:

```bash
# Required
PROJECT_ID=your-gcp-project-id
DISCOVERY_SERVING_CONFIG=projects/.../servingConfigs/default_config

# Optional (with defaults)
GENERATION_MODEL=gemini-2.0-flash-exp
VERTEX_LOCATION=us-central1
```

## API Reference

### `synthesize_answer()`

```python
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
        language: Target language for the answer (ISO code)
    
    Returns:
        Dict with:
        - answer: Generated text with citations
        - summaries: List of Tier 1 documents
        - chunks: List of Tier 2 chunks with anchors
        - prompt: The synthesis prompt used
        - model: Generation model name
        - language: Target language
        - total_results: Total number of search results
    """
```

### `categorize_results()`

```python
def categorize_results(
    results: List[Dict[str, Any]]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Split results into summaries (Tier 1) and chunks (Tier 2).
    
    Categorization logic:
    - ID starts with "summary_" → Tier 1
    - metadata.type == "document_summary" → Tier 1
    - Everything else → Tier 2
    
    Returns:
        {
            "summaries": [...],
            "chunks": [...],
            "total": int
        }
    """
```

### `format_anchor()`

```python
def format_anchor(metadata: Dict[str, Any]) -> str:
    """
    Extract and format citation anchor from metadata.
    
    Anchor types:
    - Video/audio: {"start_sec": 753, "end_sec": 788} → "[12:33-13:08]"
    - PDF page: {"page": 5} → "[Page 5]"
    - Slide: {"slide": 12} → "[Slide 12]"
    
    Returns:
        Formatted anchor string or empty string if no anchor found
    """
```

### `format_final_response()`

```python
def format_final_response(synthesis: Dict[str, Any]) -> str:
    """
    Format synthesis result into human-readable text.
    
    Output includes:
    - Answer with citations
    - Document summaries (Tier 1) with metadata
    - Specific references (Tier 2) with anchors and snippets
    - Model and results statistics
    
    Returns:
        Formatted string with boxes and sections
    """
```

## Citation Style

### In Answer Text

- **Summaries**: `[S1]`, `[S2]`, `[S3]` - Document-level citations
- **Chunks**: `[C1]`, `[C2]`, `[C3]` - Specific content citations
- **Combined**: `[C1][C2]` - Multiple sources for one claim
- **With context**: `According to the analysis [C1][Page 5]...`

### In References Section

```
📚 DOCUMENT SUMMARIES:
[S1] Document Title
     Speaker: Name | Organization: Org | Date: YYYY-MM-DD
     URL: https://...

🔍 SPECIFIC REFERENCES:
[C1] source_id [12:30-13:45]
     Text snippet from the chunk...

[C2] source_id [Page 5]
     Text snippet from the chunk...
```

## Generation Parameters

Current configuration optimized for factual responses:

```python
generation_config = {
    "temperature": 0.3,      # Lower = more deterministic
    "top_p": 0.95,           # Nucleus sampling
    "top_k": 40,             # Top-k sampling
    "max_output_tokens": 2048,  # Max answer length
}
```

Adjust in `synthesizer.py` if needed:
- **Higher temperature (0.7-1.0)**: More creative, diverse answers
- **Lower temperature (0.1-0.3)**: More factual, focused answers

## Integration with Existing Components

### With retriever_vertex_search.py

```python
from apps.agent_api.retriever_vertex_search import search_vertex
from apps.agent_api.synthesizer import synthesize_answer

# Search
results = search_vertex("your query", k=10)

# Synthesize
synthesis = synthesize_answer("your query", results)
```

### With graph.py (LangGraph)

Update the `node_generate` function:

```python
def node_generate(state: ChatState) -> ChatState:
    from .synthesizer import synthesize_answer
    
    synthesis = synthesize_answer(
        state["question"],
        state.get("contexts", []),
        language=state.get("language", "en")
    )
    
    state.update(synthesis)
    return state
```

### With main.py (FastAPI)

Already integrated! Use the `/chat` endpoint.

## Testing

### Unit Tests

```bash
# Test categorization
python -c "
from apps.agent_api.synthesizer import categorize_results
results = [
    {'id': 'summary_doc1', 'metadata': {}},
    {'id': 'chunk_123', 'metadata': {}}
]
print(categorize_results(results))
"

# Test anchor formatting
python -c "
from apps.agent_api.synthesizer import format_anchor
print(format_anchor({'start_sec': 753, 'end_sec': 788}))
print(format_anchor({'page': 5}))
"
```

### Integration Tests

```bash
# Test with real query
python tools/test_synthesis.py "matthew levitt iran"

# Test with Arabic
python tools/test_synthesis.py "ما رأي ماثيو ليفيت" --lang ar

# Test with filter
python tools/test_synthesis.py "financing" --filter "document_type:youtube"
```

### API Tests

```bash
# Start server
uvicorn apps.agent_api.main:app --reload

# Test chat endpoint
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "test query", "k": 10}'

# Test formatted endpoint
curl -X POST http://localhost:8000/chat/formatted \
  -H "Content-Type: application/json" \
  -d '{"question": "test query"}'
```

## Troubleshooting

### No results returned

```python
# Check serving config
import os
print(os.environ.get("DISCOVERY_SERVING_CONFIG"))

# Test search directly
from google.cloud import discoveryengine_v1 as des
client = des.SearchServiceClient()
# ... run search
```

### Poor answer quality

1. **Check categorization**: Run with `--show-prompt` to see how results are categorized
2. **Adjust k**: Try `--k 15` to get more results
3. **Check temperature**: Lower it in `synthesizer.py` for more focused answers
4. **Verify metadata**: Ensure chunks have proper anchors (start_sec, page, etc.)

### Citation formatting issues

```python
# Debug anchor extraction
from apps.agent_api.synthesizer import format_anchor

metadata = {
    "start_sec": 1493.2,
    "end_sec": 1528.5
}
print(format_anchor(metadata))  # Should print [24:53-25:28]
```

### Language issues

```python
# Test language parameter
synthesis = synthesize_answer(
    "your question",
    results,
    language="ar"  # Arabic
)
```

## Roadmap

Future enhancements:

- [ ] **Streaming responses**: Real-time answer generation
- [ ] **Multi-turn conversations**: Context retention across queries
- [ ] **Source filtering**: Allow user to specify preferred document types
- [ ] **Citation verification**: Check if cited sources actually support claims
- [ ] **Summary caching**: Cache document summaries for faster retrieval
- [ ] **Custom prompts**: Allow users to customize synthesis instructions
- [ ] **Confidence scores**: Add confidence metrics to citations
- [ ] **Answer evaluation**: Automated quality metrics (faithfulness, completeness)

## See Also

- [TWO_TIER_COMPLETE.md](../TWO_TIER_COMPLETE.md) - Two-tier architecture overview
- [multiModalRag.instructions.md](../.github/instructions/multiModalRag.instructions.md) - System design
- API Documentation: `/docs` endpoint when running FastAPI
