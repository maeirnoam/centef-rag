#!/usr/bin/env python3
"""
Setup Two-Tier Retrieval with Vertex AI Search

This script guides you through setting up a two-tier search system:
1. Summaries datastore - document-level search with rich metadata
2. Chunks datastore - granular chunk search with anchors (already exists)
3. Search App - combines both datastores for multi-tier retrieval

The script can also trigger imports and test the search.

Usage:
    python tools/setup_two_tier_search.py --create-summaries-datastore
    python tools/setup_two_tier_search.py --import-summaries
    python tools/setup_two_tier_search.py --test-search "your query"
    python tools/setup_two_tier_search.py --show-config
"""

import os
import argparse
import time
from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core.client_options import ClientOptions


# ========= CONFIG =========
PROJECT_ID = os.environ.get("PROJECT_ID", "sylvan-faculty-476113-c9")
PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER", "51695993895")
LOCATION = os.environ.get("VERTEX_SEARCH_LOCATION", "global")

# Existing chunks datastore
CHUNKS_DATASTORE_ID = os.environ.get("DATASTORE_ID", "centef-chunk-data-store_1761831236752_gcs_store")

# Summaries datastore (created)
SUMMARIES_DATASTORE_ID = os.environ.get("SUMMARIES_DATASTORE_ID", "centef-summaries-datastore_1762162632284_gcs_store")
SUMMARIES_BUCKET = os.environ.get("TARGET_BUCKET", "centef-rag-chunks")
SUMMARIES_PREFIX = "summaries/"

# Search App (will be created to combine both datastores)
SEARCH_APP_ID = "centef-two-tier-search-app"
# ==========================


def get_datastore_client():
    """Get Discovery Engine DataStore client."""
    client_options = ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    return discoveryengine.DataStoreServiceClient(client_options=client_options)


def get_engine_client():
    """Get Discovery Engine Engine (App) client."""
    client_options = ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    return discoveryengine.EngineServiceClient(client_options=client_options)


def get_search_client():
    """Get Discovery Engine Search client."""
    client_options = ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    return discoveryengine.SearchServiceClient(client_options=client_options)


def get_import_client():
    """Get Document Service client for imports."""
    client_options = ClientOptions(api_endpoint=f"{LOCATION}-discoveryengine.googleapis.com")
    return discoveryengine.DocumentServiceClient(client_options=client_options)


def create_summaries_datastore():
    """
    Create a new datastore for document summaries.
    """
    print("\n" + "="*70)
    print("CREATING SUMMARIES DATASTORE")
    print("="*70)
    
    client = get_datastore_client()
    
    # Parent: projects/{project}/locations/{location}/collections/default_collection
    parent = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection"
    
    print(f"\nProject: {PROJECT_ID}")
    print(f"Location: {LOCATION}")
    print(f"Datastore ID: {SUMMARIES_DATASTORE_ID}")
    print(f"Source: gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}*.jsonl")
    
    # Create datastore configuration
    datastore = discoveryengine.DataStore(
        display_name="CENTEF Document Summaries",
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH],
        content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
    )
    
    request = discoveryengine.CreateDataStoreRequest(
        parent=parent,
        data_store=datastore,
        data_store_id=SUMMARIES_DATASTORE_ID,
    )
    
    try:
        print("\nCreating datastore...")
        operation = client.create_data_store(request=request)
        print(f"Operation: {operation.operation.name}")
        
        print("Waiting for operation to complete (this may take a few minutes)...")
        response = operation.result()
        
        print(f"\n✅ Datastore created successfully!")
        print(f"   Name: {response.name}")
        print(f"   Display Name: {response.display_name}")
        
        # Get the full resource name
        datastore_path = f"{parent}/dataStores/{SUMMARIES_DATASTORE_ID}"
        print(f"\n📋 DATASTORE PATH:")
        print(f"   {datastore_path}")
        
        print(f"\n📋 Next steps:")
        print(f"   1. Configure GCS import for this datastore in the console:")
        print(f"      gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}*.jsonl")
        print(f"   2. Run: python tools/setup_two_tier_search.py --import-summaries")
        print(f"   3. Create Search App to combine datastores")
        
        return datastore_path
        
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"\n⚠️  Datastore '{SUMMARIES_DATASTORE_ID}' already exists")
            datastore_path = f"{parent}/dataStores/{SUMMARIES_DATASTORE_ID}"
            print(f"   Path: {datastore_path}")
            return datastore_path
        else:
            print(f"\n❌ Error creating datastore: {e}")
            raise


def trigger_summaries_import():
    """
    Trigger import of summaries from GCS into the summaries datastore.
    """
    print("\n" + "="*70)
    print("IMPORTING SUMMARIES")
    print("="*70)
    
    client = get_import_client()
    
    # Parent: projects/{project}/locations/{location}/collections/default_collection/dataStores/{datastore}/branches/default_branch
    parent = (
        f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/"
        f"dataStores/{SUMMARIES_DATASTORE_ID}/branches/default_branch"
    )
    
    gcs_uri = f"gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}*.jsonl"
    
    print(f"\nDatastore: {SUMMARIES_DATASTORE_ID}")
    print(f"Source: {gcs_uri}")
    
    # Configure import request
    request = discoveryengine.ImportDocumentsRequest(
        parent=parent,
        gcs_source=discoveryengine.GcsSource(
            input_uris=[gcs_uri],
            data_schema="document",  # or "content" depending on format
        ),
        reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL,
    )
    
    try:
        print("\nTriggering import...")
        operation = client.import_documents(request=request)
        print(f"Operation: {operation.operation.name}")
        
        print("\n✅ Import started successfully!")
        print("   This will run asynchronously.")
        print("   Check status in the Vertex AI Search console.")
        
        return operation.operation.name
        
    except Exception as e:
        print(f"\n❌ Error triggering import: {e}")
        raise


def create_search_app():
    """
    Create a Search App (Engine) that combines both datastores.
    """
    print("\n" + "="*70)
    print("CREATING TWO-TIER SEARCH APP")
    print("="*70)
    
    client = get_engine_client()
    
    # Parent: projects/{project}/locations/{location}/collections/default_collection
    parent = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection"
    
    chunks_datastore_path = f"{parent}/dataStores/{CHUNKS_DATASTORE_ID}"
    summaries_datastore_path = f"{parent}/dataStores/{SUMMARIES_DATASTORE_ID}"
    
    print(f"\nCombining datastores:")
    print(f"  1. Chunks: {CHUNKS_DATASTORE_ID}")
    print(f"  2. Summaries: {SUMMARIES_DATASTORE_ID}")
    
    # Create Search App configuration
    engine = discoveryengine.Engine(
        display_name="CENTEF Two-Tier Search",
        solution_type=discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH,
        industry_vertical=discoveryengine.IndustryVertical.GENERIC,
        data_store_ids=[CHUNKS_DATASTORE_ID, SUMMARIES_DATASTORE_ID],
        search_engine_config=discoveryengine.Engine.SearchEngineConfig(
            search_tier=discoveryengine.SearchTier.SEARCH_TIER_STANDARD,
            search_add_ons=[
                discoveryengine.SearchAddOn.SEARCH_ADD_ON_LLM,
            ],
        ),
    )
    
    request = discoveryengine.CreateEngineRequest(
        parent=parent,
        engine=engine,
        engine_id=SEARCH_APP_ID,
    )
    
    try:
        print("\nCreating Search App...")
        operation = client.create_engine(request=request)
        print(f"Operation: {operation.operation.name}")
        
        print("Waiting for operation to complete (this may take a few minutes)...")
        response = operation.result()
        
        print(f"\n✅ Search App created successfully!")
        print(f"   Name: {response.name}")
        print(f"   Display Name: {response.display_name}")
        
        # Get the serving config path
        serving_config = f"{response.name}/servingConfigs/default_config"
        
        print(f"\n📋 SERVING CONFIG:")
        print(f"   {serving_config}")
        
        print(f"\n📋 Update your .env file:")
        print(f'   DISCOVERY_SERVING_CONFIG="{serving_config}"')
        
        return serving_config
        
    except Exception as e:
        if "already exists" in str(e).lower():
            print(f"\n⚠️  Search App '{SEARCH_APP_ID}' already exists")
            app_path = f"{parent}/engines/{SEARCH_APP_ID}"
            serving_config = f"{app_path}/servingConfigs/default_config"
            print(f"   Serving Config: {serving_config}")
            return serving_config
        else:
            print(f"\n❌ Error creating Search App: {e}")
            raise


def test_search(query: str):
    """
    Test search against the two-tier system.
    """
    print("\n" + "="*70)
    print("TESTING TWO-TIER SEARCH")
    print("="*70)
    
    client = get_search_client()
    
    # Use the Search App serving config
    serving_config = (
        f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/"
        f"engines/{SEARCH_APP_ID}/servingConfigs/default_config"
    )
    
    print(f"\nQuery: {query}")
    print(f"Serving Config: {serving_config}")
    
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=query,
        page_size=5,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                summary_result_count=5,
                include_citations=True,
                use_semantic_chunks=True,
            ),
        ),
    )
    
    try:
        print("\nSearching...")
        response = client.search(request=request)
        
        print(f"\n📄 RESULTS:")
        for i, result in enumerate(response.results, 1):
            doc = result.document
            struct = dict(doc.struct_data) if doc.struct_data else {}
            
            print(f"\n[{i}] {doc.id}")
            print(f"    Title: {struct.get('title', 'N/A')}")
            print(f"    Type: {struct.get('document_type', struct.get('type', 'N/A'))}")
            
            # Show anchor if present
            if 'page' in struct:
                print(f"    Anchor: [Page {struct['page']}]")
            elif 'start_sec' in struct:
                start = int(float(struct['start_sec']))
                end = int(float(struct.get('end_sec', start)))
                print(f"    Anchor: [{start//60:02d}:{start%60:02d} - {end//60:02d}:{end%60:02d}]")
        
        # Show summary if available
        if hasattr(response, 'summary') and response.summary.summary_text:
            print(f"\n💡 SUMMARY:")
            print(response.summary.summary_text)
        
        print("\n✅ Search completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Error searching: {e}")
        raise


def show_config():
    """
    Show current configuration.
    """
    print("\n" + "="*70)
    print("CURRENT CONFIGURATION")
    print("="*70)
    
    print(f"\nProject:")
    print(f"  ID: {PROJECT_ID}")
    print(f"  Number: {PROJECT_NUMBER}")
    print(f"  Location: {LOCATION}")
    
    print(f"\nChunks Datastore (existing):")
    print(f"  ID: {CHUNKS_DATASTORE_ID}")
    path = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/dataStores/{CHUNKS_DATASTORE_ID}"
    print(f"  Path: {path}")
    print(f"  Serving: {path}/servingConfigs/default_search")
    
    print(f"\nSummaries Datastore (to be created):")
    print(f"  ID: {SUMMARIES_DATASTORE_ID}")
    path = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/dataStores/{SUMMARIES_DATASTORE_ID}"
    print(f"  Path: {path}")
    print(f"  Source: gs://{SUMMARIES_BUCKET}/{SUMMARIES_PREFIX}*.jsonl")
    
    print(f"\nSearch App (to be created):")
    print(f"  ID: {SEARCH_APP_ID}")
    path = f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/engines/{SEARCH_APP_ID}"
    print(f"  Path: {path}")
    print(f"  Serving: {path}/servingConfigs/default_config")
    
    print("\n" + "="*70)


def main():
    parser = argparse.ArgumentParser(
        description="Setup two-tier retrieval with Vertex AI Search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--create-summaries-datastore",
        action="store_true",
        help="Create the summaries datastore"
    )
    parser.add_argument(
        "--import-summaries",
        action="store_true",
        help="Trigger import of summaries from GCS"
    )
    parser.add_argument(
        "--create-search-app",
        action="store_true",
        help="Create Search App combining both datastores"
    )
    parser.add_argument(
        "--test-search",
        metavar="QUERY",
        help="Test search with a query"
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show current configuration"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all setup steps in sequence"
    )
    
    args = parser.parse_args()
    
    try:
        if args.show_config or (not any([args.create_summaries_datastore, args.import_summaries, 
                                          args.create_search_app, args.test_search, args.all])):
            show_config()
        
        if args.all or args.create_summaries_datastore:
            create_summaries_datastore()
            if args.all:
                print("\nWaiting 30 seconds for datastore to be ready...")
                time.sleep(30)
        
        if args.all or args.import_summaries:
            trigger_summaries_import()
            if args.all:
                print("\nWaiting 60 seconds for import to process...")
                time.sleep(60)
        
        if args.all or args.create_search_app:
            serving_config = create_search_app()
        
        if args.test_search:
            test_search(args.test_search)
        
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
