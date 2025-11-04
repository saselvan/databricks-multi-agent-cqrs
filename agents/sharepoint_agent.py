"""
SharePoint Agent - Writes Documents to SharePoint

🔐 SECURITY:
- Uses SHAREPOINT_SP credentials (manual OAuth)
- Only has permissions to:
  - Read from staging.summaries
  - Write to SharePoint API

🚫 CANNOT:
- Read source PDFs
- Read extracted documents
- Run any Databricks jobs
"""

import os
import logging
from typing import Dict


class SharePointAgent:
    """Agent responsible for writing finalized documents to SharePoint with dedicated SP"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # 🔐 MANUAL OAUTH - Dedicated Service Principal for SharePoint
        self.client_id = os.environ.get("SHAREPOINT_SP_CLIENT_ID")
        self.client_secret = os.environ.get("SHAREPOINT_SP_CLIENT_SECRET")
        self.sharepoint_site_url = os.environ.get("SHAREPOINT_SITE_URL")
        
        if not all([self.client_id, self.client_secret, self.sharepoint_site_url]):
            raise ValueError("SharePoint SP credentials not configured")
        
        self.logger.info("✅ SharePointAgent initialized with SHAREPOINT_SP")
    
    def upload_to_sharepoint(self, summarization_run_id: int, user_id: str) -> Dict:
        """
        Upload finalized summary to SharePoint
        
        Args:
            summarization_run_id: Run ID of completed summarization job
            user_id: User who triggered the workflow
        
        Returns:
            dict with SharePoint document URL and status
        
        🔐 AUTHENTICATION: Uses SHAREPOINT_SP (manual OAuth)
        """
        self.logger.info(f"🔐 Authenticating as SHAREPOINT_SP for user: {user_id}")
        
        # Verify summarization completed successfully
        if not self._verify_summarization_completed(summarization_run_id):
            raise ValueError(f"Summarization run {summarization_run_id} not completed or failed")
        
        try:
            # Get summary content from staging table
            summary_content = self._get_summary_content(summarization_run_id)
            
            if not summary_content:
                raise ValueError(f"No summary found for run {summarization_run_id}")
            
            # 🔐 Upload to SharePoint using SHAREPOINT_SP credentials
            sharepoint_url = self._upload_to_sharepoint_api(
                summary_content=summary_content,
                run_id=summarization_run_id
            )
            
            self.logger.info(f"✅ Uploaded to SharePoint: {sharepoint_url}")
            
            # 🔐 Write completion event to CQRS
            self._write_command_event(
                event_type="SharePointUploadCompleted",
                summarization_run_id=summarization_run_id,
                user_id=user_id,
                sharepoint_url=sharepoint_url
            )
            
            return {
                "success": True,
                "sharepoint_url": sharepoint_url,
                "message": f"Document successfully uploaded to SharePoint!",
                "url": sharepoint_url
            }
            
        except Exception as e:
            self.logger.error(f"❌ SharePoint upload failed: {e}")
            
            self._write_command_event(
                event_type="SharePointUploadFailed",
                summarization_run_id=summarization_run_id,
                user_id=user_id,
                error=str(e)
            )
            
            raise Exception(f"Failed to upload to SharePoint: {str(e)}")
    
    def _get_summary_content(self, summarization_run_id: int) -> str:
        """
        Retrieve summary content from staging table
        
        🔐 SECURITY: Can only read from staging.summaries (not source PDFs or extracted docs)
        """
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            result = spark.sql(f"""
                SELECT summary_text, document_metadata
                FROM staging.summaries
                WHERE summarization_run_id = {summarization_run_id}
                ORDER BY created_at DESC
                LIMIT 1
            """).collect()
            
            if result and len(result) > 0:
                return result[0].summary_text
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Could not retrieve summary: {e}")
            return None
    
    def _upload_to_sharepoint_api(self, summary_content: str, run_id: int) -> str:
        """
        Upload document to SharePoint using Microsoft Graph API
        
        🔐 AUTHENTICATION: Uses SHAREPOINT_SP credentials (OAuth with Microsoft)
        """
        # In production, this would use Microsoft Graph API
        # For demo purposes, we'll simulate the upload
        
        import requests
        import json
        
        self.logger.info("📤 Uploading to SharePoint API...")
        
        # Simulate SharePoint upload
        # In production, you would:
        # 1. Get OAuth token from Microsoft using SHAREPOINT_SP credentials
        # 2. Call Microsoft Graph API to upload document
        # 3. Return SharePoint document URL
        
        # Example production code (commented out for demo):
        """
        # Get OAuth token
        token_response = requests.post(
            f"https://login.microsoftonline.com/<tenant_id>/oauth2/v2.0/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials"
            }
        )
        access_token = token_response.json()["access_token"]
        
        # Upload document
        upload_response = requests.put(
            f"{self.sharepoint_site_url}/_api/web/GetFolderByServerRelativeUrl('Documents')/Files/add(url='summary_{run_id}.pdf',overwrite=true)",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/pdf"
            },
            data=summary_content.encode('utf-8')
        )
        
        sharepoint_url = upload_response.json()["ServerRelativeUrl"]
        """
        
        # Simulated URL for demo
        sharepoint_url = f"{self.sharepoint_site_url}/Documents/summary_{run_id}.pdf"
        
        self.logger.info(f"✅ Simulated upload to: {sharepoint_url}")
        
        return sharepoint_url
    
    def _verify_summarization_completed(self, summarization_run_id: int) -> bool:
        """Verify summarization job completed successfully"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            result = spark.sql(f"""
                SELECT event_type
                FROM oncology_cqrs.job_events
                WHERE run_id = {summarization_run_id}
                  AND agent = 'summarization_agent'
                ORDER BY timestamp DESC
                LIMIT 1
            """).collect()
            
            if result and len(result) > 0:
                return result[0].event_type == 'SummarizationJobCompleted'
            
            return False
            
        except Exception as e:
            self.logger.error(f"❌ Could not verify summarization status: {e}")
            return False
    
    def _write_command_event(self, event_type: str, summarization_run_id: int, 
                             user_id: str, sharepoint_url: str = None, error: str = None):
        """Write command event to CQRS event store"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            details = {
                "summarization_run_id": summarization_run_id,
                "sp_used": "SHAREPOINT_SP"
            }
            
            if sharepoint_url:
                details["sharepoint_url"] = sharepoint_url
            
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
                    0,
                    'sharepoint_agent',
                    'SHAREPOINT_SP',
                    '{user_id}',
                    current_timestamp(),
                    '{"COMPLETED" if sharepoint_url else "FAILED"}',
                    '{details_json}'
                )
            """)
            
            self.logger.info(f"✅ Logged {event_type} event")
            
        except Exception as e:
            self.logger.warning(f"⚠️  Could not write CQRS event: {e}")

