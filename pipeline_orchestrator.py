"""
Main Pipeline Orchestrator for CENTEF RAG System

Orchestrates the complete ingestion → chunking → summarization → manifest → indexing pipeline.

Pipeline Stages:
1. Source Detection: Scan GCS bucket for files (PDFs, videos, images, SRT)
2. Ingestion & Chunking: Route to appropriate ingestion service, generate chunks
   - Chunks written to gs://centef-rag-chunks/data/*.jsonl
3. Summarization: Generate document-level AI summaries with metadata
   - Summaries written to gs://centef-rag-chunks/summaries/*.jsonl
4. Manifest Generation: Extract metadata from summaries via populate_manifest.py
   - Manifest written to gs://centef-rag-chunks/manifest.jsonl
5. Datastore Imports: Trigger Discovery Engine imports (chunks + summaries)

Usage:
    # Process a single file
    python pipeline_orchestrator.py --file gs://centef-rag-bucket/data/document.pdf
    
    # Process all files in source bucket
    python pipeline_orchestrator.py --scan-all
    
    # Process specific file type
    python pipeline_orchestrator.py --scan-all --file-type pdf
    
    # Dry run (show what would be processed)
    python pipeline_orchestrator.py --scan-all --dry-run
"""

import os
import sys
import argparse
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import time

from google.cloud import storage

# Import our existing modules
from shared.io_gcs import read_text, write_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for pipeline orchestrator."""
    project_id: str
    source_bucket: str
    target_bucket: str
    source_prefix: str = "data"
    chunks_prefix: str = "data"
    summaries_prefix: str = "summaries"
    manifest_path: str = "manifest.jsonl"
    
    # Datastore IDs
    chunks_datastore_id: str = None
    summaries_datastore_id: str = None
    
    # Processing options
    auto_summarize: bool = True
    auto_import: bool = True
    skip_existing: bool = True


@dataclass
class FileMetadata:
    """Metadata for a file to be processed."""
    uri: str
    filename: str
    file_type: str  # pdf, video, audio, image, srt
    size_bytes: int
    updated: datetime
    source_id: str = None
    
    def __post_init__(self):
        if not self.source_id:
            # Generate source_id from filename
            self.source_id = Path(self.filename).stem.replace(" ", "_")


class PipelineOrchestrator:
    """Orchestrates the complete RAG pipeline."""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.storage_client = storage.Client(project=config.project_id)
        self.source_bucket = self.storage_client.bucket(config.source_bucket)
        self.target_bucket = self.storage_client.bucket(config.target_bucket)
        
        # Track processing state
        self.processed_files: List[str] = []
        self.failed_files: List[Tuple[str, str]] = []  # (uri, error)
        self.manifest_entries: List[Dict] = []
    
    def detect_file_type(self, filename: str) -> Optional[str]:
        """Detect file type from extension."""
        ext = Path(filename).suffix.lower()
        
        type_map = {
            '.pdf': 'pdf',
            '.mp4': 'video',
            '.mov': 'video',
            '.avi': 'video',
            '.mkv': 'video',
            '.mp3': 'audio',
            '.wav': 'audio',
            '.m4a': 'audio',
            '.jpg': 'image',
            '.jpeg': 'image',
            '.png': 'image',
            '.gif': 'image',
            '.srt': 'srt',
        }
        
        return type_map.get(ext)
    
    def scan_source_bucket(self, file_type: Optional[str] = None) -> List[FileMetadata]:
        """Scan source bucket for files to process."""
        logger.info(f"Scanning gs://{self.config.source_bucket}/{self.config.source_prefix}/")
        
        files = []
        prefix = f"{self.config.source_prefix}/"
        
        for blob in self.source_bucket.list_blobs(prefix=prefix):
            # Skip directories
            if blob.name.endswith('/'):
                continue
            
            filename = blob.name
            detected_type = self.detect_file_type(filename)
            
            # Skip if type detection failed
            if not detected_type:
                logger.debug(f"Skipping unsupported file: {filename}")
                continue
            
            # Filter by file type if specified
            if file_type and detected_type != file_type:
                continue
            
            file_meta = FileMetadata(
                uri=f"gs://{self.config.source_bucket}/{blob.name}",
                filename=blob.name,
                file_type=detected_type,
                size_bytes=blob.size,
                updated=blob.updated
            )
            
            files.append(file_meta)
        
        logger.info(f"Found {len(files)} files to process")
        return files
    
    def check_already_processed(self, source_id: str) -> bool:
        """Check if file has already been processed by looking for chunks."""
        chunks_path = f"{self.config.chunks_prefix}/{source_id}.jsonl"
        blob = self.target_bucket.blob(chunks_path)
        exists = blob.exists()
        
        if exists:
            logger.debug(f"File {source_id} already processed (found {chunks_path})")
        
        return exists
    
    def process_file(self, file_meta: FileMetadata, dry_run: bool = False) -> bool:
        """Process a single file through the complete pipeline.
        
        Returns:
            True if successful, False otherwise
        """
        source_id = file_meta.source_id
        file_type = file_meta.file_type
        uri = file_meta.uri
        
        logger.info(f"\n{'='*70}")
        logger.info(f"Processing: {file_meta.filename}")
        logger.info(f"Type: {file_type} | Source ID: {source_id}")
        logger.info(f"{'='*70}")
        
        if dry_run:
            logger.info("[DRY RUN] Would process this file")
            return True
        
        # Check if already processed
        if self.config.skip_existing and self.check_already_processed(source_id):
            logger.info(f"⏭️  Skipping {source_id} - already processed")
            return True
        
        try:
            # Stage 1: Ingestion → Chunking
            chunks_uri = self._run_ingestion(file_meta)
            if not chunks_uri:
                raise RuntimeError("Ingestion failed - no chunks generated")
            
            logger.info(f"✓ Stage 1 complete: Chunks written to {chunks_uri}")
            
            # Stage 2: Summarization (if enabled)
            summary_uri = None
            if self.config.auto_summarize:
                summary_uri = self._run_summarization(source_id, chunks_uri, file_meta)
                if summary_uri:
                    logger.info(f"✓ Stage 2 complete: Summary written to {summary_uri}")
                else:
                    logger.warning(f"⚠️  Summary generation failed for {source_id}, continuing...")
            
            # Track for manifest generation (Stage 3 will use populate_manifest.py)
            self.manifest_entries.append({"source_id": source_id, "summary_uri": summary_uri})
            
            # Track success
            self.processed_files.append(source_id)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error processing {source_id}: {e}", exc_info=True)
            self.failed_files.append((uri, str(e)))
            return False
    
    def _run_command(self, cmd: List[str]) -> bool:
        """Run a subprocess command and return success status."""
        try:
            result = subprocess.run(
                cmd,
                check=False,  # Don't raise on non-zero exit (handle manually)
                capture_output=True,
                text=True,
                errors='replace'  # Replace problematic characters instead of failing
            )
            
            # Log output if available
            if result.stdout:
                logger.debug(f"Command output: {result.stdout}")
            
            # Check return code, but be lenient about encoding errors
            # (ingestion scripts may fail to print but still succeed at upload)
            if result.returncode != 0:
                # Check if it's just a print encoding error (common on Windows)
                if "UnicodeEncodeError" in result.stderr and "charmap" in result.stderr:
                    logger.debug(f"Ignoring Unicode print error (upload likely succeeded)")
                    return True
                else:
                    logger.error(f"Command failed: {' '.join(cmd)}")
                    logger.error(f"Error: {result.stderr}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Command exception: {' '.join(cmd)}")
            logger.error(f"Exception: {str(e)}")
            return False
    
    def _run_ingestion(self, file_meta: FileMetadata) -> Optional[str]:
        """Run appropriate ingestion service based on file type.
        
        Returns:
            GCS URI of chunks file
        """
        source_id = file_meta.source_id
        file_type = file_meta.file_type
        uri = file_meta.uri
        title = Path(file_meta.filename).stem
        
        logger.info(f"  → Running {file_type} ingestion...")
        
        chunks_uri = f"gs://{self.config.target_bucket}/{self.config.chunks_prefix}/{source_id}.jsonl"
        
        success = False
        
        if file_type == 'pdf':
            # Call PDF ingestion script (it takes just a GCS URI as argument)
            cmd = [
                "python", "tools/ingest_pdf_pages.py",
                uri
            ]
            success = self._run_command(cmd)
        
        elif file_type == 'srt':
            # Call SRT ingestion script (it takes just a GCS URI as argument)
            cmd = [
                "python", "tools/ingest_srt.py",
                uri
            ]
            success = self._run_command(cmd)
        
        elif file_type in ['video', 'audio']:
            # Video/audio ingestion not yet set up for orchestrator
            # Would need translation API and other dependencies
            logger.warning(f"Video/audio ingestion via orchestrator not yet implemented")
            logger.info(f"  Run manually: python tools/ingest_video.py (then configure for this file)")
            return None
        
        elif file_type == 'image':
            # For images, we'll need to implement image ingestion
            # For now, log a warning
            logger.warning(f"Image ingestion not yet implemented for {source_id}")
            return None
        
        else:
            logger.error(f"Unsupported file type: {file_type}")
            return None
        
        if not success:
            return None
        
        # Verify chunks were written
        # Ingestion scripts append .jsonl to the original filename
        # e.g., data/file.pdf -> data/file.pdf.jsonl
        actual_chunks_path = f"{file_meta.filename}.jsonl"
        blob = self.target_bucket.blob(actual_chunks_path)
        
        if not blob.exists():
            logger.error(f"Chunks file not found: gs://{self.config.target_bucket}/{actual_chunks_path}")
            return None
        
        # Return the actual GCS URI
        return f"gs://{self.config.target_bucket}/{actual_chunks_path}"
    
    def _run_summarization(
        self, 
        source_id: str, 
        chunks_uri: str, 
        file_meta: FileMetadata
    ) -> Optional[str]:
        """Generate document-level summary.
        
        Returns:
            GCS URI of summary file
        """
        logger.info(f"  → Generating summary...")
        
        try:
            # Extract metadata for summary
            # Use clean filename without extension as title
            title = Path(file_meta.filename).stem.replace("_", " ")
            date = file_meta.updated.strftime("%Y-%m-%d")
            
            # Call summary generation script with full metadata
            cmd = [
                "python", "tools/ingest_summaries.py",
                "--source-id", source_id,
                "--chunks-uri", chunks_uri,
                "--title", title,
                "--date", date,
                "--document-type", file_meta.file_type,
                "--source-uri", file_meta.uri,
                # Note: author, organization, tags will be inferred by Gemini from content
            ]
            
            success = self._run_command(cmd)
            
            if success:
                summary_uri = f"gs://{self.config.target_bucket}/summaries/{source_id}.jsonl"
                return summary_uri
            else:
                return None
            
        except Exception as e:
            logger.warning(f"Summary generation failed for {source_id}: {e}")
            return None
    
    def finalize_manifest(self):
        """Generate manifest from summaries using populate_manifest.py."""
        if not self.manifest_entries:
            logger.info("No files were processed, skipping manifest generation")
            return
        
        logger.info(f"\n{'='*70}")
        logger.info(f"Generating manifest from {len(self.manifest_entries)} summaries")
        logger.info(f"{'='*70}")
        
        # Run populate_manifest.py to extract metadata from summaries
        manifest_uri = f"gs://{self.config.target_bucket}/{self.config.manifest_path}"
        
        cmd = [
            "python", "tools/populate_manifest.py",
            "--output", self.config.manifest_path
        ]
        
        success = self._run_command(cmd)
        
        if success:
            logger.info(f"✓ Manifest generated at {manifest_uri}")
            logger.info(f"  Processed documents: {len(self.manifest_entries)}")
        else:
            logger.error("Failed to generate manifest from summaries")
    
    def trigger_datastore_imports(self, import_both: bool = True):
        """Trigger Discovery Engine datastore imports."""
        if not self.config.auto_import:
            logger.info("Auto-import disabled, skipping datastore imports")
            return
        
        logger.info(f"\n{'='*70}")
        logger.info("Triggering datastore imports")
        logger.info(f"{'='*70}")
        
        try:
            if import_both:
                # Import both chunks and summaries
                logger.info("Importing chunks datastore...")
                cmd_chunks = ["python", "tools/trigger_datastore_import.py"]
                self._run_command(cmd_chunks)
                
                logger.info("\nImporting summaries datastore...")
                cmd_summaries = ["python", "tools/trigger_datastore_import.py", "--summaries"]
                self._run_command(cmd_summaries)
            else:
                # Just import chunks
                logger.info("Importing chunks datastore...")
                cmd = ["python", "tools/trigger_datastore_import.py"]
                self._run_command(cmd)
            
            logger.info("\n✓ Datastore import operations triggered")
            
        except Exception as e:
            logger.error(f"Error triggering imports: {e}", exc_info=True)
    
    def print_summary(self):
        """Print pipeline execution summary."""
        logger.info(f"\n{'='*70}")
        logger.info("PIPELINE EXECUTION SUMMARY")
        logger.info(f"{'='*70}")
        logger.info(f"Successfully processed: {len(self.processed_files)} files")
        
        if self.processed_files:
            for source_id in self.processed_files:
                logger.info(f"  ✓ {source_id}")
        
        if self.failed_files:
            logger.info(f"\nFailed: {len(self.failed_files)} files")
            for uri, error in self.failed_files:
                logger.info(f"  ✗ {uri}")
                logger.info(f"    Error: {error}")
        
        logger.info(f"{'='*70}\n")


def load_config_from_env() -> PipelineConfig:
    """Load pipeline configuration from environment variables."""
    return PipelineConfig(
        project_id=os.getenv("PROJECT_ID", "sylvan-faculty-476113-c9"),
        source_bucket=os.getenv("SOURCE_BUCKET", "centef-rag-bucket"),
        target_bucket=os.getenv("TARGET_BUCKET", "centef-rag-chunks"),
        source_prefix=os.getenv("SOURCE_DATA_PREFIX", "data"),
        chunks_datastore_id=os.getenv("DATASTORE_ID"),
        summaries_datastore_id=os.getenv("SUMMARIES_DATASTORE_ID"),
        auto_summarize=os.getenv("AUTO_SUMMARIZE", "true").lower() == "true",
        auto_import=os.getenv("AUTO_IMPORT", "true").lower() == "true",
        skip_existing=os.getenv("SKIP_EXISTING", "true").lower() == "true",
    )


def main():
    parser = argparse.ArgumentParser(
        description="CENTEF RAG Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single file
  python pipeline_orchestrator.py --file gs://centef-rag-bucket/data/report.pdf
  
  # Process all files in source bucket
  python pipeline_orchestrator.py --scan-all
  
  # Process only PDFs
  python pipeline_orchestrator.py --scan-all --file-type pdf
  
  # Dry run to see what would be processed
  python pipeline_orchestrator.py --scan-all --dry-run
  
  # Process without auto-summarization
  python pipeline_orchestrator.py --scan-all --no-summarize
  
  # Process without auto-import to datastores
  python pipeline_orchestrator.py --scan-all --no-import
        """
    )
    
    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--file", help="Process a single file (GCS URI)")
    input_group.add_argument("--scan-all", action="store_true", 
                            help="Scan and process all files in source bucket")
    
    # Filtering options
    parser.add_argument("--file-type", 
                       choices=['pdf', 'video', 'audio', 'image', 'srt'],
                       help="Filter by file type (only with --scan-all)")
    
    # Processing options
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be processed without actually processing")
    parser.add_argument("--no-summarize", action="store_true",
                       help="Skip automatic summarization")
    parser.add_argument("--no-import", action="store_true",
                       help="Skip automatic datastore imports")
    parser.add_argument("--skip-existing", action="store_true", default=True,
                       help="Skip files that have already been processed")
    
    args = parser.parse_args()
    
    # Load configuration
    config = load_config_from_env()
    
    # Apply CLI overrides
    if args.no_summarize:
        config.auto_summarize = False
    if args.no_import:
        config.auto_import = False
    config.skip_existing = args.skip_existing
    
    # Create orchestrator
    orchestrator = PipelineOrchestrator(config)
    
    # Determine files to process
    if args.scan_all:
        files = orchestrator.scan_source_bucket(file_type=args.file_type)
        
        if not files:
            logger.info("No files found to process")
            return
        
        # Process each file
        for file_meta in files:
            orchestrator.process_file(file_meta, dry_run=args.dry_run)
    
    else:
        # Process single file
        uri = args.file
        
        # Extract the relative path from the bucket URI
        # e.g., gs://bucket/data/file.pdf -> data/file.pdf
        if uri.startswith("gs://"):
            parts = uri.split('/', 3)  # ['gs:', '', 'bucket', 'path/to/file']
            if len(parts) >= 4:
                filename = parts[3]  # Get everything after bucket name
            else:
                filename = uri.split('/')[-1]
        else:
            filename = uri.split('/')[-1]
        
        # Create metadata
        file_meta = FileMetadata(
            uri=uri,
            filename=filename,
            file_type=orchestrator.detect_file_type(filename),
            size_bytes=0,  # Unknown
            updated=datetime.utcnow()
        )
        
        if not file_meta.file_type:
            logger.error(f"Unable to detect file type for: {filename}")
            return
        
        orchestrator.process_file(file_meta, dry_run=args.dry_run)
    
    # Finalize - Complete the pipeline
    if not args.dry_run:
        # Stage 3: Generate manifest from summaries (via populate_manifest.py)
        if orchestrator.processed_files and config.auto_summarize:
            logger.info(f"\n{'='*70}")
            logger.info("Stage 3: Generating manifest from summaries")
            logger.info(f"{'='*70}")
            orchestrator.finalize_manifest()
        elif orchestrator.processed_files and not config.auto_summarize:
            logger.info("\n⚠️  Skipping manifest generation (summaries not generated)")
        
        # Stage 4: Trigger Discovery Engine imports
        if orchestrator.processed_files and config.auto_import:
            logger.info(f"\n{'='*70}")
            logger.info("Stage 4: Triggering Discovery Engine imports")
            logger.info(f"{'='*70}")
            orchestrator.trigger_datastore_imports(
                import_both=config.auto_summarize  # Import summaries datastore only if we generated summaries
            )
        elif orchestrator.processed_files and not config.auto_import:
            logger.info("\n⚠️  Skipping datastore imports (--no-import flag)")
    
    # Print summary
    orchestrator.print_summary()


if __name__ == "__main__":
    main()
