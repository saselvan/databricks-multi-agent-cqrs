# Future Enhancement: Google Drive Integration

**Status:** Optional - Use this guide when OAuth client creation access is approved

**Your Drive Folder:** https://drive.google.com/drive/folders/1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3

**Current Demo:** Uses DBFS for file storage (no external auth needed)  
**Future:** Swap to Google Drive with these instructions

---

## Why Google Drive?

**For Demo (DBFS is fine):**
- ✅ No external auth
- ✅ Fast to set up
- ✅ Shows the pattern

**For Real Use (Google Drive/SharePoint better):**
- ✅ Accessible outside Databricks
- ✅ Integrates with existing workflows
- ✅ Familiar to end users
- ✅ Built-in collaboration features

---

## When You Have OAuth Client Creation Access

### Step 1: Create Google Cloud OAuth Client (5 min)

**Prerequisites:**
- Access to `fe-dev-sandbox` Google Cloud project
- Permission to create OAuth clients (you've requested this)

**Steps:**

1. Go to: https://console.cloud.google.com/apis/credentials?project=fe-dev-sandbox
2. Click **"+ CREATE CREDENTIALS"** → **"OAuth client ID"**
3. Application type: **"Desktop app"**
4. Name: `oncology-demo-sselvan`
5. Click **"CREATE"**
6. Click **"DOWNLOAD JSON"**
   - Save as `client_secret_697856052963-xxxx.json`
7. Click **"OK"**

---

### Step 2: Get Refresh Token (5 min)

**Run this in a Databricks notebook:**

```python
# Install dependencies
%pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client

# Upload your client_secret_....json to DBFS first
# Then update this path:
CREDENTIALS_FILE = '/dbfs/FileStore/client_secret_697856052963-xxxx.json'

from google_auth_oauthlib.flow import InstalledAppFlow
import json

# Scopes needed
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Start OAuth flow
flow = InstalledAppFlow.from_client_secrets_file(
    CREDENTIALS_FILE, 
    SCOPES
)

# This will print a URL - open it in your browser
# Log in with samuel.selvan@databricks.com
# Click "Allow"
# Copy the authorization code and paste it back
creds = flow.run_console()

# Extract credentials
print("\n" + "="*80)
print("✅ Authorization successful! Copy these to Databricks Secrets:")
print("="*80)
print(f"\nREFRESH_TOKEN:")
print(creds.refresh_token)
print()

with open(CREDENTIALS_FILE) as f:
    data = json.load(f)
    print(f"CLIENT_ID:")
    print(data['installed']['client_id'])
    print()
    print(f"CLIENT_SECRET:")
    print(data['installed']['client_secret'])
print("="*80)
```

---

### Step 3: Store in Databricks Secrets (2 min)

```bash
# Add Google Drive credentials to existing scope
databricks secrets put-secret oncology_agents google_oauth_token
# Paste refresh token

databricks secrets put-secret oncology_agents google_client_id
# Paste client ID

databricks secrets put-secret oncology_agents google_client_secret
# Paste client secret

databricks secrets put-secret oncology_agents google_drive_folder_id
# Paste: 1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3
```

---

### Step 4: Swap Agent (1 min)

In your deployment notebook (`04_deploy_coordinator.py`), change:

**Current (DBFS):**
```python
from agents.file_storage_agent import FileStorageAgent

storage_agent = FileStorageAgent()
# Uses DBFS by default
```

**New (Google Drive):**
```python
from agents.google_drive_agent import GoogleDriveAgent

# Inject Google Drive credentials
os.environ['GOOGLE_OAUTH_TOKEN'] = dbutils.secrets.get("oncology_agents", "google_oauth_token")
os.environ['GOOGLE_CLIENT_ID'] = dbutils.secrets.get("oncology_agents", "google_client_id")
os.environ['GOOGLE_CLIENT_SECRET'] = dbutils.secrets.get("oncology_agents", "google_client_secret")
os.environ['GOOGLE_DRIVE_FOLDER_ID'] = dbutils.secrets.get("oncology_agents", "google_drive_folder_id")

storage_agent = GoogleDriveAgent()
```

---

### Step 5: Redeploy (10 min)

Run the deployment notebook again with the new agent. That's it!

---

## Architecture: DBFS vs Google Drive

### Current (DBFS):
```
Summarization Job
       ↓
File Storage Agent
       ↓
DBFS: /dbfs/oncology_summaries/
       ↓
Access via: Databricks workspace or dbutils
```

### Future (Google Drive):
```
Summarization Job
       ↓
Google Drive Agent
       ↓
Google Drive: https://drive.google.com/drive/folders/1Ojhb...
       ↓
Access via: Web browser, Google Drive desktop app, mobile app
```

---

## For Banner Presentation

**What to say:**
> "For the demo, we're writing to DBFS. In production for Banner, this would be SharePoint. The agent code is identical - we just swap the storage backend. Takes 10 minutes to integrate any storage system: Google Drive, SharePoint, S3, Azure Blob, etc."

**Show them:**
1. DBFS files in `/dbfs/oncology_summaries/`
2. Explain how easy it is to swap (show `google_drive_agent.py`)
3. Banner will use their own SharePoint credentials

---

## Benefits of This Approach

✅ **Demo works TODAY** (no waiting for Google Cloud permissions)  
✅ **Shows the pattern** (multi-agent, security isolation, CQRS)  
✅ **Easy to swap** (10 minutes to add Google Drive later)  
✅ **Realistic for Banner** (they'll use SharePoint anyway)  

---

## File Structure

```
agents/
├── file_storage_agent.py     ← Current (DBFS) - in use now
├── google_drive_agent.py     ← Future (Google Drive) - use this guide
└── sharepoint_agent.py       ← For Banner production
```

All three implement the same interface - swap anytime!

---

## Testing Google Drive Access (When Ready)

```python
from agents.google_drive_agent import GoogleDriveAgent

# Set environment variables (from secrets)
os.environ['GOOGLE_OAUTH_TOKEN'] = dbutils.secrets.get("oncology_agents", "google_oauth_token")
os.environ['GOOGLE_CLIENT_ID'] = dbutils.secrets.get("oncology_agents", "google_client_id")
os.environ['GOOGLE_CLIENT_SECRET'] = dbutils.secrets.get("oncology_agents", "google_client_secret")
os.environ['GOOGLE_DRIVE_FOLDER_ID'] = "1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3"

# Test access
agent = GoogleDriveAgent()
result = agent.check_access()
print(result)

# If successful, test upload
if result['status'] == 'success':
    upload_result = agent.upload_summary(
        summary="Test summary from Databricks",
        patient_id="test_001",
        extraction_run_id="run_123",
        summarization_run_id="run_456"
    )
    print(upload_result)
    
    # Check your Drive folder - file should appear!
```

---

## Summary

**Current state:** DBFS (works now, no waiting)  
**Future state:** Google Drive (10 min to integrate when access approved)  
**Banner state:** SharePoint (same 10 min integration, they provide creds)

**All files preserved:**
- ✅ `agents/google_drive_agent.py` - ready to use
- ✅ `setup/GOOGLE_DRIVE_OAUTH_SETUP.md` - detailed setup guide
- ✅ This file - quick reference for future integration

---

**When your Google Cloud access is approved, follow this guide - takes 10 minutes total!**

