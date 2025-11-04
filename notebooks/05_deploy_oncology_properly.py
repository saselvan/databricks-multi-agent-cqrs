# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Oncology Multi-Agent System
# MAGIC 
# MAGIC ## Architecture
# MAGIC - **ExtractionAgent**: Uses EXTRACTION_SP (manual OAuth for Jobs API)
# MAGIC - **SummarizationAgent**: Uses SUMMARIZATION_SP (manual OAuth for Jobs API)  
# MAGIC - **FileStorageAgent**: Uses automatic passthrough (UC Volumes)
# MAGIC - **CoordinatorAgent**: Orchestrates the workflow
# MAGIC 
# MAGIC ## Authentication Patterns Demonstrated
# MAGIC 1. **Manual OAuth**: Dedicated SPs for Jobs API (solves Banner's session expiration issue)
# MAGIC 2. **Automatic Passthrough**: UC Volumes (zero credential management)

# COMMAND ----------

# Install the oncology-agents package from wheel (stored in Workspace Files - universally accessible)
# Note: databricks-sdk is already available on Databricks clusters, no need to install it
%pip install /Workspace/Users/samuel.selvan@databricks.com/wheels/oncology_agents-0.1.0-py3-none-any.whl databricks-agents mlflow>=2.9.0 --quiet
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

# MAGIC %md
# MAGIC ## Define MLflow PyFunc Model

# COMMAND ----------

import mlflow
import logging

class OncologyCoordinatorModel(mlflow.pyfunc.PythonModel):
    """
    Multi-Agent Coordinator for Oncology Document Processing
    
    Demonstrates:
    - Manual OAuth for Jobs API (EXTRACTION_SP, SUMMARIZATION_SP)
    - Automatic Passthrough for UC Volumes (FileStorageAgent)
    """
    
    def load_context(self, context):
        """Initialize agents when endpoint starts"""
        # Import from installed package
        from oncology_agents import ExtractionAgent, SummarizationAgent, FileStorageAgent, CoordinatorAgent
        
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
        
        self.logger.info("✅ Oncology multi-agent system initialized")
    
    def predict(self, context, model_input):
        """Handle user messages"""
        try:
            # Extract messages from Agent Framework format
            messages = model_input.get('messages', [])
            
            if not messages:
                response_text = "Please provide a message."
            else:
                # Delegate to coordinator
                response_text = self.coordinator.handle_message(messages)
            
            # Return in OpenAI format (required by Agent Framework)
            return {
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text
                    },
                    "finish_reason": "stop"
                }],
                "id": f"oncology-{hash(str(messages))}"
            }
            
        except Exception as e:
            self.logger.error(f"Error: {e}")
            return {
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"Error: {str(e)}"
                    },
                    "finish_reason": "stop"
                }],
                "id": "error"
            }

print("✅ Model class defined")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log Model to MLflow

# COMMAND ----------

from mlflow.models import infer_signature

# Define signature
example_input = {
    "messages": [
        {"role": "user", "content": "Extract /source_pdfs/patient_123.pdf"}
    ]
}

example_output = {
    "choices": [{
        "index": 0,
        "message": {
            "role": "assistant",
            "content": "Extraction started!"
        },
        "finish_reason": "stop"
    }],
    "id": "example"
}

signature = infer_signature(example_input, example_output)

# Log the model
with mlflow.start_run():
    model_info = mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=OncologyCoordinatorModel(),
        signature=signature,
        pip_requirements=[
            "/Workspace/Users/samuel.selvan@databricks.com/wheels/oncology_agents-0.1.0-py3-none-any.whl",
            "databricks-agents",
            "mlflow>=2.9.0"
        ]
    )

model_version = mlflow.register_model(
    model_uri=model_info.model_uri,
    name=MODEL_NAME
)

print(f"✅ Model registered: {MODEL_NAME} version {model_version.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Resolve SP Credentials from Secrets

# COMMAND ----------

# Get SP credentials from Databricks Secrets (deploy-time resolution)
extraction_sp_client_id = dbutils.secrets.get("oncology_agents", "extraction_sp_client_id")
extraction_sp_secret = dbutils.secrets.get("oncology_agents", "extraction_sp_secret")
summarization_sp_client_id = dbutils.secrets.get("oncology_agents", "summarization_sp_client_id")
summarization_sp_secret = dbutils.secrets.get("oncology_agents", "summarization_sp_secret")

workspace_url = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()

print("✅ SP credentials resolved from secrets")
print(f"✅ Workspace URL: {workspace_url}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy with Agent Framework

# COMMAND ----------

from databricks import agents

print(f"🚀 Deploying {MODEL_NAME} version {model_version.version}...")

deployment_info = agents.deploy(
    model_name=MODEL_NAME,
    model_version=model_version.version,
    environment_vars={
        # Manual OAuth for Jobs API
        "EXTRACTION_SP_CLIENT_ID": extraction_sp_client_id,
        "EXTRACTION_SP_CLIENT_SECRET": extraction_sp_secret,
        "SUMMARIZATION_SP_CLIENT_ID": summarization_sp_client_id,
        "SUMMARIZATION_SP_CLIENT_SECRET": summarization_sp_secret,
        
        # Configuration
        "DATABRICKS_HOST": workspace_url,
        "EXTRACTION_JOB_ID": extraction_job_id,
        "SUMMARIZATION_JOB_ID": summarization_job_id,
        "UC_VOLUME_PATH": UC_VOLUME_PATH
    },
    scale_to_zero=True
)

print("="*80)
print("✅ DEPLOYMENT COMPLETE!")
print("="*80)
print(f"Model: {MODEL_NAME} v{model_version.version}")
print(f"Endpoint: {deployment_info.endpoint_name}")
print(f"\n🔐 Authentication:")
print(f"  • ExtractionAgent → EXTRACTION_SP (manual OAuth)")
print(f"  • SummarizationAgent → SUMMARIZATION_SP (manual OAuth)")
print(f"  • FileStorageAgent → Automatic passthrough (UC Volumes)")
print(f"\n⏳ Wait 3-5 minutes for endpoint to be ready")
print("="*80)

# COMMAND ----------

# Return deployment info
import json
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "model_name": MODEL_NAME,
    "model_version": model_version.version,
    "endpoint_name": deployment_info.endpoint_name
}))

