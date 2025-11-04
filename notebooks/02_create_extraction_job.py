# Databricks notebook source
# MAGIC %md
# MAGIC # Create PDF Extraction Job
# MAGIC 
# MAGIC Creates a Databricks job that:
# MAGIC - Runs extraction_job_notebook.py
# MAGIC - Configured to run as EXTRACTION_SP
# MAGIC - Can be triggered by ExtractionAgent
# MAGIC 
# MAGIC **Run this once during setup**

# COMMAND ----------

# MAGIC %pip install databricks-sdk --quiet
dbutils.library.restartPython()

# COMMAND ----------

# Parameters - UPDATE WITH YOUR SP APPLICATION ID
dbutils.widgets.text("extraction_sp_id", "<YOUR_EXTRACTION_SP_APPLICATION_ID>", "Extraction SP ID")
dbutils.widgets.text("notebook_path", "/Workspace/Users/samuel.selvan@databricks.com/banner_oncology/extraction_job_notebook", "Extraction Notebook Path")

extraction_sp_id = dbutils.widgets.get("extraction_sp_id")
notebook_path = dbutils.widgets.get("notebook_path")

if not extraction_sp_id or extraction_sp_id == "<YOUR_EXTRACTION_SP_APPLICATION_ID>":
    raise ValueError("⚠️ Please update extraction_sp_id with your actual Extraction SP Application ID (UUID format)")

print(f"Creating extraction job with:")
print(f"  SP ID: {extraction_sp_id}")
print(f"  Notebook: {notebook_path}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Job Definition

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs, compute
import json

w = WorkspaceClient()

# Get current user for job naming
user = w.current_user.me()
user_name = user.user_name.split("@")[0]

job_name = f"{user_name}_oncology_extraction_job"

print(f"Creating job: {job_name}")

# COMMAND ----------

# Define job configuration using proper SDK objects
# NOTE: You must have 'servicePrincipal.user' role on the SP to use run_as
print("\nBuilding job configuration...")

created_job = w.jobs.create(
    name=job_name,
    tasks=[
        jobs.Task(
            task_key="extract_pdf",
            description="Extract text from PDF documents",
            notebook_task=jobs.NotebookTask(
                notebook_path=notebook_path,
                base_parameters={}
            ),
            new_cluster=compute.ClusterSpec(
                spark_version="14.3.x-scala2.12",
                node_type_id="i3.xlarge",
                num_workers=0,  # Single node for PDF extraction
                spark_conf={
                    "spark.master": "local[*]",
                    "spark.databricks.cluster.profile": "singleNode"
                },
                custom_tags={
                    "ResourceClass": "SingleNode",
                    "Purpose": "OncologyPDFExtraction"
                }
            ),
            timeout_seconds=3600  # 1 hour timeout (pypdf installed in notebook)
        )
    ],
    max_concurrent_runs=10,  # Allow multiple concurrent extractions
    timeout_seconds=3600,
    tags={
        "project": "oncology_agents",
        "agent": "extraction_agent",
        "sp": "EXTRACTION_SP"
    },
    run_as=jobs.JobRunAs(
        service_principal_name=str(extraction_sp_id)
    )
)

print("✅ Job configuration built")
print(f"  Name: {job_name}")
print(f"  Run As: {extraction_sp_id} (EXTRACTION_SP)")
print(f"  Tasks: 1 (extract_pdf)")
print(f"  Max Concurrent Runs: 10")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Job Created Successfully
# MAGIC 
# MAGIC **Security:** Job will run as EXTRACTION_SP

# COMMAND ----------

job_id = created_job.job_id

print("\n" + "="*80)
print("✅ EXTRACTION JOB CREATED")
print("="*80)
print(f"\nJob Name: {job_name}")
print(f"Job ID: {job_id}")
print(f"Run As: {extraction_sp_id} (EXTRACTION_SP)")
print(f"Notebook: {notebook_path}")
print(f"\n🔗 View Job:")
workspace_url = w.config.host
print(f"   {workspace_url}/#job/{job_id}")
print(f"\n📝 Save this Job ID for deployment:")
print(f"   EXTRACTION_JOB_ID={job_id}")
print("="*80)

# Store job ID for later use
try:
    dbutils.jobs.taskValues.set(key="extraction_job_id", value=str(job_id))
except:
    pass  # Task values not available in all contexts

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grant Permissions
# MAGIC 
# MAGIC Grant EXTRACTION_SP permission to run this job

# COMMAND ----------

try:
    from databricks.sdk.service.iam import PermissionLevel, AccessControlRequest
    
    print(f"Granting CAN_MANAGE_RUN permission to SP: {extraction_sp_id}")
    
    w.permissions.update(
        request_object_type="jobs",
        request_object_id=str(job_id),
        access_control_list=[
            AccessControlRequest(
                service_principal_name=str(extraction_sp_id),
                permission_level=PermissionLevel.CAN_MANAGE_RUN
            )
        ]
    )
    
    print(f"✅ Granted permissions to EXTRACTION_SP")
    
except Exception as e:
    print(f"⚠️  Could not grant permissions (may need to do manually): {e}")
    print(f"   You can manually grant CAN_MANAGE_RUN to the SP via the UI if needed")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Test Job (Optional)

# COMMAND ----------

test_run = input("Test run the job? (yes/no): ")

if test_run.lower() == "yes":
    print(f"🚀 Triggering test run of job {job_id}...")
    
    run = w.jobs.run_now(
        job_id=job_id,
        notebook_params={
            "document_path": "/source_pdfs/test_document.pdf",
            "triggered_by": "setup_script"
        }
    )
    
    print(f"✅ Test run started: Run ID {run.run_id}")
    print(f"🔗 View Run: {workspace_url}/#job/{job_id}/run/{run.run_id}")
    print(f"\nThe job will:")
    print(f"  1. Extract PDF content")
    print(f"  2. Write to staging.extracted_documents")
    print(f"  3. Log event to oncology_cqrs.job_events")

# COMMAND ----------

# Return job ID
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "job_id": job_id,
    "job_name": job_name
}))

