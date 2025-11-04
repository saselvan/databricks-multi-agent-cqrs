# GitHub Authentication Setup

Complete guide to authenticate Git with your GitHub account.

---

## Method 1: SSH Keys (Recommended) ⭐

### Step 1: Generate SSH Key

```bash
ssh-keygen -t ed25519 -C "samuel.selvan@databricks.com"
```

When prompted:
- **File location**: Press ENTER (accept default: `/Users/samuel.selvan/.ssh/id_ed25519`)
- **Passphrase**: Press ENTER for no passphrase, OR set a secure passphrase if you prefer

**Output should show:**
```
Your identification has been saved in /Users/samuel.selvan/.ssh/id_ed25519
Your public key has been saved in /Users/samuel.selvan/.ssh/id_ed25519.pub
```

---

### Step 2: Start SSH Agent and Add Key

```bash
# Start the ssh-agent
eval "$(ssh-agent -s)"

# Add your SSH key to the agent
ssh-add ~/.ssh/id_ed25519
```

**Expected output:**
```
Agent pid 12345
Identity added: /Users/samuel.selvan/.ssh/id_ed25519
```

---

### Step 3: Copy Public Key

```bash
# Copy the public key to clipboard
cat ~/.ssh/id_ed25519.pub | pbcopy

# Or just display it to copy manually
cat ~/.ssh/id_ed25519.pub
```

**The key will look like:**
```
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJl3dI... samuel.selvan@databricks.com
```

---

### Step 4: Add to GitHub

1. Go to **GitHub.com** and log in
2. Click your profile picture (top right) → **Settings**
3. In the left sidebar, click **SSH and GPG keys**
4. Click **New SSH key** (green button)
5. Fill in:
   - **Title**: `Databricks Laptop` (or any name you want)
   - **Key**: Paste your public key (already in clipboard)
6. Click **Add SSH key**
7. Confirm with your GitHub password if prompted

---

### Step 5: Test Connection

```bash
ssh -T git@github.com
```

**Expected output:**
```
Hi YOUR-GITHUB-USERNAME! You've successfully authenticated, but GitHub does not provide shell access.
```

If you see this, **you're all set!** ✅

---

### Step 6: Configure Git to Use SSH

```bash
# For the multi-agent repo
cd /Users/samuel.selvan/Documents/Customer/Banner/banner-oncology-multi-agent

# Add remote using SSH URL
git remote add origin git@github.com:YOUR-GITHUB-USERNAME/databricks-multi-agent-cqrs.git

# Verify
git remote -v
```

**Expected output:**
```
origin  git@github.com:YOUR-GITHUB-USERNAME/databricks-multi-agent-cqrs.git (fetch)
origin  git@github.com:YOUR-GITHUB-USERNAME/databricks-multi-agent-cqrs.git (push)
```

---

## Method 2: Personal Access Token (HTTPS)

If you prefer HTTPS instead of SSH:

### Step 1: Generate Personal Access Token

1. Go to **GitHub.com** and log in
2. Click your profile picture (top right) → **Settings**
3. Scroll down left sidebar → **Developer settings**
4. Click **Personal access tokens** → **Tokens (classic)**
5. Click **Generate new token** → **Generate new token (classic)**
6. Fill in:
   - **Note**: `Databricks Laptop`
   - **Expiration**: Choose duration (90 days recommended)
   - **Scopes**: Check `repo` (full control of private repositories)
7. Click **Generate token** (bottom of page)
8. **Copy the token immediately** (you won't see it again!)

**Token looks like:** `ghp_1234567890abcdefghijklmnopqrstuvwxyz`

---

### Step 2: Configure Git to Use Token

```bash
cd /Users/samuel.selvan/Documents/Customer/Banner/banner-oncology-multi-agent

# Add remote using HTTPS URL
git remote add origin https://github.com/YOUR-GITHUB-USERNAME/databricks-multi-agent-cqrs.git

# First time push - it will prompt for credentials
git push -u origin main
```

**When prompted:**
- **Username**: Your GitHub username
- **Password**: Paste your Personal Access Token (NOT your GitHub password!)

---

### Step 3: Cache Credentials (Optional)

To avoid typing the token every time:

```bash
# Cache credentials for 1 hour
git config --global credential.helper cache

# Or cache for longer (e.g., 1 week = 604800 seconds)
git config --global credential.helper 'cache --timeout=604800'

# Or store permanently (less secure)
git config --global credential.helper store
```

---

## Troubleshooting

### "Permission denied (publickey)"

**Cause:** SSH key not properly added to GitHub or ssh-agent

**Fix:**
```bash
# Verify key is in ssh-agent
ssh-add -l

# If not, add it
ssh-add ~/.ssh/id_ed25519

# Test GitHub connection
ssh -T git@github.com
```

---

### "Authentication failed" (HTTPS)

**Cause:** Using GitHub password instead of Personal Access Token

**Fix:**
- Generate a Personal Access Token (see Method 2 above)
- Use the token as your password, NOT your GitHub password

---

### "remote origin already exists"

**Cause:** You already added a remote

**Fix:**
```bash
# Remove existing remote
git remote remove origin

# Add new one
git remote add origin git@github.com:YOUR-USERNAME/repo.git
```

---

## Quick Reference

### After setup, push to GitHub:

```bash
cd /Users/samuel.selvan/Documents/Customer/Banner/banner-oncology-multi-agent

# First time (SSH)
git remote add origin git@github.com:YOUR-USERNAME/databricks-multi-agent-cqrs.git
git push -u origin main

# Future pushes
git push
```

---

## What's Next?

After authentication is set up:

1. Create GitHub repository: https://github.com/new
2. Name it: `databricks-multi-agent-cqrs`
3. Don't initialize with README
4. Follow the push commands above

---

**Recommended:** Use **SSH (Method 1)** - it's more secure and convenient!

