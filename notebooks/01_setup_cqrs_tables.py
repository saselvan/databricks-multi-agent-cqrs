# Databricks notebook source
# MAGIC %md
# MAGIC # Setup CQRS Tables for Oncology Multi-Agent System
# MAGIC 
# MAGIC Creates Delta tables for:
# MAGIC - **job_events**: Event store for all agent actions (immutable audit log)
# MAGIC - **conversation_state**: Workflow tracking per user
# MAGIC - **staging tables**: For PDF extraction and summarization data
# MAGIC 
# MAGIC **Security**: All agents log which SP was used for each action

# COMMAND ----------

# MAGIC %pip install databricks-sdk --quiet
dbutils.library.restartPython()

# COMMAND ----------

# Parameters
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"Creating CQRS tables in: {catalog_name}.{schema_name}")

# COMMAND ----------

# Create catalog and schema
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog_name}")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.{schema_name}")

# For demo, we'll use the same catalog for staging tables
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.staging")

# Create Unity Catalog Volumes (modern, governed file storage)
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog_name}.{schema_name}.summaries")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog_name}.{schema_name}.source_pdfs")

print(f"✅ Catalog created: {catalog_name}")
print(f"✅ Schemas created: {schema_name}, staging")
print(f"✅ Volumes created: summaries, source_pdfs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Job Events Table (Event Store)
# MAGIC 
# MAGIC Records every action taken by any agent:
# MAGIC - Which agent performed the action
# MAGIC - Which SP was used (EXTRACTION_SP, SUMMARIZATION_SP, SHAREPOINT_SP)
# MAGIC - Timestamp and status
# MAGIC - Immutable append-only log for compliance

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.job_events (
  event_id STRING NOT NULL COMMENT 'Unique event identifier',
  event_type STRING NOT NULL COMMENT 'ExtractionJobStarted, ExtractionJobCompleted, etc.',
  run_id BIGINT NOT NULL COMMENT 'Databricks job run ID',
  agent STRING NOT NULL COMMENT 'extraction_agent, summarization_agent, sharepoint_agent',
  sp_used STRING NOT NULL COMMENT 'EXTRACTION_SP, SUMMARIZATION_SP, SHAREPOINT_SP',
  triggered_by STRING COMMENT 'User who triggered the action',
  timestamp TIMESTAMP NOT NULL COMMENT 'Event timestamp',
  status STRING COMMENT 'SUCCESS, FAILED, RUNNING',
  details STRING COMMENT 'Additional details (JSON)',
  
  CONSTRAINT pk_job_events PRIMARY KEY (event_id)
)
USING DELTA
COMMENT 'Event store for all agent actions (CQRS pattern - immutable audit log)'
TBLPROPERTIES (
  'delta.enableChangeDataFeed' = 'true',
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true'
)
""")

print("✅ Created job_events table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Conversation State Table (Workflow Tracking)
# MAGIC 
# MAGIC Tracks multi-stage workflows per user:
# MAGIC - Current stage (extracting, summarizing, uploading, completed)
# MAGIC - Run IDs for each stage
# MAGIC - Allows agent to automatically advance workflow

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.conversation_state (
  state_id STRING NOT NULL COMMENT 'Unique state identifier',
  user_id STRING NOT NULL COMMENT 'User identifier',
  document_path STRING COMMENT 'Path to source PDF',
  extraction_run_id BIGINT COMMENT 'Extraction job run ID',
  summarization_run_id BIGINT COMMENT 'Summarization job run ID',
  current_stage STRING NOT NULL COMMENT 'extracting, summarizing, uploading, completed',
  triggered_at TIMESTAMP NOT NULL COMMENT 'When workflow was started',
  status STRING NOT NULL COMMENT 'in_progress, completed, failed',
  
  CONSTRAINT pk_conversation_state PRIMARY KEY (state_id)
)
USING DELTA
COMMENT 'Tracks multi-stage workflows per user (CQRS query optimization)'
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true'
)
""")

print("✅ Created conversation_state table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Staging Tables (Intermediate Data)
# MAGIC 
# MAGIC Security isolation:
# MAGIC - **extracted_documents**: Only EXTRACTION_SP can write, only SUMMARIZATION_SP can read
# MAGIC - **summaries**: Only SUMMARIZATION_SP can write, only SHAREPOINT_SP can read

# COMMAND ----------

# Extracted Documents Table
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.staging.extracted_documents (
  extraction_id STRING NOT NULL PRIMARY KEY,
  extraction_run_id BIGINT NOT NULL,
  document_path STRING NOT NULL,
  extracted_text STRING,
  page_count INT,
  extracted_at TIMESTAMP,
  extracted_by STRING COMMENT 'SP that performed extraction'
)
USING DELTA
COMMENT 'Extracted PDF content (EXTRACTION_SP writes, SUMMARIZATION_SP reads)'
""")

print("✅ Created staging.extracted_documents table")

# COMMAND ----------

# Summaries Table
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.staging.summaries (
  summary_id STRING NOT NULL PRIMARY KEY,
  summarization_run_id BIGINT NOT NULL,
  extraction_run_id BIGINT NOT NULL,
  summary_text STRING,
  document_metadata STRING COMMENT 'JSON with metadata',
  summarized_at TIMESTAMP,
  summarized_by STRING COMMENT 'SP that performed summarization'
)
USING DELTA
COMMENT 'Summarized content (SUMMARIZATION_SP writes, SHAREPOINT_SP reads)'
""")

print("✅ Created staging.summaries table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Helper Views

# COMMAND ----------

# Latest job status per run_id
spark.sql(f"""
CREATE OR REPLACE VIEW {catalog_name}.{schema_name}.job_status_latest AS
WITH ranked_events AS (
  SELECT 
    run_id,
    agent,
    sp_used,
    event_type,
    timestamp,
    ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY timestamp DESC) as rn
  FROM {catalog_name}.{schema_name}.job_events
)
SELECT 
  run_id,
  agent,
  sp_used,
  event_type as latest_status,
  timestamp as last_updated
FROM ranked_events
WHERE rn = 1
""")

print("✅ Created job_status_latest view")

# COMMAND ----------

# Active workflows
spark.sql(f"""
CREATE OR REPLACE VIEW {catalog_name}.{schema_name}.active_workflows AS
SELECT 
  cs.user_id,
  cs.document_path,
  cs.extraction_run_id,
  cs.summarization_run_id,
  cs.current_stage,
  cs.triggered_at,
  CAST((unix_timestamp() - unix_timestamp(cs.triggered_at)) / 60 AS INT) as elapsed_minutes
FROM {catalog_name}.{schema_name}.conversation_state cs
WHERE cs.status = 'in_progress'
  AND cs.triggered_at > current_timestamp() - INTERVAL 2 HOURS
ORDER BY cs.triggered_at DESC
""")

print("✅ Created active_workflows view")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verification

# COMMAND ----------

print("\n" + "="*80)
print("✅ CQRS TABLES SETUP COMPLETE")
print("="*80)
print(f"\nCatalog: {catalog_name}")
print(f"Schema: {schema_name}")
print("\nCreated tables:")
print(f"  • {catalog_name}.{schema_name}.job_events (event store)")
print(f"  • {catalog_name}.{schema_name}.conversation_state (workflow tracking)")
print(f"  • {catalog_name}.staging.extracted_documents (intermediate)")
print(f"  • {catalog_name}.staging.summaries (intermediate)")
print("\nCreated views:")
print(f"  • {catalog_name}.{schema_name}.job_status_latest")
print(f"  • {catalog_name}.{schema_name}.active_workflows")
print("\n🔐 Security Notes:")
print("  • job_events: All agents write (audit trail)")
print("  • extracted_documents: EXTRACTION_SP writes, SUMMARIZATION_SP reads")
print("  • summaries: SUMMARIZATION_SP writes, SHAREPOINT_SP reads")
print("\nNext steps:")
print("  1. Run 02_create_extraction_job.py")
print("  2. Run 03_create_summarization_job.py")
print("  3. Run 04_deploy_coordinator.py")

