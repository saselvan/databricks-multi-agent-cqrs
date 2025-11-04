# Multi-Agent System with Dual Authentication Patterns on Databricks

A reference implementation demonstrating **two authentication patterns** for Databricks multi-agent systems:
- **Automatic Passthrough Authentication** for Unity Catalog resources
- **Manual OAuth with Service Principals** for Databricks Jobs API

This implementation also showcases async job execution with CQRS event logging for production-grade workflows.

## 🎯 What This Demonstrates

### Authentication Patterns

**Pattern 1: Automatic Passthrough**
- Unity Catalog Volumes (file access)
- Unity Catalog Delta Tables (data access)
- Vector Search (if implemented)
- Agent Framework endpoint identity

**Pattern 2: Manual OAuth with Service Principals**
- Databricks Jobs API (job triggering)
- Dedicated SP per agent (least privilege)
- Credential injection via Databricks Secrets

### Architecture Patterns

- **Async Job Execution** - Fire and forget with status checking
- **CQRS Event Logging** - Complete audit trail
- **Least Privilege Security** - Dedicated Service Principal per agent
- **Unity Catalog Governance** - Full data lineage and permissions

## 🏗️ Architecture

```
User Query
    ↓
Coordinator Agent (Automatic Passthrough)
    ├─► Vector Search (Automatic Passthrough)
    └─► Triggers Job (Manual OAuth with EXTRACTION_SP)
            ↓
Extraction Job runs as EXTRACTION_SP
    ├─► Reads UC Volumes (Automatic Passthrough)
    ├─► Writes Delta Tables (Automatic Passthrough)
    └─► Logs CQRS Events (Automatic Passthrough)
```

**Key Insight**: Manual OAuth is used for *triggering* jobs, but once the job runs, it uses automatic passthrough for data access.

## 🔑 Critical Configuration

### Job Clusters MUST Have Unity Catalog Enabled

```python
from databricks.sdk.service import compute

new_cluster = compute.ClusterSpec(
    spark_version="14.3.x-scala2.12",
    node_type_id="i3.xlarge",
    data_security_mode=compute.DataSecurityMode.SINGLE_USER,  # Required!
    runtime_engine=compute.RuntimeEngine.PHOTON
)
```

**Without `data_security_mode: SINGLE_USER`**, Service Principals cannot access Unity Catalog Volumes.

### Permissions Hierarchy

Service Principals need three levels of permissions:

```sql
-- 1. Catalog access
GRANT USE CATALOG ON CATALOG <catalog> TO `<sp-client-id>`;

-- 2. Schema access
GRANT USE SCHEMA ON SCHEMA <catalog>.<schema> TO `<sp-client-id>`;

-- 3. Resource access (volumes, tables)
GRANT READ VOLUME ON VOLUME <catalog>.<schema>.<volume> TO `<sp-client-id>`;
```

## 📋 Prerequisites

- Databricks workspace (AWS, Azure, or GCP)
- Databricks Runtime 14.3 LTS or higher
- Unity Catalog enabled
- Account admin access (to create Service Principals)
- Databricks CLI installed

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone <repo-url>
cd banner-oncology-multi-agent

# Install Databricks CLI
pip install databricks-cli databricks-sdk

# Configure CLI
databricks configure --token
```

### 2. Create Service Principals

Create two Service Principals (via UI or CLI):
- `extraction-sp` - For extraction jobs
- `summarization-sp` - For summarization jobs

Save their Client IDs and Secrets.

### 3. Store Secrets

```bash
databricks secrets create-scope demo_agents
databricks secrets put-secret demo_agents extraction_sp_client_id
databricks secrets put-secret demo_agents extraction_sp_secret
databricks secrets put-secret demo_agents summarization_sp_client_id
databricks secrets put-secret demo_agents summarization_sp_secret
```

### 4. Upload and Run Notebooks

```bash
databricks workspace import-dir \
  ./notebooks \
  /Users/<your-email>/multi_agent_demo

# Run in order:
# 1. 01_setup_cqrs_tables.py
# 2. 02_create_extraction_job.py
# 3. 03_create_summarization_job.py
# 4. fix_file_in_volume.py (sample data)
# 5. 06_deploy_production_proper.py
```

See `QUICKSTART.md` for detailed step-by-step instructions.

## 📁 Repository Structure

```
├── README.md                          # This file
├── QUICKSTART.md                      # Detailed setup guide
├── AUTHENTICATION_PATTERNS.md         # Deep dive on auth patterns
├── SUCCESS_SUMMARY.md                 # Architecture & learnings
│
├── notebooks/                         # Databricks notebooks
│   ├── 01_setup_cqrs_tables.py       # Create infrastructure
│   ├── 02_create_extraction_job.py   # Create job with SP
│   ├── 03_create_summarization_job.py
│   ├── extraction_job_notebook_FIXED.py # Job logic
│   └── 06_deploy_production_proper.py # Deploy agent
│
├── agents/                            # Agent implementations
│   ├── coordinator_agent.py          # Orchestrator
│   ├── extraction_agent.py           # Extraction logic
│   ├── summarization_agent.py        # Summarization logic
│   └── file_storage_agent.py         # UC Volume storage
│
└── setup.py                           # Python package
```

## 🔐 Authentication Details

### Automatic Passthrough

**How it works:**
- Agent/job runs with an identity (user or SP)
- Databricks resources automatically use that identity
- No explicit credentials in code

**Example:**
```python
# No credentials needed - uses job's SP identity
spark.read.table("catalog.schema.table")

# No credentials needed - uses job's SP identity
with open("/Volumes/catalog/schema/volume/file.txt", "r") as f:
    content = f.read()
```

### Manual OAuth

**How it works:**
- Explicit client ID + secret provided
- Used to trigger jobs via Jobs API
- Credentials injected via environment variables

**Example:**
```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient(
    host=os.environ["DATABRICKS_HOST"],
    client_id=os.environ["EXTRACTION_SP_CLIENT_ID"],
    client_secret=os.environ["EXTRACTION_SP_CLIENT_SECRET"]
)

# Trigger job using this SP's credentials
run = w.jobs.run_now(job_id=job_id)
```

## 🧪 Verification

### Check Data Flow

```sql
-- Verify extraction succeeded
SELECT * FROM <catalog>.staging.extracted_documents
ORDER BY extracted_at DESC LIMIT 5;

-- Check CQRS audit trail
SELECT event_type, agent, sp_used, status, timestamp
FROM <catalog>.<schema>.job_events
ORDER BY timestamp DESC LIMIT 10;
```

### Test Agent

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

w = WorkspaceClient()

response = w.serving_endpoints.query(
    name="<your-agent-endpoint>",
    messages=[ChatMessage(
        role=ChatMessageRole.USER,
        content="Extract /Volumes/<catalog>/<schema>/source_pdfs/sample.txt"
    )]
)

print(response.choices[0].message.content)
```

## 🎓 Key Learnings

### 1. Unity Catalog Volumes Require SINGLE_USER Mode
Job clusters **must** have `data_security_mode: SINGLE_USER` to access UC Volumes. This is the critical requirement.

### 2. Permissions Must Be Hierarchical
Grant `USE CATALOG` → `USE SCHEMA` → `READ VOLUME` in that order.

### 3. SDK Cannot Write to UC Volumes
Files must be created from notebooks using direct Python I/O (`open()`). The SDK's `w.files.upload()` is for workspace files only.

### 4. Separate Authentication for Separate Purposes
- Use **Manual OAuth** when you need explicit control (triggering jobs with specific SP)
- Use **Automatic Passthrough** for data access within jobs (cleaner, more secure)

## 🔮 Future Enhancements

This is a reference implementation. Future additions could include:

- **Guardrails** - Content filtering, safety checks
- **Prompt Governance** - Versioning, approval workflows
- **Agent Governance** - Monitoring, usage tracking
- **Lakebase Integration** - Serverless PostgreSQL for conversation memory
- **Vector Search** - RAG implementation with automatic passthrough

## 🐛 Troubleshooting

### "File not found" in UC Volume
**Cause**: Job cluster missing `data_security_mode: SINGLE_USER`  
**Solution**: Update job cluster configuration

### "PERMISSION_DENIED" on UC Volume
**Cause**: Missing catalog/schema permissions  
**Solution**: Grant `USE CATALOG` and `USE SCHEMA` first

### Jobs API authentication fails
**Cause**: Incorrect SP credentials  
**Solution**: Regenerate secrets and update Databricks Secrets

See `SUCCESS_SUMMARY.md` for detailed troubleshooting.

## 📚 Documentation

- `QUICKSTART.md` - Step-by-step setup (30-45 minutes)
- `AUTHENTICATION_PATTERNS.md` - Deep dive on auth patterns
- `SUCCESS_SUMMARY.md` - Complete architecture documentation
- `CQRS_CHAINING_EXPLAINED.md` - CQRS pattern details

## 🤝 Use Cases

This architecture is suitable for:

- Healthcare document processing
- Legal document analysis
- Financial document extraction
- Any workflow requiring:
  - Async job execution
  - Multiple authentication patterns
  - Governed data access
  - Complete audit trails

## 📝 License

MIT License - See LICENSE file for details

---

**A Databricks reference implementation for multi-agent systems with dual authentication patterns**
