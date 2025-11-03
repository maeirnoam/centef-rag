#!/usr/bin/env python3
"""
Test the new answer synthesis system with two-tier retrieval.

This script:
1. Queries the two-tier Vertex AI Search
2. Categorizes results into summaries (Tier 1) and chunks (Tier 2)
3. Generates a well-cited answer using Gemini
4. Displays the formatted response

Usage:
    python tools/test_synthesis.py "your question here"
    python tools/test_synthesis.py "what does matthew levitt think of iran" --lang ar
    python tools/test_synthesis.py "terrorist financing" --save output.json
"""

import os
import sys
import json
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from google.cloud import discoveryengine_v1 as des
from apps.agent_api.synthesizer import synthesize_answer, format_final_response


def load_config():
    """Load configuration from environment."""
    config = {
        "serving_config": os.environ.get("DISCOVERY_SERVING_CONFIG"),
        "project_id": os.environ.get("PROJECT_ID"),
    }
    
    if not config["serving_config"]:
        raise ValueError("DISCOVERY_SERVING_CONFIG environment variable not set. Check .env file.")
    
    return config


def search_two_tier(query: str, k: int = 10, filter_expr: str = "") -> list:
    """
    Query the two-tier Vertex AI Search system.
    
    Returns:
        List of results with id, title, text, metadata
    """
    config = load_config()
    
    client = des.SearchServiceClient()
    request = des.SearchRequest(
        serving_config=config["serving_config"],
        query=query,
        page_size=k,
        filter=filter_expr,
    )
    
    results = []
    response = client.search(request=request)
    
    for r in response.results:
        doc = r.document
        
        # Use MessageToDict to properly extract all proto fields
        from google.protobuf.json_format import MessageToDict
        
        try:
            # Convert the entire document to dict
            doc_dict = MessageToDict(doc._pb, preserving_proto_field_name=True)
            # Check if struct_data is nested under structData (Discovery Engine format)
            if "struct_data" in doc_dict:
                struct_data = doc_dict["struct_data"]
            elif "structData" in doc_dict:
                struct_data = doc_dict["structData"]
            else:
                struct_data = {}
        except:
            # Fallback: manual extraction
            struct_data = {}
            if hasattr(doc, 'struct_data') and doc.struct_data:
                for key, value in doc.struct_data.items():
                    if hasattr(value, 'string_value'):
                        struct_data[key] = value.string_value
                    elif hasattr(value, 'number_value'):
                        struct_data[key] = value.number_value
                    elif hasattr(value, 'list_value'):
                        struct_data[key] = [item.string_value if hasattr(item, 'string_value') else str(item) 
                                           for item in value.list_value.values]
        
        # Get document ID from name or struct_data
        doc_name = doc_dict.get("name", "") if 'doc_dict' in locals() else (doc.name if hasattr(doc, 'name') else "")
        doc_id = doc_name.split('/')[-1] if doc_name else ""
        
        # For summaries, use the id field from struct_data if available
        if "id" in struct_data:
            doc_id = struct_data["id"]
        elif "source_id" in struct_data:
            # Fallback to source_id
            doc_id = struct_data["source_id"]
        
        # Get text - prefer text field, fallback to text_original
        text = struct_data.get("text", "") or struct_data.get("text_original", "")
        
        # Get title and URI
        doc_title = struct_data.get("title", "")
        doc_uri = struct_data.get("source_uri", "")
        
        results.append({
            "id": doc_id,
            "title": doc_title,
            "uri": doc_uri,
            "text": text,
            "metadata": struct_data,
        })
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Test answer synthesis with two-tier retrieval"
    )
    parser.add_argument(
        "query",
        type=str,
        help="Query to search for"
    )
    parser.add_argument(
        "--k",
        type=int,
        default=10,
        help="Number of results to retrieve (default: 10)"
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="en",
        help="Target language for answer (default: en)"
    )
    parser.add_argument(
        "--filter",
        type=str,
        default="",
        help="Filter expression for search"
    )
    parser.add_argument(
        "--save",
        type=str,
        help="Save full results to JSON file"
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Show the synthesis prompt used"
    )
    
    args = parser.parse_args()
    
    print(f"🔍 QUERY: {args.query}")
    print(f"📊 Retrieving up to {args.k} results from two-tier search...")
    print()
    
    try:
        # Step 1: Search
        results = search_two_tier(args.query, k=args.k, filter_expr=args.filter)
        
        if not results:
            print("❌ No results found.")
            return
        
        print(f"✅ Retrieved {len(results)} results")
        print()
        
        # Step 2: Synthesize answer
        print("🤖 Synthesizing answer with Gemini...")
        print()
        
        synthesis = synthesize_answer(
            question=args.query,
            results=results,
            language=args.lang
        )
        
        # Step 3: Display formatted response
        formatted = format_final_response(synthesis)
        print(formatted)
        
        # Optional: Show prompt
        if args.show_prompt:
            print("\n" + "=" * 80)
            print("SYNTHESIS PROMPT (DEBUG)")
            print("=" * 80)
            print(synthesis["prompt"])
        
        # Optional: Save to file
        if args.save:
            output_data = {
                "query": args.query,
                "synthesis": {
                    "answer": synthesis["answer"],
                    "model": synthesis["model"],
                    "language": synthesis["language"],
                    "total_results": synthesis["total_results"],
                },
                "summaries": synthesis["summaries"],
                "chunks": synthesis["chunks"],
                "prompt": synthesis["prompt"] if args.show_prompt else None,
            }
            
            with open(args.save, "w", encoding="utf-8") as f:
                json.dump(output_data, f, indent=2, ensure_ascii=False)
            
            print(f"\n💾 Full results saved to: {args.save}")
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
