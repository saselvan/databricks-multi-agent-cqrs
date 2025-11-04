"""
Summarization Agent - Triggers Summarization Jobs

🔐 SECURITY:
- Uses SUMMARIZATION_SP credentials (manual OAuth)
- Only has permissions to:
  - Read from staging.extracted_documents
  - Write to staging.summaries
  - Run summarization job

🚫 CANNOT:
- Read source PDFs
- Write to SharePoint
- Run extraction job
"""

import os
import logging
from databricks.sdk import WorkspaceClient


class SummarizationAgent:
    """Agent responsible for triggering summarization jobs with dedicated SP"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # 🔐 MANUAL OAUTH - Dedicated Service Principal for summarization
        self.client_id = os.environ.get("SUMMARIZATION_SP_CLIENT_ID")
        self.client_secret = os.environ.get("SUMMARIZATION_SP_CLIENT_SECRET")
        self.workspace_url = os.environ.get("DATABRICKS_HOST")
        self.summarization_job_id = int(os.environ.get("SUMMARIZATION_JOB_ID", "0"))
        
        if not all([self.client_id, self.client_secret, self.workspace_url]):
            raise ValueError("Summarization SP credentials not configured")
        
        self.logger.info("✅ SummarizationAgent initialized with SUMMARIZATION_SP")
    
    def trigger_summarization(self, extraction_run_id: int, user_id: str) -> dict:
        """
        Trigger summarization job after extraction completes
        
        Args:
            extraction_run_id: Run ID of completed extraction job
            user_id: User who triggered the workflow
        
        Returns:
            dict with run_id and status message
        
        🔐 AUTHENTICATION: Uses SUMMARIZATION_SP (manual OAuth)
        """
        self.logger.info(f"🔐 Authenticating as SUMMARIZATION_SP for user: {user_id}")
        
        # Verify extraction completed successfully
        if not self._verify_extraction_completed(extraction_run_id):
            raise ValueError(f"Extraction run {extraction_run_id} not completed or failed")
        
        try:
            # 🔐 Create WorkspaceClient with SUMMARIZATION_SP credentials
            w = WorkspaceClient(
                host=self.workspace_url,
                client_id=self.client_id,
                client_secret=self.client_secret
            )
            
            self.logger.info(f"📝 Triggering summarization for extraction run: {extraction_run_id}")
            
            # Trigger summarization job (async)
            run = w.jobs.run_now(
                job_id=self.summarization_job_id,
                notebook_params={
                    "extraction_run_id": str(extraction_run_id),
                    "triggered_by": user_id
                }
            )
            
            run_id = run.run_id
            
            self.logger.info(f"✅ Summarization job started: Run ID {run_id}")
            
            # 🔐 Write command event to CQRS
            self._write_command_event(
                event_type="SummarizationJobStarted",
                run_id=run_id,
                extraction_run_id=extraction_run_id,
                user_id=user_id
            )
            
            return {
                "success": True,
                "run_id": run_id,
                "extraction_run_id": extraction_run_id,
                "message": f"Summarization started! Run ID: {run_id}",
                "eta_minutes": 10,
                "next_steps": "Summarization typically takes 10 minutes. I'll notify you when complete."
            }
            
        except Exception as e:
            self.logger.error(f"❌ Summarization trigger failed: {e}")
            
            self._write_command_event(
                event_type="SummarizationJobFailed",
                run_id=0,
                extraction_run_id=extraction_run_id,
                user_id=user_id,
                error=str(e)
            )
            
            raise Exception(f"Failed to trigger summarization: {str(e)}")
    
    def check_summarization_status(self, run_id: int) -> dict:
        """Check status of summarization job from CQRS event store"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            result = spark.sql(f"""
                SELECT event_type, status, details, timestamp
                FROM oncology_cqrs.job_events
                WHERE run_id = {run_id}
                  AND agent = 'summarization_agent'
                ORDER BY timestamp DESC
                LIMIT 1
            """).collect()
            
            if not result or len(result) == 0:
                return {
                    "status": "NOT_FOUND",
                    "message": f"No summarization job found with Run ID {run_id}"
                }
            
            event = result[0]
            event_type = event.event_type
            
            if event_type == 'SummarizationJobCompleted':
                return {
                    "status": "COMPLETED",
                    "message": "Summarization completed successfully!",
                    "details": event.details,
                    "ready_for_sharepoint": True
                }
            elif event_type == 'SummarizationJobFailed':
                return {
                    "status": "FAILED",
                    "message": "Summarization failed",
                    "details": event.details
                }
            else:
                from datetime import datetime
                elapsed_min = (datetime.now() - event.timestamp).seconds // 60
                eta_min = max(1, 10 - elapsed_min)
                
                return {
                    "status": "RUNNING",
                    "message": f"Summarization in progress... ({elapsed_min} min elapsed, ETA: {eta_min} min)",
                    "ready_for_sharepoint": False
                }
        
        except Exception as e:
            self.logger.error(f"❌ Status check failed: {e}")
            return {
                "status": "ERROR",
                "message": f"Could not check status: {str(e)}"
            }
    
    def _verify_extraction_completed(self, extraction_run_id: int) -> bool:
        """Verify extraction job completed successfully before triggering summarization"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            result = spark.sql(f"""
                SELECT event_type
                FROM oncology_cqrs.job_events
                WHERE run_id = {extraction_run_id}
                  AND agent = 'extraction_agent'
                ORDER BY timestamp DESC
                LIMIT 1
            """).collect()
            
            if result and len(result) > 0:
                return result[0].event_type == 'ExtractionJobCompleted'
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Could not verify extraction status: {e}")
            return False
    
    def _write_command_event(self, event_type: str, run_id: int, 
                             extraction_run_id: int, user_id: str, error: str = None):
        """Write command event to CQRS event store"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            details = {
                "extraction_run_id": extraction_run_id,
                "sp_used": "SUMMARIZATION_SP"
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
                    'summarization_agent',
                    'SUMMARIZATION_SP',
                    '{user_id}',
                    current_timestamp(),
                    'RUNNING',
                    '{details_json}'
                )
            """)
            
            self.logger.info(f"✅ Logged {event_type} event for run_id: {run_id}")
            
        except Exception as e:
            self.logger.warning(f"⚠️  Could not write CQRS event: {e}")

