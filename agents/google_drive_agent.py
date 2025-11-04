"""
Google Drive Agent for Oncology Document Upload
Replaces SharePoint Agent for Demo (Databricks uses Google Workspace)

Authentication: OAuth 2.0 with user credentials
Uploads summaries to specified Google Drive folder
"""

import os
import logging
from typing import Dict, Any
from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)


class GoogleDriveAgent:
    """
    Specialist agent for uploading oncology summaries to Google Drive.
    
    Authentication:
    - Uses OAuth 2.0 credentials stored in Databricks Secrets
    - No dedicated SP needed (uses user's Google account)
    
    Permissions Required:
    - Google Drive API enabled
    - OAuth consent screen configured
    - credentials.json downloaded and stored in secrets
    
    Architecture Note:
    - This is the ONLY agent that writes to external systems (Google Drive)
    - Extraction/Summarization agents stay within Databricks
    - Demonstrates least-privilege: Even if this agent is compromised,
      attacker only gets Google Drive write access (no Databricks data access)
    """
    
    def __init__(self):
        """
        Initialize Google Drive agent with OAuth credentials.
        
        Environment Variables (injected at deployment):
        - GOOGLE_DRIVE_FOLDER_ID: Target folder for uploads
        - GOOGLE_OAUTH_TOKEN: Refresh token for OAuth (from Databricks Secrets)
        - GOOGLE_CLIENT_ID: OAuth client ID
        - GOOGLE_CLIENT_SECRET: OAuth client secret
        """
        self.folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        
        # OAuth credentials from Databricks Secrets
        # These are USER credentials, not a service account
        # User must have already authorized the app
        self.oauth_token = os.environ.get("GOOGLE_OAUTH_TOKEN")
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
        
        if not all([self.folder_id, self.oauth_token, self.client_id, self.client_secret]):
            logger.warning("Google Drive credentials not fully configured - uploads will be simulated")
            self.credentials_available = False
        else:
            self.credentials_available = True
        
        logger.info(f"GoogleDriveAgent initialized (credentials_available={self.credentials_available})")
    
    def upload_summary(
        self,
        summary: str,
        patient_id: str,
        extraction_run_id: str,
        summarization_run_id: str
    ) -> Dict[str, Any]:
        """
        Upload oncology summary to Google Drive.
        
        Args:
            summary: The generated summary text
            patient_id: Patient identifier (for filename)
            extraction_run_id: Extraction job run ID (for audit trail)
            summarization_run_id: Summarization job run ID (for audit trail)
        
        Returns:
            Dict with upload status and file metadata
        
        Architecture:
        - Uses Google Drive API v3
        - Uploads as plain text file
        - Stores in pre-configured folder
        - Returns file ID for tracking
        """
        filename = f"oncology_summary_{patient_id}.txt"
        
        if not self.credentials_available:
            # Simulate upload for demo when credentials not configured
            logger.info(f"Simulating Google Drive upload: {filename}")
            return {
                "status": "simulated",
                "message": f"Would upload {filename} to Google Drive folder {self.folder_id}",
                "file_id": f"simulated-{patient_id}",
                "file_name": filename,
                "folder_id": self.folder_id,
                "extraction_run_id": extraction_run_id,
                "summarization_run_id": summarization_run_id
            }
        
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaInMemoryUpload
            
            # Create credentials from refresh token
            # OAuth flow must be completed once to get refresh token
            credentials = Credentials(
                token=None,  # Access token (will be refreshed)
                refresh_token=self.oauth_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=['https://www.googleapis.com/auth/drive.file']
            )
            
            # Build Drive API client
            service = build('drive', 'v3', credentials=credentials)
            
            # Prepare file metadata
            file_metadata = {
                'name': filename,
                'parents': [self.folder_id],
                'description': f'Oncology summary for patient {patient_id}. '
                              f'Generated from extraction run {extraction_run_id} '
                              f'and summarization run {summarization_run_id}.'
            }
            
            # Upload file
            media = MediaInMemoryUpload(
                summary.encode('utf-8'),
                mimetype='text/plain',
                resumable=True
            )
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, webViewLink, createdTime'
            ).execute()
            
            logger.info(f"✅ Uploaded to Google Drive: {file['name']} (ID: {file['id']})")
            
            return {
                "status": "success",
                "message": f"Uploaded {filename} to Google Drive",
                "file_id": file['id'],
                "file_name": file['name'],
                "web_view_link": file['webViewLink'],
                "created_time": file['createdTime'],
                "folder_id": self.folder_id,
                "extraction_run_id": extraction_run_id,
                "summarization_run_id": summarization_run_id
            }
            
        except Exception as e:
            logger.error(f"❌ Google Drive upload failed: {e}")
            return {
                "status": "failed",
                "message": f"Upload failed: {str(e)}",
                "file_name": filename,
                "error": str(e),
                "extraction_run_id": extraction_run_id,
                "summarization_run_id": summarization_run_id
            }
    
    def check_access(self) -> Dict[str, Any]:
        """
        Check if Google Drive is accessible with current credentials.
        
        Returns:
            Dict with access status and folder information
        """
        if not self.credentials_available:
            return {
                "status": "not_configured",
                "message": "Google Drive credentials not configured",
                "folder_id": self.folder_id
            }
        
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            credentials = Credentials(
                token=None,
                refresh_token=self.oauth_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self.client_id,
                client_secret=self.client_secret,
                scopes=['https://www.googleapis.com/auth/drive.file']
            )
            
            service = build('drive', 'v3', credentials=credentials)
            
            # Try to get folder metadata
            folder = service.files().get(
                fileId=self.folder_id,
                fields='id, name, capabilities'
            ).execute()
            
            return {
                "status": "success",
                "message": "Google Drive access verified",
                "folder_id": folder['id'],
                "folder_name": folder['name'],
                "can_upload": folder['capabilities']['canAddChildren']
            }
            
        except Exception as e:
            logger.error(f"❌ Google Drive access check failed: {e}")
            return {
                "status": "failed",
                "message": f"Access check failed: {str(e)}",
                "error": str(e)
            }


# Tool interface for LangChain/Agent Framework
def upload_to_google_drive(
    summary: str,
    patient_id: str,
    extraction_run_id: str,
    summarization_run_id: str
) -> str:
    """
    LangChain tool wrapper for Google Drive upload.
    
    Args:
        summary: The summary text to upload
        patient_id: Patient identifier
        extraction_run_id: Extraction job run ID
        summarization_run_id: Summarization job run ID
    
    Returns:
        Human-readable status message
    """
    agent = GoogleDriveAgent()
    result = agent.upload_summary(summary, patient_id, extraction_run_id, summarization_run_id)
    
    if result["status"] == "success":
        return f"✅ Summary uploaded to Google Drive!\n\nFile: {result['file_name']}\nLink: {result['web_view_link']}"
    elif result["status"] == "simulated":
        return f"🔄 Simulated upload (credentials not configured)\n\n{result['message']}"
    else:
        return f"❌ Upload failed: {result['message']}"

