"""
Coordinator Agent - Orchestrates Multi-Agent Oncology Workflow

🔐 SECURITY:
- Uses AUTOMATIC PASSTHROUGH for Vector Search (no credentials needed)
- Does NOT directly trigger jobs
- Delegates to specialist agents with dedicated SPs:
  - ExtractionAgent (uses EXTRACTION_SP)
  - SummarizationAgent (uses SUMMARIZATION_SP)
  - SharePointAgent (uses SHAREPOINT_SP)

🎯 RESPONSIBILITIES:
- Classify user intent
- Route to appropriate specialist agent
- Track overall workflow state in CQRS
- Provide status updates to users
"""

import os
import logging
from typing import Dict, List
import json


class CoordinatorAgent:
    """Main orchestrator that routes requests to specialist agents"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("✅ CoordinatorAgent initialized")
        
        # Will be injected by Agent Framework
        self.extraction_agent = None
        self.summarization_agent = None
        self.sharepoint_agent = None
    
    def set_specialist_agents(self, extraction_agent, summarization_agent, sharepoint_agent):
        """Inject specialist agents (dependency injection pattern)"""
        self.extraction_agent = extraction_agent
        self.summarization_agent = summarization_agent
        self.sharepoint_agent = sharepoint_agent
        
        self.logger.info("✅ Specialist agents injected into Coordinator")
    
    def handle_user_message(self, messages: List[Dict]) -> str:
        """
        Main entry point for user messages
        
        Args:
            messages: List of chat messages (Agent Framework format)
        
        Returns:
            Response string for user
        
        🔐 AUTHENTICATION NOTES:
        - Vector Search: Automatic passthrough (Agent Framework handles it)
        - Job triggers: Delegated to specialist agents with dedicated SPs
        """
        if not messages or len(messages) == 0:
            return "Please provide a message."
        
        user_message = messages[-1].get("content", "")
        user_id = self._get_user_id()
        
        self.logger.info(f"📨 Received message from {user_id}: {user_message[:100]}...")
        
        # Check if user has pending workflow
        pending_workflow = self._check_pending_workflow(user_id)
        
        if pending_workflow:
            # Auto-check status of pending workflow
            return self._handle_pending_workflow(pending_workflow, user_message, user_id)
        
        # No pending workflow - classify new intent
        intent = self._classify_intent(user_message)
        
        if intent == "extract_document":
            return self._handle_extraction_request(user_message, user_id)
        
        elif intent == "check_status":
            return self._handle_status_check(user_message, user_id)
        
        elif intent == "search_knowledge":
            return self._handle_knowledge_search(user_message, user_id)
        
        else:
            return self._handle_general_query(user_message, user_id)
    
    def _handle_extraction_request(self, user_message: str, user_id: str) -> str:
        """
        Delegate extraction request to ExtractionAgent
        
        🔐 SECURITY: ExtractionAgent uses EXTRACTION_SP
        """
        self.logger.info("🔀 Routing to ExtractionAgent")
        
        try:
            # Extract document path from message
            document_path = self._extract_document_path(user_message)
            
            if not document_path:
                return "Please specify a document path. Example: 'Extract /source_pdfs/patient_123.pdf'"
            
            # 🔀 DELEGATE to ExtractionAgent (uses EXTRACTION_SP)
            result = self.extraction_agent.trigger_extraction(
                document_path=document_path,
                user_id=user_id
            )
            
            # Store workflow state in CQRS
            self._store_workflow_state(
                user_id=user_id,
                document_path=document_path,
                extraction_run_id=result['run_id'],
                stage="extracting"
            )
            
            return f"""
📄 **Extraction Started!**

**Document:** {document_path}  
**Run ID:** {result['run_id']}  
**ETA:** {result['eta_minutes']} minutes

{result['next_steps']}

💡 **What happens next:**
1. PDF extraction (~30 min)
2. Automatic summarization (~10 min)
3. Upload to SharePoint
4. You'll be notified at each step

Feel free to ask other questions while I process this!
            """.strip()
            
        except Exception as e:
            self.logger.error(f"❌ Extraction request failed: {e}")
            return f"Failed to start extraction: {str(e)}"
    
    def _handle_pending_workflow(self, workflow_state: Dict, user_message: str, user_id: str) -> str:
        """
        Auto-check status of pending workflow and advance if complete
        
        🔐 SECURITY: Reads from CQRS Delta tables (no API calls)
        """
        stage = workflow_state['current_stage']
        extraction_run_id = workflow_state.get('extraction_run_id')
        summarization_run_id = workflow_state.get('summarization_run_id')
        
        self.logger.info(f"🔄 Checking pending workflow for {user_id}, stage: {stage}")
        
        if stage == "extracting":
            # Check extraction status
            status = self.extraction_agent.check_extraction_status(extraction_run_id)
            
            if status['status'] == 'COMPLETED':
                # Extraction done! Trigger summarization
                self.logger.info("✅ Extraction completed, triggering summarization")
                
                try:
                    # 🔀 DELEGATE to SummarizationAgent (uses SUMMARIZATION_SP)
                    result = self.summarization_agent.trigger_summarization(
                        extraction_run_id=extraction_run_id,
                        user_id=user_id
                    )
                    
                    # Update workflow state
                    self._update_workflow_stage(
                        user_id=user_id,
                        stage="summarizing",
                        summarization_run_id=result['run_id']
                    )
                    
                    return f"""
✅ **Extraction Complete!** {status['message']}

📝 **Summarization Started!**  
**Run ID:** {result['run_id']}  
**ETA:** {result['eta_minutes']} minutes

The document is now being summarized. I'll let you know when it's ready!
                    """.strip()
                    
                except Exception as e:
                    return f"Extraction completed, but summarization failed to start: {str(e)}"
            
            elif status['status'] == 'FAILED':
                self._clear_workflow_state(user_id)
                return f"❌ Extraction failed: {status['message']}"
            
            else:  # Still running
                return f"""
📄 **Extraction In Progress...**

{status['message']}

💡 Your document is being processed. I'll notify you when it's ready!  
In the meantime, feel free to ask other questions.
                """.strip()
        
        elif stage == "summarizing":
            # Check summarization status
            status = self.summarization_agent.check_summarization_status(summarization_run_id)
            
            if status['status'] == 'COMPLETED':
                # Summarization done! Upload to SharePoint
                self.logger.info("✅ Summarization completed, uploading to SharePoint")
                
                try:
                    # 🔀 DELEGATE to SharePointAgent (uses SHAREPOINT_SP)
                    result = self.sharepoint_agent.upload_to_sharepoint(
                        summarization_run_id=summarization_run_id,
                        user_id=user_id
                    )
                    
                    # Workflow complete!
                    self._update_workflow_stage(
                        user_id=user_id,
                        stage="completed"
                    )
                    
                    return f"""
🎉 **Workflow Complete!**

✅ Extraction: Done  
✅ Summarization: Done  
✅ SharePoint Upload: Done

📎 **Document URL:** {result['sharepoint_url']}

Your document has been processed and is now available in SharePoint!
                    """.strip()
                    
                except Exception as e:
                    return f"Summarization completed, but SharePoint upload failed: {str(e)}"
            
            elif status['status'] == 'FAILED':
                self._clear_workflow_state(user_id)
                return f"❌ Summarization failed: {status['message']}"
            
            else:  # Still running
                return f"""
📝 **Summarization In Progress...**

{status['message']}

The summary will be automatically uploaded to SharePoint when complete.
                """.strip()
        
        elif stage == "completed":
            self._clear_workflow_state(user_id)
            return "Your previous workflow is complete! How can I help you today?"
        
        return "Workflow in unknown state. Please contact support."
    
    def _handle_knowledge_search(self, user_message: str, user_id: str) -> str:
        """
        Search knowledge base using Vector Search
        
        🔐 AUTHENTICATION: AUTOMATIC PASSTHROUGH
        Agent Framework automatically grants Vector Search permissions
        """
        self.logger.info("🔍 Searching knowledge base with automatic passthrough")
        
        try:
            from databricks_langchain import VectorSearchRetrieverTool
            from databricks.sdk import WorkspaceClient
            
            # 🔐 AUTOMATIC PASSTHROUGH: WorkspaceClient() auto-discovers endpoint identity
            workspace_client = WorkspaceClient()
            
            retriever_tool = VectorSearchRetrieverTool(
                index_name="oncology_knowledge.medical_literature.documents_index",
                columns=["title", "content", "source"],
                workspace_client=workspace_client  # Bridge for automatic auth
            )
            
            results = retriever_tool.invoke(user_message)
            
            # Format results
            if results and len(results) > 0:
                formatted_results = "\n\n".join([
                    f"**{doc.metadata['title']}**\n{doc.page_content[:200]}...\nSource: {doc.metadata['source']}"
                    for doc in results[:3]
                ])
                
                return f"""
📚 **Knowledge Base Results:**

{formatted_results}

💡 This information is from our medical literature database.
                """.strip()
            else:
                return "No relevant information found in the knowledge base."
        
        except Exception as e:
            self.logger.error(f"❌ Knowledge search failed: {e}")
            return f"Knowledge search error: {str(e)}"
    
    def _classify_intent(self, user_message: str) -> str:
        """Classify user intent using simple keyword matching"""
        message_lower = user_message.lower()
        
        if any(word in message_lower for word in ["extract", "process", "parse", "/source_pdfs/"]):
            return "extract_document"
        
        elif any(word in message_lower for word in ["status", "progress", "check", "run id"]):
            return "check_status"
        
        elif any(word in message_lower for word in ["search", "find", "tell me about", "what is"]):
            return "search_knowledge"
        
        else:
            return "general"
    
    def _extract_document_path(self, user_message: str) -> str:
        """Extract document path from user message"""
        import re
        
        # Look for /source_pdfs/...pdf pattern
        match = re.search(r'/source_pdfs/[^\s]+\.pdf', user_message)
        if match:
            return match.group(0)
        
        return None
    
    def _check_pending_workflow(self, user_id: str) -> Dict:
        """Check if user has a pending workflow in CQRS"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            result = spark.sql(f"""
                SELECT 
                    document_path,
                    extraction_run_id,
                    summarization_run_id,
                    current_stage
                FROM oncology_cqrs.conversation_state
                WHERE user_id = '{user_id}'
                  AND status = 'in_progress'
                  AND triggered_at > current_timestamp() - INTERVAL 2 HOURS
                ORDER BY triggered_at DESC
                LIMIT 1
            """).collect()
            
            if result and len(result) > 0:
                row = result[0]
                return {
                    'document_path': row.document_path,
                    'extraction_run_id': row.extraction_run_id,
                    'summarization_run_id': row.summarization_run_id,
                    'current_stage': row.current_stage
                }
            
            return None
            
        except Exception as e:
            self.logger.warning(f"⚠️  Could not check workflow state: {e}")
            return None
    
    def _store_workflow_state(self, user_id: str, document_path: str, 
                              extraction_run_id: int, stage: str):
        """Store workflow state in CQRS"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            spark.sql(f"""
                INSERT INTO oncology_cqrs.conversation_state
                (state_id, user_id, document_path, extraction_run_id, 
                 current_stage, triggered_at, status)
                VALUES (
                    uuid(),
                    '{user_id}',
                    '{document_path}',
                    {extraction_run_id},
                    '{stage}',
                    current_timestamp(),
                    'in_progress'
                )
            """)
            
            self.logger.info(f"✅ Stored workflow state for {user_id}")
            
        except Exception as e:
            self.logger.warning(f"⚠️  Could not store workflow state: {e}")
    
    def _update_workflow_stage(self, user_id: str, stage: str, summarization_run_id: int = None):
        """Update workflow stage in CQRS"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            if summarization_run_id:
                spark.sql(f"""
                    UPDATE oncology_cqrs.conversation_state
                    SET current_stage = '{stage}',
                        summarization_run_id = {summarization_run_id}
                    WHERE user_id = '{user_id}' AND status = 'in_progress'
                """)
            else:
                spark.sql(f"""
                    UPDATE oncology_cqrs.conversation_state
                    SET current_stage = '{stage}'
                    WHERE user_id = '{user_id}' AND status = 'in_progress'
                """)
            
            self.logger.info(f"✅ Updated workflow stage to: {stage}")
            
        except Exception as e:
            self.logger.warning(f"⚠️  Could not update workflow stage: {e}")
    
    def _clear_workflow_state(self, user_id: str):
        """Clear workflow state when complete or failed"""
        from pyspark.sql import SparkSession
        
        try:
            spark = SparkSession.builder.getOrCreate()
            
            spark.sql(f"""
                UPDATE oncology_cqrs.conversation_state
                SET status = 'completed'
                WHERE user_id = '{user_id}' AND status = 'in_progress'
            """)
            
            self.logger.info(f"✅ Cleared workflow state for {user_id}")
            
        except Exception as e:
            self.logger.warning(f"⚠️  Could not clear workflow state: {e}")
    
    def _handle_status_check(self, user_message: str, user_id: str) -> str:
        """Handle explicit status check requests"""
        # Check for pending workflow
        workflow_state = self._check_pending_workflow(user_id)
        
        if not workflow_state:
            return "You don't have any workflows in progress."
        
        return self._handle_pending_workflow(workflow_state, user_message, user_id)
    
    def _handle_general_query(self, user_message: str, user_id: str) -> str:
        """Handle general queries"""
        return """
I'm the Oncology Document Processing Assistant. I can help you:

📄 **Extract documents:** "Extract /source_pdfs/patient_123.pdf"  
📝 **Check status:** "What's the status of my workflow?"  
📚 **Search knowledge:** "Tell me about treatment protocols"

What would you like to do?
        """.strip()
    
    def _get_user_id(self) -> str:
        """Get user ID from context"""
        # In production, this would come from authentication context
        # For demo, use a placeholder
        return "current_user"

