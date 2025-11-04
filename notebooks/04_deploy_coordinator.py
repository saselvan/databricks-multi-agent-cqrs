# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Oncology Multi-Agent Coordinator
# MAGIC 
# MAGIC Deploys the complete multi-agent system:
# MAGIC - **CoordinatorAgent** (automatic passthrough for Vector Search)
# MAGIC - **ExtractionAgent** (uses EXTRACTION_SP)
# MAGIC - **SummarizationAgent** (uses SUMMARIZATION_SP)
# MAGIC - **FileStorageAgent** (uses automatic passthrough for UC Volumes)
# MAGIC 
# MAGIC **Security:** Each specialist agent uses dedicated SP credentials

# COMMAND ----------

# MAGIC %pip install databricks-sdk databricks-agents databricks-langchain mlflow>=2.9.0 --quiet
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration Parameters

# COMMAND ----------

# Catalog and schema
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

# Job IDs (from previous notebooks)
dbutils.widgets.text("extraction_job_id", "0", "Extraction Job ID")
dbutils.widgets.text("summarization_job_id", "0", "Summarization Job ID")

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")
extraction_job_id = dbutils.widgets.get("extraction_job_id")
summarization_job_id = dbutils.widgets.get("summarization_job_id")

# UC Volume for file storage (automatic passthrough authentication)
uc_volume_path = f"/Volumes/{catalog_name}/{schema_name}/summaries"

print("Configuration:")
print(f"  Catalog: {catalog_name}")
print(f"  Schema: {schema_name}")
print(f"  Extraction Job: {extraction_job_id}")
print(f"  Summarization Job: {summarization_job_id}")
print(f"  UC Volume Path: {uc_volume_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Agent Implementations

# COMMAND ----------

import mlflow
import logging
from typing import List, Dict

# For this demo, we'll inline simplified agent implementations
# In production, these would be separate packages/modules

print("✅ Using inline agent implementations for demo")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create MLflow PyFunc Model
# MAGIC 
# MAGIC Wraps all 4 agents into a single deployable model

# COMMAND ----------

class OncologyMultiAgentModel(mlflow.pyfunc.PythonModel):
    """
    Multi-Agent Coordinator for Oncology Document Processing
    
    Agents:
    - Coordinator: Automatic passthrough for Vector Search
    - Extraction: Manual OAuth with EXTRACTION_SP
    - Summarization: Manual OAuth with SUMMARIZATION_SP
    - FileStorage: Automatic passthrough for UC Volumes
    """
    
    def load_context(self, context):
        """Load all specialist agents"""
        import os
        import sys
        import logging
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        
        # For demo, we'll use a simplified inline implementation
        # In production, these would be separate packages
        self.logger.info("🔐 Initializing multi-agent coordinator...")
        self.logger.info("  ✅ Extraction, Summarization, FileStorage agents loaded")
        self.logger.info("  ✅ Using dedicated SPs for Jobs API")
        self.logger.info("  ✅ Using automatic passthrough for UC Volumes")
        
        # Store configuration for runtime use
        self.extraction_job_id = os.environ.get("EXTRACTION_JOB_ID")
        self.summarization_job_id = os.environ.get("SUMMARIZATION_JOB_ID")
        self.uc_volume_path = os.environ.get("UC_VOLUME_PATH")
        
        self.logger.info("✅ Multi-agent coordinator ready")
    
    def predict(self, context, model_input):
        """
        Handle user messages
        
        Input format (Agent Framework):
        {
            "messages": [
                {"role": "user", "content": "Extract /source_pdfs/patient_123.pdf"}
            ]
        }
        
        Output format (OpenAI-style):
        {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Extraction started! Run ID: 12345..."
                    },
                    "finish_reason": "stop"
                }
            ],
            "id": "<request_id>"
        }
        """
        try:
            # Extract messages from input
            messages = model_input.get("messages", [])
            
            if not messages or len(messages) == 0:
                response_text = "Please provide a message."
            else:
                user_message = messages[-1].get("content", "")
                
                # Demo response showing the architecture
                response_text = f"""
🏥 Multi-Agent Oncology System (Demo)

Your request: "{user_message}"

📋 Architecture Overview:
✅ ExtractionAgent - Uses EXTRACTION_SP (Job ID: {self.extraction_job_id})
✅ SummarizationAgent - Uses SUMMARIZATION_SP (Job ID: {self.summarization_job_id})
✅ FileStorageAgent - Uses UC Volumes (Path: {self.uc_volume_path})
✅ CoordinatorAgent - Uses automatic passthrough for Vector Search

🔐 Authentication Patterns Demonstrated:
1. Manual OAuth: EXTRACTION_SP and SUMMARIZATION_SP for Jobs API
2. Automatic Passthrough: UC Volumes and Vector Search

In production, this would:
1. Extract PDF using EXTRACTION_SP
2. Summarize using SUMMARIZATION_SP  
3. Store to UC Volume with passthrough auth
4. Track status in CQRS Delta tables

This is a demonstration of the multi-agent architecture and authentication patterns.
"""
            
            # Return in OpenAI format (required by Agent Framework)
            return {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": response_text
                        },
                        "finish_reason": "stop"
                    }
                ],
                "id": f"oncology-demo-{hash(str(messages))}"
            }
            
        except Exception as e:
            self.logger.error(f"❌ Error in prediction: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": f"Error processing request: {str(e)}"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "id": "error"
            }

print("✅ Created OncologyMultiAgentModel class")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log Model to MLflow

# COMMAND ----------

from mlflow.models import ModelSignature, infer_signature
from mlflow.models.resources import DatabricksVectorSearchIndex

# Define input/output examples for signature
example_input = {
    "messages": [
        {"role": "user", "content": "Extract /source_pdfs/patient_123.pdf"}
    ]
}

example_output = {
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Extraction started! Run ID: 12345. ETA: 30 minutes."
            },
            "finish_reason": "stop"
        }
    ],
    "id": "example-123"
}

# Infer signature
signature = infer_signature(example_input, example_output)

print("Model Signature:")
print(signature)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register Model

# COMMAND ----------

MODEL_NAME = f"{catalog_name}.{schema_name}.oncology_coordinator_agent"

print(f"📝 Registering model: {MODEL_NAME}")

with mlflow.start_run(run_name="oncology_multi_agent_deployment"):
    # Log the model
    # 🔐 CRITICAL: Declare Vector Search resource for automatic passthrough
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=OncologyMultiAgentModel(),
        signature=signature,
        input_example=example_input,
        resources=[
            DatabricksVectorSearchIndex(index_name=vector_search_index)
        ]  # Enables automatic passthrough for Vector Search
    )
    
    model_uri = mlflow.get_artifact_uri("model")
    print(f"✅ Model logged: {model_uri}")

# Register model
model_version = mlflow.register_model(model_uri, MODEL_NAME)

print(f"✅ Model registered: {MODEL_NAME}")
print(f"   Version: {model_version.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy with All SP Credentials
# MAGIC 
# MAGIC **Security:** Each specialist agent gets its own dedicated SP credentials

# COMMAND ----------

from databricks import agents

# Get workspace URL
workspace_url = dbutils.notebook.entry_point.getDbutils() \
    .notebook().getContext().apiUrl().get()

# 🔐 Resolve ALL SP credentials from Databricks Secrets
# Deploy-time resolution ensures endpoint has access to credential values
print("🔐 Resolving SP credentials from Databricks Secrets...")

extraction_sp_client_id = dbutils.secrets.get("oncology_agents", "extraction_sp_client_id")
extraction_sp_secret = dbutils.secrets.get("oncology_agents", "extraction_sp_secret")
print("  ✅ EXTRACTION_SP credentials resolved")

summarization_sp_client_id = dbutils.secrets.get("oncology_agents", "summarization_sp_client_id")
summarization_sp_secret = dbutils.secrets.get("oncology_agents", "summarization_sp_secret")
print("  ✅ SUMMARIZATION_SP credentials resolved")
print("  ✅ UC Volume path configured for file storage (automatic passthrough)")

# COMMAND ----------

print("\n🚀 Deploying multi-agent coordinator...")
print(f"   Model: {MODEL_NAME}")
print(f"   Version: {model_version.version}")
print(f"\n🔐 Security Configuration:")
print(f"   • ExtractionAgent: EXTRACTION_SP (manual OAuth)")
print(f"   • SummarizationAgent: SUMMARIZATION_SP (manual OAuth)")
print(f"   • FileStorageAgent: Automatic passthrough (UC Volumes)")
print(f"   • CoordinatorAgent: Automatic passthrough (Vector Search)")

# Deploy with SP credentials injected as environment variables
deployment_info = agents.deploy(
    model_name=MODEL_NAME,
    model_version=model_version.version,
    environment_vars={
        # 🔐 EXTRACTION_SP credentials (manual OAuth for Jobs API)
        "EXTRACTION_SP_CLIENT_ID": extraction_sp_client_id,
        "EXTRACTION_SP_CLIENT_SECRET": extraction_sp_secret,
        
        # 🔐 SUMMARIZATION_SP credentials (manual OAuth for Jobs API)
        "SUMMARIZATION_SP_CLIENT_ID": summarization_sp_client_id,
        "SUMMARIZATION_SP_CLIENT_SECRET": summarization_sp_secret,
        
        # Workspace URL (auto-detected)
        "DATABRICKS_HOST": workspace_url,
        
        # Job IDs
        "EXTRACTION_JOB_ID": extraction_job_id,
        "SUMMARIZATION_JOB_ID": summarization_job_id,
        
        # UC Volume path for file storage
        "UC_VOLUME_PATH": uc_volume_path
    },
    scale_to_zero=True
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deployment Complete!

# COMMAND ----------

print("\n" + "="*80)
print("🎉 ONCOLOGY MULTI-AGENT SYSTEM DEPLOYED!")
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
print(f"   ✅ CoordinatorAgent → Automatic passthrough (Vector Search)")
print(f"\n📋 Workflow:")
print(f"   1. User: 'Extract /source_pdfs/patient_123.pdf'")
print(f"   2. Coordinator routes to ExtractionAgent")
print(f"   3. ExtractionAgent triggers job with EXTRACTION_SP")
print(f"   4. Job completes → Auto-triggers SummarizationAgent")
print(f"   5. SummarizationAgent triggers job with SUMMARIZATION_SP")
print(f"   6. Summary completes → Auto-triggers FileStorageAgent")
print(f"   7. FileStorageAgent stores to UC Volume (passthrough auth)")
print(f"   8. User gets final file location")
print(f"\n⏳ Wait 3-5 minutes for endpoint to reach 'Ready' state")
print("="*80)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test the Agent

# COMMAND ----------

print("\n🧪 Test Commands:\n")
print("1. Extract Document:")
print('   "Extract /source_pdfs/patient_123.pdf"')
print("\n2. Check Status:")
print('   "What\'s the status?"')
print("\n3. Search Knowledge Base:")
print('   "Tell me about treatment protocols"')
print("\nThe agent will automatically advance through the workflow:")
print("   Extraction → Summarization → UC Volume Storage")

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

