#!/usr/bin/env python3
"""
Test two-tier search and save results as JSON.

Usage:
    python tools/test_query_json.py "your query" --output results.json
"""

import os
import json
import argparse
from google.cloud import discoveryengine_v1beta as discovery
from google.api_core.client_options import ClientOptions
from google.protobuf.json_format import MessageToDict


# Config
PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER", "51695993895")
LOCATION = os.environ.get("VERTEX_SEARCH_LOCATION", "global")
SERVING_CONFIG = os.environ.get(
    "DISCOVERY_SERVING_CONFIG",
    f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/"
    f"engines/centef-two-tier-search-app/servingConfigs/default_config"
)


def search_and_save_json(query: str, output_path: str = None, page_size: int = 10):
    """Search and save results as JSON."""
    
    client_options = ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    client = discovery.SearchServiceClient(client_options=client_options)
    
    request = discovery.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=page_size,
    )
    
    print("="*80)
    print(f"QUERY: {query}")
    print(f"Serving Config: {SERVING_CONFIG}")
    print("="*80)
    
    response = client.search(request=request)
    
    # Build JSON structure
    results_json = {
        "query": query,
        "serving_config": SERVING_CONFIG,
        "total_results": 0,
        "summaries": [],
        "chunks": [],
        "all_results": []
    }
    
    def convert_to_json_serializable(obj):
        """Recursively convert proto objects to JSON-serializable types."""
        if isinstance(obj, dict):
            return {k: convert_to_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [convert_to_json_serializable(item) for item in obj]
        elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
            return [convert_to_json_serializable(item) for item in obj]
        elif hasattr(obj, 'DESCRIPTOR'):  # Protobuf message
            return str(obj)
        else:
            return obj
    
    for result in response.results:
        doc = result.document
        struct = dict(doc.struct_data) if doc.struct_data else {}
        
        # Build result object
        result_obj = {
            "id": doc.id,
            "name": doc.name,
            "struct_data": convert_to_json_serializable(struct),
        }
        
        # Add derived data if available
        if doc.derived_struct_data:
            try:
                result_obj["derived_struct_data"] = convert_to_json_serializable(dict(doc.derived_struct_data))
            except:
                pass  # Skip if conversion fails
        
        # Categorize
        if doc.id.startswith("summary_"):
            result_obj["tier"] = "summary"
            results_json["summaries"].append(result_obj)
        else:
            result_obj["tier"] = "chunk"
            results_json["chunks"].append(result_obj)
        
        results_json["all_results"].append(result_obj)
    
    results_json["total_results"] = len(results_json["all_results"])
    results_json["summary_count"] = len(results_json["summaries"])
    results_json["chunk_count"] = len(results_json["chunks"])
    
    # Print summary
    print(f"\n📊 RESULTS SUMMARY:")
    print(f"   Total: {results_json['total_results']}")
    print(f"   Summaries (Tier 1): {results_json['summary_count']}")
    print(f"   Chunks (Tier 2): {results_json['chunk_count']}")
    
    # Print summaries
    if results_json["summaries"]:
        print(f"\n📋 SUMMARIES:")
        for idx, summary in enumerate(results_json["summaries"], 1):
            struct = summary["struct_data"]
            print(f"\n   [{idx}] {summary['id']}")
            print(f"       Title: {struct.get('title', 'N/A')}")
            print(f"       Type: {struct.get('document_type', 'N/A')}")
            print(f"       Author/Speaker: {struct.get('author', struct.get('speaker', 'N/A'))}")
            if 'tags' in struct:
                tags = struct['tags']
                if isinstance(tags, list):
                    print(f"       Tags: {', '.join(tags[:3])}")
    
    # Print chunks
    if results_json["chunks"]:
        print(f"\n📄 CHUNKS:")
        for idx, chunk in enumerate(results_json["chunks"], 1):
            struct = chunk["struct_data"]
            
            # Get anchor info
            anchor = None
            if 'page' in struct:
                anchor = f"Page {struct['page']}"
            elif 'start_sec' in struct:
                start = int(float(struct['start_sec']))
                end = int(float(struct.get('end_sec', start)))
                anchor = f"{start//60:02d}:{start%60:02d}-{end//60:02d}:{end%60:02d}"
            
            print(f"\n   [{idx}] {chunk['id']}")
            if anchor:
                print(f"       Anchor: [{anchor}]")
            
            # Show snippet
            text = struct.get('text', '')
            if text and len(text) > 100:
                print(f"       Preview: {text[:100]}...")
    
    # Save to JSON file
    if not output_path:
        output_path = f"query_results_{query.replace(' ', '_')[:30]}.json"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results_json, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 SAVED TO: {output_path}")
    print("="*80)
    
    return results_json


def main():
    parser = argparse.ArgumentParser(description="Test search and save as JSON")
    parser.add_argument("query", nargs="+", help="Search query")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--page-size", type=int, default=10, help="Number of results (default: 10)")
    
    args = parser.parse_args()
    query = " ".join(args.query)
    
    search_and_save_json(query, args.output, args.page_size)


if __name__ == "__main__":
    main()
