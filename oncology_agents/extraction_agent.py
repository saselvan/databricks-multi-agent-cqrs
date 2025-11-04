"""
Extraction Agent - Triggers PDF Extraction Jobs

🔐 SECURITY:
- Uses EXTRACTION_SP credentials (manual OAuth)
- Only has permissions to:
  - Read source PDFs
  - Write to staging.extracted_documents
  - Run extraction job

🚫 CANNOT:
- Write to SharePoint
- Run summarization job
- Access production tables
"""

import os
import logging
from databricks.sdk import WorkspaceClient


class ExtractionAgent:
    """Agent responsible for triggering PDF extraction jobs with dedicated SP"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # 🔐 MANUAL OAUTH - Dedicated Service Principal for extraction
        # These credentials are injected at deploy time from Databricks Secrets
        self.client_id = os.environ.get("EXTRACTION_SP_CLIENT_ID")
        self.client_secret = os.environ.get("EXTRACTION_SP_CLIENT_SECRET")
        self.workspace_url = os.environ.get("DATABRICKS_HOST")
        self.extraction_job_id = int(os.environ.get("EXTRACTION_JOB_ID", "0"))
        
        if not all([self.client_id, self.client_secret, self.workspace_url]):
            raise ValueError("Extraction SP credentials not configured")
        
        self.logger.info("✅ ExtractionAgent initialized with EXTRACTION_SP")
    
    def trigger_extraction(self, document_path: str, user_id: str) -> dict:
        """
        Trigger PDF extraction job asynchronously
        
        Args:
            document_path: Path to PDF file (e.g., /source_pdfs/patient_123.pdf)
            user_id: User who triggered the extraction
        
        Returns:
            dict with run_id and status message
        
        🔐 AUTHENTICATION: Uses EXTRACTION_SP (manual OAuth)
        """
        self.logger.info(f"🔐 Authenticating as EXTRACTION_SP for user: {user_id}")
        
        # Validate input
        if not document_path.endswith('.pdf'):
            raise ValueError("Only PDF files are supported")
        
        if not document_path.startswith('/source_pdfs/'):
            raise ValueError("PDFs must be in /source_pdfs/ directory")
        
        try:
            # 🔐 Create WorkspaceClient with EXTRACTION_SP credentials
            # OAuth tokens will auto-refresh - unlimited duration
            w = WorkspaceClient(
                host=self.workspace_url,
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            
            self.logger.info(f"📄 Triggering PDF extraction for: {document_path}")
            
            # Trigger extraction job (async - returns immediately)
            run = w.jobs.run_now(
                job_id=self.extraction_job_id,
                notebook_params={
                    "document_path": document_path,
                    "triggered_by": user_id
                }
            )
            
            run_id = run.run_id
            
            self.logger.info(f"✅ Extraction job started: Run ID {run_id}")
            
            # 🔐 Write command event to CQRS (for audit trail)
            self._write_command_event(
                event_type="ExtractionJobStarted",
                run_id=run_id,
                document_path=document_path,
                user_id=user_id
            )
            
            return {
                "success": True,
                "run_id": run_id,
                "message": f"PDF extraction started! Run ID: {run_id}",
                "eta_minutes": 30,
                "next_steps": "I'll notify you when extraction completes. You can ask other questions in the meantime."
            }
            
        except Exception as e:
            self.logger.error(f"❌ Extraction trigger failed: {e}")
            
            # Write failure event
            self._write_command_event(
                event_type="ExtractionJobFailed",
                run_id=0,
                document_path=document_path,
                user_id=user_id,
                error=str(e)
            )
            
            raise Exception(f"Failed to trigger extraction: {str(e)}")
    
    def check_extraction_status(self, run_id: int) -> dict:
        """
        Check status of extraction job from CQRS event store
        
        Args:
            run_id: Job run ID
        
        Returns:
            dict with status and details
        
        🔐 READS FROM DELTA: No API calls, cheap and fast
        """
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            # Query latest event for this run_id
            result = spark.sql(f"""
                SELECT event_type, status, details, timestamp
                FROM oncology_cqrs.job_events
                WHERE run_id = {run_id}
                  AND agent = 'extraction_agent'
                ORDER BY timestamp DESC
                LIMIT 1
            """).collect()
            
            if not result or len(result) == 0:
                return {
                    "status": "NOT_FOUND",
                    "message": f"No extraction job found with Run ID {run_id}"
                }
            
            event = result[0]
            event_type = event.event_type
            
            if event_type == 'ExtractionJobCompleted':
                return {
                    "status": "COMPLETED",
                    "message": "Extraction completed successfully!",
                    "details": event.details,
                    "ready_for_summarization": True
                }
            elif event_type == 'ExtractionJobFailed':
                return {
                    "status": "FAILED",
                    "message": "Extraction failed",
                    "details": event.details
                }
            else:  # Still running
                from datetime import datetime
                elapsed_min = (datetime.now() - event.timestamp).seconds // 60
                eta_min = max(1, 30 - elapsed_min)
                
                return {
                    "status": "RUNNING",
                    "message": f"Extraction in progress... ({elapsed_min} min elapsed, ETA: {eta_min} min)",
                    "ready_for_summarization": False
                }
        
        except Exception as e:
            self.logger.error(f"❌ Status check failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Could not check status: {str(e)}"
            }
    
    def _write_command_event(self, event_type: str, run_id: int, 
                             document_path: str, user_id: str, error: str = None):
        """
        Write command event to CQRS event store
        
        🔐 AUDIT TRAIL: Records which SP was used for this action
        """
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            details = {
                "document_path": document_path,
                "sp_used": "EXTRACTION_SP"
            }
            
            if error:
                details["error"] = error
            
            import json
            details_json = json.dumps(details)
            
            spark.sql(f"""
                INSERT INTO oncology_cqrs.job_events
                (event_id, event_type, run_id, agent, sp_used, triggered_by, 
                 timestamp, status, details)
                VALUES (
                    uuid(),
                    '{event_type}',
                    {run_id},
                    'extraction_agent',
                    'EXTRACTION_SP',
                    '{user_id}',
                    current_timestamp(),
                    'RUNNING',
                    '{details_json}'
                )
            """)
            
            self.logger.info(f"✅ Logged {event_type} event for run_id: {run_id}")
            
        except Exception as e:
            # Don't fail the main operation if logging fails
            self.logger.warning(f"⚠️  Could not write CQRS event: {e}")

