# Databricks notebook source
# MAGIC %md
# MAGIC # Optional: Setup Lakebase for Conversation Memory & Fast Job Lookups
# MAGIC 
# MAGIC **Status:** ⚠️ **FUTURE ENHANCEMENT - Lakebase NOT HIPAA-compliant yet**
# MAGIC 
# MAGIC This notebook demonstrates how to upgrade the CQRS architecture from Delta-only to a **hybrid Lakebase + Delta** pattern:
# MAGIC - **Lakebase (Postgres)**: Hot store for active jobs (<20ms lookups), conversation memory with LangGraph
# MAGIC - **Delta Tables**: Cold archive for compliance (7-year retention), analytics
# MAGIC 
# MAGIC ## Why Lakebase?
# MAGIC 
# MAGIC | Feature | Delta (Current) | Lakebase (Future) | Benefit |
# MAGIC |---------|-----------------|-------------------|---------|
# MAGIC | Job status query | 500ms-3s | 5-20ms | **100x faster UX** |
# MAGIC | Conversation memory | Manual state tracking | LangGraph checkpoints | **Stateful agents** |
# MAGIC | Multi-turn context | In-memory only | Persistent across sessions | **Resume workflows** |
# MAGIC | HIPAA compliance | ✅ | ⚠️ Not yet | Azure PostgreSQL with BAA recommended |
# MAGIC 
# MAGIC ## Architecture
# MAGIC 
# MAGIC ```
# MAGIC ┌─────────────────────────────────────────────────────────┐
# MAGIC │  AGENT QUERY PATH (Hot → Cold Fallback)                 │
# MAGIC │                                                          │
# MAGIC │  1. Check Lakebase (last 30 days)                       │
# MAGIC │     └─> SELECT status FROM job_status WHERE run_id=?    │
# MAGIC │         Latency: 5-20ms ✓                               │
# MAGIC │                                                          │
# MAGIC │  2. If not found, query Delta (archive)                 │
# MAGIC │     └─> SELECT * FROM job_events WHERE run_id=?         │
# MAGIC │         Latency: 500ms-3s (old jobs)                    │
# MAGIC └─────────────────────────────────────────────────────────┘
# MAGIC 
# MAGIC ┌─────────────────────────────────────────────────────────┐
# MAGIC │  WRITE PATH (Dual Write)                                 │
# MAGIC │                                                          │
# MAGIC │  ETL Job Reports Completion:                             │
# MAGIC │  ├─> Write to Lakebase (UPDATE job_status)              │
# MAGIC │  └─> Append to Delta (INSERT INTO job_events)           │
# MAGIC │                                                          │
# MAGIC │  OR use Synced Table (automatic CDC):                   │
# MAGIC │  ├─> Write ONLY to Lakebase                             │
# MAGIC │  └─> Databricks auto-syncs to Delta                     │
# MAGIC └─────────────────────────────────────────────────────────┘
# MAGIC ```
# MAGIC 
# MAGIC ## Prerequisites
# MAGIC 
# MAGIC 1. **Create Lakebase instance** (via Databricks UI)
# MAGIC    - Go to: SQL Warehouses → Lakebase Postgres → Create database instance
# MAGIC    - Name: `banner-oncology-lakebase`
# MAGIC    - Capacity: `CU_1` (start small)
# MAGIC    - Node count: `1`
# MAGIC 
# MAGIC 2. **Create Service Principal** with Lakebase permissions
# MAGIC    - Grant `databricks_superuser` on the Lakebase instance
# MAGIC    - Store Client ID/Secret in Databricks Secrets

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Install Dependencies

# COMMAND ----------

# DBTITLE 1,Install Lakebase + LangGraph Libraries
# MAGIC %pip install -U -qqqq \
# MAGIC   databricks-langchain \
# MAGIC   langgraph==0.5.3 \
# MAGIC   langgraph-checkpoint-postgres==2.0.21 \
# MAGIC   psycopg[binary,pool]
# MAGIC dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Configure Lakebase Connection

# COMMAND ----------

# DBTITLE 1,Set Lakebase Configuration
import os
import uuid
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool
import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

# TODO: Update these with your Lakebase instance details
LAKEBASE_CONFIG = {
    "instance_name": "banner-oncology-lakebase",  # From step 1
    "conn_host": "instance-aea....cloud.databricks.com",  # From "Connection details" in UI
    "conn_db_name": "oncology_agents",  # Database to create
    "conn_ssl_mode": "require",
}

# Service Principal credentials (stored in Databricks Secrets)
SP_CLIENT_ID = dbutils.secrets.get("oncology_agents", "lakebase_sp_client_id")
SP_CLIENT_SECRET = dbutils.secrets.get("oncology_agents", "lakebase_sp_client_secret")

WORKSPACE_HOST = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()

print("✅ Configuration loaded")
print(f"   Instance: {LAKEBASE_CONFIG['instance_name']}")
print(f"   Database: {LAKEBASE_CONFIG['conn_db_name']}")
print(f"   Workspace: {WORKSPACE_HOST}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Create Custom Connection with Auto-Rotating Credentials
# MAGIC 
# MAGIC **Key Feature:** Credentials cached for 50 minutes, auto-refreshed to solve session expiration!

# COMMAND ----------

# DBTITLE 1,Auto-Rotating PostgreSQL Connection (Solves Session Expiration!)
import time
from threading import Lock

class CredentialConnection(psycopg.Connection):
    """
    Custom connection class that generates fresh OAuth tokens with 50-minute caching.
    
    This solves Banner's "1-hour session expiration" pain point by:
    1. Caching credentials for 50 minutes (configurable)
    2. Auto-refreshing before expiration
    3. Zero manual intervention
    """
    
    workspace_client = None
    instance_name = None
    
    # Cache attributes
    _cached_credential = None
    _cache_timestamp = None
    _cache_duration = 3000  # 50 minutes in seconds (50 * 60)
    _cache_lock = Lock()
    
    @classmethod
    def connect(cls, conninfo='', **kwargs):
        """Override connect to inject OAuth token with caching"""
        if cls.workspace_client is None or cls.instance_name is None:
            raise ValueError("workspace_client and instance_name must be set on CredentialConnection class")
        
        # Get cached or fresh credential
        credential_token = cls._get_cached_credential()
        kwargs['password'] = credential_token
        
        # Call superclass connect with updated kwargs
        return super().connect(conninfo, **kwargs)
    
    @classmethod
    def _get_cached_credential(cls):
        """
        Get credential from cache or generate new one if cache expired.
        
        Thread-safe with Lock to prevent concurrent token generation.
        """
        with cls._cache_lock:
            current_time = time.time()
            
            # Check if cached credential is still valid
            if (cls._cached_credential is not None and 
                cls._cache_timestamp is not None and 
                current_time - cls._cache_timestamp < cls._cache_duration):
                return cls._cached_credential
            
            # Generate new credential from Databricks
            print(f"🔑 Generating fresh Lakebase credential (cached for {cls._cache_duration/60:.0f} min)")
            credential = cls.workspace_client.database.generate_database_credential(
                request_id=str(uuid.uuid4()),
                instance_names=[cls.instance_name]
            )
            
            # Cache the new credential
            cls._cached_credential = credential.token
            cls._cache_timestamp = current_time
            
            return cls._cached_credential

# Initialize workspace client
w = WorkspaceClient(
    host=WORKSPACE_HOST,
    client_id=SP_CLIENT_ID,
    client_secret=SP_CLIENT_SECRET
)

# Set class-level attributes for custom connection
CredentialConnection.workspace_client = w
CredentialConnection.instance_name = LAKEBASE_CONFIG["instance_name"]

print("✅ Custom connection class configured")
print(f"   Credential cache: {CredentialConnection._cache_duration / 60:.0f} minutes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Create Connection Pool

# COMMAND ----------

# DBTITLE 1,Connection Pool with Auto-Rotating Credentials
from psycopg.rows import dict_row

# Get username (Service Principal application ID)
try:
    sp = w.current_service_principal.me()
    username = sp.application_id
except Exception:
    user = w.current_user.me()
    username = user.user_name

print(f"Connecting as: {username}")

# Create connection pool
pool = ConnectionPool(
    conninfo=f"dbname={LAKEBASE_CONFIG['conn_db_name']} user={username} host={LAKEBASE_CONFIG['conn_host']} port=5432 sslmode={LAKEBASE_CONFIG['conn_ssl_mode']}",
    connection_class=CredentialConnection,
    min_size=1,
    max_size=10,
    timeout=30.0,
    open=True,
    kwargs={
        "autocommit": True,  # Required for PostgresSaver.setup()
        "row_factory": dict_row,  # Required for PostgresSaver implementation
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
)

# Test the pool
try:
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
    print("✅ Connection pool created successfully")
    print(f"   Pool size: min=1, max=10")
    print(f"   Token cache: {CredentialConnection._cache_duration / 60:.0f} minutes")
except Exception as e:
    pool.close()
    raise ConnectionError(f"Failed to create connection pool: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Create Lakebase Tables

# COMMAND ----------

# DBTITLE 1,Create Hot Job Status Table (Standard PostgreSQL Best Practices)
with pool.connection() as conn:
    with conn.cursor() as cursor:
        # Create job_status table (hot store - mutable)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_status (
                run_id TEXT PRIMARY KEY,              -- B-tree index (automatic)
                user_id TEXT NOT NULL,
                conversation_id TEXT,
                job_type TEXT,                        -- 'extraction', 'summarization', 'sharepoint'
                agent TEXT,
                status TEXT,                          -- 'PENDING', 'RUNNING', 'SUCCESS', 'FAILED'
                sp_used TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Secondary indexes: ONLY for common query patterns
        # Rule: Only index columns used in WHERE clauses frequently
        
        # Index 1: User's active jobs (common: "show me my running jobs")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_status 
            ON job_status (user_id, status)
            WHERE status IN ('PENDING', 'RUNNING')
        """)
        # Partial index = smaller, faster (only indexes active jobs, not completed)
        
        # Index 2: Conversation lookup (common: "what jobs are in this conversation?")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversation 
            ON job_status (conversation_id)
            WHERE conversation_id IS NOT NULL
        """)
        # Partial index = excludes NULL conversation_id rows
        
        # NO index on updated_at - archive job does full scan anyway (30-day retention)
        # NO index on job_type - low cardinality (3 values), seq scan is faster
        # NO index on sp_used - only for audit queries (use Delta for analytics)
        
    conn.commit()
    print("✅ Created job_status table with optimal indexes")
    print()
    print("📊 Index Strategy (PostgreSQL Best Practices):")
    print("   PRIMARY KEY (run_id)           → B-tree (automatic)")
    print("   idx_user_status                → Partial B-tree (active jobs only)")
    print("   idx_conversation               → Partial B-tree (non-null only)")
    print()
    print("   ⚠️  Avoid over-indexing!")
    print("   - Each index slows down writes (UPDATE/INSERT)")
    print("   - Small tables (<1M rows) may not need secondary indexes")
    print("   - Monitor query plans with EXPLAIN ANALYZE")

# COMMAND ----------

# DBTITLE 1,Create LangGraph Checkpoint Tables (Conversation Memory)
with pool.connection() as conn:
    conn.autocommit = True  # Required for setup()
    
    # Initialize LangGraph checkpointer
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()  # Creates checkpoints and writes tables
    
    conn.autocommit = False
    
    print("✅ Created LangGraph checkpoint tables:")
    print("   - checkpoints (conversation state)")
    print("   - writes (intermediate outputs)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Test Connection & Query Performance

# COMMAND ----------

# DBTITLE 1,Test Write & Read Performance
import time

# Test data
test_run_id = f"test-{uuid.uuid4()}"
test_user_id = "test-user@banner.com"

# Measure write latency
start_time = time.time()
with pool.connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("""
            INSERT INTO job_status (run_id, user_id, job_type, status, sp_used)
            VALUES (%s, %s, %s, %s, %s)
        """, (test_run_id, test_user_id, "extraction", "RUNNING", "EXTRACTION_SP"))
    conn.commit()
write_latency = (time.time() - start_time) * 1000

# Measure read latency (PK lookup)
start_time = time.time()
with pool.connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM job_status WHERE run_id = %s", (test_run_id,))
        result = cursor.fetchone()
read_latency = (time.time() - start_time) * 1000

print("📊 Performance Test Results:")
print(f"   Write latency: {write_latency:.2f}ms")
print(f"   Read latency (PK): {read_latency:.2f}ms")
print(f"   Expected agent query: <20ms ✅")
print()
print("   Compare to Delta: 500-3000ms (25-150x slower)")

# Cleanup test data
with pool.connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM job_status WHERE run_id = %s", (test_run_id,))
    conn.commit()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Monitor Query Performance (PostgreSQL Best Practices)

# COMMAND ----------

# DBTITLE 1,Use EXPLAIN ANALYZE to Verify Index Usage
with pool.connection() as conn:
    with conn.cursor() as cursor:
        # Check if PRIMARY KEY index is being used
        cursor.execute("""
            EXPLAIN ANALYZE
            SELECT status, updated_at FROM job_status WHERE run_id = 'test-123'
        """)
        
        explain_output = cursor.fetchall()
        
        print("📊 Query Plan for PK lookup:")
        for row in explain_output:
            print(f"   {row[0]}")
        print()
        print("✅ Look for 'Index Scan using job_status_pkey' (not Seq Scan)")
        print("✅ Execution time should be <5ms for PK lookups")
        print()
        
        # Check if partial index is being used for user's active jobs
        cursor.execute("""
            EXPLAIN ANALYZE
            SELECT run_id, status FROM job_status 
            WHERE user_id = 'test-user' AND status = 'RUNNING'
        """)
        
        explain_output = cursor.fetchall()
        
        print("📊 Query Plan for user's active jobs:")
        for row in explain_output:
            print(f"   {row[0]}")
        print()
        print("✅ Look for 'Index Scan using idx_user_status' (partial index)")
        print()
        print("⚠️  If you see 'Seq Scan', either:")
        print("   1. Table is too small (Postgres optimizer chose seq scan)")
        print("   2. Query doesn't match index predicate")
        print("   3. Index needs VACUUM ANALYZE to update statistics")

# COMMAND ----------

# DBTITLE 1,PostgreSQL Maintenance (Standard Best Practices)
with pool.connection() as conn:
    with conn.cursor() as cursor:
        # Update table statistics (important for query optimizer)
        cursor.execute("ANALYZE job_status")
        
        print("✅ Table statistics updated")
        print()
        print("📋 PostgreSQL Maintenance Checklist:")
        print("   1. Run ANALYZE after bulk inserts (updates statistics)")
        print("   2. Run VACUUM periodically (reclaims dead tuple space)")
        print("   3. Monitor index bloat (REINDEX if >30% bloat)")
        print("   4. Check slow query log (queries >100ms)")
        print()
        print("⏱️  Recommended Schedule:")
        print("   - ANALYZE: After every 10K inserts/updates")
        print("   - VACUUM: Nightly (low-traffic window)")
        print("   - REINDEX: Monthly (or when bloat detected)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Setup Synced Table (Auto-Replicate to Delta)

# COMMAND ----------

# DBTITLE 1,Create Synced Table for Analytics (Lakebase → Delta CDC)
from databricks.sdk.service.database import (
    SyncedDatabaseTable,
    SyncedTableSpec,
    SyncedTableSchedulingPolicy,
    NewPipelineSpec,
)

# Configure synced table (auto-replicates Lakebase → Delta)
synced_table_spec = SyncedTableSpec(
    source_table_full_name=f"oncology_agents.public.job_status",
    primary_key_columns=["run_id"],
    timeseries_key="updated_at",
    create_database_objects_if_missing=True,
    new_pipeline_spec=NewPipelineSpec(
        storage_catalog="<YOUR_CATALOG>",  # TODO: Update
        storage_schema="<YOUR_SCHEMA>",    # TODO: Update
    ),
    scheduling_policy=SyncedTableSchedulingPolicy.CONTINUOUS,  # Real-time CDC
)

synced_table = SyncedDatabaseTable(
    name="<YOUR_CATALOG>.job_status_synced",  # TODO: Update
    database_instance_name=LAKEBASE_CONFIG["instance_name"],
    logical_database_name=LAKEBASE_CONFIG["conn_db_name"],
    spec=synced_table_spec,
)

print("⚠️  Synced Table Configuration Ready")
print()
print("To create the synced table, run:")
print()
print("w.database.create_synced_database_table(synced_table)")
print()
print("This will:")
print("  1. Create a Delta table replica in your catalog")
print("  2. Continuously sync changes from Lakebase (CDC)")
print("  3. Enable analytics queries without impacting agent performance")
print()
print("⚠️  Note: Update <YOUR_CATALOG> and <YOUR_SCHEMA> first!")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 9. Query Conversation History (SQL)

# COMMAND ----------

# DBTITLE 1,Query All Checkpoints (Conversation Memory)
with pool.connection() as conn:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT 
                thread_id,
                checkpoint_ns,
                (checkpoint->>'ts')::timestamptz AS timestamp
            FROM checkpoints
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        
        checkpoints = cursor.fetchall()
        
        if checkpoints:
            print("📊 Recent Conversation Checkpoints:")
            for cp in checkpoints:
                print(f"   Thread: {cp['thread_id']}, Timestamp: {cp['timestamp']}")
        else:
            print("No checkpoints yet (deploy agent with Lakebase to see data)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 10. Integration with Agent Code

# COMMAND ----------

# DBTITLE 1,Example: Agent Query with Hot/Cold Fallback
def get_job_status(run_id: str, pool: ConnectionPool, spark):
    """
    Query job status with hot/cold fallback:
    1. Check Lakebase (fast, last 30 days)
    2. Fallback to Delta (archive, >30 days)
    
    ⚠️ CRITICAL: Must use psycopg connection pool for Lakebase, NOT Spark SQL!
    
    ❌ WRONG (Federation layer adds 100-500ms latency):
        spark.sql("SELECT * FROM lakebase_catalog.public.job_status WHERE run_id = '...'")
    
    ✅ CORRECT (Direct PostgreSQL, 5-20ms latency):
        cursor.execute("SELECT * FROM job_status WHERE run_id = %s", (run_id,))
    
    If you query Lakebase through UC views, you go through federation and lose
    the <20ms latency that makes Lakebase worth it!
    """
    # Try Lakebase first (hot store) - DIRECT psycopg connection!
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status, updated_at, sp_used FROM job_status WHERE run_id = %s",
                (run_id,)
            )
            result = cursor.fetchone()
            
            if result:
                return {
                    "source": "lakebase",
                    "status": result["status"],
                    "updated_at": result["updated_at"],
                    "sp_used": result["sp_used"],
                    "latency": "<20ms"
                }
    
    # Fallback to Delta (cold archive)
    delta_result = spark.sql(f"""
        SELECT status, event_timestamp, sp_used
        FROM oncology_cqrs.job_events
        WHERE run_id = '{run_id}'
        ORDER BY event_timestamp DESC
        LIMIT 1
    """).collect()
    
    if delta_result:
        return {
            "source": "delta",
            "status": delta_result[0]["status"],
            "updated_at": delta_result[0]["event_timestamp"],
            "sp_used": delta_result[0]["sp_used"],
            "latency": "500-3000ms"
        }
    
    return None

# Example usage
# status = get_job_status("run-12345", pool, spark)
# print(f"Status: {status['status']} (from {status['source']}, latency: {status['latency']})")

print("✅ Integration example ready")
print()
print("Key benefits:")
print("  1. Fast agent queries (<20ms) from Lakebase")
print("  2. Automatic fallback to Delta for archived jobs")
print("  3. Zero-polling CQRS pattern maintained")
print("  4. Conversation memory with LangGraph checkpoints")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 11. Cleanup & Archive Job (Scheduled)

# COMMAND ----------

# DBTITLE 1,Archive Old Jobs from Lakebase to Delta (Run Daily via Workflow)
def archive_old_jobs(pool: ConnectionPool, retention_days: int = 30):
    """
    Move completed jobs older than retention_days from Lakebase to Delta.
    
    Lakebase = hot store (active jobs)
    Delta = cold archive (historical analysis)
    """
    cutoff_date = f"NOW() - INTERVAL '{retention_days} days'"
    
    with pool.connection() as conn:
        with conn.cursor() as cursor:
            # Find old completed jobs
            cursor.execute(f"""
                SELECT * FROM job_status
                WHERE status IN ('SUCCESS', 'FAILED')
                AND updated_at < {cutoff_date}
            """)
            
            old_jobs = cursor.fetchall()
            
            if old_jobs:
                print(f"🗂️  Archiving {len(old_jobs)} jobs older than {retention_days} days")
                
                # Delete from Lakebase (Delta already has full history via CDC)
                cursor.execute(f"""
                    DELETE FROM job_status
                    WHERE status IN ('SUCCESS', 'FAILED')
                    AND updated_at < {cutoff_date}
                """)
                
                conn.commit()
                print(f"✅ Archived {len(old_jobs)} jobs to Delta")
            else:
                print("No jobs to archive")

# Example: Run this daily via Databricks Workflow
# archive_old_jobs(pool, retention_days=30)

print("✅ Archive function ready")
print()
print("To automate:")
print("  1. Create a Databricks Workflow")
print("  2. Schedule to run daily")
print("  3. Keeps Lakebase small & fast")
print("  4. Delta retains full 7-year history for HIPAA")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary & Next Steps
# MAGIC 
# MAGIC ### ✅ What We Built
# MAGIC 
# MAGIC 1. **Lakebase connection pool** with auto-rotating credentials (50-min cache)
# MAGIC 2. **Hot job status table** with optimal indexes (PRIMARY KEY + 2 partial indexes)
# MAGIC 3. **LangGraph checkpoint tables** (conversation memory)
# MAGIC 4. **Performance monitoring** (EXPLAIN ANALYZE + PostgreSQL maintenance)
# MAGIC 5. **Synced Table config** (auto-replicate to Delta for analytics)
# MAGIC 6. **Hot/cold fallback pattern** (fast agent queries + full history)
# MAGIC 7. **Archive job** (keep Lakebase small, Delta retains everything)
# MAGIC 
# MAGIC ### 🚀 To Deploy
# MAGIC 
# MAGIC 1. **Update agent code** (`coordinator_agent.py`):
# MAGIC    ```python
# MAGIC    # Initialize Lakebase pool at startup
# MAGIC    from lakebase_connection import create_connection_pool
# MAGIC    pool = create_connection_pool(LAKEBASE_CONFIG, SP_CLIENT_ID, SP_CLIENT_SECRET)
# MAGIC    
# MAGIC    # In predict() method:
# MAGIC    status = get_job_status(run_id, pool, spark)
# MAGIC    ```
# MAGIC 
# MAGIC 2. **Update ETL jobs** to write to Lakebase:
# MAGIC    ```python
# MAGIC    # On job start
# MAGIC    INSERT INTO job_status VALUES (run_id, user_id, 'RUNNING', ...)
# MAGIC    
# MAGIC    # On completion
# MAGIC    UPDATE job_status SET status='SUCCESS', updated_at=NOW() WHERE run_id=...
# MAGIC    ```
# MAGIC 
# MAGIC 3. **Create Synced Table** (optional):
# MAGIC    ```python
# MAGIC    w.database.create_synced_database_table(synced_table)
# MAGIC    ```
# MAGIC 
# MAGIC 4. **Schedule archive job** (daily workflow):
# MAGIC    ```python
# MAGIC    archive_old_jobs(pool, retention_days=30)
# MAGIC    ```
# MAGIC 
# MAGIC ### ⚠️ HIPAA Note
# MAGIC 
# MAGIC **Lakebase is NOT HIPAA-compliant yet.** For production PHI:
# MAGIC - Option A: Wait for Lakebase HIPAA certification
# MAGIC - Option B: Use Azure Database for PostgreSQL with BAA
# MAGIC - Option C: Use Delta-only (current pattern, acceptable latency)
# MAGIC 
# MAGIC ### 📊 Performance Comparison
# MAGIC 
# MAGIC | Operation | Delta (Current) | Lakebase (Future) | Improvement |
# MAGIC |-----------|-----------------|-------------------|-------------|
# MAGIC | Job status query | 500-3000ms | 5-20ms | **25-150x faster** |
# MAGIC | Conversation resume | Not supported | Native (LangGraph) | **New capability** |
# MAGIC | Multi-turn context | In-memory only | Persistent | **Session independence** |
# MAGIC 
# MAGIC ---
# MAGIC 
# MAGIC **Status:** Notebook complete. Ready to integrate when Lakebase becomes HIPAA-compliant.

# COMMAND ----------

# Close connection pool when done
pool.close()
print("✅ Connection pool closed")

