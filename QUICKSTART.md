# 🚀 Quick Start Guide

**Time to complete**: 30-45 minutes  
**Difficulty**: Intermediate

---

## Prerequisites Checklist

Before you begin, ensure you have:

- [ ] Databricks workspace (any cloud provider)
- [ ] Account admin access (to create Service Principals)
- [ ] Unity Catalog enabled on your workspace
- [ ] Databricks CLI installed (`pip install databricks-cli`)
- [ ] Personal Access Token for your workspace

---

## Step 1: Install Databricks CLI (5 minutes)

```bash
# Install Databricks CLI
pip install databricks-cli databricks-sdk

# Verify installation
databricks --version
```

---

## Step 2: Configure Databricks CLI (5 minutes)

```bash
# Configure with your workspace
databricks configure --token

# You'll be prompted for:
# - Databricks Host: https://<your-workspace>.cloud.databricks.com
# - Token: <your-personal-access-token>
```

**To get a Personal Access Token:**
1. Go to your Databricks workspace
2. Click your user icon (top right)
3. Select "User Settings"
4. Go to "Access Tokens" tab
5. Click "Generate New Token"
6. Copy the token (you won't see it again!)

---

## Step 3: Create Service Principals (10 minutes)

### Option A: Via Databricks UI (Recommended)

1. Go to **Settings → Admin Console → Service Principals**
2. Click **"Add Service Principal"**
3. Create the first SP:
   - Display Name: `oncology-extraction-sp`
   - Click "Add"
   - **Copy the Application ID** (this is the Client ID)
4. Generate a secret:
   - Click on the SP you just created
   - Go to "Secrets" tab
   - Click "Generate Secret"
   - **Copy the secret value** (you won't see it again!)
5. Repeat for the second SP:
   - Display Name: `oncology-summarization-sp`
   - Copy its Application ID and secret

**Save these 4 values securely:**
- Extraction SP Client ID: `________________________________`
- Extraction SP Secret: `________________________________`
- Summarization SP Client ID: `________________________________`
- Summarization SP Secret: `________________________________`

### Option B: Via CLI

```bash
# Create extraction SP
databricks service-principals create \
  --display-name "oncology-extraction-sp" \
  --json

# Note the "applicationId" from the output

# Create summarization SP
databricks service-principals create \
  --display-name "oncology-summarization-sp" \
  --json

# You'll need to generate secrets via the UI (Step 3, Option A, step 4)
```

---

## Step 4: Store Secrets in Databricks (5 minutes)

```bash
# Create a secret scope
databricks secrets create-scope oncology_agents

# Store extraction SP credentials
databricks secrets put-secret oncology_agents extraction_sp_client_id
# When prompted, paste the Extraction SP Client ID, then press Enter and Ctrl+D

databricks secrets put-secret oncology_agents extraction_sp_secret
# When prompted, paste the Extraction SP Secret, then press Enter and Ctrl+D

# Store summarization SP credentials
databricks secrets put-secret oncology_agents summarization_sp_client_id
# Paste the Summarization SP Client ID

databricks secrets put-secret oncology_agents summarization_sp_secret
# Paste the Summarization SP Secret

# Verify secrets are stored
databricks secrets list-secrets oncology_agents
```

**Expected output:**
```
Secret name                    Last updated
extraction_sp_client_id        <timestamp>
extraction_sp_secret           <timestamp>
summarization_sp_client_id     <timestamp>
summarization_sp_secret        <timestamp>
```

---

## Step 5: Upload Notebooks (5 minutes)

```bash
# Navigate to the repository
cd banner-oncology-multi-agent

# Create a directory in your workspace
databricks workspace mkdirs /Users/<your-email>/banner_oncology

# Upload all notebooks
databricks workspace import-dir \
  ./notebooks \
  /Users/<your-email>/banner_oncology \
  --overwrite
```

**Verify upload:**
```bash
databricks workspace list /Users/<your-email>/banner_oncology
```

---

## Step 6: Run Setup Notebooks (15 minutes)

Open your Databricks workspace UI and run the notebooks in this order:

### 6.1 Create CQRS Tables and UC Volumes

**Notebook**: `01_setup_cqrs_tables.py`

1. Go to `/Users/<your-email>/banner_oncology/01_setup_cqrs_tables.py`
2. **Update parameters**:
   - `catalog_name`: Your catalog (default: `main`)
   - `schema_name`: Your schema (default: `oncology`)
3. Click "Run All"
4. Wait ~2 minutes

**Expected output:**
```
✅ Created schema: <catalog>.oncology
✅ Created schema: <catalog>.staging
✅ Created table: job_events
✅ Created table: conversation_state
✅ Created table: extracted_documents
✅ Created table: summaries
✅ Created volume: source_pdfs
✅ Created volume: summaries
```

### 6.2 Create Extraction Job

**Notebook**: `02_create_extraction_job.py`

1. Open the notebook
2. **Update parameters**:
   - `catalog_name`: Same as above
   - `schema_name`: Same as above
   - `extraction_sp_client_id`: Your extraction SP Application ID
3. Click "Run All"
4. **Copy the Job ID** from the output

**Expected output:**
```
✅ Created job: <job-id>
🔗 Job URL: https://<workspace>/jobs/<job-id>
```

### 6.3 Create Summarization Job

**Notebook**: `03_create_summarization_job.py`

1. Open the notebook
2. **Update parameters** (same as above)
3. Click "Run All"
4. **Copy the Job ID** from the output

### 6.4 Upload Sample Data

**Notebook**: `fix_file_in_volume.py`

1. Open the notebook
2. No parameters needed
3. Click "Run All"

**Expected output:**
```
✅ File written successfully!
   Size: 1508 characters
✅ Verified: File exists and is readable
```

### 6.5 Deploy the Agent

**Notebook**: `06_deploy_production_proper.py`

1. Open the notebook
2. **Update parameters**:
   - `catalog_name`: Your catalog
   - `schema_name`: Your schema
   - `extraction_job_id`: Job ID from step 6.2
   - `summarization_job_id`: Job ID from step 6.3
3. Click "Run All"
4. Wait ~5-10 minutes (this builds and deploys the agent)

**Expected output:**
```
✅ DEPLOYMENT COMPLETE!
📊 Model: <catalog>.<schema>.oncology_coordinator
📊 Version: 1
📊 Endpoint: agents_<catalog>-<schema>-oncology_coordinator
🔗 View Endpoint: <endpoint-url>
```

**Copy the endpoint URL** - you'll need it for testing!

---

## Step 7: Grant Permissions (5 minutes)

### 7.1 Grant Service Principal User Role

For each job you created:

1. Go to the job URL (from step 6.2 and 6.3)
2. Click "Permissions" (top right)
3. Click "Grant" → "Service Principal"
4. Search for your extraction SP (for extraction job) or summarization SP (for summarization job)
5. Select "Can Manage" permission
6. Click "Add"

### 7.2 Grant UC Permissions via SQL

**📄 See `GRANT_PERMISSIONS.sql` for the full SQL script with comments.**

Open a SQL Editor in Databricks and run the SQL commands from `GRANT_PERMISSIONS.sql` after replacing the placeholders:

- `<CATALOG_NAME>`: Your catalog name (e.g., `test_demo`)
- `<SCHEMA_NAME>`: Your schema name (e.g., `multi_agent`)
- `<EXTRACTION_SP_CLIENT_ID>`: Your extraction SP's Application ID
- `<SUMMARIZATION_SP_CLIENT_ID>`: Your summarization SP's Application ID

**Quick reference:**

```sql
-- For EXTRACTION_SP:
GRANT USE CATALOG ON CATALOG <CATALOG_NAME> TO `<EXTRACTION_SP_CLIENT_ID>`;
GRANT USE SCHEMA ON SCHEMA <CATALOG_NAME>.<SCHEMA_NAME> TO `<EXTRACTION_SP_CLIENT_ID>`;
GRANT READ VOLUME ON VOLUME <CATALOG_NAME>.<SCHEMA_NAME>.source_pdfs TO `<EXTRACTION_SP_CLIENT_ID>`;
GRANT SELECT, INSERT ON TABLE <CATALOG_NAME>.staging.extracted_documents TO `<EXTRACTION_SP_CLIENT_ID>`;
GRANT SELECT, INSERT ON TABLE <CATALOG_NAME>.<SCHEMA_NAME>.job_events TO `<EXTRACTION_SP_CLIENT_ID>`;

-- For SUMMARIZATION_SP:
GRANT USE CATALOG ON CATALOG <CATALOG_NAME> TO `<SUMMARIZATION_SP_CLIENT_ID>`;
GRANT USE SCHEMA ON SCHEMA <CATALOG_NAME>.<SCHEMA_NAME> TO `<SUMMARIZATION_SP_CLIENT_ID>`;
GRANT WRITE VOLUME ON VOLUME <CATALOG_NAME>.<SCHEMA_NAME>.summaries TO `<SUMMARIZATION_SP_CLIENT_ID>`;
GRANT SELECT, INSERT ON TABLE <CATALOG_NAME>.staging.summaries TO `<SUMMARIZATION_SP_CLIENT_ID>`;
GRANT SELECT, INSERT ON TABLE <CATALOG_NAME>.<SCHEMA_NAME>.job_events TO `<SUMMARIZATION_SP_CLIENT_ID>`;
```

---

## Step 8: Test the Agent (5 minutes)

### Via Databricks UI:

1. Go to the endpoint URL (from step 6.5)
2. Click "Query Endpoint" tab
3. Enter this query:
```
Extract /Volumes/<catalog>/<schema>/source_pdfs/patient_001_oncology_report.txt
```
4. Click "Send"

**Expected response:**
```
✅ Extraction started for /Volumes/.../patient_001_oncology_report.txt
🔗 Run ID: <run-id>

This uses EXTRACTION_SP (manual OAuth) to trigger the job.
```

### Via Python:

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

w = WorkspaceClient()

response = w.serving_endpoints.query(
    name="agents_<catalog>-<schema>-oncology_coordinator",
    messages=[
        ChatMessage(
            role=ChatMessageRole.USER,
            content="Extract /Volumes/<catalog>/<schema>/source_pdfs/patient_001_oncology_report.txt"
        )
    ]
)

print(response.choices[0].message.content)
```

---

## Step 9: Verify Results (5 minutes)

### Check Extracted Data:

```sql
SELECT 
    extraction_id,
    document_path,
    LEFT(extracted_text, 500) as preview,
    extracted_by,
    extracted_at
FROM <catalog>.staging.extracted_documents
ORDER BY extracted_at DESC
LIMIT 5;
```

**Expected**: You should see real extracted text from the oncology report!

### Check CQRS Events:

```sql
SELECT 
    event_type,
    run_id,
    agent,
    sp_used,
    status,
    timestamp
FROM <catalog>.<schema>.job_events
ORDER BY timestamp DESC
LIMIT 10;
```

**Expected**: Events showing `ExtractionJobCompleted` with `sp_used: "EXTRACTION_SP"`

---

## 🎉 Success!

You now have a working multi-agent system with:

- ✅ Async job execution
- ✅ CQRS event logging
- ✅ Manual OAuth for Jobs API
- ✅ Automatic passthrough for UC resources
- ✅ Full audit trail

---

## 🐛 Troubleshooting

### Issue: "File not found" error

**Check**:
1. Did `fix_file_in_volume.py` run successfully?
2. Does the file exist?
```sql
SELECT * FROM dbfs.list('/Volumes/<catalog>/<schema>/source_pdfs/');
```

### Issue: "PERMISSION_DENIED" error

**Check**:
1. Did you grant all UC permissions in Step 7.2?
2. Verify grants:
```sql
SHOW GRANTS ON VOLUME <catalog>.<schema>.source_pdfs;
```

### Issue: "Job failed with INTERNAL_ERROR"

**Check**:
1. Go to the job run URL
2. Click on the task
3. View the notebook output
4. Look for the actual error message

Common causes:
- Job cluster not configured with `data_security_mode: SINGLE_USER`
- Missing notebook execution permissions
- Missing table write permissions

---

## 📚 Next Steps

1. Review `ELEVATOR_PITCH.md` for demo talking points
2. Read `SUCCESS_SUMMARY.md` for architecture details
3. Customize agents for your use case
4. Add your own PDF processing logic
5. Integrate with your data sources

---

**Need help?** Open an issue on GitHub or check the main README.md

