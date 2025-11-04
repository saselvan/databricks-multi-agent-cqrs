# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Oncology Multi-Agent System (Production Pattern)
# MAGIC 
# MAGIC ## ⚠️ BEFORE YOU RUN: Update the Parameters Above! ⚠️
# MAGIC 
# MAGIC You should see 4 input boxes at the top of this notebook. Fill them in with YOUR values:
# MAGIC 
# MAGIC 1. **Catalog Name**: Your Unity Catalog name (from Step 6.1)
# MAGIC 2. **Schema Name**: Your schema name (from Step 6.1)  
# MAGIC 3. **Extraction Job ID**: Copy from Step 6.2 output
# MAGIC 4. **Summarization Job ID**: Copy from Step 6.3 output
# MAGIC 
# MAGIC **If you don't see the input boxes**, run the cell below, then they'll appear.
# MAGIC 
# MAGIC ---
# MAGIC 
# MAGIC ## What This Notebook Does
# MAGIC 
# MAGIC Uses `code_paths` to bundle agent Python files directly into the MLflow model artifact.
# MAGIC This is the **production-grade approach** recommended by Databricks.
# MAGIC 
# MAGIC ## Authentication Patterns Demonstrated
# MAGIC 1. **Manual OAuth**: Dedicated SPs for Jobs API (solves session expiration issues)
# MAGIC 2. **Automatic Passthrough**: UC Volumes (zero credential management)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Configure Parameters
# MAGIC 
# MAGIC **👆 Fill in the input boxes above before continuing!**

# COMMAND ----------

# Create widgets (run this cell first to see the input boxes at the top)
dbutils.widgets.text("catalog_name", "YOUR_CATALOG_NAME", "1. Catalog Name")
dbutils.widgets.text("schema_name", "YOUR_SCHEMA_NAME", "2. Schema Name")
dbutils.widgets.text("extraction_job_id", "PASTE_EXTRACTION_JOB_ID_HERE", "3. Extraction Job ID")
dbutils.widgets.text("summarization_job_id", "PASTE_SUMMARIZATION_JOB_ID_HERE", "4. Summarization Job ID")

print("✅ Widgets created! Look at the top of this notebook to fill in your values.")
print("   Then run the next cell to validate your configuration.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Validate Configuration

# COMMAND ----------

# Read widget values
catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")
extraction_job_id = dbutils.widgets.get("extraction_job_id")
summarization_job_id = dbutils.widgets.get("summarization_job_id")

# Validate that defaults were changed
errors = []
if catalog_name == "YOUR_CATALOG_NAME":
    errors.append("❌ Please update 'Catalog Name' parameter at the top")
if schema_name == "YOUR_SCHEMA_NAME":
    errors.append("❌ Please update 'Schema Name' parameter at the top")
if "PASTE" in extraction_job_id or "JOB_ID" in extraction_job_id:
    errors.append("❌ Please update 'Extraction Job ID' parameter at the top")
if "PASTE" in summarization_job_id or "JOB_ID" in summarization_job_id:
    errors.append("❌ Please update 'Summarization Job ID' parameter at the top")

if errors:
    for error in errors:
        print(error)
    raise ValueError("Please update the parameters at the top of the notebook before running!")

# Set derived values
MODEL_NAME = f"{catalog_name}.{schema_name}.oncology_coordinator"
UC_VOLUME_PATH = f"/Volumes/{catalog_name}/{schema_name}/summaries"

print("✅ Configuration validated!")
print("=" * 80)
print(f"Model: {MODEL_NAME}")
print(f"Extraction Job: {extraction_job_id}")
print(f"Summarization Job: {summarization_job_id}")
print(f"UC Volume: {UC_VOLUME_PATH}")
print("=" * 80)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Install Dependencies

# COMMAND ----------

# Install only PyPI packages (no wheel needed!)
%pip install databricks-agents mlflow>=2.9.0 --quiet
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Re-read Configuration After Python Restart
# MAGIC 
# MAGIC **CRITICAL:** After `restartPython()`, all variables are cleared. Must re-read widgets.

# COMMAND ----------

# Re-read widget values (they were cleared by restartPython)
catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")
extraction_job_id = dbutils.widgets.get("extraction_job_id")
summarization_job_id = dbutils.widgets.get("summarization_job_id")

MODEL_NAME = f"{catalog_name}.{schema_name}.oncology_coordinator"
UC_VOLUME_PATH = f"/Volumes/{catalog_name}/{schema_name}/summaries"

print("✅ Re-read configuration after Python restart:")
print(f"   Model: {MODEL_NAME}")
print(f"   Extraction Job: {extraction_job_id}")
print(f"   Summarization Job: {summarization_job_id}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Write Agent Code to Local Files
# MAGIC 
# MAGIC We'll write each agent class to a separate Python file, then use `code_paths` to bundle them.

# COMMAND ----------

import os
import tempfile

# Create temporary directory for agent files
agent_dir = tempfile.mkdtemp()
print(f"Agent files directory: {agent_dir}")

# Write extraction_agent.py
with open(f"{agent_dir}/extraction_agent.py", "w") as f:
    f.write("""
import os
import uuid
from datetime import datetime
from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession

class ExtractionAgent:
    \"\"\"Triggers PDF extraction jobs using EXTRACTION_SP (manual OAuth)\"\"\"
    def __init__(self):
        self.client_id = os.environ.get("EXTRACTION_SP_CLIENT_ID")
        self.client_secret = os.environ.get("EXTRACTION_SP_CLIENT_SECRET")
        self.host = os.environ.get("DATABRICKS_HOST")
        self.catalog_name = os.environ.get("CATALOG_NAME")
        self.schema_name = os.environ.get("SCHEMA_NAME")
    
    def trigger_extraction(self, document_path, job_id):
        \"\"\"Trigger extraction job with manual OAuth and log JobStarted event\"\"\"
        w = WorkspaceClient(
            host=self.host,
            client_id=self.client_id,
            client_secret=self.client_secret
        )
        
        # Trigger the job
        run = w.jobs.run_now(
            job_id=int(job_id),
            notebook_params={"document_path": document_path}
        )
        
        # Log JobStarted event to CQRS table
        try:
            spark = SparkSession.builder.getOrCreate()
            event_id = str(uuid.uuid4())
            
            spark.sql(f\"\"\"
                INSERT INTO {self.catalog_name}.{self.schema_name}.job_events
                (event_id, event_type, run_id, agent, sp_used, triggered_by, 
                 timestamp, status, details)
                VALUES (
                    '{event_id}',
                    'JobStarted',
                    {run.run_id},
                    'extraction_agent',
                    '{self.client_id}',
                    'user_via_agent',
                    current_timestamp(),
                    'STARTED',
                    '{{\\"document_path\\": \\"{document_path}\\", \\"job_id\\": \\"{job_id}\\"}}'
                )
            \"\"\")
            print(f"✅ Logged JobStarted event for run {run.run_id}")
        except Exception as e:
            print(f"⚠️  Could not log JobStarted event (non-fatal): {e}")
        
        return run.run_id
""")

# Write summarization_agent.py
with open(f"{agent_dir}/summarization_agent.py", "w") as f:
    f.write("""
import os
from databricks.sdk import WorkspaceClient

class SummarizationAgent:
    \"\"\"Triggers summarization jobs using SUMMARIZATION_SP (manual OAuth)\"\"\"
    def __init__(self):
        self.client_id = os.environ.get("SUMMARIZATION_SP_CLIENT_ID")
        self.client_secret = os.environ.get("SUMMARIZATION_SP_CLIENT_SECRET")
        self.host = os.environ.get("DATABRICKS_HOST")
    
    def trigger_summarization(self, extraction_run_id, job_id):
        \"\"\"Trigger summarization job with manual OAuth\"\"\"
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
""")

# Write file_storage_agent.py
with open(f"{agent_dir}/file_storage_agent.py", "w") as f:
    f.write("""
import os
import datetime

class FileStorageAgent:
    \"\"\"Stores summaries to UC Volumes using automatic passthrough\"\"\"
    def __init__(self):
        self.uc_volume_path = os.environ.get("UC_VOLUME_PATH")
    
    def store_summary(self, summary_id, content):
        \"\"\"Store to UC Volume (automatic passthrough - no credentials needed)\"\"\"
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
            return f"⚠️  Stored to {fallback_path} (UC Volume not accessible: {e})"
""")

# Write coordinator_agent.py
with open(f"{agent_dir}/coordinator_agent.py", "w") as f:
    f.write("""
import os

class CoordinatorAgent:
    \"\"\"Orchestrates the multi-agent workflow\"\"\"
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
        \"\"\"Process user request and orchestrate workflow\"\"\"
        user_message = messages[-1].get("content", "") if messages else ""
        
        if "extract" in user_message.lower():
            # Extract document path from message
            words = user_message.split()
            doc_path = next((w for w in words if "/Volumes/" in w), None)
            
            if doc_path:
                try:
                    run_id = self.extraction_agent.trigger_extraction(doc_path, self.extraction_job_id)
                    return f"✅ Extraction started for {doc_path}\\\\n🔗 Run ID: {run_id}\\\\n\\\\nThis uses EXTRACTION_SP (manual OAuth) to trigger the job."
                except Exception as e:
                    return f"❌ Extraction failed: {str(e)}"
            else:
                return "Please provide a document path like: Extract /Volumes/catalog/schema/volume/file.pdf"
        
        return "I can help you extract oncology documents. Say 'Extract /Volumes/.../file.pdf' to start."
""")

print("✅ Created agent files:")
for filename in os.listdir(agent_dir):
    print(f"   - {filename}")

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
        # Import agents from code_paths (bundled in model artifact)
        from extraction_agent import ExtractionAgent
        from summarization_agent import SummarizationAgent
        from file_storage_agent import FileStorageAgent
        from coordinator_agent import CoordinatorAgent
        
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
# MAGIC ## Log Model with code_paths (Production Pattern)

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

# Get list of agent files to bundle
code_files = [f"{agent_dir}/{f}" for f in os.listdir(agent_dir) if f.endswith('.py')]
print(f"📦 Bundling {len(code_files)} agent files into model artifact:")
for cf in code_files:
    print(f"   - {os.path.basename(cf)}")

# Log the model with code_paths (THIS IS THE PROPER PATTERN!)
with mlflow.start_run():
    model_info = mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=OncologyCoordinatorModel(),
        signature=signature,
        code_paths=code_files,  # ← Bundles agent code into model artifact
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

print(f"\n✅ Model '{MODEL_NAME}' version {model_version.version} registered.")
print(f"📦 Agent code bundled in model artifact (no external dependencies!)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deploy Agent to Serving Endpoint

# COMMAND ----------

from databricks import agents
from databricks.sdk import WorkspaceClient

# Get workspace URL using SDK's recommended pattern
# The SDK checks (in order):
#   1. DATABRICKS_HOST environment variable
#   2. .databrickscfg file  
#   3. Notebook context
# This works correctly in all environments, including serverless
import os

try:
    # OPTION 1: Use WorkspaceClient auto-detection (BEST PRACTICE)
    # This respects DATABRICKS_HOST env var which should be correct even in serverless
    from databricks.sdk import WorkspaceClient
    temp_client = WorkspaceClient()
    workspace_url = temp_client.config.host
    print(f"✅ WorkspaceClient auto-detected: {workspace_url}")
    print(f"   (from DATABRICKS_HOST env var or config)")
except Exception as e:
    print(f"⚠️ WorkspaceClient auto-detection failed: {e}")
    # OPTION 2: Fallback to dbutils (may return wrong region in serverless)
    try:
        workspace_url = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()
        print(f"⚠️ Using dbutils fallback: {workspace_url}")
        print(f"⚠️ WARNING: In serverless, this may return wrong region (e.g., Oregon)")
        print(f"   If incorrect, set DATABRICKS_HOST environment variable")
    except:
        raise ValueError(
            "❌ Could not detect workspace URL.\n"
            "   Set the DATABRICKS_HOST environment variable or configure .databrickscfg"
        )

print(f"\n🚀 Deploying multi-agent coordinator...")
print(f"   Model: {MODEL_NAME}")
print(f"   Version: {model_version.version}")
print(f"   Workspace URL: {workspace_url}")
print(f"\n📦 Using production pattern: code_paths bundles agent files into model")

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
        
        # Catalog and Schema (for CQRS event logging)
        "CATALOG_NAME": catalog_name,
        "SCHEMA_NAME": schema_name,
        
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
print(f"\n📦 Production Pattern:")
print(f"   ✅ Agent code bundled in model artifact via code_paths")
print(f"   ✅ No external file dependencies")
print(f"   ✅ Works universally (notebooks, jobs, serving endpoints)")
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
    "summarization_job_id": summarization_job_id,
    "pattern": "code_paths (production-grade)"
}))

