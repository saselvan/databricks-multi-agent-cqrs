# Why Unity Catalog Volumes > DBFS

**Decision:** Use UC Volumes for file storage instead of DBFS

---

## The Better Architecture

```
┌─────────────────────────────────────────────────────────┐
│  AUTOMATIC PASSTHROUGH AUTHENTICATION                    │
│  (No dedicated SPs needed!)                              │
├─────────────────────────────────────────────────────────┤
│  ✅ Vector Search (Coordinator queries knowledge)        │
│  ✅ Unity Catalog tables (CQRS Delta tables)             │
│  ✅ Unity Catalog Volumes (File storage)                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  MANUAL OAUTH (Dedicated SPs required)                   │
├─────────────────────────────────────────────────────────┤
│  ❌ Jobs API (Extraction Agent) → EXTRACTION_SP          │
│  ❌ Jobs API (Summarization Agent) → SUMMARIZATION_SP    │
└─────────────────────────────────────────────────────────┘
```

**SPs needed:** 2 (not 3!)

---

## Why UC Volumes Are Better

### 1. Unity Catalog Governance ✅

**UC Volumes:**
- Permissions: Grant/revoke at volume level
- Lineage: See which job wrote which file
- Audit: Track all access (who, when, from where)
- Versioning: Time travel for files

**DBFS:**
- Permissions: Workspace-wide (all or nothing)
- Lineage: None
- Audit: Limited
- Versioning: Manual

### 2. Modern Databricks Best Practice ✅

**UC Volumes:**
- Part of Unity Catalog (the future)
- Recommended for new projects
- Integrated with lakehouse
- First-class citizen

**DBFS:**
- Legacy storage
- Being deprecated
- Not governed
- Discouraged for new projects

### 3. Automatic Passthrough Authentication ✅

**UC Volumes:**
```python
# No credentials needed!
agent = FileStorageAgent()
agent.upload_summary(...)  # Just works with automatic passthrough
```

**DBFS:**
```python
# Also works, but UC is the modern way
agent = FileStorageAgent()
agent.upload_summary(...)  # Works but not best practice
```

### 4. Security & Compliance ✅

**UC Volumes:**
- Column-level security (future)
- Data classification tags
- Compliance frameworks (HIPAA, SOC 2)
- Encryption at rest (managed)

**DBFS:**
- Workspace-level only
- No tagging
- Limited compliance features
- Encryption (but less governed)

---

## For Banner Presentation

### What to Say:

> "We're using Unity Catalog Volumes to store the final summaries. This gives us:
> - **Automatic passthrough authentication** - no dedicated SP needed
> - **Full governance** - permissions, lineage, audit trails
> - **HIPAA compliance path** - UC has the controls Banner needs
> - **Modern approach** - UC Volumes are the recommended way
> 
> We only need dedicated SPs for the Jobs API, which doesn't support automatic passthrough yet. Everything else - Vector Search, UC tables, UC volumes - uses automatic passthrough."

### Why This Resonates:

**Banner's pain point:** Manual SP management, credential rotation  
**Our solution:** "Use automatic passthrough for 95% of resources. Only need manual SPs for Jobs API."

**Banner's requirement:** HIPAA compliance  
**Our solution:** "UC provides the governance and audit trails you need."

---

## Code Comparison

### Unity Catalog Volume (Current):
```python
# File Storage Agent (uses automatic passthrough)
class FileStorageAgent:
    def __init__(self):
        # Path: /Volumes/{catalog}/{schema}/{volume}/
        self.storage_path = "/Volumes/your_catalog/your_schema_cqrs/summaries/"
        # No credentials needed - automatic passthrough! ✅
    
    def upload_summary(self, summary, patient_id, ...):
        filepath = os.path.join(self.storage_path, filename)
        with open(filepath, 'w') as f:
            f.write(summary)
        # UC automatically tracks: who, when, from which endpoint ✅
```

### DBFS (Old way):
```python
# File Storage Agent
class FileStorageAgent:
    def __init__(self):
        # Path: /dbfs/your_schema_summaries/
        self.storage_path = "/dbfs/your_schema_summaries/"
        # Works but not best practice ⚠️
    
    def upload_summary(self, summary, patient_id, ...):
        filepath = os.path.join(self.storage_path, filename)
        with open(filepath, 'w') as f:
            f.write(summary)
        # No lineage, no audit ❌
```

---

## Migration Path for Banner

**Phase 1 (Demo):**
```
Summaries → UC Volume (/Volumes/your_catalog/your_schema_cqrs/summaries/)
```

**Phase 2 (Production):**
```
Summaries → Banner's SharePoint (same agent interface, just swap the storage backend)
```

**Key point:** UC Volume for demo shows the governance model. SharePoint for production uses the same pattern.

---

## Technical Benefits

### 1. Query Files with SQL
```sql
-- List all summary files
LIST '/Volumes/your_catalog/your_schema_cqrs/summaries/';

-- Read file metadata
SELECT * FROM information_schema.files
WHERE file_path LIKE '%/summaries/%';
```

### 2. Permissions Management
```sql
-- Grant read access to specific users
GRANT READ FILES ON VOLUME your_catalog.your_schema_cqrs.summaries 
TO `clinician@banner.com`;

-- Revoke write access
REVOKE WRITE FILES ON VOLUME your_catalog.your_schema_cqrs.summaries 
FROM `extraction-sp`;
```

### 3. Lineage Tracking
- See which endpoint wrote which file
- Track downstream consumption
- Build data lineage graphs
- Required for compliance

---

## Summary

**What changed:** DBFS → Unity Catalog Volumes  
**Why:** Governance, modern best practice, automatic passthrough, HIPAA path  
**Impact:** Same code, better architecture, stronger story for Banner  
**SPs needed:** Still 2 (Extraction + Summarization for Jobs API only)

---

## Files Updated

1. ✅ `agents/file_storage_agent.py` - Now uses UC Volumes
2. ✅ `QUICKSTART_BANNER.md` - Updated to reference UC Volumes
3. ✅ Setup notebook will create UC Volume

**Status:** Ready to deploy with UC Volumes!

