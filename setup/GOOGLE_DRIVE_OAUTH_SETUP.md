# Google Drive OAuth Setup for Demo

**Your Folder ID:** `1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3`  
**Your Email:** `samuel.selvan@databricks.com`

**Time Required:** 10 minutes

---

## Step 1: Create Google Cloud Project (3 min)

1. Go to: https://console.cloud.google.com/
2. Sign in with `samuel.selvan@databricks.com`
3. Click "Select a project" → "New Project"
4. Project name: `oncology-demo`
5. Click "Create"
6. Wait for project to be created (~30 seconds)

---

## Step 2: Enable Google Drive API (2 min)

1. In Google Cloud Console, make sure `oncology-demo` project is selected
2. Go to: https://console.cloud.google.com/apis/library
3. Search for "Google Drive API"
4. Click on "Google Drive API"
5. Click "Enable"
6. Wait for it to enable (~10 seconds)

---

## Step 3: Create OAuth 2.0 Credentials (3 min)

### 3.1. Configure OAuth Consent Screen

1. Go to: https://console.cloud.google.com/apis/credentials/consent
2. Select "Internal" (since you're @databricks.com)
3. Click "Create"
4. Fill in:
   - **App name:** `Oncology Demo`
   - **User support email:** `samuel.selvan@databricks.com`
   - **Developer contact:** `samuel.selvan@databricks.com`
5. Click "Save and Continue"
6. **Scopes:** Click "Add or Remove Scopes"
   - Search for: `Google Drive API`
   - Check: `.../auth/drive.file` (View and manage Google Drive files created by this app)
7. Click "Update" → "Save and Continue"
8. Click "Back to Dashboard"

### 3.2. Create OAuth Client ID

1. Go to: https://console.cloud.google.com/apis/credentials
2. Click "Create Credentials" → "OAuth client ID"
3. Application type: **Desktop app**
4. Name: `Oncology Demo Desktop`
5. Click "Create"
6. **IMPORTANT:** Click "Download JSON"
   - Save as `credentials.json`
   - You'll need this file!
7. Click "OK"

---

## Step 4: Get Refresh Token (2 min)

### Option A: Use Python Script (Recommended)

```python
# Run this in a Databricks notebook or local Python

!pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import json

# Upload your credentials.json file first, then update this path
CREDENTIALS_FILE = '/path/to/credentials.json'

# Scopes needed
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Start OAuth flow
flow = InstalledAppFlow.from_client_secrets_file(
    CREDENTIALS_FILE, 
    SCOPES
)

# This will open a browser window for you to authorize
# Click "Allow" to grant access
creds = flow.run_local_server(port=0)

# Extract the important parts
print("✅ Authorization successful!")
print()
print("Copy these values to Databricks Secrets:")
print("="*60)
print(f"GOOGLE_OAUTH_TOKEN (refresh_token):")
print(creds.refresh_token)
print()
print(f"GOOGLE_CLIENT_ID:")
with open(CREDENTIALS_FILE) as f:
    data = json.load(f)
    print(data['installed']['client_id'])
print()
print(f"GOOGLE_CLIENT_SECRET:")
print(data['installed']['client_secret'])
print("="*60)
```

**What happens:**
1. Browser opens
2. You log in with `samuel.selvan@databricks.com`
3. Click "Allow"
4. Script prints your refresh token + client ID/secret

### Option B: Manual (if Python doesn't work)

Use Google's OAuth 2.0 Playground:
1. Go to: https://developers.google.com/oauthplayground/
2. Click gear icon (top right) → "Use your own OAuth credentials"
3. Paste your Client ID and Client Secret (from downloaded JSON)
4. In Step 1: Select "Drive API v3" → `.../auth/drive.file`
5. Click "Authorize APIs"
6. Log in with `samuel.selvan@databricks.com`
7. Click "Allow"
8. In Step 2: Click "Exchange authorization code for tokens"
9. **Copy the "Refresh token"** (you'll need this!)

---

## Step 5: Store in Databricks Secrets (2 min)

Now store the credentials from Step 4 in Databricks:

### Via UI:

1. Go to: Databricks → Settings → Developer → Secrets
2. Select scope: `oncology_agents` (you created this earlier)
3. Add 4 new secrets:

| Key | Value |
|-----|-------|
| `google_oauth_token` | Your refresh token from Step 4 |
| `google_client_id` | Client ID from credentials.json |
| `google_client_secret` | Client secret from credentials.json |
| `google_drive_folder_id` | `1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3` |

### Via CLI:

```bash
# Store refresh token
databricks secrets put-secret oncology_agents google_oauth_token
# Paste your refresh token when prompted

# Store client ID
databricks secrets put-secret oncology_agents google_client_id
# Paste your client ID when prompted

# Store client secret
databricks secrets put-secret oncology_agents google_client_secret
# Paste your client secret when prompted

# Store folder ID
databricks secrets put-secret oncology_agents google_drive_folder_id
# Paste: 1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3
```

---

## ✅ Verify Setup

### Test 1: Check Secrets Exist

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

secrets = w.secrets.list_secrets(scope="oncology_agents")
for s in secrets:
    print(f"✅ Secret: {s.key}")

# Should see:
# ✅ Secret: google_oauth_token
# ✅ Secret: google_client_id
# ✅ Secret: google_client_secret
# ✅ Secret: google_drive_folder_id
# ✅ Secret: extraction_sp_client_id
# ✅ Secret: extraction_sp_secret
# ✅ Secret: summarization_sp_client_id
# ✅ Secret: summarization_sp_secret
```

### Test 2: Test Upload (Optional)

```python
import os
os.environ['GOOGLE_OAUTH_TOKEN'] = dbutils.secrets.get("oncology_agents", "google_oauth_token")
os.environ['GOOGLE_CLIENT_ID'] = dbutils.secrets.get("oncology_agents", "google_client_id")
os.environ['GOOGLE_CLIENT_SECRET'] = dbutils.secrets.get("oncology_agents", "google_client_secret")
os.environ['GOOGLE_DRIVE_FOLDER_ID'] = dbutils.secrets.get("oncology_agents", "google_drive_folder_id")

# Import the agent
from agents.google_drive_agent import GoogleDriveAgent

# Test access
agent = GoogleDriveAgent()
result = agent.check_access()
print(result)

# If successful, try upload
if result['status'] == 'success':
    upload_result = agent.upload_summary(
        summary="Test summary",
        patient_id="test_123",
        extraction_run_id="run_001",
        summarization_run_id="run_002"
    )
    print(upload_result)
```

---

## 🎯 Summary

After completing these steps, you'll have:

✅ Google Cloud project: `oncology-demo`  
✅ Google Drive API enabled  
✅ OAuth 2.0 credentials created  
✅ Refresh token obtained  
✅ All credentials stored in Databricks Secrets  
✅ Google Drive agent ready to use  

**Next:** Update your deployment notebook to use Google Drive instead of SharePoint!

---

## 🔒 Security Notes

**What you're storing:**
- `google_oauth_token` - Refresh token (long-lived, can generate new access tokens)
- `google_client_id` - Public identifier (not sensitive, but keep private)
- `google_client_secret` - Secret (like a password, must keep secure)
- `google_drive_folder_id` - Just a folder ID (not sensitive)

**Permissions:**
- OAuth scope: `drive.file` = Can only access files created by this app
- Cannot: Read/modify other files in your Drive
- Cannot: Access other Google services (Gmail, Calendar, etc.)
- Your folder `1OjhbQOl2nojXkLI-cp9SgwgD10G4U0j3` is accessible

**Refresh token:**
- Never expires (unless you revoke it)
- Can generate new access tokens automatically
- Used by agent to upload files without asking for permission each time

---

## 🚨 Troubleshooting

### "Access denied" or "Invalid grant"
- Refresh token expired or revoked
- Solution: Re-run Step 4 to get new refresh token

### "Folder not found"
- Agent doesn't have access to folder
- Solution: Make sure folder is owned by `samuel.selvan@databricks.com` or shared with you

### "Insufficient permissions"
- OAuth scope too restrictive
- Solution: Re-create OAuth credentials with `drive.file` scope

### "Quota exceeded"
- Too many API calls
- Solution: Wait a few minutes, Google has rate limits

---

**Ready?** Once you complete these 5 steps, come back and I'll update the deployment notebook to use Google Drive!

