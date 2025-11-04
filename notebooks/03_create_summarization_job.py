# Databricks notebook source
# MAGIC %md
# MAGIC # Create Summarization Job
# MAGIC 
# MAGIC Creates a Databricks job that:
# MAGIC - Runs summarization_job_notebook.py
# MAGIC - Configured to run as SUMMARIZATION_SP
# MAGIC - Can be triggered by SummarizationAgent
# MAGIC 
# MAGIC **Run this once during setup**

# COMMAND ----------

# MAGIC %pip install databricks-sdk --quiet
dbutils.library.restartPython()

# COMMAND ----------

# Parameters - UPDATE WITH YOUR SP APPLICATION ID
dbutils.widgets.text("summarization_sp_id", "YOUR_SUMMARIZATION_SP_APPLICATION_ID", "Summarization SP ID")
dbutils.widgets.text("notebook_path", "/Workspace/Users/<YOUR_EMAIL>/multi_agent_demo/summarization_job_notebook_REAL", "Summarization Notebook Path")

summarization_sp_id = dbutils.widgets.get("summarization_sp_id")
notebook_path = dbutils.widgets.get("notebook_path")

if not summarization_sp_id or summarization_sp_id == "<YOUR_SUMMARIZATION_SP_APPLICATION_ID>":
    raise ValueError("⚠️ Please update summarization_sp_id with your actual Summarization SP Application ID (UUID format)")

print(f"Creating summarization job with:")
print(f"  SP ID: {summarization_sp_id}")
print(f"  Notebook: {notebook_path}")

# COMMAND ----------

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs, compute
import json

w = WorkspaceClient()

# Get current user for job naming
user = w.current_user.me()
user_name = user.user_name.split("@")[0]

job_name = f"{user_name}_oncology_summarization_job"

print(f"Creating job: {job_name}")

# COMMAND ----------

# Define job configuration using proper SDK objects
print("\nBuilding job configuration...")

created_job = w.jobs.create(
    name=job_name,
    tasks=[
        jobs.Task(
            task_key="summarize_document",
            description="Generate clinical summary from extracted text",
            notebook_task=jobs.NotebookTask(
                notebook_path=notebook_path,
                base_parameters={}
            ),
            new_cluster=compute.ClusterSpec(
                spark_version="14.3.x-scala2.12",
                node_type_id="i3.xlarge",
                num_workers=0,  # Single node for summarization
                spark_conf={
                    "spark.master": "local[*]",
                    "spark.databricks.cluster.profile": "singleNode"
                },
                custom_tags={
                    "ResourceClass": "SingleNode",
                    "Purpose": "OncologySummarization"
                }
            ),
            timeout_seconds=1800  # 30 min timeout
        )
    ],
    max_concurrent_runs=10,
    timeout_seconds=1800,
    tags={
        "project": "oncology_agents",
        "agent": "summarization_agent",
        "sp": "SUMMARIZATION_SP"
    },
    run_as=jobs.JobRunAs(
        service_principal_name=str(summarization_sp_id)
    )
)

print("✅ Job configuration built")
print(f"  Name: {job_name}")
print(f"  Run As: {summarization_sp_id} (SUMMARIZATION_SP)")
print(f"  Tasks: 1 (summarize_document)")
print(f"  Max Concurrent Runs: 10")

# COMMAND ----------

# Job created successfully
job_id = created_job.job_id

print("\n" + "="*80)
print("✅ SUMMARIZATION JOB CREATED")
print("="*80)
print(f"\nJob Name: {job_name}")
print(f"Job ID: {job_id}")
print(f"Run As: {summarization_sp_id} (SUMMARIZATION_SP)")
print(f"Notebook: {notebook_path}")
print(f"\n🔗 View Job:")
workspace_url = w.config.host
print(f"   {workspace_url}/#job/{job_id}")
print(f"\n📝 Save this Job ID for deployment:")
print(f"   SUMMARIZATION_JOB_ID={job_id}")
print("="*80)

# Store job ID for later use
try:
    dbutils.jobs.taskValues.set(key="summarization_job_id", value=str(job_id))
except:
    pass  # Task values not available in all contexts

# COMMAND ----------

# Grant permissions
try:
    from databricks.sdk.service.iam import PermissionLevel, AccessControlRequest
    
    print(f"Granting CAN_MANAGE_RUN permission to SP: {summarization_sp_id}")
    
    w.permissions.update(
        request_object_type="jobs",
        request_object_id=str(job_id),
        access_control_list=[
            AccessControlRequest(
                service_principal_name=str(summarization_sp_id),
                permission_level=PermissionLevel.CAN_MANAGE_RUN
            )
        ]
    )
    
    print(f"✅ Granted permissions to SUMMARIZATION_SP")
    
except Exception as e:
    print(f"⚠️  Could not grant permissions (may need to do manually): {e}")
    print(f"   You can manually grant CAN_MANAGE_RUN to the SP via the UI if needed")

# COMMAND ----------

# Return job ID
dbutils.notebook.exit(json.dumps({
    "status": "SUCCESS",
    "job_id": job_id,
    "job_name": job_name
}))

