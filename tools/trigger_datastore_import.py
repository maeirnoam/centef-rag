"""
Trigger Discovery Engine datastore import from GCS.

Dynamically handles both chunk datastore and summaries datastore.

Usage:
    python tools/trigger_datastore_import.py                 # Import chunks
    python tools/trigger_datastore_import.py --summaries     # Import summaries
    python tools/trigger_datastore_import.py --both          # Import both
"""
import os
import sys
import argparse
from google.cloud import discoveryengine_v1 as discoveryengine


def env(name: str, default: str = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# Configuration
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
PROJECT_NUMBER = "51695993895"  # For direct path construction
LOCATION = "global"
CHUNKS_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")

# Datastore configurations
DATASTORES = {
    "chunks": {
        "id": env("DATASTORE_ID", "centef-chunk-data-store_1761831236752_gcs_store"),
        "gcs_pattern": f"gs://{CHUNKS_BUCKET}/**/*.jsonl",
        "description": "Chunks datastore (granular content)"
    },
    "summaries": {
        "id": env("SUMMARIES_DATASTORE_ID", "centef-summaries-datastore_1762162632284_gcs_store"),
        "gcs_pattern": f"gs://{CHUNKS_BUCKET}/summaries/*.jsonl",
        "description": "Summaries datastore (document-level)"
    }
}


def trigger_import(datastore_key: str):
    """Trigger a GCS import operation for the specified datastore.
    
    Args:
        datastore_key: Key for DATASTORES dict ("chunks" or "summaries")
    """
    config = DATASTORES[datastore_key]
    datastore_id = config["id"]
    gcs_pattern = config["gcs_pattern"]
    
    # Create the client
    client = discoveryengine.DocumentServiceClient()
    
    # Build the parent path (branch)
    parent = client.branch_path(
        project=PROJECT_ID,
        location=LOCATION,
        data_store=datastore_id,
        branch="default_branch"
    )
    
    print(f"\n{'='*70}")
    print(f"Triggering {datastore_key.upper()} import")
    print(f"Description: {config['description']}")
    print(f"GCS Pattern: {gcs_pattern}")
    print(f"Target: {parent}")
    print(f"{'='*70}")
    
    # Create the import request
    # For JSONL with structured data, use "document" schema
    gcs_source = discoveryengine.GcsSource(
        input_uris=[gcs_pattern],
        data_schema="document"  # For JSONL with id, content, metadata
    )
    
    request = discoveryengine.ImportDocumentsRequest(
        parent=parent,
        gcs_source=gcs_source,
        reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL
        # Don't set auto_generate_ids or id_field for document schema
    )
    
    # Start the import operation
    operation = client.import_documents(request=request)
    
    print(f"\n✅ Import operation started!")
    print(f"Operation name: {operation.operation.name}")
    print("\nThe import will run in the background. You can monitor it in the console at:")
    print(f"https://console.cloud.google.com/gen-app-builder/engines?project={PROJECT_ID}")
    
    # Optionally wait for completion (can take a while)
    # print("\nWaiting for import to complete...")
    # response = operation.result(timeout=3600)  # 1 hour timeout
    # print(f"Import completed: {response}")
    
    return operation


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Trigger Discovery Engine datastore import from GCS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tools/trigger_datastore_import.py                  # Import chunks (default)
  python tools/trigger_datastore_import.py --summaries      # Import summaries only
  python tools/trigger_datastore_import.py --both           # Import both datastores
        """
    )
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--summaries", action="store_true", 
                      help="Import summaries datastore only")
    group.add_argument("--both", action="store_true",
                      help="Import both chunks and summaries datastores")
    
    args = parser.parse_args()
    
    if args.both:
        # Import both datastores
        trigger_import("chunks")
        trigger_import("summaries")
    elif args.summaries:
        # Import summaries only
        trigger_import("summaries")
    else:
        # Default: import chunks
        trigger_import("chunks")
