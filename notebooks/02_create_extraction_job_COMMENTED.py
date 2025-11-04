# Databricks notebook source
# MAGIC %md
# MAGIC # Create PDF Extraction Job
# MAGIC 
# MAGIC ## Purpose
# MAGIC Creates a Databricks job that will be triggered by the **ExtractionAgent** to extract text from PDF documents.
# MAGIC 
# MAGIC ## Key Concepts
# MAGIC 
# MAGIC ### What is a Databricks Job?
# MAGIC A job is a **scheduled or on-demand workflow** that runs notebooks, Python scripts, or JARs on Databricks clusters.
# MAGIC 
# MAGIC ### Why Create Jobs via SDK (not UI)?
# MAGIC - **Reproducibility:** Code-based job creation is version-controlled
# MAGIC - **Automation:** Can be part of CI/CD pipelines
# MAGIC - **Consistency:** Same job config across dev/staging/prod
# MAGIC 
# MAGIC ### Service Principal "Run As"
# MAGIC The `run_as` configuration specifies **which Service Principal** executes the job.
# MAGIC - **Why?** Least-privilege security - job only has EXTRACTION_SP's permissions
# MAGIC - **Benefit:** If job is compromised, attacker only gets extraction permissions (not summarization, not admin)
# MAGIC 
# MAGIC ## What This Notebook Does
# MAGIC 1. Connects to Databricks workspace using SDK
# MAGIC 2. Defines job configuration (cluster spec, notebook path, SP to run as)
# MAGIC 3. Creates the job via Jobs API
# MAGIC 4. Grants EXTRACTION_SP permission to run the job
# MAGIC 
# MAGIC ## Security Model
# MAGIC - **Job runs as:** EXTRACTION_SP (dedicated service principal)
# MAGIC - **Job can only:** Trigger extraction notebook, write to `staging.extracted_documents`
# MAGIC - **Job cannot:** Trigger summarization, access other resources
# MAGIC 
# MAGIC **Run this notebook ONCE during initial setup**

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Install Dependencies
# MAGIC 
# MAGIC **Why:** We need `databricks-sdk` to programmatically create jobs via the Jobs API
# MAGIC 
# MAGIC **Note:** This SDK allows us to:
# MAGIC - Create/update/delete jobs
# MAGIC - Configure job clusters
# MAGIC - Set run-as Service Principals
# MAGIC - Grant permissions

# Install Databricks SDK
# Already available on clusters, but we install explicitly for version consistency
# MAGIC %pip install databricks-sdk --quiet

# Restart Python to load the newly installed package
# Required after any pip install in Databricks notebooks
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Configure Parameters
# MAGIC 
# MAGIC ### Critical Parameter: extraction_sp_id
# MAGIC This is the **Application ID** (also called Client ID) of the Service Principal.
# MAGIC 
# MAGIC **Where to find it:**
# MAGIC 1. Azure Portal → Azure Active Directory → App Registrations
# MAGIC 2. Click on your `oncology-extraction-sp`
# MAGIC 3. Copy the **Application (client) ID** (UUID format)
# MAGIC 
# MAGIC **Important:** This is NOT the Client Secret! The secret is stored in Databricks Secrets.
# MAGIC 
# MAGIC ### notebook_path Parameter
# MAGIC Path to the extraction notebook that this job will execute.
# MAGIC Must match where you uploaded `extraction_job_notebook.py` in Databricks workspace.

# Create widgets for parameters
# These can be overridden via UI or Jobs API without modifying code
dbutils.widgets.text("extraction_sp_id", "<YOUR_EXTRACTION_SP_APPLICATION_ID>", "Extraction SP ID")
dbutils.widgets.text("notebook_path", "/Workspace/Users/samuel.selvan@databricks.com/banner_oncology/extraction_job_notebook", "Extraction Notebook Path")

# Retrieve widget values
extraction_sp_id = dbutils.widgets.get("extraction_sp_id")
notebook_path = dbutils.widgets.get("notebook_path")

# Validation: Ensure user updated the default placeholder
if not extraction_sp_id or extraction_sp_id == "<YOUR_EXTRACTION_SP_APPLICATION_ID>":
    raise ValueError(
        "⚠️ Please update extraction_sp_id with your actual Extraction SP Application ID (UUID format)\n"
        "Find it in: Azure Portal → Azure AD → App Registrations → oncology-extraction-sp\n"
        "Example: e38cc0e4-7322-4777-b845-75d51fbb2be7"
    )

print(f"Creating extraction job with:")
print(f"  SP ID: {extraction_sp_id}")
print(f"  Notebook: {notebook_path}")
print(f"")
print(f"🔐 Security: Job will run as EXTRACTION_SP (least privilege)")
print(f"   → Can only trigger extraction notebook")
print(f"   → Cannot trigger summarization or access other resources")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Initialize Databricks SDK
# MAGIC 
# MAGIC ### WorkspaceClient
# MAGIC The SDK's main entry point for interacting with Databricks APIs.
# MAGIC 
# MAGIC **Authentication:**
# MAGIC - Uses your current notebook's authentication context
# MAGIC - If running manually: Uses your user credentials
# MAGIC - If running in a job: Uses the job's run-as identity
# MAGIC 
# MAGIC **What we'll use it for:**
# MAGIC - `w.jobs.create()` - Create the extraction job
# MAGIC - `w.permissions.update()` - Grant SP permissions
# MAGIC - `w.current_user.me()` - Get current user for job naming

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs, compute
import json

# Initialize Workspace Client
# Automatically uses current authentication context
w = WorkspaceClient()

# Get current user info for job naming convention
# Best practice: Prefix jobs with username to avoid conflicts in shared workspaces
user = w.current_user.me()
user_name = user.user_name.split("@")[0]  # Extract 'jsmith' from 'jsmith@company.com'

# Construct job name (user-specific to avoid collisions)
job_name = f"{user_name}_oncology_extraction_job"

print(f"Creating job: {job_name}")
print(f"Current user: {user.user_name}")
print(f"")
print(f"💡 Job Naming Convention:")
print(f"   {user_name}_oncology_extraction_job")
print(f"   → Avoids collisions in shared workspaces")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Define Job Configuration
# MAGIC 
# MAGIC ### Job Configuration Components
# MAGIC 
# MAGIC #### 1. **Tasks**
# MAGIC A job can have multiple tasks that run sequentially or in parallel.
# MAGIC For extraction, we have 1 task: `extract_pdf`
# MAGIC 
# MAGIC #### 2. **Cluster Configuration**
# MAGIC We use a **single-node cluster** for PDF extraction:
# MAGIC - **Why single-node?** PDF extraction is not parallelizable (1 PDF = 1 task)
# MAGIC - **Cost:** ~$0.50-1.00 per extraction (vs $5-10 for multi-node)
# MAGIC - **Spark version:** 14.3.x (latest LTS with stability)
# MAGIC - **Node type:** i3.xlarge (4 cores, 30GB RAM - enough for large PDFs)
# MAGIC 
# MAGIC #### 3. **run_as Configuration** (CRITICAL FOR SECURITY)
# MAGIC Specifies which Service Principal executes the job.
# MAGIC - **MUST have "Service Principal User" role** to use run_as
# MAGIC - **Permissions:** Job inherits ONLY the SP's permissions (least privilege)
# MAGIC 
# MAGIC #### 4. **max_concurrent_runs**
# MAGIC Allows multiple extractions to run in parallel.
# MAGIC - **10 concurrent runs:** Can process 10 PDFs simultaneously
# MAGIC - **Cost consideration:** 10 clusters running = 10x cost
# MAGIC - **Adjust based on:** Expected load and budget
# MAGIC 
# MAGIC #### 5. **Tags**
# MAGIC Metadata for organization, cost tracking, and filtering.
# MAGIC - `project`: Group related jobs
# MAGIC - `agent`: Which agent triggers this job
# MAGIC - `sp`: Which SP is used (for audit/reporting)

print("\nBuilding job configuration...")
print(f"")
print(f"📦 Job Components:")
print(f"   • Task: extract_pdf (runs extraction_job_notebook.py)")
print(f"   • Cluster: Single-node i3.xlarge (cost-optimized for PDF extraction)")
print(f"   • Run As: {extraction_sp_id} (EXTRACTION_SP - least privilege)")
print(f"   • Timeout: 1 hour (sufficient for large PDFs)")
print(f"   • Max Concurrent: 10 extractions simultaneously")

# Create job using Databricks SDK
# Uses proper SDK objects (not raw dictionaries) for type safety
created_job = w.jobs.create(
    name=job_name,
    
    # Define tasks (can have multiple, but we only need 1 for extraction)
    tasks=[
        jobs.Task(
            # Unique identifier for this task (used in multi-task jobs)
            task_key="extract_pdf",
            
            # Human-readable description
            description="Extract text from PDF documents using PyPDF",
            
            # Notebook to execute
            notebook_task=jobs.NotebookTask(
                notebook_path=notebook_path,
                
                # Base parameters passed to the notebook
                # Can be overridden when triggering the job via run_now()
                base_parameters={}
            ),
            
            # Cluster configuration for this task
            # Each task can have its own cluster (or share a job cluster)
            new_cluster=compute.ClusterSpec(
                # Databricks Runtime version (14.3.x = latest LTS)
                # Why LTS? Stability and long-term support
                spark_version="14.3.x-scala2.12",
                
                # Node type: i3.xlarge (4 cores, 30GB RAM)
                # Why? Sufficient for PDF processing, cost-effective
                node_type_id="i3.xlarge",
                
                # Number of worker nodes
                # 0 = single-node cluster (driver only, no workers)
                # Why? PDF extraction is not parallelizable
                num_workers=0,
                
                # Spark configuration for single-node mode
                spark_conf={
                    # Run Spark in local mode (no distributed processing)
                    "spark.master": "local[*]",
                    
                    # Single-node cluster profile (disables distributed features)
                    "spark.databricks.cluster.profile": "singleNode"
                },
                
                # Custom tags for cost tracking and organization
                custom_tags={
                    "ResourceClass": "SingleNode",  # For filtering in cost reports
                    "Purpose": "OncologyPDFExtraction"  # For documentation
                },
                
                # Data security mode (required for Unity Catalog access)
                # SINGLE_USER: Cluster runs with one user's permissions
                # This is required to access Unity Catalog tables/volumes
                data_security_mode=compute.DataSecurityMode.SINGLE_USER,
                
                # Runtime engine: Photon (faster query execution)
                # Photon is Databricks' vectorized query engine
                runtime_engine=compute.RuntimeEngine.PHOTON
            ),
            
            # Task timeout (1 hour)
            # Job will be killed if it runs longer than this
            # Why 1 hour? Large PDFs (500+ pages) can take 30-45 min to extract
            timeout_seconds=3600  # 60 minutes
        )
    ],
    
    # Job-level configurations
    
    # Maximum number of concurrent runs
    # Allows processing multiple PDFs simultaneously
    # Example: 10 users request extraction → 10 jobs run in parallel
    max_concurrent_runs=10,
    
    # Job-level timeout (same as task timeout for single-task jobs)
    timeout_seconds=3600,
    
    # Job tags (for organization and cost tracking)
    tags={
        "project": "oncology_agents",  # Group all oncology-related jobs
        "agent": "extraction_agent",   # Which agent triggers this job
        "sp": "EXTRACTION_SP"          # Which SP is used (for audit reports)
    },
    
    # **CRITICAL:** Configure job to run as EXTRACTION_SP
    # This enforces least-privilege security
    # Job will have ONLY the permissions granted to EXTRACTION_SP
    run_as=jobs.JobRunAs(
        # Service Principal name = Application ID (UUID format)
        service_principal_name=str(extraction_sp_id)
    )
)

print("✅ Job configuration built successfully")
print(f"")
print(f"📊 Job Details:")
print(f"   Name: {job_name}")
print(f"   Run As: {extraction_sp_id} (EXTRACTION_SP)")
print(f"   Tasks: 1 (extract_pdf)")
print(f"   Max Concurrent Runs: 10")
print(f"   Timeout: 3600 seconds (1 hour)")
print(f"")
print(f"🔐 Security: Job runs with EXTRACTION_SP permissions only")
print(f"   → Can write to staging.extracted_documents")
print(f"   → Cannot access summarization resources")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Job Created Successfully
# MAGIC 
# MAGIC ### What Just Happened
# MAGIC The Jobs API created a new job definition in your Databricks workspace.
# MAGIC 
# MAGIC ### Important: Job ID
# MAGIC The `job_id` returned is a **unique identifier** for this job.
# MAGIC **Save this ID** - you'll need it when deploying the agent!
# MAGIC 
# MAGIC ### Next Steps
# MAGIC 1. Verify job in Databricks UI (click the link below)
# MAGIC 2. Check "Run as" configuration shows EXTRACTION_SP
# MAGIC 3. Grant permissions to EXTRACTION_SP (next cell)
# MAGIC 4. Save job ID for agent deployment

# Extract job ID from created job
job_id = created_job.job_id

print("\n" + "="*80)
print("✅ EXTRACTION JOB CREATED SUCCESSFULLY")
print("="*80)
print(f"\nJob Name: {job_name}")
print(f"Job ID: {job_id}")
print(f"Run As: {extraction_sp_id} (EXTRACTION_SP)")
print(f"Notebook: {notebook_path}")

# Construct job URL for verification
workspace_url = w.config.host
print(f"\n🔗 View Job in UI:")
print(f"   {workspace_url}/#job/{job_id}")
print(f"")
print(f"🔍 Verify in UI:")
print(f"   1. Click the link above")
print(f"   2. Check 'Run as' shows: {extraction_sp_id}")
print(f"   3. Check 'Tasks' shows: extract_pdf")
print(f"   4. Check 'Cluster' shows: Single node, i3.xlarge")

print(f"\n📝 **SAVE THIS JOB ID FOR DEPLOYMENT:**")
print(f"   EXTRACTION_JOB_ID={job_id}")
print(f"")
print(f"   You'll need this when running 06_deploy_production_proper.py")

print("="*80)

# Store job ID for later use (if running in a job context)
try:
    # Task values allow passing data between notebook tasks in multi-task jobs
    dbutils.jobs.taskValues.set(key="extraction_job_id", value=str(job_id))
    print(f"✅ Job ID stored in task values (accessible to downstream tasks)")
except:
    # Task values not available when running manually (only in job context)
    pass

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Grant Permissions to Service Principal
# MAGIC 
# MAGIC ### Why Grant Permissions?
# MAGIC Even though the job is configured to `run_as` the Service Principal,
# MAGIC the SP still needs **explicit permission** to trigger the job.
# MAGIC 
# MAGIC ### Permission Levels for Jobs
# MAGIC - **CAN_VIEW:** Can see the job (read-only)
# MAGIC - **CAN_MANAGE_RUN:** Can trigger runs, view run history, cancel runs
# MAGIC - **CAN_MANAGE:** Full control (edit job, delete job, grant permissions)
# MAGIC 
# MAGIC ### Why CAN_MANAGE_RUN?
# MAGIC This is the **minimum permission** needed for the agent to trigger the job.
# MAGIC - ✅ Can trigger new runs via `jobs.run_now()`
# MAGIC - ✅ Can view run status via `jobs.get_run()`
# MAGIC - ✅ Can cancel stuck runs via `jobs.cancel_run()`
# MAGIC - ❌ Cannot modify job configuration
# MAGIC - ❌ Cannot delete the job
# MAGIC 
# MAGIC ### Common Error
# MAGIC If you see "Access denied" when the agent tries to trigger the job,
# MAGIC it means this permission grant failed. You can manually grant it via UI:
# MAGIC 1. Go to the job page (link above)
# MAGIC 2. Click "Permissions"
# MAGIC 3. Add EXTRACTION_SP with "Can manage run" permission

try:
    from databricks.sdk.service.iam import PermissionLevel, AccessControlRequest
    
    print(f"Granting CAN_MANAGE_RUN permission to SP: {extraction_sp_id}")
    print(f"")
    print(f"📋 Permission Details:")
    print(f"   Service Principal: {extraction_sp_id}")
    print(f"   Permission Level: CAN_MANAGE_RUN")
    print(f"   Allows: Trigger runs, view status, cancel runs")
    print(f"   Denies: Edit job config, delete job, grant permissions")
    
    # Update permissions via Permissions API
    w.permissions.update(
        # Object type (jobs, clusters, notebooks, etc.)
        request_object_type="jobs",
        
        # Object ID (the job we just created)
        request_object_id=str(job_id),
        
        # Access control list (who gets what permission)
        access_control_list=[
            AccessControlRequest(
                # Service Principal identifier (Application ID)
                service_principal_name=str(extraction_sp_id),
                
                # Permission level to grant
                permission_level=PermissionLevel.CAN_MANAGE_RUN
            )
        ]
    )
    
    print(f"")
    print(f"✅ Granted permissions to EXTRACTION_SP")
    print(f"   → Agent can now trigger this job via Jobs API")
    
except Exception as e:
    # Permission grant can fail if:
    # 1. User doesn't have permission to grant permissions (need CAN_MANAGE on job)
    # 2. Service Principal doesn't exist in workspace
    # 3. Network/API issues
    
    print(f"⚠️  Could not grant permissions automatically: {e}")
    print(f"")
    print(f"📝 Manual workaround:")
    print(f"   1. Go to: {workspace_url}/#job/{job_id}")
    print(f"   2. Click 'Permissions' tab")
    print(f"   3. Click 'Add' or 'Grant'")
    print(f"   4. Search for: {extraction_sp_id}")
    print(f"   5. Select permission: 'Can manage run'")
    print(f"   6. Click 'Save'")
    print(f"")
    print(f"   Without this permission, the agent will get 'Access denied' errors!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Optional - Test Job
# MAGIC 
# MAGIC ### Should You Test Now?
# MAGIC **Not required!** The agent will trigger this job automatically.
# MAGIC 
# MAGIC **However**, testing now can help verify:
# MAGIC - ✅ Job configuration is correct
# MAGIC - ✅ Notebook path is valid
# MAGIC - ✅ Service Principal has necessary permissions
# MAGIC - ✅ Cluster can be created successfully
# MAGIC - ✅ Extraction logic works
# MAGIC 
# MAGIC ### How to Test
# MAGIC Uncomment the code below and run this cell.
# MAGIC 
# MAGIC **Note:** Test run will likely fail because:
# MAGIC - Sample PDF doesn't exist yet
# MAGIC - CQRS tables may not be fully set up
# MAGIC But it will verify the job infrastructure works!

# Uncomment to test:
# print(f"🚀 Triggering test run of job {job_id}...")
# 
# run = w.jobs.run_now(
#     job_id=job_id,
#     notebook_params={
#         "document_path": "/Volumes/sselvan_banner/oncology/source_pdfs/test_document.pdf",
#         "triggered_by": "setup_script_test",
#         "catalog_name": "sselvan_banner",
#         "schema_name": "oncology"
#     }
# )
# 
# print(f"✅ Test run started: Run ID {run.run_id}")
# print(f"🔗 View Run: {workspace_url}/#job/{job_id}/run/{run.run_id}")
# print(f"")
# print(f"📊 The job will:")
# print(f"   1. Start a single-node cluster (~3 min)")
# print(f"   2. Install PyPDF library (~1 min)")
# print(f"   3. Extract PDF content (~5 min for sample)")
# print(f"   4. Write to staging.extracted_documents")
# print(f"   5. Log event to job_events table")
# print(f"")
# print(f"⚠️  Test may fail if:")
# print(f"   • Sample PDF doesn't exist")
# print(f"   • CQRS tables not created yet")
# print(f"   • Permissions not granted")
# print(f"   → This is expected! Real PDFs will be added later.")

print("✅ Test job cell ready (uncomment to run)")
print(f"   Skipping test for now - job will be tested end-to-end after agent deployment")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Return Job Info
# MAGIC 
# MAGIC ### Notebook Exit Values
# MAGIC When a notebook is run as part of a multi-task job, it can return values
# MAGIC to be consumed by downstream tasks.
# MAGIC 
# MAGIC **Why JSON format?**
# MAGIC - Standard format for structured data
# MAGIC - Easy to parse in downstream tasks or orchestration scripts
# MAGIC - Can include multiple fields (status, job_id, job_name, etc.)
# MAGIC 
# MAGIC **How to access in downstream tasks:**
# MAGIC ```python
# MAGIC upstream_output = dbutils.jobs.taskValues.get(
# MAGIC     taskKey="create_extraction_job",
# MAGIC     key="result"
# MAGIC )
# MAGIC result = json.loads(upstream_output)
# MAGIC extraction_job_id = result["job_id"]
# MAGIC ```

# Return job information as JSON
# This can be consumed by downstream tasks in orchestrated workflows
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "job_id": job_id,
    "job_name": job_name,
    "sp_used": extraction_sp_id,
    "notebook_path": notebook_path
}))

