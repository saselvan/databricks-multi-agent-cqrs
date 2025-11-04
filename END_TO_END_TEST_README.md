# End-to-End Test Guide

This automated test script validates the entire multi-agent setup from a fresh clone.

---

## Prerequisites

Before running the test:

### 1. Create Two Service Principals

Via Databricks UI (Settings → Admin Console → Service Principals):

1. **Extraction SP**: `test-extraction-sp`
   - Copy Application ID (Client ID)
   - Generate and copy secret

2. **Summarization SP**: `test-summarization-sp`
   - Copy Application ID (Client ID)
   - Generate and copy secret

### 2. Install Dependencies

```bash
pip install databricks-sdk
```

### 3. Configure Databricks CLI

```bash
databricks configure --token
# Enter your workspace URL and PAT
```

---

## Run the Test

```bash
python END_TO_END_TEST.py \
  --catalog test_demo \
  --schema multi_agent \
  --extraction-sp-id "YOUR-EXTRACTION-SP-CLIENT-ID" \
  --extraction-sp-secret "YOUR-EXTRACTION-SP-SECRET" \
  --summarization-sp-id "YOUR-SUMMARIZATION-SP-CLIENT-ID" \
  --summarization-sp-secret "YOUR-SUMMARIZATION-SP-SECRET"
```

---

## What the Test Does

The script automates **10 steps**:

1. ✅ **Create Catalog & Schemas** - Creates Unity Catalog resources
2. ✅ **Store Secrets** - Stores SP credentials in Databricks Secrets
3. ✅ **Upload Notebooks** - Uploads notebooks to workspace
4. ⏱️  **Run Setup Notebook** - Creates CQRS tables and UC Volumes (~5 min)
5. ✅ **Create Jobs** - Creates extraction and summarization jobs with SPs
6. 🖐️ **Grant Permissions** - Provides SQL to grant UC permissions (manual)
7. 🖐️ **Create Sample Data** - Provides instructions to create sample file (manual)
8. 🖐️ **Deploy Agent** - Provides instructions to run deployment notebook (manual)
9. ✅ **Test Agent** - Sends test query to deployed agent
10. ✅ **Verify Results** - Provides SQL queries to verify CQRS events

**Legend**:
- ✅ Fully automated
- ⏱️  Automated (requires waiting)
- 🖐️ Semi-automated (requires user confirmation/input)

---

## Manual Steps

Some steps require user interaction:

### Step 6: Grant Permissions

The script will print SQL commands. Execute them in a Databricks SQL editor:

```sql
GRANT USE CATALOG ON CATALOG test_demo TO `<sp-client-id>`;
GRANT USE SCHEMA ON SCHEMA test_demo.multi_agent TO `<sp-client-id>`;
-- ... more grants
```

Then press ENTER in the script to continue.

### Step 7: Create Sample Data

Option A: Run the notebook `00_upload_sample_pdf.py` in the UI

Option B: Manually create a file at:
```
/Volumes/test_demo/multi_agent/source_pdfs/patient_001.txt
```

Press ENTER to continue.

### Step 8: Deploy Agent

Run the deployment notebook `06_deploy_production_proper.py` in the UI with parameters:
- `catalog_name`: test_demo
- `schema_name`: multi_agent
- `extraction_job_id`: (provided by script)
- `summarization_job_id`: (provided by script)

When deployment completes, enter the endpoint name in the script.

---

## Expected Duration

- **Automated steps**: ~10-15 minutes (mostly cluster startup)
- **Manual steps**: ~10-15 minutes (SQL execution, notebook runs)
- **Total**: ~30-45 minutes

---

## Troubleshooting

### "PERMISSION_DENIED" errors

**Cause**: Service Principal doesn't have UC permissions

**Fix**: Run the SQL grant commands from Step 6

### "File not found" in UC Volume

**Cause**: Job cluster not configured with `SINGLE_USER` mode

**Fix**: The script creates jobs with correct config. If you created jobs manually, update them to use `DataSecurityMode.SINGLE_USER`.

### "Endpoint not found"

**Cause**: Deployment notebook hasn't completed

**Fix**: Wait for deployment notebook to finish (~5-10 minutes)

---

## Cleanup

To remove test resources after verification:

```python
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

# Delete catalog (cascades to all resources)
w.catalogs.delete(name="test_demo", force=True)

# Delete jobs
w.jobs.delete(job_id=EXTRACTION_JOB_ID)
w.jobs.delete(job_id=SUMMARIZATION_JOB_ID)

# Delete endpoint
w.serving_endpoints.delete(name=ENDPOINT_NAME)

# Delete workspace files
w.workspace.delete(path="/Users/<your-email>/test_multi_agent_demo", recursive=True)

# Delete secrets
w.secrets.delete_scope(scope="test_agents")
```

---

## Success Criteria

The test is successful when:

1. ✅ All automated steps complete without errors
2. ✅ Agent responds to test query
3. ✅ CQRS events are logged in Delta table
4. ✅ Extraction job can be triggered via Jobs API
5. ✅ UC permissions are correctly enforced

---

## What This Validates

- ✅ **Automatic Passthrough Authentication** works for UC resources
- ✅ **Manual OAuth** works for Jobs API
- ✅ **CQRS event logging** captures all operations
- ✅ **Service Principal isolation** (different SPs for different agents)
- ✅ **Unity Catalog permissions** are correctly configured
- ✅ **Serverless workspace URL detection** works correctly
- ✅ **Agent Framework deployment** succeeds
- ✅ **End-to-end workflow** (trigger job → extract data → log events)

---

**This test validates that someone cloning the GitHub repo can successfully set up and run the multi-agent system!** 🎉

