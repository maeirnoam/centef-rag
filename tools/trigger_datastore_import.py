"""
Trigger Discovery Engine datastore import from GCS.
"""
import os
from google.cloud import discoveryengine_v1 as discoveryengine


def env(name: str, default: str = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


# Configuration
PROJECT_ID = env("PROJECT_ID", "sylvan-faculty-476113-c9")
LOCATION = "global"
DATASTORE_ID = env("DATASTORE_ID", "centef-chunk-data-store_1761831236752_gcs_store")
CHUNKS_BUCKET = env("TARGET_BUCKET", "centef-rag-chunks").replace("gs://", "").strip("/")

# The GCS path pattern for import (e.g., gs://bucket/path/*.jsonl)
# You can specify a specific path or use wildcards
GCS_URI = f"gs://{CHUNKS_BUCKET}/**/*.jsonl"  # Import all JSONL files recursively


def trigger_import():
    """Trigger a GCS import operation for the datastore"""
    
    # Create the client
    client = discoveryengine.DocumentServiceClient()
    
    # Build the parent path (branch)
    parent = client.branch_path(
        project=PROJECT_ID,
        location=LOCATION,
        data_store=DATASTORE_ID,
        branch="default_branch"
    )
    
    print(f"Triggering import from: {GCS_URI}")
    print(f"To datastore: {parent}")
    
    # Create the import request
    # For JSONL with structured data, use "document" schema
    gcs_source = discoveryengine.GcsSource(
        input_uris=[GCS_URI],
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
    print("\nTo wait for completion, run:")
    print("  # This may take several minutes to hours depending on data size")
    
    # Optionally wait for completion (can take a while)
    # print("\nWaiting for import to complete...")
    # response = operation.result(timeout=3600)  # 1 hour timeout
    # print(f"Import completed: {response}")
    
    return operation


if __name__ == "__main__":
    trigger_import()
