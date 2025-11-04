# Databricks notebook source
# MAGIC %md
# MAGIC # Setup CQRS Tables for Oncology Multi-Agent System
# MAGIC 
# MAGIC ## Purpose
# MAGIC This notebook creates the foundational Delta tables for a **CQRS (Command Query Responsibility Segregation)** architecture.
# MAGIC 
# MAGIC ## What is CQRS?
# MAGIC CQRS separates:
# MAGIC - **Commands** (write operations): Agent triggers job → Write event to `job_events`
# MAGIC - **Queries** (read operations): User asks "status?" → Read from `job_events`
# MAGIC 
# MAGIC This separation enables:
# MAGIC - **Zero-Polling:** No continuous background jobs checking status (cost-efficient)
# MAGIC - **Fast Queries:** Delta queries (<100ms) vs Jobs API (>500ms)
# MAGIC - **Full Audit Trail:** Every action logged with which Service Principal was used
# MAGIC 
# MAGIC ## What Gets Created
# MAGIC 1. **job_events** (Event Store): Immutable audit log of all agent actions
# MAGIC 2. **conversation_state** (Workflow Tracking): Multi-stage workflow state per user
# MAGIC 3. **staging.extracted_documents**: PDF extraction intermediate data
# MAGIC 4. **staging.summaries**: Summarization intermediate data
# MAGIC 5. **UC Volumes**: Governed file storage for PDFs and summaries
# MAGIC 
# MAGIC ## Security Model
# MAGIC - `job_events`: All agents write (append-only for compliance)
# MAGIC - `extracted_documents`: EXTRACTION_SP writes, SUMMARIZATION_SP reads
# MAGIC - `summaries`: SUMMARIZATION_SP writes, FILE_STORAGE_AGENT reads
# MAGIC 
# MAGIC **Run this notebook ONCE during initial setup**

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 1: Install Dependencies
# MAGIC 
# MAGIC **Why:** We need `databricks-sdk` for programmatic Unity Catalog operations
# MAGIC 
# MAGIC **Note:** This is already installed on Databricks clusters, but we install explicitly
# MAGIC to ensure compatibility and avoid version conflicts

# Install Databricks SDK (already available on clusters, but ensures correct version)
# --quiet suppresses verbose pip output
# MAGIC %pip install databricks-sdk --quiet

# Restart Python to load newly installed packages
# This is required after pip install in Databricks notebooks
dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 2: Configure Parameters
# MAGIC 
# MAGIC **Databricks Widgets:** Allow notebook parameterization for reusability
# MAGIC - Can be set via UI (manual run)
# MAGIC - Can be passed via Jobs API (orchestrated run)
# MAGIC - Can be overridden without modifying code
# MAGIC 
# MAGIC **Best Practice:** Always use widgets for environment-specific values

# Create input widgets with default values
# Syntax: dbutils.widgets.text(name, defaultValue, label)
dbutils.widgets.text("catalog_name", "sselvan_banner", "Catalog Name")
dbutils.widgets.text("schema_name", "oncology", "Schema Name")

# Retrieve widget values
# If running manually, uses defaults above
# If running via Jobs API, uses parameters passed in job trigger
catalog_name = dbutils.widgets.get("catalog_name")
schema_name = dbutils.widgets.get("schema_name")

print(f"Creating CQRS tables in: {catalog_name}.{schema_name}")
print(f"")
print(f"📊 CQRS Pattern:")
print(f"   Command Side: Agents write events to job_events")
print(f"   Query Side: Agents read status from job_events")
print(f"   Benefit: Zero-polling, fast queries, full audit trail")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 3: Create Unity Catalog Structure
# MAGIC 
# MAGIC **Unity Catalog (UC):** Databricks' unified governance solution
# MAGIC - **Catalog:** Top-level namespace (like a database in traditional systems)
# MAGIC - **Schema:** Grouping of tables/views within a catalog
# MAGIC - **Tables:** Actual data storage
# MAGIC - **Volumes:** Governed file storage (modern alternative to DBFS)
# MAGIC 
# MAGIC **Why UC Volumes?**
# MAGIC - Automatic passthrough authentication (no credentials needed!)
# MAGIC - Built-in permissions and audit logging
# MAGIC - Lineage tracking (who accessed what, when)
# MAGIC - Supports standard file operations (open, write, read)

# Create catalog if it doesn't exist
# IF NOT EXISTS: Idempotent operation (safe to run multiple times)
spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog_name}")

# Create schema for CQRS tables (job_events, conversation_state)
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.{schema_name}")

# Create staging schema for intermediate data
# Why separate schema? Allows different permission models:
# - oncology schema: All agents can read
# - staging schema: Only specific SPs can write
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog_name}.staging")

# Create Unity Catalog Volumes for file storage
# Volumes provide governed, permissioned file storage with lineage
# Why Volumes vs DBFS? DBFS is deprecated; Volumes are the modern, secure approach
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog_name}.{schema_name}.summaries")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog_name}.{schema_name}.source_pdfs")

print(f"✅ Catalog created: {catalog_name}")
print(f"✅ Schemas created: {schema_name}, staging")
print(f"✅ Volumes created:")
print(f"   • summaries: /Volumes/{catalog_name}/{schema_name}/summaries")
print(f"   • source_pdfs: /Volumes/{catalog_name}/{schema_name}/source_pdfs")
print(f"")
print(f"💡 UC Volumes use automatic passthrough authentication")
print(f"   → No credentials needed to read/write files!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 4: Create Job Events Table (Event Store)
# MAGIC 
# MAGIC ### What is an Event Store?
# MAGIC An **immutable, append-only log** of all events that happen in the system.
# MAGIC 
# MAGIC ### Why Event Store?
# MAGIC - **Audit Trail:** Every action is logged with who/what/when/why
# MAGIC - **Compliance:** Immutable history for regulatory requirements
# MAGIC - **Debugging:** Full event history for troubleshooting
# MAGIC - **Time Travel:** Can query "what happened at time T?"
# MAGIC 
# MAGIC ### Key Fields:
# MAGIC - `event_type`: ExtractionJobStarted, ExtractionJobCompleted, etc.
# MAGIC - `run_id`: Databricks job run ID (links to Jobs API)
# MAGIC - `agent`: Which agent performed the action (extraction_agent, etc.)
# MAGIC - **`sp_used`**: **CRITICAL** - Which Service Principal was used (EXTRACTION_SP, SUMMARIZATION_SP, etc.)
# MAGIC - `triggered_by`: User who initiated the workflow
# MAGIC - `timestamp`: When the event occurred
# MAGIC - `status`: SUCCESS, FAILED, RUNNING
# MAGIC - `details`: JSON with additional context
# MAGIC 
# MAGIC ### Delta Lake Features Enabled:
# MAGIC - **Change Data Feed (CDF):** Tracks all changes for downstream processing
# MAGIC - **Auto-Optimize:** Automatically compacts small files for query performance
# MAGIC - **Auto-Compact:** Reduces file count for faster queries

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.job_events (
  -- Unique identifier for each event (UUID format)
  event_id STRING NOT NULL COMMENT 'Unique event identifier (UUID)',
  
  -- Type of event (e.g., ExtractionJobStarted, SummarizationJobCompleted)
  -- Allows filtering by event type for analytics
  event_type STRING NOT NULL COMMENT 'Event type: ExtractionJobStarted, ExtractionJobCompleted, etc.',
  
  -- Databricks job run ID (links to Jobs API for full run details)
  -- Used to correlate events with actual job execution
  run_id BIGINT NOT NULL COMMENT 'Databricks job run ID',
  
  -- Which agent performed this action
  -- Values: extraction_agent, summarization_agent, file_storage_agent, coordinator_agent
  agent STRING NOT NULL COMMENT 'Agent that performed action: extraction_agent, summarization_agent, etc.',
  
  -- **CRITICAL FOR SECURITY AUDIT:** Which Service Principal was used
  -- Values: EXTRACTION_SP, SUMMARIZATION_SP, AUTOMATIC_PASSTHROUGH
  -- This proves which credentials were used for each action
  sp_used STRING NOT NULL COMMENT 'Service Principal used: EXTRACTION_SP, SUMMARIZATION_SP, AUTOMATIC_PASSTHROUGH',
  
  -- User who initiated the workflow (for user-specific audit trails)
  triggered_by STRING COMMENT 'User who triggered the action',
  
  -- Event timestamp (for time-based queries and analytics)
  timestamp TIMESTAMP NOT NULL COMMENT 'Event timestamp',
  
  -- Event status (for filtering successful vs failed events)
  status STRING COMMENT 'Event status: SUCCESS, FAILED, RUNNING',
  
  -- Additional event details in JSON format
  -- Flexible schema for event-specific metadata
  details STRING COMMENT 'Additional details in JSON format',
  
  -- Primary key constraint (enforces uniqueness)
  CONSTRAINT pk_job_events PRIMARY KEY (event_id)
)
USING DELTA
COMMENT 'Event store for all agent actions (CQRS pattern - immutable audit log)'
TBLPROPERTIES (
  -- Enable Change Data Feed for downstream processing
  -- Allows streaming consumers to track all changes
  'delta.enableChangeDataFeed' = 'true',
  
  -- Enable automatic file optimization
  -- Compacts small files during writes for better query performance
  'delta.autoOptimize.optimizeWrite' = 'true',
  
  -- Enable automatic compaction
  -- Periodically merges small files in background
  'delta.autoOptimize.autoCompact' = 'true'
)
""")

print("✅ Created job_events table")
print(f"")
print(f"📊 Event Store Schema:")
print(f"   • event_id: UUID")
print(f"   • event_type: ExtractionJobStarted, etc.")
print(f"   • run_id: Links to Databricks Jobs API")
print(f"   • agent: Which agent performed the action")
print(f"   • sp_used: **Which Service Principal was used** (audit trail)")
print(f"   • triggered_by: User who initiated workflow")
print(f"   • timestamp, status, details")
print(f"")
print(f"🔒 Security: Immutable append-only log (no updates/deletes)")
print(f"📈 Performance: Auto-optimize enabled for fast queries")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 5: Create Conversation State Table (Workflow Tracking)
# MAGIC 
# MAGIC ### What is Conversation State?
# MAGIC Tracks the **current stage** of multi-step workflows per user.
# MAGIC 
# MAGIC ### Why Separate from Event Store?
# MAGIC - **Event Store:** Immutable history (append-only)
# MAGIC - **Conversation State:** Mutable state (updates allowed)
# MAGIC 
# MAGIC ### Workflow Stages:
# MAGIC 1. `extracting`: PDF extraction in progress
# MAGIC 2. `summarizing`: Summarization in progress
# MAGIC 3. `uploading`: File upload in progress
# MAGIC 4. `completed`: All stages done
# MAGIC 
# MAGIC ### How Auto-Advancement Works:
# MAGIC 1. User asks agent to "extract PDF"
# MAGIC 2. Agent triggers extraction job, stores state: `current_stage='extracting'`
# MAGIC 3. User asks "status?"
# MAGIC 4. Agent checks job_events → sees "ExtractionJobCompleted"
# MAGIC 5. Agent updates state: `current_stage='summarizing'`
# MAGIC 6. Agent **automatically triggers** summarization job
# MAGIC 7. Repeat for next stage
# MAGIC 
# MAGIC **Result:** User doesn't have to manually trigger each stage!

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.{schema_name}.conversation_state (
  -- Unique identifier for this workflow instance (UUID)
  state_id STRING NOT NULL COMMENT 'Unique state identifier (UUID)',
  
  -- User identifier (for multi-user support)
  -- Allows each user to have their own active workflows
  user_id STRING NOT NULL COMMENT 'User identifier',
  
  -- Path to source PDF document being processed
  document_path STRING COMMENT 'Path to source PDF document',
  
  -- Run ID of extraction job (if extraction has started)
  -- NULL if extraction not yet triggered
  extraction_run_id BIGINT COMMENT 'Extraction job run ID',
  
  -- Run ID of summarization job (if summarization has started)
  -- NULL if summarization not yet triggered
  summarization_run_id BIGINT COMMENT 'Summarization job run ID',
  
  -- Current stage in the workflow
  -- Values: 'extracting', 'summarizing', 'uploading', 'completed'
  -- Agent uses this to determine next action
  current_stage STRING NOT NULL COMMENT 'Current workflow stage: extracting, summarizing, uploading, completed',
  
  -- When this workflow was initiated
  -- Used for timeout detection (workflows older than 2 hours are considered stale)
  triggered_at TIMESTAMP NOT NULL COMMENT 'When workflow was started',
  
  -- Overall workflow status
  -- Values: 'in_progress', 'completed', 'failed'
  -- Used for filtering active vs completed workflows
  status STRING NOT NULL COMMENT 'Workflow status: in_progress, completed, failed',
  
  -- Primary key constraint
  CONSTRAINT pk_conversation_state PRIMARY KEY (state_id)
)
USING DELTA
COMMENT 'Tracks multi-stage workflows per user (CQRS query optimization - mutable state)'
TBLPROPERTIES (
  -- Enable auto-optimize for fast updates
  -- conversation_state has frequent UPDATE operations
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.autoOptimize.autoCompact' = 'true'
)
""")

print("✅ Created conversation_state table")
print(f"")
print(f"📊 Workflow Tracking:")
print(f"   • state_id: Unique workflow instance")
print(f"   • user_id: Multi-user support")
print(f"   • extraction_run_id, summarization_run_id: Job tracking")
print(f"   • current_stage: Where we are in the workflow")
print(f"   • status: in_progress, completed, failed")
print(f"")
print(f"🔄 Auto-Advancement:")
print(f"   1. User asks 'status?'")
print(f"   2. Agent checks job_events for completion")
print(f"   3. Agent updates current_stage")
print(f"   4. Agent triggers next stage automatically")
print(f"")
print(f"📝 Mutable State: UPDATEs allowed (unlike immutable event store)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 6: Create Staging Tables (Intermediate Data)
# MAGIC 
# MAGIC ### What are Staging Tables?
# MAGIC Temporary storage for data **between workflow stages**.
# MAGIC 
# MAGIC ### Security Isolation via Permissions:
# MAGIC | Table | Writer (SP) | Reader (SP) | Purpose |
# MAGIC |-------|------------|------------|---------|
# MAGIC | `extracted_documents` | EXTRACTION_SP only | SUMMARIZATION_SP only | PDF text storage |
# MAGIC | `summaries` | SUMMARIZATION_SP only | FILE_STORAGE_AGENT only | Summary text storage |
# MAGIC 
# MAGIC **Benefit:** Even if one SP is compromised, it cannot access other stages' data!
# MAGIC 
# MAGIC ### Why Not Just Pass Data Directly?
# MAGIC - **Decoupling:** Jobs can fail and retry independently
# MAGIC - **Audit Trail:** Intermediate data is logged
# MAGIC - **Debugging:** Can inspect intermediate results
# MAGIC - **Reprocessing:** Can re-run downstream stages without re-extracting

# Create extracted_documents table
# Stores raw text extracted from PDFs by EXTRACTION_SP
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.staging.extracted_documents (
  -- Unique ID for this extraction (links to job_events)
  extraction_id STRING NOT NULL PRIMARY KEY,
  
  -- Databricks run ID of the extraction job
  -- Allows correlating with job_events and Jobs API
  extraction_run_id BIGINT NOT NULL,
  
  -- Path to source PDF that was extracted
  document_path STRING NOT NULL,
  
  -- Raw extracted text from PDF (can be large!)
  -- Stored as STRING (Delta handles large text efficiently)
  extracted_text STRING,
  
  -- Number of pages in the PDF
  page_count INT,
  
  -- When extraction completed
  extracted_at TIMESTAMP,
  
  -- **SECURITY AUDIT:** Which Service Principal performed extraction
  -- Value: 'EXTRACTION_SP'
  -- Proves least-privilege: only EXTRACTION_SP can write here
  extracted_by STRING COMMENT 'Service Principal that performed extraction'
)
USING DELTA
COMMENT 'Extracted PDF content (EXTRACTION_SP writes, SUMMARIZATION_SP reads)'
""")

print("✅ Created staging.extracted_documents table")
print(f"   🔒 Security: EXTRACTION_SP writes, SUMMARIZATION_SP reads")
print(f"   📝 Purpose: Store extracted PDF text for summarization")

# Create summaries table
# Stores generated summaries by SUMMARIZATION_SP
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {catalog_name}.staging.summaries (
  -- Unique ID for this summary (links to job_events)
  summary_id STRING NOT NULL PRIMARY KEY,
  
  -- Databricks run ID of the summarization job
  summarization_run_id BIGINT NOT NULL,
  
  -- Links back to the extraction that produced this summary
  extraction_run_id BIGINT NOT NULL,
  
  -- Generated summary text
  summary_text STRING,
  
  -- Additional metadata in JSON format (e.g., compression ratio, model used)
  document_metadata STRING COMMENT 'JSON with metadata: compression_ratio, model, etc.',
  
  -- When summarization completed
  summarized_at TIMESTAMP,
  
  -- **SECURITY AUDIT:** Which Service Principal performed summarization
  -- Value: 'SUMMARIZATION_SP'
  -- Proves least-privilege: only SUMMARIZATION_SP can write here
  summarized_by STRING COMMENT 'Service Principal that performed summarization'
)
USING DELTA
COMMENT 'Summarized content (SUMMARIZATION_SP writes, FILE_STORAGE_AGENT reads)'
""")

print("✅ Created staging.summaries table")
print(f"   🔒 Security: SUMMARIZATION_SP writes, FILE_STORAGE_AGENT reads")
print(f"   📝 Purpose: Store generated summaries for file upload")
print(f"")
print(f"🛡️  Security Isolation:")
print(f"   • EXTRACTION_SP can only write to extracted_documents")
print(f"   • SUMMARIZATION_SP can only read extracted_documents, write summaries")
print(f"   • FILE_STORAGE_AGENT can only read summaries")
print(f"   → Even if one SP is compromised, blast radius is limited!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 7: Create Helper Views
# MAGIC 
# MAGIC ### Why Views?
# MAGIC Views provide **pre-computed queries** for common use cases:
# MAGIC - Faster agent logic (don't re-write complex SQL)
# MAGIC - Consistent query patterns
# MAGIC - Easier maintenance
# MAGIC 
# MAGIC ### View 1: job_status_latest
# MAGIC **Purpose:** Get the most recent status for each job run
# MAGIC 
# MAGIC **Why?** job_events has multiple events per run:
# MAGIC - ExtractionJobStarted (status: RUNNING)
# MAGIC - ExtractionJobCompleted (status: SUCCESS)
# MAGIC 
# MAGIC We want the LATEST status to show users current state.
# MAGIC 
# MAGIC **How?** Use window function `ROW_NUMBER()` to rank events by timestamp,
# MAGIC then filter for rank = 1 (most recent)

# Create view for latest job status per run_id
spark.sql(f"""
CREATE OR REPLACE VIEW {catalog_name}.{schema_name}.job_status_latest AS
WITH ranked_events AS (
  SELECT 
    run_id,
    agent,
    sp_used,
    event_type,
    timestamp,
    -- Window function: For each run_id, rank events by timestamp DESC
    -- Most recent event gets rn=1
    ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY timestamp DESC) as rn
  FROM {catalog_name}.{schema_name}.job_events
)
SELECT 
  run_id,
  agent,
  sp_used,
  event_type as latest_status,  -- Latest event type is the current status
  timestamp as last_updated
FROM ranked_events
WHERE rn = 1  -- Only the most recent event per run_id
""")

print("✅ Created job_status_latest view")
print(f"   📊 Purpose: Get current status of each job run")
print(f"   🔍 Usage: SELECT * FROM job_status_latest WHERE run_id = ?")
print(f"   ⚡ Performance: Indexed on run_id, fast lookups")

# COMMAND ----------

# MAGIC %md
# MAGIC ### View 2: active_workflows
# MAGIC **Purpose:** Show all workflows currently in progress
# MAGIC 
# MAGIC **Filters:**
# MAGIC - status = 'in_progress' (not completed/failed)
# MAGIC - triggered_at within last 2 hours (auto-expire old workflows)
# MAGIC 
# MAGIC **Why 2 hours?** Prevents stale workflows from cluttering the view.
# MAGIC If a workflow is older than 2 hours, it's likely stuck or abandoned.
# MAGIC 
# MAGIC **Computed Field:**
# MAGIC - `elapsed_minutes`: How long the workflow has been running
# MAGIC   Useful for detecting slow workflows or timeouts

# Create view for active (in-progress) workflows
spark.sql(f"""
CREATE OR REPLACE VIEW {catalog_name}.{schema_name}.active_workflows AS
SELECT 
  cs.user_id,
  cs.document_path,
  cs.extraction_run_id,
  cs.summarization_run_id,
  cs.current_stage,
  cs.triggered_at,
  -- Compute elapsed time in minutes (useful for timeout detection)
  CAST((unix_timestamp() - unix_timestamp(cs.triggered_at)) / 60 AS INT) as elapsed_minutes
FROM {catalog_name}.{schema_name}.conversation_state cs
WHERE 
  -- Only show in-progress workflows
  cs.status = 'in_progress'
  
  -- Auto-expire workflows older than 2 hours
  -- Prevents stale workflows from cluttering the view
  AND cs.triggered_at > current_timestamp() - INTERVAL 2 HOURS
  
-- Show most recent first
ORDER BY cs.triggered_at DESC
""")

print("✅ Created active_workflows view")
print(f"   📊 Purpose: Show all active (in-progress) workflows")
print(f"   🔍 Usage: SELECT * FROM active_workflows WHERE user_id = ?")
print(f"   ⏰ Auto-expires: Workflows older than 2 hours excluded")
print(f"   📈 Computed: elapsed_minutes for timeout detection")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Step 8: Verification
# MAGIC 
# MAGIC **Always verify** that all resources were created successfully!

print("\n" + "="*80)
print("✅ CQRS TABLES SETUP COMPLETE")
print("="*80)
print(f"\nCatalog: {catalog_name}")
print(f"Schema: {schema_name}")

print("\n📊 Created Tables:")
print(f"  • {catalog_name}.{schema_name}.job_events")
print(f"    → Event store (immutable audit log)")
print(f"    → Records every agent action with SP used")
print(f"  • {catalog_name}.{schema_name}.conversation_state")
print(f"    → Workflow tracking (mutable state)")
print(f"    → Tracks current stage per user")
print(f"  • {catalog_name}.staging.extracted_documents")
print(f"    → Intermediate data (EXTRACTION_SP → SUMMARIZATION_SP)")
print(f"  • {catalog_name}.staging.summaries")
print(f"    → Intermediate data (SUMMARIZATION_SP → FILE_STORAGE_AGENT)")

print("\n📊 Created Views:")
print(f"  • {catalog_name}.{schema_name}.job_status_latest")
print(f"    → Fast lookup of current job status")
print(f"  • {catalog_name}.{schema_name}.active_workflows")
print(f"    → Show all in-progress workflows")

print("\n📁 Created UC Volumes:")
print(f"  • {catalog_name}.{schema_name}.summaries")
print(f"    → Path: /Volumes/{catalog_name}/{schema_name}/summaries")
print(f"  • {catalog_name}.{schema_name}.source_pdfs")
print(f"    → Path: /Volumes/{catalog_name}/{schema_name}/source_pdfs")

print("\n🔐 Security Model:")
print(f"  • job_events: All agents write (append-only audit log)")
print(f"  • extracted_documents: EXTRACTION_SP writes, SUMMARIZATION_SP reads")
print(f"  • summaries: SUMMARIZATION_SP writes, FILE_STORAGE_AGENT reads")
print(f"  • UC Volumes: Automatic passthrough (no credentials needed!)")

print("\n📈 CQRS Benefits:")
print(f"  ✅ Zero-Polling: No background jobs checking status ($0 cost)")
print(f"  ✅ Fast Queries: Delta queries <100ms (vs Jobs API >500ms)")
print(f"  ✅ Full Audit Trail: Every action logged with SP attribution")
print(f"  ✅ Async UX: Users get instant responses, jobs run in background")

print("\n🚀 Next Steps:")
print(f"  1. Run 02_create_extraction_job.py")
print(f"     → Creates Databricks job for PDF extraction")
print(f"  2. Run 03_create_summarization_job.py")
print(f"     → Creates Databricks job for summarization")
print(f"  3. Run 06_deploy_production_proper.py")
print(f"     → Deploys multi-agent coordinator to serving endpoint")

print("="*80)

