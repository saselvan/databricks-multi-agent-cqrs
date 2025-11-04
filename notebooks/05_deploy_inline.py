# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Oncology Multi-Agent System (Inline Version)
# MAGIC 
# MAGIC All agent code is inlined in this notebook to avoid wheel installation issues.
# MAGIC 
# MAGIC ## Authentication Patterns Demonstrated
# MAGIC 1. **Manual OAuth**: Dedicated SPs for Jobs API (solves Banner's session expiration issue)
# MAGIC 2. **Automatic Passthrough**: UC Volumes (zero credential management)

# COMMAND ----------

# Install only databricks-agents and mlflow
%pip install databricks-agents mlflow>=2.9.0 --quiet
dbutils.library.restartPython()

# COMMAND ----------

# Configuration
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")
dbutils.widgets.text("extraction_job_id", "256785017981854", "Extraction Job ID")
dbutils.widgets.text("summarization_job_id", "319195034335878", "Summarization Job ID")

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")
extraction_job_id = dbutils.widgets.get("extraction_job_id")
summarization_job_id = dbutils.widgets.get("summarization_job_id")

MODEL_NAME = f"{catalog_name}.{schema_name}.oncology_coordinator"
UC_VOLUME_PATH = f"/Volumes/{catalog_name}/{schema_name}/summaries"

print(f"Model: {MODEL_NAME}")
print(f"Extraction Job: {extraction_job_id}")
print(f"Summarization Job: {summarization_job_id}")
print(f"UC Volume: {UC_VOLUME_PATH}")

# COMMAND ----------

import mlflow
import logging
import os
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs

# COMMAND ----------

# MAGIC %md
# MAGIC ## Inline Agent Definitions

# COMMAND ----------

class ExtractionAgent:
    """Triggers PDF extraction jobs using EXTRACTION_SP"""
    def __init__(self):
        self.client_id = os.environ.get("EXTRACTION_SP_CLIENT_ID")
        self.client_secret = os.environ.get("EXTRACTION_SP_CLIENT_SECRET")
        self.host = os.environ.get("DATABRICKS_HOST")
    
    def trigger_extraction(self, document_path, job_id):
        """Trigger extraction job with manual OAuth"""
        w = WorkspaceClient(
            host=self.host,
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        run = w.jobs.run_now(
            job_id=int(job_id),
            notebook_params={"document_path": document_path}
        )
        return run.run_id

class SummarizationAgent:
    """Triggers summarization jobs using SUMMARIZATION_SP"""
    def __init__(self):
        self.client_id = os.environ.get("SUMMARIZATION_SP_CLIENT_ID")
        self.client_secret = os.environ.get("SUMMARIZATION_SP_CLIENT_SECRET")
        self.host = os.environ.get("DATABRICKS_HOST")
    
    def trigger_summarization(self, extraction_run_id, job_id):
        """Trigger summarization job with manual OAuth"""
        w = WorkspaceClient(
            host=self.host,
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        run = w.jobs.run_now(
            job_id=int(job_id),
            notebook_params={"extraction_run_id": str(extraction_run_id)}
        )
        return run.run_id

class FileStorageAgent:
    """Stores summaries to UC Volumes using automatic passthrough"""
    def __init__(self):
        self.uc_volume_path = os.environ.get("UC_VOLUME_PATH")
    
    def store_summary(self, summary_id, content):
        """Store to UC Volume (automatic passthrough - no credentials needed)"""
        import datetime
        
        output_path = f"{self.uc_volume_path}/{summary_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        try:
            with open(output_path, "w") as f:
                f.write(content)
            return output_path
        except Exception as e:
            # Fallback to /tmp if UC Volume not accessible
            fallback_path = f"/tmp/{summary_id}.txt"
            with open(fallback_path, "w") as f:
                f.write(content)
            return f"⚠️  Stored to {fallback_path} (UC Volume not accessible)"

class CoordinatorAgent:
    """Orchestrates the multi-agent workflow"""
    def __init__(self):
        self.extraction_agent = None
        self.summarization_agent = None
        self.file_storage_agent = None
        self.extraction_job_id = os.environ.get("EXTRACTION_JOB_ID")
        self.summarization_job_id = os.environ.get("SUMMARIZATION_JOB_ID")
    
    def set_specialist_agents(self, extraction, summarization, file_storage):
        self.extraction_agent = extraction
        self.summarization_agent = summarization
        self.file_storage_agent = file_storage
    
    def handle_user_message(self, messages):
        """Process user request and orchestrate workflow"""
        user_message = messages[-1].get("content", "") if messages else ""
        
        if "extract" in user_message.lower():
            # Extract document path from message
            words = user_message.split()
            doc_path = next((w for w in words if "/Volumes/" in w), None)
            
            if doc_path:
                try:
                    run_id = self.extraction_agent.trigger_extraction(doc_path, self.extraction_job_id)
                    return f"✅ Extraction started for {doc_path}\\n🔗 Run ID: {run_id}\\n\\nThis uses EXTRACTION_SP (manual OAuth) to trigger the job."
                except Exception as e:
                    return f"❌ Extraction failed: {str(e)}"
            else:
                return "Please provide a document path like: Extract /Volumes/catalog/schema/volume/file.pdf"
        
        return "I can help you extract oncology documents. Say 'Extract /Volumes/.../file.pdf' to start."

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define MLflow PyFunc Model

# COMMAND ----------

class OncologyCoordinatorModel(mlflow.pyfunc.PythonModel):
    """
    Multi-Agent Coordinator for Oncology Document Processing
    
    Demonstrates:
    - Manual OAuth for Jobs API (EXTRACTION_SP, SUMMARIZATION_SP)
    - Automatic Passthrough for UC Volumes (FileStorageAgent)
    """
    
    def load_context(self, context):
        """Initialize agents when endpoint starts"""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # Initialize specialist agents (each uses its own SP)
        self.extraction_agent = ExtractionAgent()
        self.summarization_agent = SummarizationAgent()
        self.file_storage_agent = FileStorageAgent()
        
        # Initialize coordinator
        self.coordinator = CoordinatorAgent()
        self.coordinator.set_specialist_agents(
            self.extraction_agent,
            self.summarization_agent,
            self.file_storage_agent
        )
        
        self.logger.info("✅ Oncology Coordinator initialized")
    
    def predict(self, context, model_input):
        """Handle user messages"""
        import pandas as pd
        
        # Extract messages from Agent Framework's chat format
        if isinstance(model_input, pd.DataFrame):
            messages = model_input.iloc[0]['messages']
        elif isinstance(model_input, dict):
            messages = model_input.get('messages', [])
        else:
            messages = []
        
        if not messages:
            return self._chat_response("I didn't receive a message.")
        
        # Delegate to coordinator
        response_content = self.coordinator.handle_user_message(messages)
        
        # Return in OpenAI format (required by Agent Framework)
        return {
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_content
                },
                "finish_reason": "stop"
            }],
            "id": f"oncology-{hash(str(messages))}"
        }
    
    def _chat_response(self, content):
        """Helper to format response"""
        return {
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }],
            "id": "response"
        }

print("✅ Created OncologyCoordinatorModel class")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log Model to MLflow

# COMMAND ----------

from mlflow.models import infer_signature

# Define input/output examples for signature
example_input = {
    "messages": [{
        "role": "user",
        "content": f"Extract /Volumes/{catalog_name}/{schema_name}/source_pdfs/patient_record_1.pdf"
    }]
}

example_output = {
    "choices": [{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": "✅ Extraction started..."
        },
        "finish_reason": "stop"
    }],
    "id": "example"
}

# Infer signature
signature = infer_signature(example_input, example_output)

# Log the model
with mlflow.start_run():
    model_info = mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=OncologyCoordinatorModel(),
        signature=signature,
        pip_requirements=[
            "databricks-agents",
            "databricks-sdk>=0.12.0",
            "mlflow>=2.9.0"
        ]
    )

model_version = mlflow.register_model(
    model_uri=model_info.model_uri,
    name=MODEL_NAME
)

print(f"✅ Model '{MODEL_NAME}' version {model_version.version} registered.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy Agent to Serving Endpoint

# COMMAND ----------

from databricks import agents

w = WorkspaceClient()
workspace_url = w.config.host

print(f"\n🚀 Deploying multi-agent coordinator...")
print(f"   Model: {MODEL_NAME}")
print(f"   Version: {model_version.version}")

# Deploy with SP credentials injected as environment variables
deployment_info = agents.deploy(
    model_name=MODEL_NAME,
    model_version=model_version.version,
    environment_vars={
        # EXTRACTION_SP credentials (manual OAuth for Jobs API)
        "EXTRACTION_SP_CLIENT_ID": dbutils.secrets.get("oncology_agents", "extraction_sp_client_id"),
        "EXTRACTION_SP_CLIENT_SECRET": dbutils.secrets.get("oncology_agents", "extraction_sp_secret"),
        
        # SUMMARIZATION_SP credentials (manual OAuth for Jobs API)
        "SUMMARIZATION_SP_CLIENT_ID": dbutils.secrets.get("oncology_agents", "summarization_sp_client_id"),
        "SUMMARIZATION_SP_CLIENT_SECRET": dbutils.secrets.get("oncology_agents", "summarization_sp_secret"),
        
        # Workspace URL (auto-detected)
        "DATABRICKS_HOST": workspace_url,
        
        # Job IDs
        "EXTRACTION_JOB_ID": extraction_job_id,
        "SUMMARIZATION_JOB_ID": summarization_job_id,
        
        # UC Volume path for file storage
        "UC_VOLUME_PATH": UC_VOLUME_PATH,
        
        # Catalog and Schema for CQRS tables
        "CATALOG_NAME": catalog_name,
        "SCHEMA_NAME": schema_name
    },
    scale_to_zero=True
)

print("\n" + "="*80)
print("✅ DEPLOYMENT COMPLETE!")
print("="*80)
print(f"\n📊 Model: {MODEL_NAME}")
print(f"📊 Version: {model_version.version}")
print(f"📊 Endpoint: {deployment_info.endpoint_name}")
print(f"\n🔗 View Endpoint:")
print(f"   {workspace_url}/ml/endpoints/{deployment_info.endpoint_name}")
print(f"\n🔐 Security Configuration:")
print(f"   ✅ ExtractionAgent → EXTRACTION_SP (manual OAuth)")
print(f"   ✅ SummarizationAgent → SUMMARIZATION_SP (manual OAuth)")
print(f"   ✅ FileStorageAgent → Automatic passthrough (UC Volumes)")
print(f"\n🧪 Test Command:")
print(f'   "Extract /Volumes/{catalog_name}/{schema_name}/source_pdfs/patient_record_1.pdf"')
print("="*80)

# COMMAND ----------

# Return deployment info
import json

dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "model_name": MODEL_NAME,
    "model_version": model_version.version,
    "endpoint_name": deployment_info.endpoint_name,
    "extraction_job_id": extraction_job_id,
    "summarization_job_id": summarization_job_id
}))

