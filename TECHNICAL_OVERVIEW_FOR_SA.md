# Multi-Agent Authentication Patterns - Technical Overview

**For**: Solutions Architects  
**Repo**: https://github.com/saselvan/databricks-multi-agent-cqrs

---

## TL;DR

Reference implementation demonstrating **two authentication patterns** for multi-agent systems on Databricks, with async job execution and CQRS event logging. Solves the "which SP to use where" problem.

---

## The Problem

Multi-agent systems need to access multiple Databricks resources:
- **Unity Catalog resources** (Vector Search, UC Volumes, Delta Tables)
- **Databricks Jobs API** (triggering ETL jobs)
- **External APIs** (if applicable)

**Challenge**: Each resource may require different authentication patterns. Mixing them incorrectly causes:
- Permissions errors
- Wrong SP used for the wrong resource
- Credential contamination (env vars interfering with auto-discovery)

---

## The Solution: Dual Authentication Patterns

### **Pattern 1: Automatic Passthrough** (Databricks-native resources)

**When**: Unity Catalog Volumes, Delta Tables, Vector Search, Model Serving  
**How**: Declare resources in `mlflow.pyfunc.log_model(resources=[...])`  
**Auth**: Agent Framework auto-grants endpoint SP permissions

```python
from mlflow.models.resources import DatabricksVectorSearchIndex

mlflow.pyfunc.log_model(
    artifact_path="model",
    python_model=MyAgent(),
    resources=[
        DatabricksVectorSearchIndex(index_name="catalog.schema.index")
    ]
)

# In agent code - NO credentials needed!
from databricks.vector_search.client import VectorSearchClient
vsc = VectorSearchClient()  # Auto-discovers endpoint identity
results = vsc.similarity_search(...)  # Just works™
```

**Benefits**:
- Zero credential management in code
- Automatic token refresh
- Full UC governance and audit trail
- Endpoint SP lifecycle managed by platform

---

### **Pattern 2: Manual OAuth** (Jobs API, External APIs)

**When**: Jobs API, external APIs, or when you need explicit SP control  
**How**: Inject SP credentials via environment variables from Databricks Secrets  
**Auth**: Explicit `client_id` + `client_secret`

```python
# At deployment (notebook):
agents.deploy(
    model_name="catalog.schema.agent",
    model_version=1,
    environment_vars={
        "JOBS_API_CLIENT_ID": dbutils.secrets.get("scope", "sp_client_id"),
        "JOBS_API_CLIENT_SECRET": dbutils.secrets.get("scope", "sp_secret")
    }
)

# In agent code:
from databricks.sdk import WorkspaceClient
import os

w = WorkspaceClient(
    host=os.environ["DATABRICKS_HOST"],
    client_id=os.environ["JOBS_API_CLIENT_ID"],
    client_secret=os.environ["JOBS_API_CLIENT_SECRET"]
)
run = w.jobs.run_now(job_id=job_id)  # Explicit SP, full control
```

**Benefits**:
- Explicit SP selection (least privilege)
- Persistent SP (no unexpected rotation)
- Works for any API (not just Databricks)
- Deploy-time secret resolution (secrets never in code)

---

## Critical: Avoiding Credential Contamination

**Problem**: If you use standard env var names (`DATABRICKS_CLIENT_ID`, `DATABRICKS_CLIENT_SECRET`), `WorkspaceClient()` for Vector Search will auto-discover them and use the **Jobs API SP** (which has no Vector Search permissions) → fails.

**Solution**: Custom env var names for manual OAuth:

```python
# ❌ BAD - Standard names contaminate auto-discovery
environment_vars={
    "DATABRICKS_CLIENT_ID": sp_client_id,      # ← WorkspaceClient() finds this!
    "DATABRICKS_CLIENT_SECRET": sp_secret,
}

# ✅ GOOD - Custom names prevent interference
environment_vars={
    "JOBS_API_CLIENT_ID": sp_client_id,        # ← WorkspaceClient() ignores this
    "JOBS_API_CLIENT_SECRET": sp_secret,
}
```

---

## Architecture

```
User Query
    ↓
Coordinator Agent (Serving Endpoint)
  │
  ├─► Vector Search (Automatic Passthrough)
  │   • Uses endpoint's SP identity
  │   • Declared via resources=[]
  │   • Zero credentials in code
  │
  └─► Jobs API (Manual OAuth with JOBS_SP)
      • Explicit client_id + client_secret
      • Persistent SP (no rotation)
      • Returns immediately (async)
          ↓
      Job Execution (runs as JOBS_SP)
        ├─► Read UC Volumes (Automatic Passthrough)
        ├─► Write Delta Tables (Automatic Passthrough)
        └─► Log CQRS Events (Automatic Passthrough)
```

**Key Insight**: Manual OAuth for *triggering*, automatic passthrough for *data access*.

---

## CQRS Pattern

**Command**: Agent triggers job, writes "JobStarted" event to Delta  
**Event Store**: `job_events` Delta table (immutable audit trail)  
**Query**: Agent reads job status from Delta (cheap, fast)  
**Self-Reporting**: Job writes "JobCompleted" event on finish (zero polling)

**Benefits**:
- Complete audit trail (which SP did what, when)
- Zero-cost status checks (read Delta, not poll Jobs API)
- Async UX (return immediately, auto-check on user retry)

---

## Serverless Workspace URL Detection

**Issue**: `dbutils.notebook.getContext().apiUrl()` returns wrong region in serverless (e.g., Oregon instead of actual workspace).

**Solution**: Use `WorkspaceClient()` auto-detection:

```python
from databricks.sdk import WorkspaceClient

# SDK checks (in order):
#   1. DATABRICKS_HOST environment variable ← Correct in serverless!
#   2. .databrickscfg file
#   3. Notebook context (fallback)
w = WorkspaceClient()
workspace_url = w.config.host  # Always correct
```

---

## Critical Configuration

### Job Clusters MUST Have Unity Catalog Enabled

```python
from databricks.sdk.service import compute

new_cluster = compute.ClusterSpec(
    data_security_mode=compute.DataSecurityMode.SINGLE_USER,  # Required!
    runtime_engine=compute.RuntimeEngine.PHOTON
)
```

**Without `SINGLE_USER` mode**: Service Principals cannot access UC Volumes → "File not found" errors.

---

## Permissions Hierarchy

Service Principals need **three levels** of permissions (in order):

```sql
-- 1. Catalog access (prerequisite for everything)
GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;

-- 2. Schema access (prerequisite for resources)
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;

-- 3. Resource access (actual data)
GRANT READ VOLUME ON VOLUME <catalog>.<schema>.<volume> TO `<sp-client-id>`;
GRANT SELECT, INSERT ON TABLE <catalog>.<schema>.<table> TO `<sp-client-id>`;
```

**Skipping any level → PERMISSION_DENIED errors.**

---

## Repository Contents

- **15+ notebooks**: Setup, job creation, agent deployment
- **6 agent implementations**: Coordinator, extraction, summarization, file storage
- **Complete docs**: Setup guide, auth patterns, troubleshooting
- **Security**: No credentials, clean git history, production-ready patterns

---

## Key Learnings

1. **Automatic Passthrough is the default** - use it whenever possible
2. **Manual OAuth only when necessary** - Jobs API, external APIs, explicit SP control
3. **Custom env var names prevent contamination** - critical for hybrid patterns
4. **UC permissions are hierarchical** - grant catalog → schema → resource
5. **Job clusters need SINGLE_USER mode** - for UC Volume access
6. **WorkspaceClient() handles serverless correctly** - via DATABRICKS_HOST env var

---

## Use Cases

- Healthcare document processing (HIPAA-compliant workflows)
- Legal document analysis (audit trails required)
- Financial document extraction (regulatory compliance)
- Any multi-stage workflow requiring async execution + full audit trail

---

## Reference

- **Repo**: https://github.com/saselvan/databricks-multi-agent-cqrs
- **Quick Start**: `QUICKSTART.md` (30-45 min setup)
- **Deep Dive**: `AUTHENTICATION_PATTERNS.md`
- **Architecture**: `SUCCESS_SUMMARY.md`

---

**Bottom Line**: This is the pattern for production multi-agent systems that need both automatic UC governance AND explicit API control.

