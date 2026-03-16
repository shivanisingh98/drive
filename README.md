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

## Setup

### 1. Create Google Cloud Project & OAuth Credentials

For **each** Google account you want to connect:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or reuse one)
3. Enable the **Google Drive API**
4. Go to **Credentials** → **Create Credentials** → **OAuth 2.0 Client ID**
5. Application type: **Desktop app**
6. Download the JSON file

**Tip**: You can use a single Cloud project for all accounts — just use the same OAuth client credentials file. Each account will authenticate separately via the browser.

### 2. Install

```bash
pip install -r requirements.txt
```

### 3. Configure

```bash
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "accounts": [
    {
      "name": "personal",
      "credentials_file": "credentials/personal_credentials.json",
      "role": "primary"
    },
    {
      "name": "work",
      "credentials_file": "credentials/work_credentials.json",
      "role": "secondary"
    },
    {
      "name": "old-account",
      "credentials_file": "credentials/old_credentials.json",
      "role": "source"
    },
    {
      "name": "backup",
      "credentials_file": "credentials/backup_credentials.json",
      "role": "source"
    }
  ]
}
```

**Roles:**
- `primary` — Where all consolidated files end up (required, exactly one)
- `secondary` — Overflow destination when primary is full (optional)
- `source` — Drives to scan and pull files from (duplicates on these get deleted)

### 4. Place Credentials

```bash
mkdir credentials
# Copy your downloaded OAuth JSON files here
cp ~/Downloads/client_secret_*.json credentials/personal_credentials.json
# ... repeat for each account
```

## Usage

### Scan only (see what's on each drive)

```bash
python -m drive_consolidator.cli scan
```

### Analyze (dry-run — find duplicates, show plan)

```bash
python -m drive_consolidator.cli analyze
```

### Consolidate (execute the plan)

```bash
python -m drive_consolidator.cli consolidate
```

Skip confirmation prompt:

```bash
python -m drive_consolidator.cli consolidate --yes
```

## How It Works

1. **Authenticate** all configured Google accounts via OAuth (browser popup per account, tokens cached for reuse)
2. **Scan** every drive — lists all files with metadata (name, size, MD5, path)
3. **Detect duplicates**:
   - Primary method: Group files by MD5 checksum (Google Drive provides this for uploaded files)
   - Fallback: Group by filename + file size (for files without checksums)
4. **Build plan**:
   - For each duplicate group, keep one copy (preferring primary drive)
   - Transfer files not on primary drive to primary
   - If primary is full, overflow to secondary
   - Mark remaining duplicates for deletion
5. **Show plan** for review (dry-run)
6. **Execute** on confirmation: transfer files, then trash duplicates

## Safety

- Duplicates are **trashed**, not permanently deleted — you can recover from Drive's trash within 30 days
- The `analyze` command is a pure dry-run that changes nothing
- The `consolidate` command shows the full plan and asks for confirmation before proceeding
- Folder structure is preserved under a `Consolidated Media/` folder in the destination drive
