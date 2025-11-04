# Authentication Patterns in Databricks Multi-Agent Systems

A technical guide to implementing dual authentication patterns for production multi-agent systems on Databricks.

---

## Overview

This implementation demonstrates **two distinct authentication patterns**:

1. **Automatic Passthrough Authentication** - For Databricks-managed resources
2. **Manual OAuth with Service Principals** - For explicit API calls

Understanding when to use each pattern is critical for building secure, maintainable multi-agent systems.

---

## Pattern 1: Automatic Passthrough Authentication

### What It Is

Databricks resources automatically inherit the identity of the calling context (user or Service Principal). No explicit credentials required in code.

### When to Use

✅ **Use automatic passthrough for:**
- Unity Catalog Volumes (file access)
- Unity Catalog Tables (data access)
- Vector Search indices
- Model Serving endpoints
- Feature Store

### How It Works

```python
# Running as Service Principal via job's run_as configuration
# No credentials in code!

# Read from UC Volume
with open("/Volumes/catalog/schema/volume/file.txt", "r") as f:
    content = f.read()  # Uses job's SP identity automatically

# Write to Delta Table
df.write.mode("append").saveAsTable("catalog.schema.table")
# Uses job's SP identity automatically

# Query Vector Search
from databricks.vector_search.client import VectorSearchClient
vsc = VectorSearchClient()  # Auto-discovers endpoint identity
results = vsc.get_index("catalog.schema.index").similarity_search(...)
```

### Configuration Required

**Job Configuration:**
```python
from databricks.sdk.service import jobs, compute

w.jobs.create(
    name="Extraction Job",
    tasks=[
        jobs.Task(
            task_key="extract",
            notebook_task=jobs.NotebookTask(...),
            new_cluster=compute.ClusterSpec(
                data_security_mode=compute.DataSecurityMode.SINGLE_USER  # Critical!
            )
        )
    ],
    run_as=jobs.JobRunAs(
        service_principal_name="<sp-client-id>"  # This SP's identity is used
    )
)
```

**Permissions:**
```sql
-- Grant permissions to the Service Principal
GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
GRANT READ VOLUME ON VOLUME <catalog>.<schema>.<volume> TO `<sp-client-id>`;
```

### Advantages

✅ **No credentials in code** - More secure  
✅ **Cleaner code** - No auth boilerplate  
✅ **Automatic token refresh** - Databricks handles it  
✅ **Full audit trail** - UC tracks which SP accessed what  

### Limitations

❌ Cannot use for external APIs  
❌ Cannot use for triggering jobs (Jobs API requires manual OAuth)  
❌ Requires Unity Catalog setup

---

## Pattern 2: Manual OAuth with Service Principals

### What It Is

Explicit client ID + secret provided to authenticate API calls. Used when automatic passthrough is not available.

### When to Use

✅ **Use manual OAuth for:**
- Databricks Jobs API (triggering jobs)
- External APIs (SharePoint, Google Drive, etc.)
- Cross-workspace operations
- When you need explicit control over which SP is used

### How It Works

```python
from databricks.sdk import WorkspaceClient
import os

# Credentials injected via environment variables (from Databricks Secrets)
w = WorkspaceClient(
    host=os.environ["DATABRICKS_HOST"],
    client_id=os.environ["EXTRACTION_SP_CLIENT_ID"],
    client_secret=os.environ["EXTRACTION_SP_CLIENT_SECRET"]
)

# Trigger job using this SP's credentials
run = w.jobs.run_now(
    job_id=job_id,
    notebook_params={"document_path": "/Volumes/..."}
)

print(f"Job triggered: Run ID {run.run_id}")
```

### Configuration Required

**Secrets Setup:**
```bash
# Store SP credentials in Databricks Secrets
databricks secrets create-scope agents
databricks secrets put-secret agents extraction_sp_client_id
databricks secrets put-secret agents extraction_sp_secret
```

**Agent Deployment:**
```python
from databricks import agents

agents.deploy(
    model_name="catalog.schema.agent",
    model_version=1,
    environment_vars={
        "DATABRICKS_HOST": workspace_url,
        "EXTRACTION_SP_CLIENT_ID": dbutils.secrets.get("agents", "extraction_sp_client_id"),
        "EXTRACTION_SP_CLIENT_SECRET": dbutils.secrets.get("agents", "extraction_sp_secret")
    }
)
```

### Advantages

✅ **Explicit control** - You choose which SP  
✅ **Works for external APIs** - Not limited to Databricks  
✅ **Cross-workspace** - Can call other workspaces  
✅ **Per-agent isolation** - Different SP per agent (least privilege)

### Limitations

❌ Must manage credentials  
❌ More code complexity  
❌ Credentials in environment (even if from Secrets)

---

## Hybrid Pattern: The Best of Both

### Architecture

```
Coordinator Agent
├─► Uses Manual OAuth to trigger jobs
│   (Explicit SP selection, least privilege)
│
└─► Job Execution
    └─► Uses Automatic Passthrough for data access
        (Cleaner code, no credentials, full UC governance)
```

### Implementation

**Coordinator Agent** (Manual OAuth):
```python
class ExtractionAgent:
    def __init__(self):
        # Manual OAuth for Jobs API
        self.w = WorkspaceClient(
            host=os.environ["DATABRICKS_HOST"],
            client_id=os.environ["EXTRACTION_SP_CLIENT_ID"],
            client_secret=os.environ["EXTRACTION_SP_CLIENT_SECRET"]
        )
    
    def trigger_extraction(self, document_path: str):
        # Trigger job with this specific SP
        run = self.w.jobs.run_now(
            job_id=self.job_id,
            notebook_params={"document_path": document_path}
        )
        return run.run_id
```

**Extraction Job** (Automatic Passthrough):
```python
# This code runs in the job (as EXTRACTION_SP)
# No credentials needed!

document_path = dbutils.widgets.get("document_path")

# Read from UC Volume (automatic passthrough)
with open(document_path, "r") as f:
    text = f.read()

# Write to Delta Table (automatic passthrough)
df = spark.createDataFrame([{"text": text}])
df.write.mode("append").saveAsTable("catalog.staging.documents")

# Log event (automatic passthrough)
spark.sql(f"""
    INSERT INTO catalog.schema.job_events 
    VALUES (uuid(), 'ExtractionComplete', current_timestamp(), 'EXTRACTION_SP')
""")
```

### Why This Is Powerful

1. **Security**: Dedicated SP per agent (least privilege)
2. **Clarity**: Explicit job triggering, implicit data access
3. **Governance**: Full UC audit trail for all data operations
4. **Maintainability**: Clean separation of concerns

---

## Critical Configuration: Unity Catalog for Service Principals

### The Requirement

Job clusters **MUST** have `data_security_mode: SINGLE_USER` to access Unity Catalog resources.

```python
new_cluster = compute.ClusterSpec(
    spark_version="14.3.x-scala2.12",
    node_type_id="i3.xlarge",
    num_workers=0,
    data_security_mode=compute.DataSecurityMode.SINGLE_USER,  # Required!
    runtime_engine=compute.RuntimeEngine.PHOTON
)
```

### Why This Matters

**Without `SINGLE_USER` mode:**
- `os.path.exists("/Volumes/...")` returns `False`
- Service Principal cannot read UC Volume files
- Permissions are ignored
- Jobs fail with "File not found"

**With `SINGLE_USER` mode:**
- Service Principal can access UC Volumes
- Permissions are enforced correctly
- Automatic passthrough works as expected

### Permissions Hierarchy

Service Principals need permissions at **three levels**:

```sql
-- Level 1: Catalog access (prerequisite for everything else)
GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;

-- Level 2: Schema access (prerequisite for volumes/tables)
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;

-- Level 3: Resource access (actual data)
GRANT READ VOLUME ON VOLUME <catalog>.<schema>.<volume> TO `<sp-client-id>`;
GRANT SELECT, INSERT ON TABLE <catalog>.<schema>.<table> TO `<sp-client-id>`;
```

**Skipping any level will result in PERMISSION_DENIED errors.**

---

## Choosing the Right Pattern

| Scenario | Pattern | Why |
|----------|---------|-----|
| Reading from UC Volumes | Automatic Passthrough | Cleaner, no credentials |
| Writing to Delta Tables | Automatic Passthrough | UC governance, audit trail |
| Triggering a job | Manual OAuth | Need explicit SP selection |
| Calling external API | Manual OAuth | Only option available |
| Vector Search | Automatic Passthrough | Built for it |
| Model Serving | Automatic Passthrough | Endpoint identity |

### General Rule of Thumb

**Default to Automatic Passthrough** unless you specifically need:
- Explicit SP selection
- External API calls
- Cross-workspace operations

---

## Security Best Practices

### 1. Least Privilege

Each agent should have its own Service Principal with minimal permissions.

```sql
-- EXTRACTION_SP: Only what it needs
GRANT READ VOLUME ON VOLUME catalog.schema.source_pdfs TO `<extraction-sp>`;
GRANT INSERT ON TABLE catalog.staging.extracted_documents TO `<extraction-sp>`;

-- SUMMARIZATION_SP: Different permissions
GRANT SELECT ON TABLE catalog.staging.extracted_documents TO `<summarization-sp>`;
GRANT INSERT ON TABLE catalog.staging.summaries TO `<summarization-sp>`;
```

### 2. Never Hardcode Credentials

❌ **Never do this:**
```python
client_id = "abcd1234-..."  # Hardcoded!
client_secret = "secret123"  # Hardcoded!
```

✅ **Always do this:**
```python
client_id = os.environ["EXTRACTION_SP_CLIENT_ID"]  # From Databricks Secrets
client_secret = os.environ["EXTRACTION_SP_CLIENT_SECRET"]  # From Databricks Secrets
```

### 3. Use Custom Environment Variable Names

Avoid conflicts with auto-discovery:

```python
# ❌ Bad: These might interfere with automatic passthrough
DATABRICKS_CLIENT_ID = "..."
DATABRICKS_CLIENT_SECRET = "..."

# ✅ Good: Custom names prevent conflicts
EXTRACTION_SP_CLIENT_ID = "..."
EXTRACTION_SP_CLIENT_SECRET = "..."
```

### 4. Audit Everything

Use CQRS event logging to track which SP did what:

```sql
-- Log every operation
INSERT INTO catalog.schema.job_events 
VALUES (
    uuid(),
    'ExtractionComplete',
    current_timestamp(),
    'EXTRACTION_SP',  -- Which SP performed this action
    'user@example.com',  -- Who triggered it
    '{"document": "/Volumes/..."}'  -- What was accessed
);
```

---

## Debugging Authentication Issues

### Issue: "File not found" in UC Volume

**Symptoms:**
- `os.path.exists("/Volumes/...")` returns `False`
- File is visible in UI but not accessible from job

**Cause:** Job cluster missing `data_security_mode: SINGLE_USER`

**Fix:**
```python
# Update job cluster configuration
new_cluster = compute.ClusterSpec(
    data_security_mode=compute.DataSecurityMode.SINGLE_USER
)
```

### Issue: "PERMISSION_DENIED" on UC Volume

**Symptoms:**
- Cluster has `SINGLE_USER` mode
- File exists
- Still getting permission errors

**Cause:** Missing catalog or schema permissions

**Fix:**
```sql
-- Grant all three levels
GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;
GRANT READ VOLUME ON VOLUME <catalog>.<schema>.<volume> TO `<sp-client-id>`;
```

### Issue: Jobs API "invalid_client" error

**Symptoms:**
- Manual OAuth failing
- `invalid_client` or `unauthorized_client` errors

**Causes:**
1. Wrong client ID or secret
2. SP doesn't exist
3. Secrets not synced

**Fix:**
```bash
# Verify SP exists
databricks service-principals list | grep <client-id>

# Recreate secrets
databricks secrets put-secret agents extraction_sp_client_id
databricks secrets put-secret agents extraction_sp_secret

# Redeploy agent with new secrets
```

---

## Complete Example

See `notebooks/06_deploy_production_proper.py` for a full implementation showing:

- ✅ Manual OAuth for Jobs API (triggering)
- ✅ Automatic Passthrough for UC Volumes (file access)
- ✅ Automatic Passthrough for Delta Tables (data writes)
- ✅ Automatic Passthrough for CQRS events (audit logging)
- ✅ Dedicated SP per agent (least privilege)
- ✅ Secrets management (no hardcoded credentials)

---

## References

- [Databricks Service Principals](https://docs.databricks.com/administration-guide/users-groups/service-principals.html)
- [Unity Catalog Permissions](https://docs.databricks.com/data-governance/unity-catalog/manage-privileges/index.html)
- [Agent Framework Authentication](https://docs.databricks.com/generative-ai/agent-framework/agent-authentication.html)
- [Jobs API](https://docs.databricks.com/workflows/jobs/jobs-api.html)

---

**Bottom Line**: Use automatic passthrough by default. Use manual OAuth only when you need explicit SP control or external API calls.

