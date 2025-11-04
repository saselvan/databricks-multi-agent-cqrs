# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy Agent PROPERLY with Databricks Agent Framework
# MAGIC 
# MAGIC ## 🎯 What This Notebook Does
# MAGIC This notebook demonstrates the **CORRECT** way to deploy an AI agent that uses TWO different authentication patterns:
# MAGIC 
# MAGIC 1. **Automatic Passthrough** (Vector Search) - Zero credentials in code
# MAGIC 2. **Manual OAuth** (Jobs API) - Explicit Service Principal credentials
# MAGIC 
# MAGIC ## 🔐 Why Two Patterns?
# MAGIC 
# MAGIC ### Pattern 1: Automatic Passthrough (Recommended for Databricks Resources)
# MAGIC - **What:** Agent Framework automatically handles authentication
# MAGIC - **When:** Accessing Databricks-native resources (Vector Search, Unity Catalog, Model Serving)
# MAGIC - **How:** Declare resources in `mlflow.pyfunc.log_model()`, Agent Framework grants permissions
# MAGIC - **Benefit:** Zero credential management, automatic rotation, secure by default
# MAGIC 
# MAGIC ### Pattern 2: Manual OAuth (Required for Some APIs)
# MAGIC - **What:** Explicitly pass Service Principal credentials
# MAGIC - **When:** Jobs API, external APIs, or APIs that don't support automatic passthrough
# MAGIC - **How:** Store SP credentials in secrets, inject as environment variables
# MAGIC - **Benefit:** You control the SP lifecycle (no unexpected rotation), works with any API
# MAGIC 
# MAGIC ## 🚀 Banner's Use Case
# MAGIC This solves Banner's specific pain points:
# MAGIC - **SP Rotation Issues** → Fixed: We use a persistent SP (no auto-rotation)
# MAGIC - **30-min Timeout Issues** → Fixed: Async job triggering (returns immediately)
# MAGIC - **Manual SP Assignment** → Fixed: Agent Framework auto-configures permissions

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Install Required Packages

# COMMAND ----------

# Install all necessary packages for Agent Framework deployment
# - databricks-vectorsearch: For searching product data
# - databricks-sdk: For Jobs API calls
# - mlflow>=2.9.0: For model logging and deployment
# - databricks-agents: For agents.deploy() function (Agent Framework)
%pip install databricks-vectorsearch databricks-sdk databricks-langchain mlflow>=2.9.0 databricks-agents --quiet
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Configuration
# MAGIC 
# MAGIC ### 🔑 Critical Import: DatabricksVectorSearchIndex
# MAGIC 
# MAGIC **This is the KEY to automatic passthrough authentication!**
# MAGIC 
# MAGIC By importing `DatabricksVectorSearchIndex` from `mlflow.models.resources`, we can **declare** 
# MAGIC which Databricks resources our agent needs access to. 
# MAGIC 
# MAGIC When we log the model with `resources=[DatabricksVectorSearchIndex(...)]`, Agent Framework:
# MAGIC 1. Sees the resource dependency during deployment
# MAGIC 2. Automatically grants the endpoint's Service Principal permission to access that resource
# MAGIC 3. Configures the authentication context so VectorSearchClient() "just works"
# MAGIC 
# MAGIC **Without this declaration, the endpoint has NO permissions and authentication fails!**

# COMMAND ----------

import os
import mlflow
from mlflow.models import infer_signature

# 🔑 THIS IS CRITICAL for automatic passthrough!
# DatabricksVectorSearchIndex tells Agent Framework which vector index we need access to
from mlflow.models.resources import DatabricksVectorSearchIndex

# Configuration (via widgets for easy customization)
dbutils.widgets.text("catalog", "sselvan_banner", "Catalog")
dbutils.widgets.text("schema", "agent_demo", "Schema")
dbutils.widgets.text("vector_search_endpoint", "one-env-shared-endpoint-1", "Vector Search Endpoint")
dbutils.widgets.text("refresh_job_id", "343083600730867", "Refresh Job ID")
dbutils.widgets.text("workspace_url", "", "Workspace URL (leave empty to auto-detect)")

CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
MODEL_NAME = f"{CATALOG}.{SCHEMA}.support_agent_final"

VECTOR_SEARCH_ENDPOINT = dbutils.widgets.get("vector_search_endpoint")
VECTOR_SEARCH_INDEX = f"{CATALOG}.{SCHEMA}.product_docs_index"
REFRESH_JOB_ID = dbutils.widgets.get("refresh_job_id")
workspace_url_param = dbutils.widgets.get("workspace_url")

print(f"Deploying: {MODEL_NAME}")
print(f"Using Agent Framework for automatic auth handling")
print(f"Vector Search Index: {VECTOR_SEARCH_INDEX}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Define the Agent
# MAGIC 
# MAGIC ### 🤖 FinalWorkingAgent Class
# MAGIC 
# MAGIC This is an MLflow PyFunc model that implements our agent logic. It has two main capabilities:
# MAGIC 
# MAGIC #### Capability 1: Search Products (Automatic Passthrough)
# MAGIC - Uses `VectorSearchClient()` with **NO credentials**
# MAGIC - Works because Agent Framework granted the endpoint access (via resources parameter)
# MAGIC - This is the "magic" of automatic passthrough!
# MAGIC 
# MAGIC #### Capability 2: Trigger Data Refresh (Manual OAuth)
# MAGIC - Uses `WorkspaceClient(client_id=..., client_secret=...)`  with **explicit credentials**
# MAGIC - Required because Jobs API doesn't support automatic passthrough
# MAGIC - Credentials come from environment variables (injected by Agent Framework from secrets)
# MAGIC - Uses async pattern: triggers job and returns immediately (no 30-min wait!)

# COMMAND ----------

class FinalWorkingAgent(mlflow.pyfunc.PythonModel):
    """
    🤖 Production-Ready AI Agent for Product Support & Data Refresh
    
    This agent demonstrates TWO authentication patterns:
    1. Automatic Passthrough (Vector Search)
    2. Manual OAuth (Jobs API)
    
    Architecture:
    - Uses only Databricks SDK (no Spark) for serving endpoint compatibility
    - Implements async job triggering (no blocking/timeout issues)
    - Follows Agent Framework best practices
    """
    
    def load_context(self, context):
        """
        🔧 Initialize agent when endpoint starts up
        
        This runs ONCE when the serving endpoint initializes.
        Sets up logging for observability.
        """
        import logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        self.logger.info("FinalWorkingAgent loaded successfully")
    
    def predict(self, context, model_input):
        """
        🎯 Main entry point for all requests to the agent
        
        Agent Framework requires this signature for chat-based agents:
        - Input: ChatCompletionRequest format (messages array)
        - Output: OpenAI-style response format (choices array)
        
        Routing Logic:
        - If query contains "refresh/update/stale" → Trigger data refresh job
        - Otherwise → Search product catalog
        """
        import pandas as pd
        
        self.logger.info("📨 Processing incoming request...")
        
        # Extract question from Agent Framework's chat format
        # Input format: {"messages": [{"role": "user", "content": "..."}]}
        if isinstance(model_input, pd.DataFrame):
            messages = model_input.iloc[0]['messages']
        elif isinstance(model_input, dict):
            messages = model_input.get('messages', [])
        else:
            messages = []
        
        if not messages:
            return self._chat_response("I didn't receive a question.")
        
        # Get the user's question (last message in conversation)
        question = messages[-1].get('content', '')
        question_lower = question.lower()
        
        # Route based on intent
        if any(word in question_lower for word in ['refresh', 'update', 'stale', 'old']):
            self.logger.info("🔄 Routing to data refresh handler")
            return self._handle_refresh()
        else:
            self.logger.info("🔍 Routing to product search handler")
            return self._search_products(question)
    
    def _search_products(self, query):
        """
        🔍 Search Product Catalog using Vector Search
        
        🔐 AUTHENTICATION PATTERN: AUTOMATIC PASSTHROUGH
        ================================================
        
        CRITICAL: This method uses CUSTOM env var names (JOBS_API_*) for Jobs API credentials
        to avoid SDK auto-discovery interference!
        
        How It Works:
        -------------
        1. Create WorkspaceClient() with NO credentials
        2. SDK checks for DATABRICKS_* env vars → NOT FOUND (we use JOBS_API_* instead!)
        3. Falls back to automatic discovery → Uses endpoint's system SP
        4. System SP has Vector Search permissions (granted via resources=[DatabricksVectorSearchIndex(...)])
        5. Pass workspace_client to VectorSearchRetrieverTool
        6. Search works with zero credential management!
        
        Why Custom Env Var Names Matter:
        --------------------------------
        ❌ If we used DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET:
           → WorkspaceClient() would find them (SDK auto-discovery)
           → Would authenticate as Jobs API SP
           → Jobs API SP doesn't have Vector Search permissions
           → Authentication fails!
        
        ✅ By using JOBS_API_CLIENT_ID, JOBS_API_CLIENT_SECRET:
           → WorkspaceClient() doesn't find standard env vars
           → Falls back to automatic discovery
           → Uses endpoint's system SP (which HAS Vector Search permissions)
           → Works perfectly!
        """
        try:
            from databricks_langchain import VectorSearchRetrieverTool
            from databricks.sdk import WorkspaceClient
            
            self.logger.info("🔐 Using VectorSearchRetrieverTool with automatic passthrough authentication")
            
            # ✅ AUTOMATIC PASSTHROUGH: Create WorkspaceClient with no credentials
            # It will auto-discover the endpoint's system identity (NOT the Jobs API SP!)
            workspace_client = WorkspaceClient()
            
            # Pass the workspace_client to VectorSearchRetrieverTool
            retriever_tool = VectorSearchRetrieverTool(
                index_name="sselvan_banner.agent_demo.product_docs_index",
                columns=["product_name", "category", "price"],
                num_results=3,
                workspace_client=workspace_client  # ← Bridges to auto-discovered identity
            )
            
            # Execute the search using the tool's invoke method
            # Results come back as Document objects
            results = retriever_tool.invoke(query)
            
            if not results or len(results) == 0:
                return self._chat_response("I couldn't find any relevant products.")
            
            # Format results nicely
            lines = ["Here are the relevant products:\n"]
            for doc in results:
                if hasattr(doc, 'metadata'):
                    name = doc.metadata.get('product_name', 'Unknown')
                    category = doc.metadata.get('category', 'Unknown')
                    price = doc.metadata.get('price', 0)
                    lines.append(f"• **{name}** ({category}) - ${price:,.2f}")
                    if hasattr(doc, 'page_content'):
                        lines.append(f"  {doc.page_content}")
                    lines.append("")  # Blank line between products
            
            self.logger.info(f"✅ Found {len(results)} products via automatic passthrough!")
            return self._chat_response("\n".join(lines))
            
        except Exception as e:
            self.logger.error(f"❌ Search error: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return self._chat_response(f"Error searching: {str(e)}")
    
    def _handle_refresh(self):
        """
        🔄 Trigger Data Refresh Job using Jobs API
        
        🔐 AUTHENTICATION PATTERN: MANUAL OAUTH
        ========================================
        
        CRITICAL: Uses CUSTOM environment variable names (JOBS_API_*) instead of
        standard SDK names (DATABRICKS_*) to prevent SDK auto-discovery interference!
        
        Why Custom Names:
        ----------------
        If we used DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET:
        → WorkspaceClient() in _search_products would find them via SDK auto-discovery
        → Would authenticate Vector Search as Jobs API SP (which lacks Vector Search permissions)
        → Vector Search would fail!
        
        By using JOBS_API_CLIENT_ID, JOBS_API_CLIENT_SECRET:
        → WorkspaceClient() in _search_products doesn't find standard env vars
        → Falls back to automatic discovery for Vector Search
        → We manually read JOBS_API_* vars here for Jobs API
        → Both authentication patterns coexist peacefully!
        """
        try:
            from databricks.sdk import WorkspaceClient
            import os
            
            # Get credentials from CUSTOM env vars (NOT standard DATABRICKS_* names!)
            client_id = os.environ.get("JOBS_API_CLIENT_ID")
            client_secret = os.environ.get("JOBS_API_CLIENT_SECRET")
            workspace_url = os.environ.get("JOBS_API_HOST")
            
            if not all([client_id, client_secret, workspace_url]):
                self.logger.error("❌ Jobs API credentials not configured")
                return self._chat_response(
                    "Data refresh is not configured. Please contact your administrator."
                )
            
            # Create WorkspaceClient with EXPLICIT credentials for Jobs API
            self.logger.info("🔐 Using manual OAuth authentication for Jobs API")
            w = WorkspaceClient(
                host=workspace_url,
                client_id=client_id,
                client_secret=client_secret
            )
            
            # Trigger job ASYNCHRONOUSLY
            self.logger.info(f"🚀 Triggering job {REFRESH_JOB_ID} asynchronously...")
            run = w.jobs.run_now(job_id=343083600730867)
            
            message = (
                f"✅ Data refresh triggered successfully!\n\n"
                f"Job is running in the background (Run ID: {run.run_id})\n"
                f"Please retry your question in 2-3 minutes once the data is refreshed.\n\n"
                f"🎯 This demonstrates the ASYNC pattern:\n"
                f"   - No blocking/waiting\n"
                f"   - No 30-minute timeouts\n"
                f"   - Job runs independently\n"
                f"   - User gets immediate response"
            )
            
            self.logger.info(f"✅ Job triggered successfully: Run ID {run.run_id}")
            return self._chat_response(message)
            
        except Exception as e:
            self.logger.error(f"❌ Refresh error: {e}")
            return self._chat_response(f"Error triggering refresh: {str(e)}")
    
    def _chat_response(self, content):
        """Format response in OpenAI chat completion format"""
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content
                    },
                    "finish_reason": "stop"
                }
            ]
        }

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Log Model with Resource Declaration

# COMMAND ----------

# Set Unity Catalog as model registry
mlflow.set_registry_uri("databricks-uc")

# Define example input/output for model signature
example_input = {
    "messages": [
        {"role": "user", "content": "What gaming laptops do you have?"}
    ]
}

example_output = {
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Here are the relevant products..."
            },
            "finish_reason": "stop"
        }
    ]
}

signature = infer_signature(example_input, example_output)

# Log model with resources for automatic passthrough
with mlflow.start_run(run_name="final_working_agent"):
    logged_model = mlflow.pyfunc.log_model(
        artifact_path="agent",
        python_model=FinalWorkingAgent(),
        signature=signature,
        input_example=example_input,
        pip_requirements=[
            "databricks-vectorsearch",
            "databricks-sdk",
            "databricks-langchain",
        ],
        # ✅ THIS IS CRITICAL for automatic passthrough!
        resources=[
            DatabricksVectorSearchIndex(
                index_name=VECTOR_SEARCH_INDEX
            ),
        ]
    )
    
    model_uri = logged_model.model_uri
    print(f"✅ Model logged: {model_uri}")
    print(f"✅ Resources declared: {VECTOR_SEARCH_INDEX}")

# Register model to Unity Catalog
model_version = mlflow.register_model(model_uri, MODEL_NAME)
print(f"✅ Model registered: {MODEL_NAME} version {model_version.version}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Deploy with Agent Framework

# COMMAND ----------

from databricks import agents

print("🚀 Deploying agent with Agent Framework...")

# Get workspace URL
# NOTE: In serverless, auto-detection may return wrong region (e.g., Oregon instead of your actual region)
# If this happens, set workspace_url widget parameter manually
if workspace_url_param:
    workspace_url = workspace_url_param
    print(f"✅ Using workspace URL from widget parameter: {workspace_url}")
else:
    try:
        workspace_url = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()
        print(f"✅ Auto-detected workspace URL: {workspace_url}")
        print(f"⚠️  If this URL is incorrect (common in serverless), set the 'workspace_url' widget parameter")
    except:
        raise ValueError(
            "❌ Could not detect workspace URL. Please set the 'workspace_url' widget parameter.\n"
            "   Example: https://your-workspace.cloud.databricks.com"
        )

# Resolve secrets at deploy time
print("\n🔐 Resolving secrets at deploy time...")
client_id = dbutils.secrets.get("banner_demo", "sp_client_id")
client_secret = dbutils.secrets.get("banner_demo", "sp_client_secret")

print(f"✅ Got SP client ID: {client_id[:10]}...")
print(f"✅ Got SP client secret: ***")

# Deploy with CUSTOM env var names (JOBS_API_* instead of DATABRICKS_*)
deployment_info = agents.deploy(
    model_name=MODEL_NAME,
    model_version=model_version.version,
    
    # 🔐 CRITICAL: Use CUSTOM env var names to avoid SDK auto-discovery!
    # If we used DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET:
    # → WorkspaceClient() in Vector Search would find them
    # → Would use Jobs API SP (no Vector Search permissions)
    # → Vector Search would fail!
    environment_vars={
        "JOBS_API_CLIENT_ID": client_id,      # Custom name!
        "JOBS_API_CLIENT_SECRET": client_secret,  # Custom name!
        "JOBS_API_HOST": workspace_url  # Auto-detected workspace URL
    },
)

print("\n" + "="*80)
print("🎉🎉🎉 DEPLOYMENT COMPLETE! 🎉🎉🎉")
print("="*80)
print(f"\n✅ Model: {MODEL_NAME}")
print(f"✅ Version: {model_version.version}")
print(f"✅ Endpoint: {deployment_info.endpoint_name}")
print(f"\n🔗 View Endpoint:")
print(f"   {workspace_url}/ml/endpoints/{deployment_info.endpoint_name}")
print(f"\n⏳ Wait 3-5 minutes for endpoint to reach 'Ready' state")
print(f"\n🧪 Then Test:")
print(f"   1. 'What gaming laptops do you have?'")
print(f"      → Uses automatic passthrough (Vector Search)")
print(f"   2. 'Please refresh the data'")
print(f"      → Uses manual OAuth (Jobs API)")
print(f"\n{'='*80}")
print(f"\n🎓 KEY FIX:")
print(f"   ✅ Custom env var names (JOBS_API_*) prevent SDK auto-discovery")
print(f"   ✅ Vector Search uses endpoint system SP (automatic passthrough)")
print(f"   ✅ Jobs API uses persistent SP (manual OAuth)")
print(f"   ✅ Both authentication patterns work together!")
print(f"\n{'='*80}")
