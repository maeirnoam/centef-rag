#!/usr/bin/env python3
"""
Test two-tier search and visualize results from both datastores.

Shows which results come from summaries (document-level) vs chunks (granular).
"""

import os
from google.cloud import discoveryengine_v1beta as discovery
from google.api_core.client_options import ClientOptions


# Config
PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER", "51695993895")
LOCATION = os.environ.get("VERTEX_SEARCH_LOCATION", "global")
SERVING_CONFIG = os.environ.get(
    "DISCOVERY_SERVING_CONFIG",
    f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/"
    f"engines/centef-two-tier-search-app/servingConfigs/default_config"
)


def search_two_tier(query: str, page_size: int = 10):
    """Search across both tiers and categorize results."""
    
    client_options = ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    client = discovery.SearchServiceClient(client_options=client_options)
    
    request = discovery.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=page_size,
    )
    
    print("="*80)
    print(f"QUERY: {query}")
    print(f"Serving Config: .../{SERVING_CONFIG.split('/')[-3]}/{SERVING_CONFIG.split('/')[-2]}")
    print("="*80)
    
    response = client.search(request=request)
    
    summaries = []
    chunks = []
    
    for result in response.results:
        doc = result.document
        struct = dict(doc.struct_data) if doc.struct_data else {}
        
        # Categorize by document type or ID
        if doc.id.startswith("summary_"):
            summaries.append((doc, struct))
        else:
            chunks.append((doc, struct))
    
    # Display summaries (Tier 1)
    print(f"\n📋 TIER 1: DOCUMENT SUMMARIES ({len(summaries)} results)")
    print("-"*80)
    
    if summaries:
        for doc, struct in summaries:
            print(f"\n🔷 {doc.id}")
            print(f"   Title: {struct.get('title', 'N/A')}")
            print(f"   Type: {struct.get('document_type', 'N/A')}")
            print(f"   Author/Speaker: {struct.get('author', struct.get('speaker', 'N/A'))}")
            print(f"   Organization: {struct.get('organization', 'N/A')}")
            print(f"   Date: {struct.get('date', 'N/A')}")
            
            if 'tags' in struct:
                tags = struct['tags']
                if isinstance(tags, list):
                    print(f"   Tags: {', '.join(tags[:5])}")
            
            # Show snippet of summary
            text = struct.get('text', '')
            if text:
                snippet = text[:200] + "..." if len(text) > 200 else text
                print(f"   Summary: {snippet}")
            
            print(f"   Source: {struct.get('source_uri', 'N/A')}")
            print(f"   Chunks: {struct.get('num_chunks', 'N/A')}")
    else:
        print("   (No document-level results)")
    
    # Display chunks (Tier 2)
    print(f"\n📄 TIER 2: GRANULAR CHUNKS ({len(chunks)} results)")
    print("-"*80)
    
    if chunks:
        for doc, struct in chunks:
            print(f"\n🔹 {doc.id}")
            
            # Extract content
            text = struct.get('text', doc.derived_struct_data.get('snippets', [{}])[0].get('snippet', 'N/A') if doc.derived_struct_data else 'N/A')
            if isinstance(text, str):
                snippet = text[:150] + "..." if len(text) > 150 else text
                print(f"   Content: {snippet}")
            
            # Show anchor
            anchor = None
            if 'page' in struct:
                anchor = f"[Page {struct['page']}]"
            elif 'start_sec' in struct:
                start = int(float(struct['start_sec']))
                end = int(float(struct.get('end_sec', start)))
                anchor = f"[{start//60:02d}:{start%60:02d} - {end//60:02d}:{end%60:02d}]"
            
            if anchor:
                print(f"   Anchor: {anchor}")
            
            # Show source
            source_uri = struct.get('source_uri', 'N/A')
            if source_uri != 'N/A' and len(source_uri) > 60:
                source_uri = "..." + source_uri[-60:]
            print(f"   Source: {source_uri}")
    else:
        print("   (No chunk-level results)")
    
    print("\n" + "="*80)
    print(f"TOTAL RESULTS: {len(summaries)} summaries + {len(chunks)} chunks = {len(summaries) + len(chunks)}")
    print("="*80)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Matthew Levitt Iran resistance"
    
    search_two_tier(query)
