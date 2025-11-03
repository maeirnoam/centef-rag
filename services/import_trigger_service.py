"""
Cloud Run service for triggering Discovery Engine datastore imports.
Wraps tools/trigger_datastore_import.py with FastAPI.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal
import sys
import os

# Add tools directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from trigger_datastore_import import trigger_import, DATASTORES

app = FastAPI(title="Import Trigger Service")


class TriggerImportRequest(BaseModel):
    datastore: Literal["chunks", "summaries", "both"] = "both"


class ImportOperation(BaseModel):
    datastore: str
    operation_name: str
    description: str


class TriggerImportResponse(BaseModel):
    success: bool
    operations: list[ImportOperation]
    message: str


@app.post("/trigger", response_model=TriggerImportResponse)
async def trigger_datastore_import(request: TriggerImportRequest):
    """
    Trigger Discovery Engine import for chunks and/or summaries datastores.
    
    Args:
        datastore: Which datastore(s) to import - "chunks", "summaries", or "both"
    
    Returns:
        List of triggered operations with their names
    """
    try:
        operations = []
        
        if request.datastore == "both":
            # Import both datastores
            print("[import_trigger] Triggering BOTH imports")
            
            # Chunks
            chunks_op = trigger_import("chunks")
            operations.append(ImportOperation(
                datastore="chunks",
                operation_name=chunks_op.operation.name,
                description=DATASTORES["chunks"]["description"]
            ))
            
            # Summaries
            summaries_op = trigger_import("summaries")
            operations.append(ImportOperation(
                datastore="summaries",
                operation_name=summaries_op.operation.name,
                description=DATASTORES["summaries"]["description"]
            ))
            
        elif request.datastore == "chunks":
            print("[import_trigger] Triggering CHUNKS import")
            chunks_op = trigger_import("chunks")
            operations.append(ImportOperation(
                datastore="chunks",
                operation_name=chunks_op.operation.name,
                description=DATASTORES["chunks"]["description"]
            ))
            
        elif request.datastore == "summaries":
            print("[import_trigger] Triggering SUMMARIES import")
            summaries_op = trigger_import("summaries")
            operations.append(ImportOperation(
                datastore="summaries",
                operation_name=summaries_op.operation.name,
                description=DATASTORES["summaries"]["description"]
            ))
        
        return TriggerImportResponse(
            success=True,
            operations=operations,
            message=f"Successfully triggered {len(operations)} import operation(s)"
        )
        
    except Exception as e:
        print(f"[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "import-trigger"}


@app.get("/datastores")
async def list_datastores():
    """List available datastores configuration"""
    return {
        "datastores": {
            key: {
                "id": config["id"],
                "description": config["description"],
                "gcs_pattern": config["gcs_pattern"]
            }
            for key, config in DATASTORES.items()
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
