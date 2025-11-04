"""
File Storage Agent for Oncology Document Upload
Writes summaries to Unity Catalog Volume (modern, governed approach)

Authentication: Automatic passthrough via Agent Framework
Demonstrates: UC governance, permissions, lineage, audit trail
"""

import os
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class FileStorageAgent:
    """
    Specialist agent for storing oncology summaries.
    
    For Demo: Writes to Unity Catalog Volume
    For Production: Swap to Google Drive, SharePoint, S3, etc.
    
    Architecture Note:
    - Uses Unity Catalog Volumes (modern, governed file storage)
    - AUTOMATIC PASSTHROUGH authentication (no dedicated SP needed!)
    - UC provides: permissions, lineage, audit trail, versioning
    - This is the ONLY agent that writes final outputs to storage
    - Extraction/Summarization agents stay within Databricks processing
    
    Why UC Volumes > DBFS:
    - ✅ Unity Catalog governed (permissions, audit, lineage)
    - ✅ Automatic passthrough authentication
    - ✅ Part of the lakehouse (not deprecated like DBFS)
    - ✅ Shows best practice for Banner
    """
    
    def __init__(self):
        """
        Initialize file storage agent.
        
        Environment Variables (injected at deployment):
        - STORAGE_TYPE: 'uc_volume' or 'google_drive' (default: uc_volume)
        - STORAGE_PATH: Path to UC volume (default: /Volumes/{catalog}/{schema}/summaries/)
        - CATALOG_NAME: Unity Catalog name (default: from env)
        - SCHEMA_NAME: Schema name (default: from env)
        """
        self.storage_type = os.environ.get("STORAGE_TYPE", "uc_volume")
        
        # Get catalog/schema from environment
        catalog = os.environ.get("CATALOG_NAME", "sselvan_banner")
        schema = os.environ.get("SCHEMA_NAME", "oncology_cqrs")
        
        # UC Volume path: /Volumes/{catalog}/{schema}/{volume_name}/
        # This is the modern way to store files in Databricks
        self.storage_path = os.environ.get(
            "STORAGE_PATH", 
            f"/Volumes/{catalog}/{schema}/summaries/"
        )
        
        # Ensure storage path exists
        if self.storage_type == "uc_volume":
            try:
                os.makedirs(self.storage_path, exist_ok=True)
                logger.info(f"FileStorageAgent initialized (type={self.storage_type}, path={self.storage_path})")
                logger.info(f"✅ Using Unity Catalog Volume with AUTOMATIC PASSTHROUGH authentication")
            except Exception as e:
                logger.error(f"Failed to create storage path: {e}")
                # Fallback to tmp if volume doesn't exist yet
                self.storage_path = "/tmp/oncology_summaries/"
                os.makedirs(self.storage_path, exist_ok=True)
                logger.warning(f"⚠️ Fell back to: {self.storage_path}")
    
    def upload_summary(
        self,
        summary: str,
        patient_id: str,
        extraction_run_id: str,
        summarization_run_id: str
    ) -> Dict[str, Any]:
        """
        Store oncology summary to Unity Catalog Volume.
        
        Args:
            summary: The generated summary text
            patient_id: Patient identifier (for filename)
            extraction_run_id: Extraction job run ID (for audit trail)
            summarization_run_id: Summarization job run ID (for audit trail)
        
        Returns:
            Dict with upload status and file metadata
        
        Authentication:
            - Uses AUTOMATIC PASSTHROUGH (no dedicated SP needed!)
            - Agent Framework grants endpoint permissions to UC Volume
            - UC tracks: who wrote, when, from which job
        
        File Format:
            - Path: /Volumes/{catalog}/{schema}/summaries/
            - Filename: oncology_summary_{patient_id}_{timestamp}.txt
            - Content: Summary text with audit metadata header
            - UC Lineage: Automatically tracked
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"oncology_summary_{patient_id}_{timestamp}.txt"
        filepath = os.path.join(self.storage_path, filename)
        
        try:
            # Write summary with metadata header
            with open(filepath, 'w') as f:
                # Header with audit trail
                f.write("="*80 + "\n")
                f.write(f"ONCOLOGY SUMMARY - Patient {patient_id}\n")
                f.write("="*80 + "\n")
                f.write(f"Generated: {datetime.now().isoformat()}\n")
                f.write(f"Extraction Run ID: {extraction_run_id}\n")
                f.write(f"Summarization Run ID: {summarization_run_id}\n")
                f.write("="*80 + "\n\n")
                
                # Actual summary
                f.write(summary)
            
            logger.info(f"✅ Wrote summary to UC Volume: {filepath}")
            
            return {
                "status": "success",
                "message": f"Summary saved to Unity Catalog Volume (automatic passthrough auth)",
                "file_path": filepath,
                "file_name": filename,
                "storage_type": self.storage_type,
                "patient_id": patient_id,
                "extraction_run_id": extraction_run_id,
                "summarization_run_id": summarization_run_id,
                "timestamp": timestamp
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to write summary: {e}")
            return {
                "status": "failed",
                "message": f"Upload failed: {str(e)}",
                "file_name": filename,
                "error": str(e),
                "extraction_run_id": extraction_run_id,
                "summarization_run_id": summarization_run_id
            }
    
    def list_summaries(self, patient_id: str = None) -> Dict[str, Any]:
        """
        List stored summaries.
        
        Args:
            patient_id: Optional filter for specific patient
        
        Returns:
            Dict with list of summary files
        """
        try:
            files = os.listdir(self.storage_path)
            
            if patient_id:
                files = [f for f in files if patient_id in f]
            
            files = [f for f in files if f.endswith('.txt')]
            files.sort(reverse=True)  # Most recent first
            
            return {
                "status": "success",
                "files": files,
                "count": len(files),
                "storage_path": self.storage_path
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to list summaries: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }
    
    def get_summary(self, filename: str) -> Dict[str, Any]:
        """
        Retrieve a specific summary.
        
        Args:
            filename: Name of the summary file
        
        Returns:
            Dict with file content and metadata
        """
        filepath = os.path.join(self.storage_path, filename)
        
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            return {
                "status": "success",
                "filename": filename,
                "content": content,
                "file_path": filepath
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to read summary: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }


# Tool interface for LangChain/Agent Framework
def upload_to_storage(
    summary: str,
    patient_id: str,
    extraction_run_id: str,
    summarization_run_id: str
) -> str:
    """
    LangChain tool wrapper for Unity Catalog Volume storage.
    
    Authentication: Uses automatic passthrough (no dedicated SP needed!)
    
    Args:
        summary: The summary text to store
        patient_id: Patient identifier
        extraction_run_id: Extraction job run ID
        summarization_run_id: Summarization job run ID
    
    Returns:
        Human-readable status message
    """
    agent = FileStorageAgent()
    result = agent.upload_summary(summary, patient_id, extraction_run_id, summarization_run_id)
    
    if result["status"] == "success":
        return f"✅ Summary saved to Unity Catalog Volume!\n\nFile: {result['file_name']}\nLocation: {result['file_path']}\n\n(Used automatic passthrough authentication)"
    else:
        return f"❌ Save failed: {result['message']}"

