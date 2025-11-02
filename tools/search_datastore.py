"""
Simple search script for Discovery Engine datastore.
"""
import os
from google.cloud import discoveryengine_v1 as discoveryengine
from google.protobuf.json_format import MessageToDict


def env(name: str, default: str = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# Configuration
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = "global"
DATASTORE_ID = env("DATASTORE_ID", "centef-chunk-data-store_1761831236752_gcs_store")
SERVING_CONFIG = f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/dataStores/{DATASTORE_ID}/servingConfigs/default_search"


def search(query: str, page_size: int = 5):
    """Search the Discovery Engine datastore"""
    
    client = discoveryengine.SearchServiceClient()
    
    request = discoveryengine.SearchRequest(
        serving_config=SERVING_CONFIG,
        query=query,
        page_size=page_size,
    )
    
    print(f"Searching for: '{query}'\n")
    print("=" * 80)
    
    response = client.search(request)
    
    if not response.results:
        print("No results found.")
        return
    
    for i, result in enumerate(response.results, 1):
        print(f"\n[Result {i}]")
        print(f"Document ID: {result.id}")
        
        # Extract structured data
        if result.document.struct_data:
            # struct_data is already a dict-like object
            struct_dict = dict(result.document.struct_data)
            
            print(f"\nPage: {struct_dict.get('page', 'N/A')}")
            print(f"Source: {struct_dict.get('source_uri', 'N/A')}")
            print(f"Type: {struct_dict.get('type', 'N/A')}")
            
            text = struct_dict.get('text', '')
            if text:
                # Show first 500 chars
                preview = text[:500] + "..." if len(text) > 500 else text
                print(f"\nContent Preview:\n{preview}")
        
        print("-" * 80)
    
    print(f"\nTotal results: {response.total_size}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = input("Enter search query: ")
    
    search(query)
