# Google Drive Consolidator

Deduplicate and consolidate files across multiple Google Drive accounts.

## Problem

When you have multiple Google accounts (personal, work, old accounts), media and files can end up duplicated across drives — especially iPhone backups via Google Photos. This tool scans all your drives, finds duplicates, and consolidates everything into one primary drive.

## Features

- **Multi-account auth**: Connect up to 4+ Google Drive accounts via OAuth
- **Full drive scan**: Indexes all files with folder path reconstruction
- **Duplicate detection**: MD5 hash matching (using Drive's built-in checksums) with name+size fallback for files without hashes
- **Dry-run mode**: See exactly what will happen before any files are moved or deleted
- **Smart consolidation**: Transfers unique files to your primary drive, overflows to secondary when space runs out
- **Safe deletion**: Duplicates are trashed (not permanently deleted) so you can recover if needed

## Prerequisites

- **Python 3.11+** (check with `python3 --version`)
- **A Google account** you can use to create a Cloud project
- **A web browser** on the same machine (the OAuth flow opens a browser tab)

If you don't have Python installed:
- **macOS**: `brew install python` (or download from python.org)
- **Windows**: Download from [python.org](https://www.python.org/downloads/) — check "Add to PATH" during install
- **Linux**: `sudo apt install python3 python3-pip python3-venv` (Ubuntu/Debian)

## Setup — Full Walkthrough

### Step 1: Clone this repo

```bash
git clone <this-repo-url>
cd drive
```

### Step 2: Create a Python virtual environment

A virtual environment keeps this project's dependencies isolated from your system Python. Run these commands in your terminal (Terminal on macOS/Linux, PowerShell or Command Prompt on Windows):

```bash
# Create the virtual environment (one-time)
python3 -m venv .venv

# Activate it
# On macOS / Linux:
source .venv/bin/activate

# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# On Windows (Command Prompt):
.venv\Scripts\activate.bat
```

You'll see `(.venv)` appear at the start of your terminal prompt — that means it's active. **You need to activate the venv every time you open a new terminal window** before running the tool.

### Step 3: Install dependencies

With the venv activated (you should see `(.venv)` in your prompt):

```bash
pip install -r requirements.txt
```

This installs the Google API client, OAuth libraries, and the CLI framework.

### Step 4: Create a Google Cloud project and enable Drive API

You only need ONE Google Cloud project — it works for all 4 accounts.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Sign in with **any** of your 4 Google accounts
3. Click the project dropdown at the top → **New Project**
4. Name it something like `drive-consolidator` → **Create**
5. Make sure the new project is selected in the dropdown
6. In the left sidebar, go to **APIs & Services** → **Library**
7. Search for **Google Drive API** → click it → **Enable**

### Step 5: Create OAuth credentials

Still in Google Cloud Console:

1. Go to **APIs & Services** → **Credentials**
2. Click **+ CREATE CREDENTIALS** → **OAuth client ID**
3. If prompted to configure the consent screen:
   - Choose **External** (unless you have Google Workspace)
   - Fill in the required fields (app name, your email)
   - Add scopes: search for `Google Drive API` and select `.../auth/drive`
   - Add all 4 of your Google email addresses as **Test users**
   - Save and go back to Credentials
4. Now create the OAuth client:
   - Application type: **Desktop app**
   - Name: anything (e.g., `drive-consolidator`)
   - Click **Create**
5. Click **Download JSON** on the popup

### Step 6: Place the credentials file

```bash
mkdir credentials

# You only need ONE credentials file — the same file works for all accounts.
# Copy the downloaded JSON into the credentials folder:
cp ~/Downloads/client_secret_XXXXX.json credentials/oauth_client.json
```

### Step 7: Configure your accounts

```bash
cp config.example.json config.json
```

Edit `config.json` with any text editor. Since you're using one OAuth client for all accounts, point them all to the same credentials file:

```json
{
  "accounts": [
    {
      "name": "personal",
      "credentials_file": "credentials/oauth_client.json",
      "role": "primary"
    },
    {
      "name": "work",
      "credentials_file": "credentials/oauth_client.json",
      "role": "secondary"
    },
    {
      "name": "old-account",
      "credentials_file": "credentials/oauth_client.json",
      "role": "source"
    },
    {
      "name": "backup",
      "credentials_file": "credentials/oauth_client.json",
      "role": "source"
    }
  ],
  "scan_options": {
    "include_trashed": false,
    "mime_types": [],
    "skip_google_docs": true,
    "large_file_threshold_mb": 100
  },
  "dedup_options": {
    "hash_algorithm": "md5",
    "use_drive_md5": true,
    "fallback_to_name_size": true
  }
}
```

**Choose your roles carefully:**
- `primary` — The drive where ALL consolidated files end up. Pick the account with the most storage or the one you want to keep long-term. **Exactly one required.**
- `secondary` — Overflow when primary is full. Pick your second-biggest drive. **Optional.**
- `source` — Drives to scan and pull files from. Duplicates on source drives get trashed.

### Step 8: Authenticate (first run)

When you run the tool for the first time, it will open your browser **once per account** to authorize access:

```bash
python -m drive_consolidator.cli scan
```

What happens:
1. Browser opens → Google sign-in page for account #1
2. Sign in with the **correct** Google account for that entry (e.g., your "personal" account)
3. Click **Allow** to grant Drive access
4. Browser shows "The authentication flow has completed" → go back to terminal
5. Repeat for accounts #2, #3, #4

Tokens are cached in the `tokens/` folder, so you only do this once. Future runs skip the browser.

**Important**: When the browser opens for each account, make sure you sign into the **right** Google account. The tool authenticates them in the order listed in config.json.

## Usage

Always make sure your venv is activated first (`source .venv/bin/activate`).

### 1. Scan — see what's on each drive

```bash
python -m drive_consolidator.cli scan
```

Shows a table of how many files and total size per account. Good sanity check before doing anything else.

### 2. Analyze — dry-run, find duplicates, preview the plan

```bash
python -m drive_consolidator.cli analyze
```

This is **read-only** — nothing gets moved or deleted. It shows:
- File counts per drive
- Duplicate groups found (with file names, which accounts, wasted space)
- The consolidation plan (what would be transferred, what would be deleted)

**Run this first. Review the output carefully before proceeding.**

### 3. Consolidate — execute the plan

```bash
python -m drive_consolidator.cli consolidate
```

This will:
1. Scan all drives
2. Find duplicates
3. Show you the plan
4. Ask **"Proceed with consolidation?"** — you must type `y` to continue
5. Transfer files to primary drive (with progress bar)
6. Trash duplicates on source drives (with progress bar)
7. Show a summary of what was done

### Custom config file location

All commands accept `-c` / `--config` to point to a different config file:

```bash
python -m drive_consolidator.cli analyze -c ~/my-config.json
```

## How It Works

1. **Authenticate** all configured Google accounts via OAuth (browser popup per account, tokens cached for reuse)
2. **Scan** every drive — lists all files with metadata (name, size, MD5, path)
3. **Detect duplicates**:
   - Primary: Group files by MD5 checksum (Google Drive provides this natively for uploaded files — no download needed)
   - Fallback: Group by filename + file size (for files without checksums, like Google Docs)
4. **Build plan**:
   - For each duplicate group, keep one copy (preferring the copy already on primary drive)
   - Transfer files not yet on primary to primary
   - If primary runs out of space, overflow to secondary
   - Mark remaining duplicates for deletion
5. **Show plan** for review (dry-run)
6. **Execute** on confirmation: transfer files, then trash duplicates

## Safety

- Duplicates are **trashed**, not permanently deleted — you can recover from Drive's trash within 30 days
- The `analyze` command is a pure dry-run that changes nothing
- The `consolidate` command shows the full plan and asks for confirmation before proceeding
- Folder structure is preserved under a `Consolidated Media/` folder in the destination drive

## Troubleshooting

**"Credentials file not found"**
→ Check that the path in `config.json` matches where you saved the OAuth JSON file.

**"Access blocked: This app's request is invalid" in browser**
→ You haven't added yourself as a test user in the OAuth consent screen. Go to Cloud Console → APIs & Services → OAuth consent screen → Test users → add your email.

**"Quota exceeded" or "Rate limit" errors**
→ The Drive API has per-user rate limits. The tool includes small delays between operations. If you hit limits, wait a few minutes and re-run — it will pick up where it left off since tokens are cached.

**Browser doesn't open / headless environment**
→ This tool needs a browser for the first-time OAuth flow. Run it on a machine with a desktop/browser. After the first auth, tokens are cached and you can move the `tokens/` folder to a server.

**Wrong account authenticated**
→ Delete the corresponding token file in `tokens/` (e.g., `tokens/personal_token.json`) and re-run. Make sure you sign into the right Google account when the browser opens.
